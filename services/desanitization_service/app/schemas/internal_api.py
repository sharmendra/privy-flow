"""What this service expects from the Sanitization Service's internal mapping API (SPEC 9.5).

This is the De-sanitization side's own copy of the contract, so the two services share no code.
Compatibility is checked at the HTTP boundary against the saved contract file
(tests/fixtures/contracts/internal_mappings_retrieve_v1.json). The reader is tolerant of extra
fields so an additive change in the other service does not break restoration.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

MAX_MAPPINGS = 10000
PLACEHOLDER_PATTERN = r"^\[[A-Z][A-Z0-9_]*_[0-9]{3,}\]$"


class MappingItem(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    placeholder: Annotated[str, Field(pattern=PLACEHOLDER_PATTERN)]
    value: str


class MappingResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    mappings: Annotated[list[MappingItem], Field(max_length=MAX_MAPPINGS)]
    policy_id: str
