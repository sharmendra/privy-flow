"""Liveness and readiness. Readiness checks configuration only; there is no database."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

_OK = {"status": "ok"}
_UNAVAILABLE = {"status": "unavailable"}


@router.get("/health/live")
async def live() -> dict[str, str]:
    return _OK


@router.get("/health/ready")
async def ready(request: Request) -> JSONResponse:
    """Ready once settings, API keys, the service secret and the internal client loaded. The
    Sanitization Service itself is not probed: its availability is reported per request."""
    state = request.app.state
    loaded = (
        getattr(state, "settings", None) is not None
        and getattr(state, "authenticator", None) is not None
        and getattr(state, "sanitization_client", None) is not None
    )
    return JSONResponse(_OK if loaded else _UNAVAILABLE, status_code=200 if loaded else 503)
