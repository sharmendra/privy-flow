"""The internal mapping-retrieval contract (SPEC 9.5), Sanitization side.

Unknown fields are rejected in requests, and the response holds only placeholders, values and
the policy ID. The saved contract that both services test against is
tests/fixtures/contracts/internal_mappings_retrieve_v1.json.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.auth import TENANT_ID_PATTERN
from app.schemas.sanitization import REQUEST_SCOPE_ID_PATTERN

# The most distinct mappings one reference can hold. Sanitization refuses text with more, so
# every stored reference can be returned in full.
MAX_MAPPINGS = 10000


class MappingRetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # The format is checked by the vault, so a malformed reference is a plain not-found and
    # looks the same as an unknown one.
    restore_reference: str
    tenant_id: Annotated[str, StringConstraints(pattern=TENANT_ID_PATTERN.pattern)]
    request_scope_id: Annotated[str, StringConstraints(pattern=REQUEST_SCOPE_ID_PATTERN)]


class MappingItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    placeholder: str
    value: str


class MappingRetrievalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mappings: Annotated[list[MappingItem], Field(max_length=MAX_MAPPINGS)]
    policy_id: str
