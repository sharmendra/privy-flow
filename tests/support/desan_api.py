"""A running De-sanitization app wired to a stub of the Sanitization Service's internal API.

The app, authentication, internal client (retries, timeout, parsing) and restorer are the real
code. Only the HTTP transport underneath the client is replaced, so the stub sits at the HTTP
boundary as docs/CODE_STANDARDS.md requires. The stub follows the saved contract; the real
endpoint is checked against that contract by the Sanitization tests and the two services run
together in the end-to-end suite.
"""

import importlib
from dataclasses import dataclass
from typing import Any

import httpx

from tests.support.desan_env import DESAN_API_KEYS
from tests.support.sanitization_stub import SanitizationStub
from tests.support.vault_env import SERVICE_SECRET, TENANT_A

SCOPE = "scope-desan-test"
REFERENCE = "pf1_" + "A" * 43
OTHER_REFERENCE = "pf1_" + "B" * 43


@dataclass
class DesanApi:
    app: Any
    client: httpx.AsyncClient
    stub: SanitizationStub

    @staticmethod
    def headers(tenant: str = TENANT_A) -> dict[str, str]:
        return {"X-API-Key": DESAN_API_KEYS[tenant], "Content-Type": "application/json"}

    async def restore(
        self,
        text: str,
        reference: str = REFERENCE,
        tenant: str = TENANT_A,
        scope: str = SCOPE,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> httpx.Response:
        body = {
            "sanitized_text": text,
            "restore_reference": reference,
            "request_scope_id": scope,
            **extra,
        }
        return await self.client.post(
            "/api/v1/desanitizations",
            json=body,
            headers=self.headers(tenant) if headers is None else headers,
        )


async def install_stub(app: Any, stub: SanitizationStub) -> None:
    """Replace the app's internal client with one whose transport is the stub. Retries do not
    wait, so tests need no sleeping."""
    client_module = importlib.import_module("app.clients.sanitization")
    previous = app.state.sanitization_client
    app.state.sanitization_client = client_module.SanitizationClient(
        "http://sanitization.test",
        SERVICE_SECRET,
        timeout_seconds=1.0,
        transport=stub.transport(),
        retry_delay_seconds=0,
    )
    if previous is not None:
        await previous.aclose()
