"""Client for the Sanitization Service's internal mapping API (SPEC 9.5 and 9.6).

The only way this service obtains a mapping. It authenticates with the service secret, passes
the correlation ID on, and applies a timeout to every attempt. Only connection errors and a 503
are retried, at most twice, because the call only reads. A read timeout, any other status and an
unreadable response are not retried. Failures carry a category and nothing from the request or
the response.
"""

import asyncio

import httpx
from pydantic import ValidationError

from app.core.auth import SERVICE_SECRET_HEADER
from app.core.errors import CORRELATION_HEADER
from app.schemas.internal_api import MappingResponse

RETRIEVE_PATH = "/internal/v1/mappings/retrieve"
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 0.1


class ReferenceNotFoundError(Exception):
    """The Sanitization Service has no active mapping for this reference, tenant and scope."""


class SanitizationUnavailableError(Exception):
    """The Sanitization Service could not give a usable answer. `category` is safe to log."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class SanitizationClient:
    def __init__(
        self,
        base_url: str,
        service_secret: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = MAX_RETRIES,
        retry_delay_seconds: float = RETRY_DELAY_SECONDS,
    ) -> None:
        self._secret = service_secret
        self._max_retries = max_retries
        self._retry_delay = retry_delay_seconds
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            follow_redirects=False,
        )

    def __repr__(self) -> str:
        return "SanitizationClient()"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def retrieve(
        self, reference: str, tenant_id: str, request_scope_id: str, correlation_id: str
    ) -> dict[str, str]:
        """The mappings for the reference, or ReferenceNotFoundError, or
        SanitizationUnavailableError."""
        body = {
            "restore_reference": reference,
            "tenant_id": tenant_id,
            "request_scope_id": request_scope_id,
        }
        headers = {SERVICE_SECRET_HEADER: self._secret, CORRELATION_HEADER: correlation_id}
        category = "Unknown"
        for attempt in range(self._max_retries + 1):
            if attempt:
                await asyncio.sleep(self._retry_delay)
            try:
                response = await self._client.post(RETRIEVE_PATH, json=body, headers=headers)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                category = type(exc).__name__
                continue
            except httpx.HTTPError as exc:
                raise SanitizationUnavailableError(type(exc).__name__) from None
            if response.status_code == 503:
                category = "ServiceUnavailable"
                continue
            return _interpret(response)
        raise SanitizationUnavailableError(category)


def _interpret(response: httpx.Response) -> dict[str, str]:
    if response.status_code == 404:
        raise ReferenceNotFoundError
    if response.status_code != 200:
        # Includes a 401 (the service secret is wrong) and any other failure. The caller of
        # this service learns only that a dependency is unavailable.
        raise SanitizationUnavailableError(f"UpstreamStatus{response.status_code}")
    try:
        parsed = MappingResponse.model_validate_json(response.content)
    except ValidationError:
        raise SanitizationUnavailableError("InvalidResponse") from None
    mappings: dict[str, str] = {}
    for item in parsed.mappings:
        if mappings.setdefault(item.placeholder, item.value) != item.value:
            raise SanitizationUnavailableError("InvalidResponse")
    return mappings
