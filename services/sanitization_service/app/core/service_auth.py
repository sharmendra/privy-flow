"""Authentication of the De-sanitization Service on the internal API (decision D3, pilot only).

One shared secret in the `X-Service-Secret` header, compared in constant time. It is separate
from every client API key, so a client key cannot call an internal route and the service
secret cannot call a public one.
"""

import hmac
from collections.abc import Collection

from fastapi import Request

from app.core.errors import ApiError
from app.vault.errors import VaultConfigError

SERVICE_SECRET_HEADER = "X-Service-Secret"
MIN_SERVICE_SECRET_LENGTH = 32


def parse_service_secret(raw: str, api_keys: Collection[str]) -> str:
    """Check the secret is long, ASCII, without whitespace, and not also a client API key."""
    if len(raw) < MIN_SERVICE_SECRET_LENGTH or not raw.isascii() or not raw.isprintable():
        raise VaultConfigError(
            "the service secret must be printable ASCII of at least 32 characters"
        )
    if " " in raw or raw in api_keys:
        raise VaultConfigError("the service secret must contain no space and differ from API keys")
    return raw


class ServiceSecretAuthenticator:
    def __init__(self, secret: str) -> None:
        self._secret = secret.encode("ascii")

    def __repr__(self) -> str:
        return "ServiceSecretAuthenticator()"

    def is_valid(self, presented: str | None) -> bool:
        return hmac.compare_digest((presented or "").encode("utf-8"), self._secret)


def require_internal_caller(request: Request) -> None:
    """FastAPI dependency: the caller presented the service secret, or a 401."""
    authenticator: ServiceSecretAuthenticator | None = getattr(
        request.app.state, "service_authenticator", None
    )
    if authenticator is None:
        raise ApiError(503, "dependency_unavailable", "The service is not ready.")
    if not authenticator.is_valid(request.headers.get(SERVICE_SECRET_HEADER)):
        raise ApiError(401, "unauthorized", "Authentication failed.")
