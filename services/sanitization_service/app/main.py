"""Sanitization Service application."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine

from app.api import health
from app.core.config import SERVICE_NAME, SERVICE_VERSION, load_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, log_event
from app.core.middleware import RequestContextMiddleware
from app.core.size_limit import RequestSizeLimitMiddleware
from app.db.session import get_engine
from app.sanitization.policy import PolicyResolver
from app.settings.selector import load_snapshot


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Load settings and build the tenant policies once. A failure at either step leaves the
    service alive but not ready, with no fallback."""
    app.state.settings_snapshot = None
    app.state.policy_resolver = None
    try:
        bootstrap = load_settings()
        engine = get_engine(app) if bootstrap.settings_backend == "db" else None
        snapshot = load_snapshot(bootstrap, engine)
        resolver = PolicyResolver(snapshot.content)
    except Exception as exc:
        log_event("settings_load_failed", logging.ERROR, error_category=type(exc).__name__)
    else:
        app.state.settings_snapshot = snapshot
        app.state.policy_resolver = resolver
        log_event(
            "settings_loaded",
            settings_backend=snapshot.backend,
            settings_version=snapshot.version,
            settings_hash=snapshot.content_hash,
        )
    yield
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
    return app


app = create_app()
