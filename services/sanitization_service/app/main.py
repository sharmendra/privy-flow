"""Sanitization Service application."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine

from app.api import health, internal, sanitizations
from app.core.auth import ApiKeyAuthenticator, parse_api_keys
from app.core.config import SERVICE_NAME, SERVICE_VERSION, load_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, log_event
from app.core.middleware import RequestContextMiddleware
from app.core.service_auth import ServiceSecretAuthenticator, parse_service_secret
from app.core.size_limit import RequestSizeLimitMiddleware
from app.db.session import get_engine
from app.repositories.mapping_repository import MappingRepository
from app.sanitization.policy import PolicyResolver
from app.settings.selector import load_snapshot
from app.vault.config import parse_keyring, parse_pepper
from app.vault.vault import Vault


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Load settings, build the tenant policies, the vault and the API key check once. A failure
    at any step leaves the service alive but not ready, with no fallback."""
    # Start with everything unset. Readiness checks these, so a failed load means "not ready".
    app.state.settings_snapshot = None
    app.state.policy_resolver = None
    app.state.vault = None
    app.state.authenticator = None
    app.state.service_authenticator = None
    try:
        bootstrap = load_settings()  # environment and .env
        engine = get_engine(app) if bootstrap.settings_backend == "db" else None
        snapshot = load_snapshot(bootstrap, engine)  # file or database, never both
        resolver = PolicyResolver(snapshot.content)
        vault = Vault(
            MappingRepository(get_engine(app)),
            parse_keyring(
                bootstrap.encryption_keys.get_secret_value(), bootstrap.active_key_version
            ),
            parse_pepper(bootstrap.credential_pepper.get_secret_value()),
        )
        api_keys = parse_api_keys(bootstrap.api_keys.get_secret_value())
        authenticator = ApiKeyAuthenticator(api_keys)
        service_authenticator = ServiceSecretAuthenticator(
            parse_service_secret(bootstrap.service_secret.get_secret_value(), api_keys.values())
        )
    except Exception as exc:
        log_event("settings_load_failed", logging.ERROR, error_category=type(exc).__name__)
    else:
        # Publish the objects only after every step worked.
        app.state.settings_snapshot = snapshot
        app.state.policy_resolver = resolver
        app.state.vault = vault
        app.state.authenticator = authenticator
        app.state.service_authenticator = service_authenticator
        log_event(
            "settings_loaded",
            settings_backend=snapshot.backend,
            settings_version=snapshot.version,
            settings_hash=snapshot.content_hash,
        )
    yield
    # Shutdown: release database connections.
    engine_in_use: Engine | None = getattr(app.state, "engine", None)
    if engine_in_use is not None:
        engine_in_use.dispose()


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title=f"PrivyFlow {SERVICE_NAME} service",
        version=SERVICE_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan,
    )
    # The last middleware added is the outermost. Request context must wrap the size limit,
    # so a 413 still gets a correlation ID and a log line.
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(sanitizations.router)
    app.include_router(internal.router)
    return app


app = create_app()
