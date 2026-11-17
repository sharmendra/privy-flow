"""Security properties of the internal mapping API: route separation, isolation and leakage."""

import importlib
import itertools
import logging
from typing import Any

import pytest

from tests.support.leak import CANARIES, assert_no_leak
from tests.support.routes import http_routes
from tests.support.vault_api import VaultApi
from tests.support.vault_env import API_KEYS, SERVICE_SECRET, TENANT_A, TENANT_B, TENANT_C

pytestmark = pytest.mark.anyio

EMAIL, PHONE, CARD = CANARIES[1], CANARIES[2], CANARIES[3]
TEXT = f"Mail {EMAIL}, call {PHONE}, card {CARD}"
SECRETS_IN_PLAY = [SERVICE_SECRET, *API_KEYS.values()]
UNKNOWN_REFERENCE = "pf1_" + "B" * 43


def _captured(caplog: pytest.LogCaptureFixture) -> str:
    formatter = importlib.import_module("app.core.logging").JsonFormatter()
    return "\n".join(formatter.format(r) for r in caplog.records if r.name.startswith("privyflow"))


def _routes(api: VaultApi, prefix: str) -> list[tuple[str, str]]:
    return [(m, p) for m, p in http_routes(api.app) if p.startswith(prefix)]


async def test_no_client_api_key_works_on_any_internal_route(vault_api: VaultApi) -> None:
    routes = _routes(vault_api, "/internal")
    assert routes
    for method, path in routes:
        for tenant, key in API_KEYS.items():
            for header in ("X-API-Key", "X-Service-Secret", "Authorization"):
                response = await vault_api.client.request(
                    method, path, headers={header: key}, json={}
                )
                assert response.status_code == 401, (tenant, header)


async def test_the_service_secret_works_on_no_public_route(vault_api: VaultApi) -> None:
    routes = _routes(vault_api, "/api/v1")
    assert len(routes) >= 2
    for method, path in routes:
        for header in ("X-API-Key", "X-Service-Secret", "Authorization"):
            response = await vault_api.client.request(
                method, path, headers={header: SERVICE_SECRET}, json={}
            )
            assert response.status_code == 401, (path, header)


async def test_every_internal_and_public_route_rejects_an_unauthenticated_caller(
    vault_api: VaultApi,
) -> None:
    for method, path in _routes(vault_api, "/internal") + _routes(vault_api, "/api/v1"):
        response = await vault_api.client.request(method, path, json={})
        assert response.status_code == 401, path


async def test_no_reference_is_retrievable_across_the_tenant_and_scope_matrix_except_its_own(
    vault_api: VaultApi,
) -> None:
    tenants = (TENANT_A, TENANT_B, TENANT_C)
    scopes = ("scope-1", "scope-2")
    issued: dict[tuple[str, str], str] = {}
    for tenant, scope in itertools.product(tenants, scopes):
        sanitized = await vault_api.sanitize(TEXT, tenant=tenant, scope=scope)
        issued[(tenant, scope)] = sanitized.json()["restore_reference"]
    own: list[int] = []
    cross: list[int] = []
    for (owner, owner_scope), reference in issued.items():
        for tenant, scope in itertools.product(tenants, scopes):
            response = await vault_api.retrieve(reference, tenant, scope)
            is_own = (tenant, scope) == (owner, owner_scope)
            (own if is_own else cross).append(response.status_code)
    assert own == [200] * 6
    assert cross == [404] * 30
    assert cross.count(200) == 0


async def test_decrypted_values_never_reach_logs_or_error_bodies(
    vault_api: VaultApi, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    reference = (await vault_api.sanitize(TEXT)).json()["restore_reference"]
    responses = [
        await vault_api.retrieve(reference, TENANT_B),  # wrong tenant
        await vault_api.retrieve(reference, TENANT_A, "other"),  # wrong scope
        await vault_api.retrieve(UNKNOWN_REFERENCE),  # unknown
        await vault_api.retrieve(f"bad-{EMAIL}"),  # malformed
        await vault_api.retrieve(reference, headers={"X-Service-Secret": f"wrong-{CARD}"}),
        await vault_api.retrieve(reference, tenant=EMAIL),  # invalid tenant text
    ]
    assert [r.status_code for r in responses] == [404, 404, 404, 404, 401, 422]
    ok = await vault_api.retrieve(reference)  # the only response that carries values
    assert ok.status_code == 200
    for response in responses:
        assert_no_leak(response.text)
        assert_no_leak(response.text, [reference, UNKNOWN_REFERENCE, f"wrong-{CARD}"])
        assert_no_leak(response.text, SECRETS_IN_PLAY)
    logs = _captured(caplog)
    assert "request_completed" in logs
    assert_no_leak(logs)
    assert_no_leak(logs, [reference, UNKNOWN_REFERENCE, "pf1_", *SECRETS_IN_PLAY])


async def test_a_tampered_row_logs_a_category_only_and_returns_the_plain_404(
    vault_api: VaultApi, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    reference = (await vault_api.sanitize(TEXT)).json()["restore_reference"]
    (row,) = vault_api.store.rows.values()
    flipped = bytes([row.record.ciphertext[0] ^ 1]) + row.record.ciphertext[1:]
    vault_api.store.tamper(ciphertext=flipped)
    response = await vault_api.retrieve(reference)
    assert response.status_code == 404
    logs = _captured(caplog)
    assert "mapping_integrity_failure" in logs
    assert "MappingIntegrityError" in logs
    assert_no_leak(logs)
    assert_no_leak(response.text)


async def test_an_unexpected_error_in_retrieval_is_a_standard_500_without_values(
    vault_api: VaultApi, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    class Boom:
        def find_active(self, *args: Any) -> Any:
            raise RuntimeError(f"boom {EMAIL} {PHONE} {SERVICE_SECRET}")

    vault_api.vault._store = Boom()  # pyright: ignore[reportPrivateUsage]
    response = await vault_api.retrieve(UNKNOWN_REFERENCE)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "Traceback" not in response.text
    assert_no_leak(response.text)
    assert_no_leak(response.text, SECRETS_IN_PLAY)
    assert_no_leak(_captured(caplog))
    assert_no_leak(_captured(caplog), SECRETS_IN_PLAY)
