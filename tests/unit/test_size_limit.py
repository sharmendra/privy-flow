"""The request size limit middleware, tested on its own against a stub ASGI app."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

LIMIT = 100
DEFAULT_LIMIT = 262144


@pytest.fixture(scope="module")
def middleware(san: Callable[[str], Any]) -> Any:
    return san("app.core.size_limit").RequestSizeLimitMiddleware


def _scope(
    headers: list[tuple[bytes, bytes]] | None = None, limit: int | None = LIMIT, kind: str = "http"
) -> dict[str, Any]:
    snapshot = (
        None if limit is None else SimpleNamespace(content=SimpleNamespace(max_request_bytes=limit))
    )
    return {
        "type": kind,
        "headers": headers or [],
        "state": {"correlation_id": "corr-12345678"},
        "app": SimpleNamespace(state=SimpleNamespace(settings_snapshot=snapshot)),
    }


class Run:
    """Drives the middleware with a body delivered in chunks and records what it sent."""

    def __init__(self, middleware: Any, chunks: list[bytes]) -> None:
        self.sent: list[dict[str, Any]] = []
        self.inner_called = False
        self.body_read = b""
        self._chunks = list(chunks)
        self._middleware = middleware

    async def _inner(self, scope: Any, receive: Any, send: Any) -> None:
        self.inner_called = True
        more = True
        while more:
            message = await receive()
            self.body_read += message.get("body", b"")
            more = message.get("more_body", False)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def _receive(self) -> dict[str, Any]:
        body = self._chunks.pop(0) if self._chunks else b""
        return {"type": "http.request", "body": body, "more_body": bool(self._chunks)}

    async def _send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    async def __call__(self, scope: dict[str, Any]) -> None:
        await self._middleware(self._inner)(scope, self._receive, self._send)

    @property
    def status(self) -> int:
        return next(m["status"] for m in self.sent if m["type"] == "http.response.start")


def _length(value: str) -> list[tuple[bytes, bytes]]:
    return [(b"content-length", value.encode("utf-8"))]


@pytest.mark.anyio
async def test_a_declared_length_over_the_limit_is_refused_without_calling_the_app(
    middleware: Any,
) -> None:
    run = Run(middleware, [b"x" * 5])
    await run(_scope(_length(str(LIMIT + 1))))
    assert run.status == 413
    assert not run.inner_called


@pytest.mark.anyio
async def test_a_declared_length_at_the_limit_reaches_the_app(middleware: Any) -> None:
    run = Run(middleware, [b"x" * LIMIT])
    await run(_scope(_length(str(LIMIT))))
    assert run.status == 200
    assert run.body_read == b"x" * LIMIT


@pytest.mark.anyio
async def test_the_refusal_carries_the_correlation_id_and_the_standard_body(
    middleware: Any,
) -> None:
    run = Run(middleware, [])
    await run(_scope(_length(str(LIMIT + 1))))
    start = next(m for m in run.sent if m["type"] == "http.response.start")
    body = next(m for m in run.sent if m["type"] == "http.response.body")["body"]
    assert (b"x-correlation-id", b"corr-12345678") in start["headers"]
    assert b'"payload_too_large"' in body and b"corr-12345678" in body


@pytest.mark.anyio
async def test_a_body_over_the_limit_with_no_declared_length_stops_the_read(
    middleware: Any,
) -> None:
    run = Run(middleware, [b"x" * 60, b"x" * 60])
    with pytest.raises(HTTPException) as raised:
        await run(_scope())
    assert raised.value.status_code == 413
    assert run.body_read == b"x" * 60  # the second chunk was never delivered


@pytest.mark.anyio
async def test_chunks_that_add_up_to_exactly_the_limit_are_accepted(middleware: Any) -> None:
    run = Run(middleware, [b"x" * 40, b"x" * 40, b"x" * 20])
    await run(_scope())
    assert run.status == 200
    assert len(run.body_read) == LIMIT


@pytest.mark.anyio
async def test_a_declared_length_that_understates_the_body_is_still_counted(
    middleware: Any,
) -> None:
    run = Run(middleware, [b"x" * 80, b"x" * 80])
    with pytest.raises(HTTPException):
        await run(_scope(_length("10")))


@pytest.mark.anyio
@pytest.mark.parametrize("declared", ["abc", "-5", "1e3", "١٢", " 12", ""])
async def test_a_malformed_content_length_falls_back_to_counting(
    middleware: Any, declared: str
) -> None:
    run = Run(middleware, [b"x" * 10])
    await run(_scope(_length(declared)))
    assert run.status == 200


@pytest.mark.anyio
async def test_the_default_limit_applies_when_settings_did_not_load(middleware: Any) -> None:
    ok = Run(middleware, [])
    await ok(_scope(_length(str(DEFAULT_LIMIT)), limit=None))
    assert ok.status == 200
    refused = Run(middleware, [])
    await refused(_scope(_length(str(DEFAULT_LIMIT + 1)), limit=None))
    assert refused.status == 413


@pytest.mark.anyio
async def test_requests_that_are_not_http_pass_straight_through(middleware: Any) -> None:
    seen: list[str] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        seen.append(scope["type"])

    scope = _scope(kind="lifespan")
    scope.pop("app")  # a lifespan scope has no request state to read
    await middleware(inner)(scope, None, None)
    assert seen == ["lifespan"]
