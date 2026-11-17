"""Liveness and readiness. Readiness checks configuration only; there is no database."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import load_settings
from app.core.logging import log_event

router = APIRouter()

_OK = {"status": "ok"}
_UNAVAILABLE = {"status": "unavailable"}


@router.get("/health/live")
async def live() -> dict[str, str]:
    return _OK


@router.get("/health/ready")
async def ready(request: Request) -> JSONResponse:
    try:
        load_settings()
    except Exception as exc:
        log_event(
            "readiness_failed",
            logging.WARNING,
            correlation_id=request.state.correlation_id,
            error_category=type(exc).__name__,
        )
        return JSONResponse(_UNAVAILABLE, status_code=503)
    return JSONResponse(_OK)
