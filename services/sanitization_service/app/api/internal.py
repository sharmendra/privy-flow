"""Internal mapping retrieval for the De-sanitization Service (SPEC 9.5).

Authenticated by the service secret, never by a client API key. The tenant and request scope in
the body are asserted by the authenticated internal caller (decision D8); the lookup still needs
the reference, tenant and scope to all match. Every reason a lookup fails answers with the same
404, so a caller learns nothing about whether a mapping exists.
"""

import logging

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.core.errors import ApiError
from app.core.logging import log_event
from app.core.service_auth import require_internal_caller
from app.schemas.internal import (
    MappingItem,
    MappingRetrievalRequest,
    MappingRetrievalResponse,
)
from app.vault.errors import MappingIntegrityError
from app.vault.vault import Vault

router = APIRouter(prefix="/internal/v1", dependencies=[Depends(require_internal_caller)])

_EFFECTIVE_POLICY_ID = "effective"


def _not_found() -> ApiError:
    return ApiError(404, "restore_reference_not_found", "The restore reference was not found.")


async def _parse_request(request: Request) -> MappingRetrievalRequest:
    """Read the body after authentication. The size limit applies while it is read."""
    raw = await request.body()
    try:
        return MappingRetrievalRequest.model_validate_json(raw)
    except ValidationError:
        raise ApiError(422, "validation_error", "The request is not valid.") from None


def _retrieve(request: Request, body: MappingRetrievalRequest) -> MappingRetrievalResponse:
    vault: Vault | None = getattr(request.app.state, "vault", None)
    if vault is None:
        raise ApiError(503, "dependency_unavailable", "The service is not ready.")
    correlation_id = request.state.correlation_id
    try:
        # Needs the reference, tenant and scope to match one active record.
        mappings = vault.retrieve(body.restore_reference, body.tenant_id, body.request_scope_id)
    except MappingIntegrityError as exc:
        # A row that fails authentication must not look different from a miss to the caller.
        # The category is logged so operators can see it; nothing about the row is.
        log_event(
            "mapping_integrity_failure",
            logging.ERROR,
            correlation_id=correlation_id,
            error_category=type(exc).__name__,
        )
        raise _not_found() from None
    except SQLAlchemyError as exc:
        log_event(
            "vault_unavailable",
            logging.WARNING,
            correlation_id=correlation_id,
            error_category=type(exc).__name__,
        )
        raise ApiError(
            503, "dependency_unavailable", "A required dependency is unavailable."
        ) from None
    if mappings is None:
        # Unknown, expired, revoked, wrong tenant or wrong scope all look the same.
        raise _not_found()
    return MappingRetrievalResponse(
        mappings=[MappingItem(placeholder=p, value=v) for p, v in mappings.items()],
        policy_id=_EFFECTIVE_POLICY_ID,
    )


@router.post("/mappings/retrieve")
async def retrieve_mappings(request: Request, response: Response) -> MappingRetrievalResponse:
    body = await _parse_request(request)
    # The response carries decrypted values, so it must never be cached.
    response.headers["Cache-Control"] = "no-store"
    return await run_in_threadpool(_retrieve, request, body)
