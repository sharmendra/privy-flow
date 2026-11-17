"""The sanitization request body (SPEC 9.3).

Unknown fields are rejected, so a body can name neither a tenant nor profiles. The tenant
comes from the authenticated API key. Whether `policy_id` is `effective` is checked by the
endpoint, which answers 422 `unsupported_policy`.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

REQUEST_SCOPE_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,128}$"


class SanitizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Empty text is invalid. Whitespace-only text is valid and kept exactly as sent.
    text: Annotated[str, Field(min_length=1)]
    request_scope_id: Annotated[str, StringConstraints(pattern=REQUEST_SCOPE_ID_PATTERN)]
    policy_id: str
