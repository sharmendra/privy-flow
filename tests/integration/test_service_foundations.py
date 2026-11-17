"""Correlation IDs, the standard error body, and log redaction, for both services."""

import importlib
import json
import logging
import re
from typing import Any

import pytest
from pydantic import BaseModel

from tests.conftest import AppFactory, client_for
from tests.support.leak import CANARIES, assert_no_leak

ALLOWED_LOG_KEYS = {
    "ts",
    "level",
    "event",
    "service",
    "version",
    "correlation_id",
    "method",
    "route",
    "status_code",
    "latency_ms",
    "outcome",
    "error_category",
    "settings_backend",
    "settings_version",
    "settings_hash",
}
SQL_CANARY = "SELECT secret FROM vault WHERE value = 'x'"
GENERATED_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class EchoBody(BaseModel):
    text: str


@pytest.fixture(params=["sanitization", "desanitization"])
def app(
    request: pytest.FixtureRequest,
    sanitization_app_factory: AppFactory,
    desanitization_app_factory: AppFactory,
) -> Any:
    """Each service app, with test-only routes added to exercise shared behavior."""
    factory = (
        sanitization_app_factory if request.param == "sanitization" else desanitization_app_factory
    )
    built: Any = factory()

    async def echo(body: EchoBody) -> dict[str, str]:
        return {"ok": "yes"}

    async def boom() -> None:
        raise RuntimeError(f"failure with {CANARIES[0]} and {SQL_CANARY}")

    built.add_api_route("/test/echo", echo, methods=["POST"])
    built.add_api_route("/test/boom", boom, methods=["GET"])
    return built


def _captured_logs(caplog: pytest.LogCaptureFixture) -> str:
    formatter = importlib.import_module("app.core.logging").JsonFormatter()
    lines: list[str] = []
    for record in caplog.records:
        # The test client's own request log is not the service's output.
        if record.name.startswith(("httpx", "httpcore")):
            continue
        lines.append(record.getMessage())
        lines.append(formatter.format(record))
    return "\n".join(lines)


@pytest.mark.anyio
async def test_correlation_id_is_generated_when_absent(app: Any) -> None:
    async with client_for(app) as client:
        response = await client.get("/health/live")
    assert GENERATED_ID.match(response.headers["X-Correlation-ID"])


@pytest.mark.anyio
async def test_correlation_id_is_echoed_when_valid(app: Any) -> None:
    async with client_for(app) as client:
        response = await client.get("/health/live", headers={"X-Correlation-ID": "client-id-12345"})
    assert response.headers["X-Correlation-ID"] == "client-id-12345"


@pytest.mark.anyio
@pytest.mark.parametrize("bad", ["short", "has spaces in it", "x" * 65, "semi;colon-123456"])
async def test_correlation_id_is_replaced_when_invalid(app: Any, bad: str) -> None:
    async with client_for(app) as client:
        response = await client.get("/health/live", headers={"X-Correlation-ID": bad})
    returned = response.headers["X-Correlation-ID"]
    assert returned != bad
    assert GENERATED_ID.match(returned)


@pytest.mark.anyio
async def test_unknown_route_returns_standard_error_body(app: Any) -> None:
    async with client_for(app) as client:
        response = await client.get("/api/v1/nothing-here")
    body = response.json()
    assert response.status_code == 404
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "correlation_id"}
    assert body["error"]["code"] == "not_found"
    assert body["error"]["correlation_id"] == response.headers["X-Correlation-ID"]


@pytest.mark.anyio
async def test_validation_error_uses_standard_body_and_does_not_echo_input(app: Any) -> None:
    async with client_for(app) as client:
        response = await client.post("/test/echo", json={"text": 5, "extra": CANARIES[0]})
    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["correlation_id"] == response.headers["X-Correlation-ID"]
    assert_no_leak(response.text)


@pytest.mark.anyio
async def test_unhandled_exception_returns_standard_500_without_details(app: Any) -> None:
    async with client_for(app) as client:
        response = await client.get("/test/boom")
    body = response.json()
    assert response.status_code == 500
    assert body["error"]["code"] == "internal_error"
    assert set(body["error"]) == {"code", "message", "correlation_id"}
    assert body["error"]["correlation_id"] == response.headers["X-Correlation-ID"]
    for forbidden in ("Traceback", "RuntimeError", "SELECT", "vault", "File "):
        assert forbidden not in response.text
    assert_no_leak(response.text)


@pytest.mark.anyio
async def test_logs_never_contain_request_body_header_or_query_canaries(
    app: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    async with client_for(app) as client:
        await client.post(
            f"/test/echo?q={CANARIES[1]}",
            json={"text": CANARIES[0], "phone": CANARIES[2]},
            headers={"Authorization": CANARIES[3], "X-Api-Key": CANARIES[3]},
        )
        await client.get("/test/boom", headers={"X-Custom": CANARIES[0]})
    logs = _captured_logs(caplog)
    assert "request_completed" in logs
    assert_no_leak(logs)
    assert SQL_CANARY not in logs
    assert "failure with" not in logs


@pytest.mark.anyio
async def test_log_lines_only_use_allowlisted_fields(
    app: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    async with client_for(app) as client:
        await client.get("/health/live")
        await client.get("/test/boom")
    formatter = importlib.import_module("app.core.logging").JsonFormatter()
    lines = [
        json.loads(formatter.format(r)) for r in caplog.records if r.name.startswith("privyflow")
    ]
    assert lines
    for line in lines:
        assert set(line) <= ALLOWED_LOG_KEYS
    boom = [line for line in lines if line.get("route") == "/test/boom"][-1]
    assert boom["status_code"] == 500
    assert boom["error_category"] == "RuntimeError"


@pytest.mark.anyio
async def test_log_formatter_drops_fields_that_are_not_allowlisted(app: Any) -> None:
    logging_module = importlib.import_module("app.core.logging")
    record = logging.LogRecord(
        "privyflow.test", logging.INFO, __file__, 1, "event_name", None, None
    )
    record.text = CANARIES[0]
    record.correlation_id = "abc12345"
    output = logging_module.JsonFormatter().format(record)
    assert CANARIES[0] not in output
    assert json.loads(output)["correlation_id"] == "abc12345"
