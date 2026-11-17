"""De-sanitization Service application."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import desanitizations, health
from app.clients.sanitization import SanitizationClient
from app.core.auth import ApiKeyAuthenticator, parse_api_keys, parse_service_secret
from app.core.config import SERVICE_NAME, SERVICE_VERSION, load_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, log_event
from app.core.middleware import RequestContextMiddleware
from app.core.size_limit import RequestSizeLimitMiddleware


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Load settings, the API keys and the internal client once. A failure at any step leaves
    the service alive but not ready."""
    app.state.settings = None
    app.state.authenticator = None
    app.state.sanitization_client = None
    try:
        settings = load_settings()
        api_keys = parse_api_keys(settings.api_keys.get_secret_value())
        authenticator = ApiKeyAuthenticator(api_keys)
        secret = parse_service_secret(settings.service_secret.get_secret_value(), api_keys.values())
        client = SanitizationClient(
            str(settings.sanitization_base_url), secret, settings.internal_client_timeout_seconds
        )
    except Exception as exc:
        log_event("settings_load_failed", logging.ERROR, error_category=type(exc).__name__)
    else:
        app.state.settings = settings
        app.state.authenticator = authenticator
        app.state.sanitization_client = client
        log_event("settings_loaded")
    yield
    client_in_use: SanitizationClient | None = getattr(app.state, "sanitization_client", None)
    if client_in_use is not None:
        await client_in_use.aclose()


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
    app.include_router(desanitizations.router)
    return app


app = create_app()
