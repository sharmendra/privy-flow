"""Public API authentication: one API key per tenant (decision D2, pilot only).

The tenant comes from the key and nowhere else. Keys are compared in constant time against
every configured key, with no early exit, so timing does not show which key came close.
"""

import hmac
import json
import re
from collections.abc import Mapping
from typing import cast

from fastapi import Request

from app.core.errors import ApiError
from app.vault.errors import VaultConfigError

API_KEY_HEADER = "X-API-Key"
TENANT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,62}$")
MIN_API_KEY_LENGTH = 24


def parse_api_keys(raw: str) -> dict[str, str]:
    """`raw` is a JSON object of tenant ID to API key. Errors name no tenant and no key."""
    try:
        loaded = json.loads(raw)
    except ValueError:
        raise VaultConfigError("API keys are not valid JSON") from None
    if not isinstance(loaded, dict) or not loaded:
        raise VaultConfigError("API keys must be a non-empty JSON object")
    keys: dict[str, str] = {}
    for tenant_id, key in cast("dict[str, object]", loaded).items():
        if not TENANT_ID_PATTERN.fullmatch(tenant_id):
            raise VaultConfigError("an API key names a malformed tenant ID")
        if not isinstance(key, str) or len(key) < MIN_API_KEY_LENGTH or not key.isascii():
            raise VaultConfigError("every API key must be ASCII text of at least 24 characters")
        keys[tenant_id] = key
    if len(set(keys.values())) != len(keys):
        raise VaultConfigError("two tenants share an API key")
    return keys


class ApiKeyAuthenticator:
    def __init__(self, keys_by_tenant: Mapping[str, str]) -> None:
        self._keys = [(tenant, key.encode("ascii")) for tenant, key in keys_by_tenant.items()]

    def __repr__(self) -> str:
        return f"ApiKeyAuthenticator(tenants={len(self._keys)})"

    def tenant_for(self, presented: str | None) -> str | None:
        candidate = (presented or "").encode("utf-8")
        found: str | None = None
        # Check every key with no early exit, so timing does not reveal which key came close.
        for tenant, key in self._keys:
            if hmac.compare_digest(candidate, key):
                found = tenant
        return found


def authenticated_tenant(request: Request) -> str:
    """FastAPI dependency: the tenant of the caller's API key, or a 401."""
    authenticator: ApiKeyAuthenticator | None = getattr(request.app.state, "authenticator", None)
    if authenticator is None:
        raise ApiError(503, "dependency_unavailable", "The service is not ready.")
    tenant_id = authenticator.tenant_for(request.headers.get(API_KEY_HEADER))
    if tenant_id is None:
        raise ApiError(401, "unauthorized", "Authentication failed.")
    return tenant_id
