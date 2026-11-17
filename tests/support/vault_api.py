"""A running Sanitization app wired to an in-memory vault store, for API-level tests.

The app, authentication, policy, sanitizer, credentials and encryption are the real code. Only
the storage boundary is replaced, so these tests need no database. Tests of the SQL repository
and of the stored rows use a real PostgreSQL (tests/integration/test_mapping_repository.py).
"""

import importlib
from dataclasses import dataclass
from typing import Any

import httpx

from tests.support.vault_env import API_KEYS, KEY_V1, PEPPER, TENANT_A
from tests.support.vault_fakes import FakeClock, InMemoryMappingStore

SCOPE = "scope-api-test"


@dataclass
class VaultApi:
    app: Any
    client: httpx.AsyncClient
    store: InMemoryMappingStore
    clock: FakeClock
    vault: Any

    @staticmethod
    def headers(tenant: str = TENANT_A) -> dict[str, str]:
        return {"X-API-Key": API_KEYS[tenant], "Content-Type": "application/json"}

    async def sanitize(
        self,
        text: str,
        tenant: str = TENANT_A,
        scope: str = SCOPE,
        policy_id: str = "effective",
        **extra: Any,
    ) -> httpx.Response:
        body = {"text": text, "request_scope_id": scope, "policy_id": policy_id, **extra}
        return await self.client.post(
            "/api/v1/sanitizations", json=body, headers=self.headers(tenant)
        )


def install_in_memory_vault(app: Any) -> tuple[InMemoryMappingStore, FakeClock, Any]:
    """Replace the app's vault with one over an in-memory store and a fake clock."""
    repositories = importlib.import_module("app.repositories.mapping_repository")
    crypto = importlib.import_module("app.vault.crypto")
    vault_module = importlib.import_module("app.vault.vault")
    store = InMemoryMappingStore(repositories.StoredMappingRecord)
    clock = FakeClock()
    vault = vault_module.Vault(store, crypto.Keyring({1: KEY_V1}, 1), PEPPER, clock)
    app.state.vault = vault
    return store, clock, vault
