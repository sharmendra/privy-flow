"""Public API authentication: one API key per tenant (decision D2, pilot only).

The tenant comes from the key and nowhere else. This service has its own key list, separate
from the Sanitization Service's, so a key for one service never works on the other. Keys are
compared in constant time against every configured key, with no early exit.
"""

import hmac
import json
import re
from collections.abc import Collection, Mapping
from typing import cast

from fastapi import Request

from app.core.errors import ApiError

API_KEY_HEADER = "X-API-Key"
SERVICE_SECRET_HEADER = "X-Service-Secret"
TENANT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,62}$")
MIN_API_KEY_LENGTH = 24
MIN_SERVICE_SECRET_LENGTH = 32


class ConfigError(Exception):
    """A secret is missing or malformed. The message names no value."""


def parse_api_keys(raw: str) -> dict[str, str]:
    """`raw` is a JSON object of tenant ID to API key. Errors name no tenant and no key."""
    try:
        loaded = json.loads(raw)
    except ValueError:
        raise ConfigError("API keys are not valid JSON") from None
    if not isinstance(loaded, dict) or not loaded:
        raise ConfigError("API keys must be a non-empty JSON object")
    keys: dict[str, str] = {}
    for tenant_id, key in cast("dict[str, object]", loaded).items():
        if not TENANT_ID_PATTERN.fullmatch(tenant_id):
            raise ConfigError("an API key names a malformed tenant ID")
        if not isinstance(key, str) or len(key) < MIN_API_KEY_LENGTH or not key.isascii():
            raise ConfigError("every API key must be ASCII text of at least 24 characters")
        keys[tenant_id] = key
    if len(set(keys.values())) != len(keys):
        raise ConfigError("two tenants share an API key")
    return keys


def parse_service_secret(raw: str, api_keys: Collection[str]) -> str:
    """Check the secret is long, printable ASCII with no space, and not also a client API key."""
    if len(raw) < MIN_SERVICE_SECRET_LENGTH or not raw.isascii() or not raw.isprintable():
        raise ConfigError("the service secret must be printable ASCII of at least 32 characters")
    if " " in raw or raw in api_keys:
        raise ConfigError("the service secret must contain no space and differ from API keys")
    return raw


class ApiKeyAuthenticator:
    def __init__(self, keys_by_tenant: Mapping[str, str]) -> None:
        self._keys = [(tenant, key.encode("ascii")) for tenant, key in keys_by_tenant.items()]

    def __repr__(self) -> str:
        return f"ApiKeyAuthenticator(tenants={len(self._keys)})"

    def tenant_for(self, presented: str | None) -> str | None:
        candidate = (presented or "").encode("utf-8")
        found: str | None = None
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
