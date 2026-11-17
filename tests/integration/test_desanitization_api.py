"""POST /api/v1/desanitizations through the real De-sanitization app.

The Sanitization Service is stubbed at its HTTP boundary (tests/support/sanitization_stub.py),
so the real authentication, internal client and restorer run and no database is needed.
"""

from typing import Any

import pytest

from tests.conftest import AppFactory, DesanApiFactory, client_for
from tests.support.desan_api import OTHER_REFERENCE, REFERENCE, SCOPE, DesanApi
from tests.support.desan_env import DESAN_API_KEYS, desanitization_env
from tests.support.leak import CANARIES, assert_no_leak
from tests.support.vault_env import API_KEYS, SERVICE_SECRET, TENANT_A, TENANT_B

pytestmark = pytest.mark.anyio

EMAIL, PHONE = CANARIES[1], CANARIES[2]
MAPPINGS = {"[EMAIL_001]": EMAIL, "[PHONE_001]": PHONE}
TEXT = "Write to [EMAIL_001] or call [PHONE_001]."
RESTORED = f"Write to {EMAIL} or call {PHONE}."
ERROR_KEYS = {"code", "message", "correlation_id"}


def _seeded(api: DesanApi, tenant: str = TENANT_A, scope: str = SCOPE) -> None:
    api.stub.add(REFERENCE, tenant, scope, MAPPINGS)


def _error(response: Any, status: int, code: str) -> dict[str, Any]:
    body = response.json()
    assert response.status_code == status
    assert set(body) == {"error"}
    assert set(body["error"]) == ERROR_KEYS
    assert body["error"]["code"] == code
    assert body["error"]["correlation_id"] == response.headers["X-Correlation-ID"]
    return {"error": {**body["error"], "correlation_id": "-"}}


# --- authorized restoration -------------------------------------------------------------------


async def test_authorized_restoration_returns_the_original_text(desan_api: DesanApi) -> None:
    _seeded(desan_api)
    response = await desan_api.restore(TEXT)
    body = response.json()
    assert response.status_code == 200
    assert set(body) == {
        "restored_text",
        "restored_count",
        "unmatched_placeholder_count",
        "correlation_id",
    }
    assert body["restored_text"] == RESTORED
    assert body["restored_count"] == 2
    assert body["unmatched_placeholder_count"] == 0
    assert body["correlation_id"] == response.headers["X-Correlation-ID"]
    assert response.headers["Cache-Control"] == "no-store"


async def test_the_internal_call_carries_the_tenant_of_the_key_and_the_service_secret(
    desan_api: DesanApi,
) -> None:
    _seeded(desan_api)
    response = await desan_api.restore(
        TEXT, headers={**desan_api.headers(), "X-Correlation-ID": "trace-0000001"}
    )
    (call,) = desan_api.stub.calls
    assert call.body == {
        "restore_reference": REFERENCE,
        "tenant_id": TENANT_A,
        "request_scope_id": SCOPE,
    }
    assert call.headers["x-service-secret"] == SERVICE_SECRET
    assert call.headers["x-correlation-id"] == "trace-0000001"
    assert "x-api-key" not in call.headers
    assert response.headers["X-Correlation-ID"] == "trace-0000001"


async def test_restoration_can_be_repeated_within_the_lifetime(desan_api: DesanApi) -> None:
    _seeded(desan_api)
    first = await desan_api.restore(TEXT)
    second = await desan_api.restore(TEXT)
    assert first.json()["restored_text"] == second.json()["restored_text"] == RESTORED


async def test_unknown_and_altered_placeholders_are_left_untouched_and_counted(
    desan_api: DesanApi,
) -> None:
    _seeded(desan_api)
    response = await desan_api.restore("[EMAIL_001] [EMAIL_002] [PHONE_001_009] [email_001]")
    body = response.json()
    assert body["restored_text"] == f"{EMAIL} [EMAIL_002] [PHONE_001_009] [email_001]"
    assert (body["restored_count"], body["unmatched_placeholder_count"]) == (1, 2)


# --- authentication: a reference alone never authorizes ---------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-API-Key": "wrong-" + "k" * 30},
        {"X-API-Key": ""},
        {"X-Service-Secret": SERVICE_SECRET},
        {"X-API-Key": SERVICE_SECRET},
        {"X-API-Key": API_KEYS[TENANT_A]},  # a Sanitization Service client key is not valid here
        {"Authorization": f"Bearer {DESAN_API_KEYS[TENANT_A]}"},
    ],
    ids=[
        "none",
        "wrong_key",
        "empty_key",
        "service_secret_header",
        "service_secret_as_key",
        "sanitization_key",
        "bearer",
    ],
)
async def test_a_valid_reference_without_a_valid_api_key_is_rejected_and_never_looked_up(
    desan_api: DesanApi, headers: dict[str, str]
) -> None:
    _seeded(desan_api)
    response = await desan_api.restore(TEXT, headers=headers)
    assert _error(response, 401, "unauthorized")
    assert desan_api.stub.calls == []
    assert_no_leak(response.text, [EMAIL, PHONE, REFERENCE])


async def test_a_key_for_another_tenant_cannot_restore_the_reference(desan_api: DesanApi) -> None:
    _seeded(desan_api, TENANT_A)
    response = await desan_api.restore(TEXT, tenant=TENANT_B)
    assert _error(response, 404, "restore_reference_not_found")
    (call,) = desan_api.stub.calls
    assert call.body["tenant_id"] == TENANT_B  # the tenant is the key's, whatever the caller wants
    assert_no_leak(response.text)


async def test_authentication_runs_before_the_body_is_read(desan_api: DesanApi) -> None:
    response = await desan_api.client.post("/api/v1/desanitizations", content=b"not json")
    assert response.status_code == 401


async def test_the_tenant_cannot_be_named_in_the_body(desan_api: DesanApi) -> None:
    _seeded(desan_api, TENANT_A)
    response = await desan_api.restore(TEXT, tenant=TENANT_B, tenant_id=TENANT_A)
    assert _error(response, 422, "validation_error")
    assert desan_api.stub.calls == []


# --- non-disclosure and scope -----------------------------------------------------------------


async def test_every_failed_lookup_returns_the_same_404(desan_api: DesanApi) -> None:
    _seeded(desan_api, TENANT_A, SCOPE)
    desan_api.stub.add(OTHER_REFERENCE, TENANT_B, SCOPE, MAPPINGS)
    attempts = {
        "unknown": await desan_api.restore(TEXT, reference="pf1_" + "C" * 43),
        "wrong_scope": await desan_api.restore(TEXT, scope="another-scope"),
        "other_tenants_reference": await desan_api.restore(TEXT, reference=OTHER_REFERENCE),
        "malformed": await desan_api.restore(TEXT, reference=f"bad-{EMAIL}"),
        "wrong_length": await desan_api.restore(TEXT, reference="pf1_" + "A" * 42),
        "trailing_newline": await desan_api.restore(TEXT, reference=REFERENCE + "\n"),
    }
    desan_api.stub.remove(REFERENCE)  # as expiry or revocation would
    attempts["expired_or_revoked"] = await desan_api.restore(TEXT)
    bodies = {name: _error(r, 404, "restore_reference_not_found") for name, r in attempts.items()}
    assert len({str(b) for b in bodies.values()}) == 1
    assert len({r.headers["Content-Type"] for r in attempts.values()}) == 1
    for response in attempts.values():
        assert_no_leak(response.text, [EMAIL, PHONE, REFERENCE])


async def test_a_malformed_reference_is_answered_without_calling_the_sanitization_service(
    desan_api: DesanApi,
) -> None:
    response = await desan_api.restore(TEXT, reference="not-a-reference")
    assert response.status_code == 404
    assert desan_api.stub.calls == []


# --- validation and limits --------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation",
    [
        {"sanitized_text": ""},
        {"sanitized_text": 5},
        {"request_scope_id": "has spaces"},
        {"request_scope_id": ""},
        {"restore_reference": None},
        {"unexpected": "field"},
    ],
    ids=["empty_text", "text_type", "bad_scope", "empty_scope", "null_reference", "unknown_field"],
)
async def test_an_invalid_body_gets_422_and_calls_nothing(
    desan_api: DesanApi, mutation: dict[str, Any]
) -> None:
    body = {
        "sanitized_text": TEXT,
        "restore_reference": REFERENCE,
        "request_scope_id": SCOPE,
        **mutation,
    }
    response = await desan_api.client.post(
        "/api/v1/desanitizations", json=body, headers=desan_api.headers()
    )
    assert _error(response, 422, "validation_error")
    assert desan_api.stub.calls == []


async def test_whitespace_only_text_is_valid_and_returned_unchanged(desan_api: DesanApi) -> None:
    _seeded(desan_api)
    response = await desan_api.restore("  \r\n\t ")
    assert response.status_code == 200
    assert response.json()["restored_text"] == "  \r\n\t "


async def test_a_body_over_the_input_limit_gets_413(desan_api_factory: DesanApiFactory) -> None:
    async with desan_api_factory({"PRIVYFLOW_DESAN_MAX_REQUEST_BYTES": "1024"}) as api:
        response = await api.restore("x" * 2000)
        _seeded(api)
        at_limit = await api.restore("[EMAIL_001]")
    assert _error(response, 413, "payload_too_large")
    assert at_limit.status_code == 200
    assert api.stub.calls and len(api.stub.calls) == 1


async def test_a_body_declaring_a_huge_length_is_refused_before_it_is_read(
    desan_api_factory: DesanApiFactory,
) -> None:
    async with desan_api_factory({"PRIVYFLOW_DESAN_MAX_REQUEST_BYTES": "1024"}) as api:
        response = await api.client.post(
            "/api/v1/desanitizations",
            content=b"{}",
            headers={**api.headers(), "Content-Length": "99999999"},
        )
    assert response.status_code == 413


async def test_restored_text_over_the_output_limit_gets_413(
    desan_api_factory: DesanApiFactory,
) -> None:
    async with desan_api_factory({"PRIVYFLOW_DESAN_MAX_OUTPUT_BYTES": "2048"}) as api:
        api.stub.add(REFERENCE, TENANT_A, SCOPE, {"[EMAIL_001]": "x" * 1500})
        ok = await api.restore("[EMAIL_001]")
        too_big = await api.restore("[EMAIL_001] [EMAIL_001]")
    assert ok.status_code == 200
    assert _error(too_big, 413, "output_too_large")
    assert "xxxx" not in too_big.text


# --- readiness --------------------------------------------------------------------------------


async def test_readiness_is_ok_with_valid_configuration(desan_api: DesanApi) -> None:
    response = await desan_api.client.get("/health/ready")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})


@pytest.mark.parametrize(
    "override",
    [
        {"PRIVYFLOW_DESAN_API_KEYS": None},
        {"PRIVYFLOW_DESAN_SERVICE_SECRET": None},
        {"PRIVYFLOW_DESAN_API_KEYS": "not json"},
        {"PRIVYFLOW_DESAN_SERVICE_SECRET": "short"},
        {"PRIVYFLOW_DESAN_SERVICE_SECRET": DESAN_API_KEYS[TENANT_A]},
        {"PRIVYFLOW_DESAN_MAX_REQUEST_BYTES": "10"},
    ],
    ids=["no_keys", "no_secret", "bad_keys", "weak_secret", "secret_is_a_key", "bad_limit"],
)
async def test_the_service_is_alive_but_not_ready_when_a_secret_or_limit_is_wrong(
    desanitization_app_factory: AppFactory, override: dict[str, str | None]
) -> None:
    app = desanitization_app_factory(override)
    async with client_for(app) as client:
        live = await client.get("/health/live")
        ready = await client.get("/health/ready")
        restore = await client.post("/api/v1/desanitizations", json={}, headers={"X-API-Key": "k"})
    assert live.status_code == 200
    assert (ready.status_code, ready.json()) == (503, {"status": "unavailable"})
    assert restore.status_code == 503
    assert restore.json()["error"]["code"] == "dependency_unavailable"


async def test_readiness_does_not_call_the_sanitization_service(desan_api: DesanApi) -> None:
    await desan_api.client.get("/health/ready")
    assert desan_api.stub.calls == []


def test_the_default_environment_names_no_database_setting() -> None:
    assert not [name for name in desanitization_env() if "DATABASE" in name]
