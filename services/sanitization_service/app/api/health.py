"""Liveness and readiness. Responses carry no detail about why a check failed."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from app.core.config import load_settings
from app.core.logging import log_event
from app.db.session import create_db_engine, database_is_reachable

router = APIRouter()

_OK = {"status": "ok"}
_UNAVAILABLE = {"status": "unavailable"}


def _engine(request: Request) -> Engine:
    """Create the engine on first use so a missing setting only affects readiness."""
    state = request.app.state
    if getattr(state, "engine", None) is None:
        state.engine = create_db_engine(load_settings().database_url.get_secret_value())
    engine: Engine = state.engine
    return engine


@router.get("/health/live")
async def live() -> dict[str, str]:
    return _OK


@router.get("/health/ready")
def ready(request: Request) -> JSONResponse:
    try:
        reachable = database_is_reachable(_engine(request))
    except Exception as exc:
        log_event(
            "readiness_failed",
            logging.WARNING,
            correlation_id=request.state.correlation_id,
            error_category=type(exc).__name__,
        )
        reachable = False
    return JSONResponse(_OK if reachable else _UNAVAILABLE, status_code=200 if reachable else 503)
