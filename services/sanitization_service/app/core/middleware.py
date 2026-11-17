"""Correlation IDs, one safe access log line per request, and the standard 500 body."""

import logging
import re
import time
import uuid
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import CORRELATION_HEADER, internal_error
from app.core.logging import log_event

_VALID_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def _correlation_id(scope: Scope) -> str:
    supplied = Headers(scope=scope).get(CORRELATION_HEADER)
    if supplied is not None and _VALID_CORRELATION_ID.match(supplied):
        return supplied
    return uuid.uuid4().hex


def _outcome(status_code: int) -> str:
    if status_code >= 500:
        return "error"
    return "rejected" if status_code >= 400 else "ok"


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Reuse a valid caller ID, or make a new one. Handlers read it from the request state.
        correlation_id = _correlation_id(scope)
        scope.setdefault("state", {})["correlation_id"] = correlation_id
        started = time.perf_counter()
        status_code = 500  # replaced by the real status when the response starts
        error_category: str | None = None
        response_started = False

        async def send_with_header(message: Message) -> None:
            nonlocal status_code, response_started
            # Add the correlation ID header to every response, errors included.
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                MutableHeaders(scope=message)[CORRELATION_HEADER] = correlation_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        except Exception as exc:
            # Only the exception class name is kept. The message could hold sensitive text.
            error_category = type(exc).__name__
            if response_started:
                # Too late for a clean 500 body; log and let the server close the connection.
                self._log(scope, correlation_id, status_code, started, error_category)
                raise
            # Nothing sent yet, so answer with the standard 500 body.
            await internal_error(correlation_id)(scope, receive, send_with_header)
        self._log(scope, correlation_id, status_code, started, error_category)

    @staticmethod
    def _log(
        scope: Scope,
        correlation_id: str,
        status_code: int,
        started: float,
        error_category: str | None,
    ) -> None:
        # Log the route template (/api/v1/x), never the raw path or query string.
        route: Any = scope.get("route")
        fields: dict[str, object] = {
            "correlation_id": correlation_id,
            "method": scope["method"],
            "route": getattr(route, "path", "unmatched"),
            "status_code": status_code,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "outcome": _outcome(status_code),
        }
        if error_category is not None:
            fields["error_category"] = error_category
        level = logging.ERROR if status_code >= 500 else logging.INFO
        log_event("request_completed", level, **fields)
