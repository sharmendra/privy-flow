"""Request size limit and empty or whitespace-only input on the Sanitization Service.

The public endpoint arrives in phase 5. These tests mount a test-only route that uses the
real request schema, the real size limit and the real sanitizer, so the behavior that the
endpoint will inherit is proven now. Nothing here needs a database.
"""

import importlib
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import Request

from tests.conftest import AppFactory, client_for
from tests.support.leak import CANARIES, assert_no_leak
from tests.support.settings_data import valid_content, write_settings_file

LIMIT = 1024  # the smallest limit the settings validator allows
SCOPE = "scope-limit-test"


def _body(text: str) -> bytes:
    # ensure_ascii=False keeps non-ASCII text as raw UTF-8, as a client would send it.
    return json.dumps(
        {"text": text, "request_scope_id": SCOPE, "policy_id": "effective"},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _body_of_exactly(size: int) -> bytes:
    overhead = len(_body(""))
    body = _body("a" * (size - overhead))
    assert len(body) == size
    return body


def _build(factory: AppFactory, tmp_path: Path, **settings: Any) -> Any:
    settings_file = write_settings_file(tmp_path / "limit.json", valid_content(**settings))
    app: Any = factory({"PRIVYFLOW_SETTINGS_FILE": str(settings_file)})
    request_schema = importlib.import_module("app.schemas.sanitization").SanitizationRequest
    sanitizer = importlib.import_module("app.sanitization.sanitizer")

    async def sanitize(body: Any, request: Request) -> dict[str, object]:
        policy = request.app.state.policy_resolver.policy_for("tenant-test-a")
        result = sanitizer.sanitize_text(body.text, policy)
        return {"sanitized_text": result.sanitized_text, "entity_count": result.entity_count}

    # The schema class is only known after the service is loaded, so its annotation is set here.
    sanitize.__annotations__["body"] = request_schema
    app.add_api_route("/test/sanitize", sanitize, methods=["POST"])
    return app


@pytest.fixture
def app(sanitization_app_factory: AppFactory, tmp_path: Path) -> Any:
    return _build(sanitization_app_factory, tmp_path, max_request_bytes=LIMIT)


async def _post(client: Any, content: bytes | AsyncIterator[bytes], **kwargs: Any) -> Any:
    return await client.post(
        "/test/sanitize", content=content, headers={"Content-Type": "application/json"}, **kwargs
    )


async def _chunks(body: bytes, size: int = 100) -> AsyncIterator[bytes]:
    for index in range(0, len(body), size):
        yield body[index : index + size]


def _assert_standard_413(response: Any) -> None:
    body = response.json()
    assert response.status_code == 413
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "correlation_id"}
    assert body["error"]["code"] == "payload_too_large"
    assert body["error"]["correlation_id"] == response.headers["X-Correlation-ID"]
    assert_no_leak(response.text)


# ---- size limit --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_body_exactly_at_the_limit_is_accepted(app: Any) -> None:
    async with client_for(app) as client:
        response = await _post(client, _body_of_exactly(LIMIT))
    assert response.status_code == 200


@pytest.mark.anyio
async def test_a_body_one_byte_over_the_limit_is_rejected_with_413(app: Any) -> None:
    async with client_for(app) as client:
        response = await _post(client, _body_of_exactly(LIMIT + 1))
    _assert_standard_413(response)


@pytest.mark.anyio
async def test_a_body_far_over_the_limit_is_rejected_with_413(app: Any) -> None:
    async with client_for(app) as client:
        response = await _post(client, _body_of_exactly(LIMIT * 50))
    _assert_standard_413(response)


@pytest.mark.anyio
async def test_the_limit_counts_bytes_not_characters(app: Any) -> None:
    """Each of these characters is two bytes in UTF-8, so half the characters hit the limit."""
    overhead = len(_body(""))
    fits = _body("é" * ((LIMIT - overhead) // 2))
    too_big = _body("é" * ((LIMIT - overhead) // 2 + 1))
    assert len(fits) <= LIMIT < len(too_big)
    async with client_for(app) as client:
        ok = await _post(client, fits)
        rejected = await _post(client, too_big)
    assert ok.status_code == 200
    _assert_standard_413(rejected)


@pytest.mark.anyio
async def test_an_oversized_chunked_body_with_no_content_length_is_rejected_with_413(
    app: Any,
) -> None:
    async with client_for(app) as client:
        response = await _post(client, _chunks(_body_of_exactly(LIMIT * 4)))
    _assert_standard_413(response)


@pytest.mark.anyio
async def test_a_chunked_body_at_the_limit_is_accepted(app: Any) -> None:
    async with client_for(app) as client:
        response = await _post(client, _chunks(_body_of_exactly(LIMIT)))
    assert response.status_code == 200


@pytest.mark.anyio
async def test_a_content_length_over_the_limit_is_rejected_before_the_body_is_read(
    app: Any,
) -> None:
    """The early check answers from the header alone, so a small body with a large declared
    length is still refused."""
    async with client_for(app) as client:
        response = await client.post(
            "/test/sanitize",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": str(LIMIT + 1)},
        )
    _assert_standard_413(response)


@pytest.mark.anyio
async def test_the_limit_comes_from_the_settings_snapshot(
    sanitization_app_factory: AppFactory, tmp_path: Path
) -> None:
    app = _build(sanitization_app_factory, tmp_path, max_request_bytes=4096)
    async with client_for(app) as client:
        under = await _post(client, _body_of_exactly(4096))
        over = await _post(client, _body_of_exactly(4097))
        # 1500 bytes is over the 1024 test default and under this snapshot's limit.
        middle = await _post(client, _body_of_exactly(1500))
    assert under.status_code == 200
    assert middle.status_code == 200
    _assert_standard_413(over)


@pytest.mark.anyio
async def test_the_default_limit_applies_when_settings_did_not_load(
    sanitization_app_factory: AppFactory, tmp_path: Path
) -> None:
    app = sanitization_app_factory({"PRIVYFLOW_SETTINGS_FILE": str(tmp_path / "missing.json")})
    request_schema = importlib.import_module("app.schemas.sanitization").SanitizationRequest

    async def sanitize(body: Any) -> dict[str, str]:
        return {"ok": "yes"}

    sanitize.__annotations__["body"] = request_schema
    app.add_api_route("/test/sanitize", sanitize, methods=["POST"])
    async with client_for(app) as client:
        assert app.state.settings_snapshot is None
        under = await _post(client, _body_of_exactly(262144))
        over = await _post(client, _body_of_exactly(262145))
    assert under.status_code == 200
    _assert_standard_413(over)


@pytest.mark.anyio
async def test_a_too_large_request_is_logged_without_its_content(
    app: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    big = _body(CANARIES[0] + " " + "a" * LIMIT)
    async with client_for(app) as client:
        response = await _post(client, big)
    assert response.status_code == 413
    formatter = importlib.import_module("app.core.logging").JsonFormatter()
    lines = [
        formatter.format(r) for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))
    ]
    completed = [json.loads(line) for line in lines if '"request_completed"' in line]
    assert [entry["status_code"] for entry in completed] == [413]
    assert_no_leak("\n".join(lines))


@pytest.mark.anyio
async def test_a_request_without_a_body_is_unaffected_by_the_limit(app: Any) -> None:
    async with client_for(app) as client:
        response = await client.get("/health/live")
    assert response.status_code == 200


# ---- empty and whitespace-only text ------------------------------------------------------


@pytest.mark.anyio
async def test_empty_text_is_rejected_with_422(app: Any) -> None:
    async with client_for(app) as client:
        response = await _post(client, _body(""))
    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["correlation_id"] == response.headers["X-Correlation-ID"]


@pytest.mark.anyio
@pytest.mark.parametrize("text", [" ", "   ", "\n", "\t\t", "\r\n \r\n", "   "])
async def test_whitespace_only_text_returns_200_unchanged_with_no_entities(
    app: Any, text: str
) -> None:
    async with client_for(app) as client:
        response = await _post(client, _body(text))
    assert response.status_code == 200
    assert response.json() == {"sanitized_text": text, "entity_count": 0}


@pytest.mark.anyio
async def test_valid_text_is_sanitized_through_the_whole_stack(app: Any) -> None:
    text = "Write to alice@example.com or call +1 202-555-0143. é\r\nBye"
    async with client_for(app) as client:
        response = await _post(client, _body(text))
    assert response.status_code == 200
    assert response.json() == {
        "sanitized_text": "Write to [EMAIL_001] or call [PHONE_001]. é\r\nBye",
        "entity_count": 2,
    }


@pytest.mark.anyio
async def test_the_422_for_a_bad_body_does_not_echo_the_input(app: Any) -> None:
    async with client_for(app) as client:
        response = await client.post(
            "/test/sanitize",
            json={"text": "", "request_scope_id": CANARIES[0], "policy_id": CANARIES[1]},
        )
    assert response.status_code == 422
    assert_no_leak(response.text)
