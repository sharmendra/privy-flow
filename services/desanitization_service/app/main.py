"""De-sanitization Service application."""

from fastapi import FastAPI

from app.api import health
from app.core.config import SERVICE_NAME, SERVICE_VERSION
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title=f"PrivyFlow {SERVICE_NAME} service",
        version=SERVICE_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    app.include_router(health.router)
    return app


app = create_app()
