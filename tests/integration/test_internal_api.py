"""POST /internal/v1/mappings/retrieve through the real Sanitization app.

The vault runs its real cryptography over an in-memory store, so none of this needs a database.
The stored rows and a real PostgreSQL are covered by test_mapping_repository.py and by the
end-to-end suite.
"""

import re
from typing import Any

import pytest

from tests.conftest import AppFactory, VaultApiFactory, client_for
from tests.support.contracts import assert_conforms, conforms, load_contract
from tests.support.leak import CANARIES, assert_no_leak
from tests.support.routes import http_routes
from tests.support.vault_api import SCOPE, VaultApi
from tests.support.vault_env import API_KEYS, SERVICE_SECRET, TENANT_A, TENANT_B

pytestmark = pytest.mark.anyio

EMAIL, PHONE = CANARIES[1], CANARIES[2]
TEXT = f"Write to {EMAIL} or call {PHONE}."
EXPECTED = [
    {"placeholder": "[EMAIL_001]", "value": EMAIL},
    {"placeholder": "[PHONE_001]", "value": PHONE},
]
ERROR_KEYS = {"code", "message", "correlation_id"}
UNKNOWN_REFERENCE = "pf1_" + "A" * 43


async def _reference(api: VaultApi, tenant: str = TENANT_A, scope: str = SCOPE) -> str:
    return (await api.sanitize(TEXT, tenant=tenant, scope=scope)).json()["restore_reference"]


def _normalized_error(response: Any) -> dict[str, Any]:
    """The error body with the per-request correlation ID replaced by a constant."""
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == ERROR_KEYS
    assert body["error"]["correlation_id"] == response.headers["X-Correlation-ID"]
    return {"error": {**body["error"], "correlation_id": "-"}}


# --- success --------------------------------------------------------------------------------


async def test_a_valid_request_returns_the_mappings_and_the_policy_id(vault_api: VaultApi) -> None:
    reference = await _reference(vault_api)
    response = await vault_api.retrieve(reference)
    body = response.json()
    assert response.status_code == 200
    assert sorted(body["mappings"], key=lambda m: m["placeholder"]) == EXPECTED
    assert body["policy_id"] == "effective"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Correlation-ID"]


async def test_the_response_has_exactly_the_documented_fields(vault_api: VaultApi) -> None:
    body = (await vault_api.retrieve(await _reference(vault_api))).json()
    assert set(body) == {"mappings", "policy_id"}
    assert all(set(item) == {"placeholder", "value"} for item in body["mappings"])


async def test_a_reference_can_be_retrieved_again_within_its_lifetime(vault_api: VaultApi) -> None:
    reference = await _reference(vault_api)
    first = await vault_api.retrieve(reference)
    second = await vault_api.retrieve(reference)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


async def test_the_response_echoes_a_safe_correlation_id(vault_api: VaultApi) -> None:
    reference = await _reference(vault_api)
    headers = {**vault_api.internal_headers(), "X-Correlation-ID": "caller-corr-0001"}
    response = await vault_api.retrieve(reference, headers=headers)
    assert response.headers["X-Correlation-ID"] == "caller-corr-0001"


# --- authentication ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Service-Secret": "wrong-" + SERVICE_SECRET},
        {"X-Service-Secret": ""},
        {"X-API-Key": API_KEYS[TENANT_A]},
        {"X-Service-Secret": API_KEYS[TENANT_A]},
        {"Authorization": f"Bearer {SERVICE_SECRET}"},
    ],
    ids=["none", "wrong_secret", "empty_secret", "client_key_header", "client_key_value", "bearer"],
)
async def test_a_request_without_the_service_secret_gets_401(
    vault_api: VaultApi, headers: dict[str, str]
) -> None:
    reference = await _reference(vault_api)
    response = await vault_api.retrieve(reference, headers={**headers})
    assert response.status_code == 401
    assert _normalized_error(response)["error"]["code"] == "unauthorized"
    assert_no_leak(response.text, [EMAIL, PHONE, reference])


async def test_authentication_runs_before_the_body_is_read(vault_api: VaultApi) -> None:
    response = await vault_api.client.post(
        "/internal/v1/mappings/retrieve", content=b"not json at all"
    )
    assert response.status_code == 401


# --- non-disclosure ---------------------------------------------------------------------------


async def _make_unknown(api: VaultApi, tenant: str, scope: str) -> dict[str, Any]:
    return {"reference": UNKNOWN_REFERENCE, "tenant": tenant, "scope": scope}


async def _make_expired(api: VaultApi, tenant: str, scope: str) -> dict[str, Any]:
    reference = await _reference(api, tenant, scope)
    api.clock.advance(7200)
    return {"reference": reference, "tenant": tenant, "scope": scope}


async def _make_revoked(api: VaultApi, tenant: str, scope: str) -> dict[str, Any]:
    reference = await _reference(api, tenant, scope)
    assert api.vault.revoke(reference, tenant)
    return {"reference": reference, "tenant": tenant, "scope": scope}


async def _make_deleted(api: VaultApi, tenant: str, scope: str) -> dict[str, Any]:
    reference = await _reference(api, tenant, scope)
    assert api.vault.mark_deleted(reference, tenant)
    return {"reference": reference, "tenant": tenant, "scope": scope}


async def _make_wrong_tenant(api: VaultApi, tenant: str, scope: str) -> dict[str, Any]:
    reference = await _reference(api, tenant, scope)
    return {"reference": reference, "tenant": TENANT_B, "scope": scope}


async def _make_wrong_scope(api: VaultApi, tenant: str, scope: str) -> dict[str, Any]:
    reference = await _reference(api, tenant, scope)
    return {"reference": reference, "tenant": tenant, "scope": "some-other-scope"}


async def _make_malformed(api: VaultApi, tenant: str, scope: str) -> dict[str, Any]:
    return {"reference": f"not-a-reference-{EMAIL}", "tenant": tenant, "scope": scope}


async def _make_tampered(api: VaultApi, tenant: str, scope: str) -> dict[str, Any]:
    reference = await _reference(api, tenant, scope)
    (row,) = api.store.rows.values()
    flipped = bytes([row.record.ciphertext[0] ^ 1]) + row.record.ciphertext[1:]
    api.store.tamper(ciphertext=flipped)
    return {"reference": reference, "tenant": tenant, "scope": scope}


CAUSES = {
    "unknown": _make_unknown,
    "expired": _make_expired,
    "revoked": _make_revoked,
    "deleted": _make_deleted,
    "wrong_tenant": _make_wrong_tenant,
    "wrong_scope": _make_wrong_scope,
    "malformed": _make_malformed,
    "tampered_ciphertext": _make_tampered,
}


@pytest.mark.parametrize("cause", list(CAUSES))
async def test_every_failed_lookup_returns_the_same_404(vault_api: VaultApi, cause: str) -> None:
    case = await CAUSES[cause](vault_api, TENANT_A, SCOPE)
    response = await vault_api.retrieve(case["reference"], case["tenant"], case["scope"])
    assert response.status_code == 404
    assert _normalized_error(response) == {
        "error": {
            "code": "restore_reference_not_found",
            "message": "The restore reference was not found.",
            "correlation_id": "-",
        }
    }
    assert_no_leak(response.text, [EMAIL, PHONE, case["reference"]])


async def test_all_failure_causes_are_indistinguishable_by_status_headers_and_shape(
    vault_api_factory: VaultApiFactory,
) -> None:
    seen: set[tuple[int, str, tuple[str, ...], str]] = set()
    for make in CAUSES.values():
        async with vault_api_factory() as api:
            case = await make(api, TENANT_A, SCOPE)
            response = await api.retrieve(case["reference"], case["tenant"], case["scope"])
        seen.add(
            (
                response.status_code,
                response.headers["Content-Type"],
                tuple(sorted(k.lower() for k in response.headers)),
                str(_normalized_error(response)),
            )
        )
    assert len(seen) == 1


async def test_a_still_valid_reference_is_unaffected_by_a_failed_lookup(
    vault_api: VaultApi,
) -> None:
    reference = await _reference(vault_api)
    assert (await vault_api.retrieve(reference, tenant=TENANT_B)).status_code == 404
    assert (await vault_api.retrieve(reference)).status_code == 200


# --- validation -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation",
    [
        {"tenant_id": "Bad Tenant!"},
        {"request_scope_id": "has spaces"},
        {"request_scope_id": ""},
        {"restore_reference": 123},
        {"unexpected": "field"},
    ],
    ids=["bad_tenant", "bad_scope", "empty_scope", "reference_type", "unknown_field"],
)
async def test_an_invalid_body_gets_422_and_names_nothing(
    vault_api: VaultApi, mutation: dict[str, Any]
) -> None:
    body = {
        "restore_reference": UNKNOWN_REFERENCE,
        "tenant_id": TENANT_A,
        "request_scope_id": SCOPE,
        **mutation,
    }
    response = await vault_api.client.post(
        "/internal/v1/mappings/retrieve", json=body, headers=vault_api.internal_headers()
    )
    assert response.status_code == 422
    assert _normalized_error(response)["error"]["code"] == "validation_error"


async def test_a_body_over_the_size_limit_gets_413(vault_api_factory: VaultApiFactory) -> None:
    async with vault_api_factory(max_request_bytes=1024) as api:
        response = await api.client.post(
            "/internal/v1/mappings/retrieve",
            json={"restore_reference": "x" * 2000, "tenant_id": TENANT_A, "request_scope_id": "s"},
            headers=api.internal_headers(),
        )
    assert response.status_code == 413
    assert _normalized_error(response)["error"]["code"] == "payload_too_large"


# --- bounded response -------------------------------------------------------------------------


def _many_addresses(count: int) -> str:
    return " ".join(f"10.{n // 65536}.{(n // 256) % 256}.{n % 256}" for n in range(count))


async def test_a_request_with_exactly_the_maximum_number_of_mappings_round_trips(
    vault_api_factory: VaultApiFactory,
) -> None:
    async with vault_api_factory(max_request_bytes=262144) as api:
        sanitized = await api.sanitize(_many_addresses(10000))
        assert sanitized.status_code == 200
        response = await api.retrieve(sanitized.json()["restore_reference"])
    assert response.status_code == 200
    assert len(response.json()["mappings"]) == 10000
    assert_conforms(response.json(), "response_200")


async def test_sanitization_refuses_more_distinct_values_than_the_response_can_hold(
    vault_api_factory: VaultApiFactory,
) -> None:
    async with vault_api_factory(max_request_bytes=262144) as api:
        response = await api.sanitize(_many_addresses(10001))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert api.store.rows == {}


# --- dependency failures ---------------------------------------------------------------------


async def test_a_database_failure_gets_503_without_detail(vault_api: VaultApi) -> None:
    from sqlalchemy.exc import OperationalError

    class Failing:
        def find_active(self, *args: Any) -> Any:
            raise OperationalError(f"select {EMAIL}", {}, Exception(PHONE))

    vault_api.vault._store = Failing()  # pyright: ignore[reportPrivateUsage]
    response = await vault_api.retrieve(UNKNOWN_REFERENCE)
    assert response.status_code == 503
    assert _normalized_error(response)["error"]["code"] == "dependency_unavailable"
    assert_no_leak(response.text)


async def test_the_endpoint_is_not_ready_when_the_service_secret_is_missing(
    sanitization_app_factory: AppFactory,
) -> None:
    app = sanitization_app_factory({"PRIVYFLOW_SAN_SERVICE_SECRET": None})
    async with client_for(app) as client:
        response = await client.post(
            "/internal/v1/mappings/retrieve",
            json={
                "restore_reference": UNKNOWN_REFERENCE,
                "tenant_id": TENANT_A,
                "request_scope_id": "s",
            },
            headers={"X-Service-Secret": SERVICE_SECRET},
        )
        ready = await client.get("/health/ready")
    assert response.status_code == 503
    assert ready.status_code == 503


@pytest.mark.parametrize("secret", ["short", "has space " + "x" * 40, "é" * 40])
async def test_a_weak_or_malformed_service_secret_leaves_the_service_not_ready(
    sanitization_app_factory: AppFactory, secret: str
) -> None:
    app = sanitization_app_factory({"PRIVYFLOW_SAN_SERVICE_SECRET": secret})
    async with client_for(app) as client:
        assert (await client.get("/health/ready")).status_code == 503


async def test_a_service_secret_equal_to_a_client_api_key_leaves_the_service_not_ready(
    sanitization_app_factory: AppFactory,
) -> None:
    app = sanitization_app_factory({"PRIVYFLOW_SAN_SERVICE_SECRET": API_KEYS[TENANT_A]})
    async with client_for(app) as client:
        assert (await client.get("/health/ready")).status_code == 503


# --- the saved contract ----------------------------------------------------------------------


async def test_real_responses_conform_to_the_saved_contract(vault_api: VaultApi) -> None:
    ok = await vault_api.retrieve(await _reference(vault_api))
    missing = await vault_api.retrieve(UNKNOWN_REFERENCE)
    unauthorized = await vault_api.retrieve(UNKNOWN_REFERENCE, headers={})
    invalid = await vault_api.retrieve(UNKNOWN_REFERENCE, tenant="Bad Tenant!")
    assert_conforms(ok.json(), "response_200")
    codes = load_contract()["errors"]
    for response, status in ((missing, "404"), (unauthorized, "401"), (invalid, "422")):
        assert response.status_code == int(status)
        assert_conforms(response.json(), "error")
        assert response.json()["error"]["code"] == codes[status]


async def test_the_contract_and_the_real_endpoint_agree_on_what_a_valid_request_is(
    vault_api: VaultApi,
) -> None:
    contract = load_contract()
    example = contract["examples"]["request"]
    assert conforms(example, "request")
    assert not conforms({**example, "extra": 1}, "request")
    assert not conforms({**example, "tenant_id": "Bad Tenant!"}, "request")
    assert conforms(contract["examples"]["response_200"], "response_200")
    assert not conforms({"mappings": [], "policy_id": "effective", "extra": 1}, "response_200")
    for body in (example, {**example, "extra": 1}, {**example, "tenant_id": "Bad Tenant!"}):
        response = await vault_api.client.post(
            "/internal/v1/mappings/retrieve", json=body, headers=vault_api.internal_headers()
        )
        assert (response.status_code in (200, 404)) is conforms(body, "request")


async def test_the_contract_names_the_only_internal_route_of_the_service(
    vault_api: VaultApi,
) -> None:
    internal = [(m, p) for m, p in http_routes(vault_api.app) if p.startswith("/internal")]
    assert internal == [("POST", "/internal/v1/mappings/retrieve")]
    assert re.fullmatch(r"v\d+", load_contract()["version"])
