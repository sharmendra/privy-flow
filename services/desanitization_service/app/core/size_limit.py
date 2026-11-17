"""Request body size limit (SPEC 9.2): bodies over `max_request_bytes` get 413.

A declared Content-Length over the limit is refused before any of the body is read. A body
with no declared length, or one that lies, is counted as it arrives and refused once it goes
over. A body of exactly the limit is accepted.
"""

from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import DEFAULT_MAX_REQUEST_BYTES
from app.core.errors import payload_too_large


def _limit(scope: Scope) -> int:
    """The limit from the loaded settings, or the default when settings did not load."""
    settings = getattr(scope["app"].state, "settings", None)
    return DEFAULT_MAX_REQUEST_BYTES if settings is None else settings.max_request_bytes


class RequestSizeLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = _limit(scope)
        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isascii() and declared.isdigit():
            if int(declared) > limit:
                response = payload_too_large(str(scope["state"]["correlation_id"]))
                await response(scope, receive, send)
                return
        received = 0

        async def counted() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # FastAPI's own HTTPException passes through its body parsing untouched;
                    # the standard handler then writes the 413 body.
                    raise HTTPException(status_code=413)
            return message

        await self.app(scope, counted, send)
