"""Security properties of the public sanitization API and the vault behind it.

Leakage: canary values must not reach logs or error bodies. Isolation: a reference works for
exactly one tenant and one request scope. Neither needs a database.
"""

import importlib
import itertools
import logging
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from tests.conftest import VaultApiFactory
from tests.support.leak import CANARIES, assert_no_leak
from tests.support.vault_api import VaultApi
from tests.support.vault_env import API_KEYS, TENANT_A, TENANT_B, TENANT_C

pytestmark = pytest.mark.anyio

EMAIL, PHONE, CARD = CANARIES[1], CANARIES[2], CANARIES[3]
TEXT = f"Mail {EMAIL}, call {PHONE}, card {CARD}"


def _captured(caplog: pytest.LogCaptureFixture) -> str:
    formatter = importlib.import_module("app.core.logging").JsonFormatter()
    return "\n".join(formatter.format(record) for record in caplog.records)


async def test_a_successful_request_logs_no_text_value_reference_or_key(
    vault_api: VaultApi, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    response = await vault_api.sanitize(TEXT)
    reference = response.json()["restore_reference"]
    logs = _captured(caplog)
    assert "request_completed" in logs
    assert_no_leak(logs)
    assert_no_leak(logs, [reference, *API_KEYS.values(), "pf1_"])


@pytest.mark.parametrize("failure", ["bad_key", "bad_body", "bad_policy", "too_large"])
async def test_failed_requests_log_and_return_no_canary(
    vault_api_factory: VaultApiFactory, caplog: pytest.LogCaptureFixture, failure: str
) -> None:
    caplog.set_level(logging.DEBUG)
    async with vault_api_factory(max_request_bytes=1024) as api:
        body: dict[str, Any] = {"text": TEXT, "request_scope_id": "s1", "policy_id": "effective"}
        headers = api.headers()
        if failure == "bad_key":
            headers = {"X-API-Key": f"wrong-{CARD}"}
        elif failure == "bad_body":
            body["request_scope_id"] = f"{EMAIL} invalid scope"
        elif failure == "bad_policy":
            body["policy_id"] = f"unknown-{PHONE}"
        else:
            body["text"] = TEXT + "x" * 2000
        response = await api.client.post("/api/v1/sanitizations", json=body, headers=headers)
    assert response.status_code in (401, 413, 422)
    assert_no_leak(response.text)
    assert_no_leak(response.text, [headers["X-API-Key"]])
    assert_no_leak(_captured(caplog))
    assert_no_leak(_captured(caplog), [headers["X-API-Key"], f"unknown-{PHONE}"])


class _FailingStore:
    """A store whose failures carry sensitive text, as a driver message might."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def add(self, record: Any) -> None:
        raise self._error


async def test_a_database_error_carrying_text_is_neither_logged_nor_returned(
    vault_api: VaultApi, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    leaky = OperationalError(f"INSERT ... {EMAIL}", {"value": PHONE}, Exception(CARD))
    crypto = importlib.import_module("app.vault.crypto")
    vault_module = importlib.import_module("app.vault.vault")
    keyring = crypto.Keyring({1: b"k" * 32}, 1)
    vault_api.app.state.vault = vault_module.Vault(_FailingStore(leaky), keyring, b"p" * 32)
    response = await vault_api.sanitize(TEXT)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"
    assert_no_leak(response.text)
    logs = _captured(caplog)
    assert_no_leak(logs)
    assert "OperationalError" in logs  # the category is logged, the message is not


async def test_an_unexpected_error_is_a_standard_500_without_text_or_trace(
    vault_api: VaultApi, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    crypto = importlib.import_module("app.vault.crypto")
    vault_module = importlib.import_module("app.vault.vault")
    keyring = crypto.Keyring({1: b"k" * 32}, 1)
    broken = vault_module.Vault(
        _FailingStore(RuntimeError(f"boom {EMAIL} {PHONE}")), keyring, b"p" * 32
    )
    vault_api.app.state.vault = broken
    response = await vault_api.sanitize(TEXT)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "Traceback" not in response.text
    assert_no_leak(response.text)
    assert_no_leak(_captured(caplog))


async def test_no_reference_works_across_the_tenant_and_scope_matrix_except_its_own(
    vault_api: VaultApi,
) -> None:
    tenants = (TENANT_A, TENANT_B, TENANT_C)
    scopes = ("scope-1", "scope-2")
    issued: dict[tuple[str, str], str] = {}
    for tenant, scope in itertools.product(tenants, scopes):
        response = await vault_api.sanitize(TEXT, tenant=tenant, scope=scope)
        issued[(tenant, scope)] = response.json()["restore_reference"]
    successes = 0
    for (owner, owner_scope), reference in issued.items():
        for tenant, scope in itertools.product(tenants, scopes):
            found = vault_api.vault.retrieve(reference, tenant, scope)
            if (tenant, scope) == (owner, owner_scope):
                assert found is not None
            elif found is not None:
                successes += 1
    assert successes == 0


async def test_each_tenants_references_are_independent_of_the_others(
    vault_api: VaultApi,
) -> None:
    a = (await vault_api.sanitize(TEXT, tenant=TENANT_A)).json()["restore_reference"]
    b = (await vault_api.sanitize(TEXT, tenant=TENANT_B)).json()["restore_reference"]
    assert a != b
    assert vault_api.vault.revoke(a, TENANT_B) is False  # tenant B cannot revoke A's reference
    assert vault_api.vault.retrieve(a, TENANT_A, "scope-api-test") is not None
