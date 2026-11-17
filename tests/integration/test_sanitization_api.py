"""POST /api/v1/sanitizations and GET /api/v1/policies, through the real app.

The vault runs its real cryptography over an in-memory store, so none of this needs a database.
Rows in PostgreSQL are covered by test_mapping_repository.py.
"""

import importlib
import json
import re
from typing import Any

import pytest

from tests.conftest import AppFactory, VaultApiFactory, client_for
from tests.support.leak import CANARIES, assert_no_leak
from tests.support.placeholders import restore_in_memory
from tests.support.vault_api import VaultApi
from tests.support.vault_env import API_KEYS, TENANT_A, TENANT_B, TENANT_C

pytestmark = pytest.mark.anyio

EMAIL, PHONE = CANARIES[1], CANARIES[2]
SSN = "900-12-3456"  # area 900 is never issued; accepted by the recognizer on purpose
TEXT = f"Write to {EMAIL} or call {PHONE}."
REFERENCE = re.compile(r"^pf1_[A-Za-z0-9_-]{43}$")
ERROR_KEYS = {"code", "message", "correlation_id"}


def _assert_standard_error(response: Any, status: int, code: str) -> None:
    body = response.json()
    assert response.status_code == status
    assert set(body) == {"error"}
    assert set(body["error"]) == ERROR_KEYS
    assert body["error"]["code"] == code
    assert body["error"]["correlation_id"] == response.headers["X-Correlation-ID"]


# --- valid requests -----------------------------------------------------------------------


async def test_valid_request_returns_sanitized_text_and_a_restore_reference(
    vault_api: VaultApi,
) -> None:
    response = await vault_api.sanitize(TEXT)
    body = response.json()
    assert response.status_code == 200
    assert set(body) == {
        "sanitized_text",
        "restore_reference",
        "expires_at",
        "profiles_applied",
        "uncovered_entity_types",
        "entity_count",
        "correlation_id",
    }
    assert body["sanitized_text"] == "Write to [EMAIL_001] or call [PHONE_001]."
    assert REFERENCE.match(body["restore_reference"])
    assert body["entity_count"] == 2
    assert body["profiles_applied"] == ["gdpr"]
    assert "PERSON" in body["uncovered_entity_types"]
    assert body["correlation_id"] == response.headers["X-Correlation-ID"]
    assert response.headers["Cache-Control"] == "no-store"
    assert_no_leak(response.text)


async def test_the_stored_mapping_restores_the_original_text(vault_api: VaultApi) -> None:
    body = (await vault_api.sanitize(TEXT)).json()
    mappings = vault_api.vault.retrieve(body["restore_reference"], TENANT_A, "scope-api-test")
    assert mappings == {"[EMAIL_001]": EMAIL, "[PHONE_001]": PHONE}
    assert restore_in_memory(body["sanitized_text"], mappings) == TEXT


async def test_repeated_value_gets_one_placeholder_and_is_counted_each_time(
    vault_api: VaultApi,
) -> None:
    body = (await vault_api.sanitize(f"{EMAIL} and again {EMAIL}")).json()
    assert body["sanitized_text"] == "[EMAIL_001] and again [EMAIL_001]"
    assert body["entity_count"] == 2


async def test_each_call_creates_a_new_reference_and_record(vault_api: VaultApi) -> None:
    first = (await vault_api.sanitize(TEXT)).json()["restore_reference"]
    second = (await vault_api.sanitize(TEXT)).json()["restore_reference"]
    assert first != second
    assert len(vault_api.store.rows) == 2


@pytest.mark.parametrize("text", ["nothing sensitive here", "   \n\t "])
async def test_text_with_no_entities_stores_nothing_and_returns_a_null_reference(
    vault_api: VaultApi, text: str
) -> None:
    response = await vault_api.sanitize(text)
    body = response.json()
    assert response.status_code == 200
    assert body["sanitized_text"] == text
    assert body["restore_reference"] is None
    assert body["expires_at"] is None
    assert body["entity_count"] == 0
    assert vault_api.store.rows == {}


async def test_the_stored_record_names_the_profiles_and_settings_in_force(
    vault_api: VaultApi,
) -> None:
    await vault_api.sanitize(TEXT, tenant=TENANT_B)
    (row,) = vault_api.store.rows.values()
    assert row.record.profiles["profiles"] == [
        {"id": "gdpr", "version": 1},
        {"id": "hipaa", "version": 1},
    ]
    assert row.record.profiles["settings_version"] == 0
    assert len(row.record.profiles["settings_hash"]) == 64


# --- authentication ------------------------------------------------------------------------


@pytest.mark.parametrize("header", [None, "", "wrong-key", "x" * 40])
async def test_missing_or_wrong_api_key_is_401_and_stores_nothing(
    vault_api: VaultApi, header: str | None
) -> None:
    headers = {"Content-Type": "application/json"}
    if header is not None:
        headers["X-API-Key"] = header
    body = {"text": TEXT, "request_scope_id": "s1", "policy_id": "effective"}
    response = await vault_api.client.post("/api/v1/sanitizations", json=body, headers=headers)
    _assert_standard_error(response, 401, "unauthorized")
    assert vault_api.store.rows == {}
    assert_no_leak(response.text)


async def test_authentication_is_checked_before_the_body(vault_api: VaultApi) -> None:
    response = await vault_api.client.post(
        "/api/v1/sanitizations", content=b"{not json", headers={"X-API-Key": "wrong"}
    )
    _assert_standard_error(response, 401, "unauthorized")


async def test_a_bearer_token_or_other_header_does_not_authenticate(vault_api: VaultApi) -> None:
    key = API_KEYS[TENANT_A]
    body = {"text": TEXT, "request_scope_id": "s1", "policy_id": "effective"}
    for headers in ({"Authorization": f"Bearer {key}"}, {"X-Service-Secret": key}):
        response = await vault_api.client.post("/api/v1/sanitizations", json=body, headers=headers)
        _assert_standard_error(response, 401, "unauthorized")


async def test_the_api_key_in_the_query_string_does_not_authenticate(vault_api: VaultApi) -> None:
    body = {"text": TEXT, "request_scope_id": "s1", "policy_id": "effective"}
    response = await vault_api.client.post(
        f"/api/v1/sanitizations?api_key={API_KEYS[TENANT_A]}", json=body
    )
    _assert_standard_error(response, 401, "unauthorized")


async def test_the_tenant_is_taken_from_the_key(vault_api: VaultApi) -> None:
    await vault_api.sanitize(TEXT, tenant=TENANT_A)
    await vault_api.sanitize(TEXT, tenant=TENANT_B)
    assert sorted(r.record.tenant_id for r in vault_api.store.rows.values()) == [
        TENANT_A,
        TENANT_B,
    ]


@pytest.mark.parametrize("field", ["tenant_id", "tenant", "profiles", "profile_ids"])
async def test_a_body_that_names_a_tenant_or_profiles_is_rejected_and_stores_nothing(
    vault_api: VaultApi, field: str
) -> None:
    value: Any = [TENANT_A] if field == "profiles" else TENANT_A
    body = {"text": TEXT, "request_scope_id": "s1", "policy_id": "effective", field: value}
    response = await vault_api.client.post(
        "/api/v1/sanitizations", json=body, headers=vault_api.headers(TENANT_B)
    )
    _assert_standard_error(response, 422, "validation_error")
    assert vault_api.store.rows == {}


# --- validation, size and policy id ----------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"text": "", "request_scope_id": "s1", "policy_id": "effective"},
        {"request_scope_id": "s1", "policy_id": "effective"},
        {"text": "x", "policy_id": "effective"},
        {"text": "x", "request_scope_id": "s1"},
        {"text": 5, "request_scope_id": "s1", "policy_id": "effective"},
        {"text": None, "request_scope_id": "s1", "policy_id": "effective"},
        {"text": "x", "request_scope_id": "", "policy_id": "effective"},
        {"text": "x", "request_scope_id": "bad scope!", "policy_id": "effective"},
        {"text": "x", "request_scope_id": "s" * 129, "policy_id": "effective"},
        {"text": "x", "request_scope_id": "s1", "policy_id": 1},
        {"text": "x", "request_scope_id": "s1", "policy_id": "effective", "extra": 1},
        [],
        "text",
        None,
    ],
    ids=[
        "empty_text",
        "missing_text",
        "missing_scope",
        "missing_policy",
        "number_text",
        "null_text",
        "empty_scope",
        "bad_scope",
        "long_scope",
        "number_policy",
        "unknown_field",
        "list_body",
        "string_body",
        "null_body",
    ],
)
async def test_invalid_input_is_a_422_with_the_standard_body(
    vault_api: VaultApi, body: Any
) -> None:
    response = await vault_api.client.post(
        "/api/v1/sanitizations", json=body, headers=vault_api.headers()
    )
    _assert_standard_error(response, 422, "validation_error")
    assert response.json()["error"]["message"] == "The request is not valid."
    assert vault_api.store.rows == {}


@pytest.mark.parametrize("content", [b"", b"{not json", b"\xff\xfe", b'{"text": "unterminated'])
async def test_a_body_that_is_not_json_is_a_422(vault_api: VaultApi, content: bytes) -> None:
    response = await vault_api.client.post(
        "/api/v1/sanitizations", content=content, headers=vault_api.headers()
    )
    _assert_standard_error(response, 422, "validation_error")


async def test_validation_errors_never_echo_the_input(vault_api: VaultApi) -> None:
    response = await vault_api.client.post(
        "/api/v1/sanitizations",
        json={"text": EMAIL, "request_scope_id": f"{PHONE} bad", "policy_id": "effective"},
        headers=vault_api.headers(),
    )
    assert response.status_code == 422
    assert_no_leak(response.text)


@pytest.mark.parametrize("policy_id", ["strict", "gdpr", "hipaa", "Effective", "", " effective"])
async def test_a_policy_other_than_effective_is_unsupported(
    vault_api: VaultApi, policy_id: str
) -> None:
    response = await vault_api.sanitize(TEXT, policy_id=policy_id)
    _assert_standard_error(response, 422, "unsupported_policy")
    assert vault_api.store.rows == {}


async def test_a_body_over_the_size_limit_is_a_413(
    vault_api_factory: VaultApiFactory,
) -> None:
    async with vault_api_factory(max_request_bytes=1024) as api:
        response = await api.sanitize("a" * 1100)
        _assert_standard_error(response, 413, "payload_too_large")
        assert api.store.rows == {}
        assert (await api.sanitize("a" * 100)).status_code == 200


# --- policy: two tenants, lifetime, redaction ----------------------------------------------------


async def test_two_tenants_with_different_profiles_get_different_masking(
    vault_api: VaultApi,
) -> None:
    text = f"Mail {EMAIL}, SSN {SSN}."
    a = (await vault_api.sanitize(text, tenant=TENANT_A)).json()
    b = (await vault_api.sanitize(text, tenant=TENANT_B)).json()
    c = (await vault_api.sanitize(text, tenant=TENANT_C)).json()
    assert a["sanitized_text"] == f"Mail [EMAIL_001], SSN {SSN}."  # gdpr does not name US_SSN
    assert b["sanitized_text"] == "Mail [EMAIL_001], SSN [US_SSN_001]."  # hipaa does
    assert c["sanitized_text"] == a["sanitized_text"]  # no entry: the default profile only
    assert a["profiles_applied"] == ["gdpr"]
    assert b["profiles_applied"] == ["gdpr", "hipaa"]
    assert c["profiles_applied"] == ["gdpr"]


async def test_stored_expiry_is_the_smallest_profile_lifetime(
    vault_api_factory: VaultApiFactory,
) -> None:
    async with vault_api_factory(default_ttl_seconds=3600) as api:
        a = (await api.sanitize(TEXT, tenant=TENANT_A)).json()  # gdpr: 3600
        b = (await api.sanitize(TEXT, tenant=TENANT_B)).json()  # gdpr + hipaa: min(3600, 1800)
    seconds = {
        row.record.tenant_id: (row.record.expires_at - row.record.created_at).total_seconds()
        for row in api.store.rows.values()
    }
    assert seconds == {TENANT_A: 3600, TENANT_B: 1800}
    assert a["expires_at"] is not None and b["expires_at"] is not None
    assert a["expires_at"] > b["expires_at"]


async def test_stored_expiry_is_never_longer_than_the_default_ttl(
    vault_api_factory: VaultApiFactory,
) -> None:
    async with vault_api_factory(default_ttl_seconds=600) as api:
        await api.sanitize(TEXT, tenant=TENANT_A)  # gdpr allows 3600 but the default is 600
        await api.sanitize(TEXT, tenant=TENANT_B)  # hipaa allows 1800 but the default is 600
    lifetimes = {
        (r.record.expires_at - r.record.created_at).total_seconds() for r in api.store.rows.values()
    }
    assert lifetimes == {600}


class _FixedPolicy:
    """A stand-in tenant policy table with one synthetic policy for every tenant."""

    def __init__(self, policy: Any) -> None:
        self._policy = policy

    def policy_for(self, tenant_id: str) -> Any:
        return self._policy


def _synthetic_policy(**actions: str) -> Any:
    policy_module = importlib.import_module("app.sanitization.policy")
    return policy_module.EffectivePolicy(
        profiles=(("synthetic", 1),),
        actions=actions,
        max_ttl_seconds=600,
        uncovered_entity_types=(),
    )


async def test_a_redact_rule_masks_the_value_stores_nothing_and_returns_no_reference(
    vault_api: VaultApi,
) -> None:
    vault_api.app.state.policy_resolver = _FixedPolicy(_synthetic_policy(EMAIL="redact"))
    response = await vault_api.sanitize(f"Mail {EMAIL}.")
    body = response.json()
    assert body["sanitized_text"] == "Mail [EMAIL_REDACTED]."
    assert body["restore_reference"] is None
    assert body["expires_at"] is None
    assert body["entity_count"] == 1
    assert vault_api.store.rows == {}
    assert restore_in_memory(body["sanitized_text"], {}) == body["sanitized_text"]
    assert_no_leak(response.text)


async def test_a_redacted_value_is_not_in_the_vault_next_to_a_reversible_one(
    vault_api: VaultApi,
) -> None:
    vault_api.app.state.policy_resolver = _FixedPolicy(
        _synthetic_policy(EMAIL="redact", PHONE="placeholder")
    )
    body = (await vault_api.sanitize(TEXT)).json()
    assert body["sanitized_text"] == "Write to [EMAIL_REDACTED] or call [PHONE_001]."
    mappings = vault_api.vault.retrieve(body["restore_reference"], TENANT_A, "scope-api-test")
    assert mappings == {"[PHONE_001]": PHONE}
    assert body["entity_count"] == 2
    (row,) = vault_api.store.rows.values()
    assert EMAIL.encode() not in row.record.ciphertext


# --- GET /api/v1/policies -------------------------------------------------------------------------


async def test_policy_listing_is_the_calling_tenants_own_policy(vault_api: VaultApi) -> None:
    a = await vault_api.client.get("/api/v1/policies", headers=vault_api.headers(TENANT_A))
    b = await vault_api.client.get("/api/v1/policies", headers=vault_api.headers(TENANT_B))
    assert a.status_code == b.status_code == 200
    a_body, b_body = a.json(), b.json()
    assert set(a_body) == {
        "policy_id",
        "profiles",
        "entity_types",
        "max_ttl_seconds",
        "uncovered_entity_types",
    }
    assert a_body["policy_id"] == "effective"
    assert a_body["profiles"] == [{"id": "gdpr", "version": 1}]
    assert b_body["profiles"] == [{"id": "gdpr", "version": 1}, {"id": "hipaa", "version": 1}]
    assert {"type": "EMAIL", "action": "placeholder"} in a_body["entity_types"]
    assert "US_SSN" not in {e["type"] for e in a_body["entity_types"]}
    assert "US_SSN" in {e["type"] for e in b_body["entity_types"]}
    assert a_body["max_ttl_seconds"] == 1800  # the test settings default is below gdpr's 3600
    assert "PERSON" in a_body["uncovered_entity_types"]
    assert "hipaa" not in a.text
    assert b_body["entity_types"] != a_body["entity_types"]


async def test_policy_listing_never_names_a_tenant_or_another_tenants_settings(
    vault_api: VaultApi,
) -> None:
    response = await vault_api.client.get("/api/v1/policies", headers=vault_api.headers(TENANT_A))
    for text in (TENANT_A, TENANT_B, TENANT_C, API_KEYS[TENANT_A], API_KEYS[TENANT_B]):
        assert text not in response.text


async def test_policy_listing_ignores_a_tenant_in_the_query_string(vault_api: VaultApi) -> None:
    response = await vault_api.client.get(
        f"/api/v1/policies?tenant_id={TENANT_B}", headers=vault_api.headers(TENANT_A)
    )
    assert response.json()["profiles"] == [{"id": "gdpr", "version": 1}]


@pytest.mark.parametrize("header", [None, "wrong-key"])
async def test_policy_listing_needs_a_valid_key(vault_api: VaultApi, header: str | None) -> None:
    headers = {} if header is None else {"X-API-Key": header}
    response = await vault_api.client.get("/api/v1/policies", headers=headers)
    _assert_standard_error(response, 401, "unauthorized")


@pytest.mark.parametrize(
    ("method", "path"), [("get", "/api/v1/sanitizations"), ("post", "/api/v1/policies")]
)
async def test_wrong_method_is_405_in_the_standard_body(
    vault_api: VaultApi, method: str, path: str
) -> None:
    response = await getattr(vault_api.client, method)(path, headers=vault_api.headers())
    _assert_standard_error(response, 405, "method_not_allowed")


# --- failure behavior -----------------------------------------------------------------------------


async def test_database_unavailable_is_a_503_and_the_service_stays_up(
    sanitization_app_factory: AppFactory,
) -> None:
    # The default test database URL points at a closed port, so storing a mapping fails.
    async with client_for(sanitization_app_factory()) as client:
        headers = {"X-API-Key": API_KEYS[TENANT_A]}
        body = {"text": TEXT, "request_scope_id": "s1", "policy_id": "effective"}
        failed = await client.post("/api/v1/sanitizations", json=body, headers=headers)
        _assert_standard_error(failed, 503, "dependency_unavailable")
        assert_no_leak(failed.text)
        # Text with nothing to store needs no database, and the policy listing still works.
        body["text"] = "nothing sensitive"
        assert (
            await client.post("/api/v1/sanitizations", json=body, headers=headers)
        ).status_code == 200
        assert (await client.get("/api/v1/policies", headers=headers)).status_code == 200
        assert (await client.get("/health/live")).status_code == 200


@pytest.mark.parametrize(
    "variable",
    [
        "PRIVYFLOW_SAN_API_KEYS",
        "PRIVYFLOW_SAN_ENCRYPTION_KEYS",
        "PRIVYFLOW_SAN_ACTIVE_KEY_VERSION",
        "PRIVYFLOW_SAN_CREDENTIAL_PEPPER",
    ],
)
async def test_missing_secret_leaves_the_service_not_ready_and_requests_fail_closed(
    sanitization_app_factory: AppFactory, variable: str
) -> None:
    app = sanitization_app_factory({variable: None})
    async with client_for(app) as client:
        assert app.state.vault is None or app.state.authenticator is None
        assert (await client.get("/health/live")).status_code == 200
        assert (await client.get("/health/ready")).status_code == 503
        body = {"text": TEXT, "request_scope_id": "s1", "policy_id": "effective"}
        response = await client.post(
            "/api/v1/sanitizations", json=body, headers={"X-API-Key": API_KEYS[TENANT_A]}
        )
        _assert_standard_error(response, 503, "dependency_unavailable")


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("PRIVYFLOW_SAN_API_KEYS", "not json"),
        ("PRIVYFLOW_SAN_API_KEYS", json.dumps({"tenant-test-a": "short"})),
        ("PRIVYFLOW_SAN_ENCRYPTION_KEYS", "not json"),
        ("PRIVYFLOW_SAN_ENCRYPTION_KEYS", json.dumps({"1": "c2hvcnQ="})),
        ("PRIVYFLOW_SAN_ACTIVE_KEY_VERSION", "2"),
        ("PRIVYFLOW_SAN_CREDENTIAL_PEPPER", "c2hvcnQ="),
    ],
    ids=[
        "api_keys_not_json",
        "api_key_short",
        "enc_keys_not_json",
        "enc_key_short",
        "active_version_missing",
        "pepper_short",
    ],
)
async def test_malformed_secret_leaves_the_service_not_ready_without_logging_it(
    sanitization_app_factory: AppFactory,
    caplog: pytest.LogCaptureFixture,
    variable: str,
    value: str,
) -> None:
    app = sanitization_app_factory({variable: value})
    async with client_for(app):
        assert app.state.vault is None
        assert app.state.authenticator is None
    logs = "\n".join(r.getMessage() + str(r.__dict__) for r in caplog.records)
    assert "settings_load_failed" in logs
    assert value not in logs or len(value) < 12
    assert API_KEYS[TENANT_A] not in logs


async def test_valid_configuration_builds_the_vault_and_the_key_check(
    sanitization_app_factory: AppFactory,
) -> None:
    app = sanitization_app_factory()
    async with client_for(app):
        assert app.state.vault is not None
        assert app.state.authenticator is not None
