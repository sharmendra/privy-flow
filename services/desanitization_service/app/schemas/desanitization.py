"""The restoration request and response (SPEC 9.6).

Unknown fields are rejected, so a body can name no tenant. The tenant comes from the
authenticated API key.
"""

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

REQUEST_SCOPE_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,128}$"
# `pf1_` followed by 43 URL-safe base64 characters (32 random bytes). Anything else cannot be a
# reference, so it is answered as not found without calling the Sanitization Service.
RESTORE_REFERENCE_PATTERN = re.compile(r"pf1_[A-Za-z0-9_-]{43}")


class DesanitizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sanitized_text: Annotated[str, Field(min_length=1)]
    # Any string. The format is checked by the endpoint so a malformed value is a plain
    # not-found and looks the same as an unknown reference.
    restore_reference: str
    request_scope_id: Annotated[str, StringConstraints(pattern=REQUEST_SCOPE_ID_PATTERN)]


class DesanitizationResponse(BaseModel):
    restored_text: str
    restored_count: int
    unmatched_placeholder_count: int
    correlation_id: str
