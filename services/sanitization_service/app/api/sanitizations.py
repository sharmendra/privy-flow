"""Public sanitization endpoints (SPEC 9.3 and 9.4). Authenticated by API key; the tenant is the
key's tenant and is never read from the body.

Sanitization is not idempotent: every call that stores mappings creates a new reference.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.core.auth import authenticated_tenant
from app.core.errors import ApiError
from app.core.logging import log_event
from app.sanitization.policy import EffectivePolicy, PolicyResolver
from app.sanitization.sanitizer import sanitize_text
from app.schemas.sanitization import (
    EntityRule,
    PolicyResponse,
    ProfileRef,
    SanitizationRequest,
    SanitizationResponse,
)
from app.settings.snapshot import SettingsSnapshot
from app.vault.vault import Vault

router = APIRouter(prefix="/api/v1")

_EFFECTIVE_POLICY_ID = "effective"
Tenant = Annotated[str, Depends(authenticated_tenant)]


def _not_ready() -> ApiError:
    return ApiError(503, "dependency_unavailable", "The service is not ready.")


def _resolver(request: Request) -> PolicyResolver:
    resolver: PolicyResolver | None = getattr(request.app.state, "policy_resolver", None)
    if resolver is None:
        raise _not_ready()
    return resolver


async def _parse_request(request: Request) -> SanitizationRequest:
    """Read and validate the body after authentication, so a caller without a valid key learns
    nothing about the schema. The size limit middleware applies while the body is read."""
    raw = await request.body()
    try:
        return SanitizationRequest.model_validate_json(raw)
    except ValidationError:
        raise ApiError(422, "validation_error", "The request is not valid.") from None


def _sanitize_and_store(
    request: Request, tenant_id: str, body: SanitizationRequest
) -> SanitizationResponse:
    resolver = _resolver(request)
    vault: Vault | None = getattr(request.app.state, "vault", None)
    snapshot: SettingsSnapshot | None = getattr(request.app.state, "settings_snapshot", None)
    if vault is None or snapshot is None:
        raise _not_ready()
    policy = resolver.policy_for(tenant_id)
    result = sanitize_text(body.text, policy)
    reference: str | None = None
    expires_at = None
    if result.mappings:
        try:
            stored = vault.store(
                tenant_id=tenant_id,
                request_scope_id=body.request_scope_id,
                mappings=result.mappings,
                profiles={
                    "profiles": [{"id": i, "version": v} for i, v in policy.profiles],
                    "settings_version": snapshot.version,
                    "settings_hash": snapshot.content_hash,
                },
                ttl_seconds=policy.max_ttl_seconds,
            )
        except SQLAlchemyError as exc:
            log_event(
                "vault_unavailable",
                logging.WARNING,
                correlation_id=request.state.correlation_id,
                error_category=type(exc).__name__,
            )
            raise ApiError(
                503, "dependency_unavailable", "A required dependency is unavailable."
            ) from None
        reference, expires_at = stored.reference, stored.expires_at
    return SanitizationResponse(
        sanitized_text=result.sanitized_text,
        restore_reference=reference,
        expires_at=expires_at,
        profiles_applied=[profile_id for profile_id, _ in policy.profiles],
        uncovered_entity_types=list(policy.uncovered_entity_types),
        entity_count=result.entity_count,
        correlation_id=str(request.state.correlation_id),
    )


@router.post("/sanitizations")
async def create_sanitization(
    request: Request, response: Response, tenant_id: Tenant
) -> SanitizationResponse:
    body = await _parse_request(request)
    if body.policy_id != _EFFECTIVE_POLICY_ID:
        raise ApiError(422, "unsupported_policy", "The requested policy is not supported.")
    # The response carries a restore-reference, so it must not be cached.
    response.headers["Cache-Control"] = "no-store"
    return await run_in_threadpool(_sanitize_and_store, request, tenant_id, body)


def _policy_response(policy: EffectivePolicy) -> PolicyResponse:
    return PolicyResponse(
        policy_id=_EFFECTIVE_POLICY_ID,
        profiles=[ProfileRef(id=i, version=v) for i, v in policy.profiles],
        entity_types=[EntityRule(type=t, action=a) for t, a in policy.actions.items()],
        max_ttl_seconds=policy.max_ttl_seconds,
        uncovered_entity_types=list(policy.uncovered_entity_types),
    )


@router.get("/policies")
def get_policy(request: Request, tenant_id: Tenant) -> PolicyResponse:
    """The calling tenant's own effective policy. No other tenant's is reachable here."""
    return _policy_response(_resolver(request).policy_for(tenant_id))
