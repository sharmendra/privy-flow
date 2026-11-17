"""Liveness and readiness. Responses carry no detail about why a check failed."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.logging import log_event
from app.db.session import database_is_reachable, get_engine

router = APIRouter()

_OK = {"status": "ok"}
_UNAVAILABLE = {"status": "unavailable"}


@router.get("/health/live")
async def live() -> dict[str, str]:
    return _OK


@router.get("/health/ready")
def ready(request: Request) -> JSONResponse:
    """Ready means the startup settings, keys and API keys loaded and the database answers."""
    try:
        state = request.app.state
        settings_loaded = (
            getattr(state, "settings_snapshot", None) is not None
            and getattr(state, "vault", None) is not None
            and getattr(state, "authenticator", None) is not None
        )
        reachable = database_is_reachable(get_engine(request.app))
    except Exception as exc:
        log_event(
            "readiness_failed",
            logging.WARNING,
            correlation_id=request.state.correlation_id,
            error_category=type(exc).__name__,
        )
        settings_loaded = reachable = False
    healthy = settings_loaded and reachable
    return JSONResponse(_OK if healthy else _UNAVAILABLE, status_code=200 if healthy else 503)
