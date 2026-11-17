"""Public restoration endpoint (SPEC 9.6). Authenticated by API key; the tenant is the key's
tenant and is never read from the body.

Restoration is read-only and safe to retry. A restore-reference alone never authorizes
anything: the caller needs a valid API key, and the tenant of that key and the request scope
must match the mapping the Sanitization Service holds.
"""

import hashlib
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError

from app.clients.sanitization import (
    ReferenceNotFoundError,
    SanitizationClient,
    SanitizationUnavailableError,
)
from app.core.auth import authenticated_tenant
from app.core.errors import ApiError
from app.core.logging import log_event
from app.restoration.restorer import OutputTooLargeError, restore
from app.schemas.desanitization import (
    RESTORE_REFERENCE_PATTERN,
    DesanitizationRequest,
    DesanitizationResponse,
)

router = APIRouter(prefix="/api/v1")

Tenant = Annotated[str, Depends(authenticated_tenant)]


def _not_found() -> ApiError:
    return ApiError(404, "restore_reference_not_found", "The restore reference was not found.")


def _unavailable() -> ApiError:
    return ApiError(503, "dependency_unavailable", "A required dependency is unavailable.")


def _tenant_ref(tenant_id: str) -> str:
    """An opaque stand-in for the tenant in audit logs."""
    return hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:12]


async def _parse_request(request: Request) -> DesanitizationRequest:
    """Read and validate the body after authentication, so a caller without a valid key learns
    nothing about the schema. The size limit middleware applies while the body is read."""
    raw = await request.body()
    try:
        return DesanitizationRequest.model_validate_json(raw)
    except ValidationError:
        raise ApiError(422, "validation_error", "The request is not valid.") from None


@router.post("/desanitizations")
async def create_desanitization(
    request: Request, response: Response, tenant_id: Tenant
) -> DesanitizationResponse:
    # The API key was already checked by the `Tenant` dependency, before the body is read.
    body = await _parse_request(request)
    client: SanitizationClient | None = getattr(request.app.state, "sanitization_client", None)
    settings = getattr(request.app.state, "settings", None)
    if client is None or settings is None:
        # Startup failed to load settings or keys: alive but not ready.
        raise ApiError(503, "dependency_unavailable", "The service is not ready.")
    # The response carries restored text, so it must not be cached.
    response.headers["Cache-Control"] = "no-store"
    correlation_id = str(request.state.correlation_id)
    # A value that cannot be a reference gets the same 404 as an unknown one, and the
    # Sanitization Service is never called for it.
    if not RESTORE_REFERENCE_PATTERN.fullmatch(body.restore_reference):
        raise _not_found()
    # Fetch the mapping over the internal API. The tenant comes from the API key, never the body.
    try:
        mappings = await client.retrieve(
            body.restore_reference, tenant_id, body.request_scope_id, correlation_id
        )
    except ReferenceNotFoundError:
        raise _not_found() from None
    except SanitizationUnavailableError as exc:
        # Log only the error category. The caller just learns a dependency is unavailable.
        log_event(
            "sanitization_unavailable",
            logging.WARNING,
            correlation_id=correlation_id,
            error_category=exc.category,
        )
        raise _unavailable() from None
    try:
        result = restore(body.sanitized_text, mappings, settings.max_output_bytes)
    except OutputTooLargeError:
        raise ApiError(
            413, "output_too_large", "The restored text is larger than the output limit."
        ) from None
    # Audit line: counts and an opaque tenant reference only, never text, values or the reference.
    log_event(
        "restoration_completed",
        correlation_id=correlation_id,
        operation="restore",
        tenant_ref=_tenant_ref(tenant_id),
        restored_count=result.restored_count,
        unmatched_count=result.unmatched_placeholder_count,
        outcome="ok",
    )
    return DesanitizationResponse(
        restored_text=result.text,
        restored_count=result.restored_count,
        unmatched_placeholder_count=result.unmatched_placeholder_count,
        correlation_id=correlation_id,
    )
