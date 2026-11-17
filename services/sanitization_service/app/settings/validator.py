"""The settings schema and its validation.

Both backends feed raw content through `validate_settings`, so the same rules apply to a
file and to a database row. Error messages name fields and reasons only, never values.
"""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    ValidationError,
)
from pydantic_core import PydanticCustomError

PROFILE_DATA_DIR = Path(__file__).resolve().parents[1] / "sanitization" / "profiles" / "data"
TENANT_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{2,62}$"
MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 3600
MIN_REQUEST_BYTES = 1024
_SECRET_NAME = re.compile(
    r"secret|passw|token|pepper|credential|private|api[_-]?key|encryption|signing|dsn"
    r"|database[_-]?url|connection|(^|[_-])keys?($|[_-])",
    re.IGNORECASE,
)
_MAX_ERRORS = 20


class SettingsError(Exception):
    """Settings could not be loaded. The message never includes a setting's value."""


@lru_cache(maxsize=1)
def known_profile_ids() -> frozenset[str]:
    ids: set[str] = set()
    for path in sorted(PROFILE_DATA_DIR.glob("*.json")):
        if path.name != "entity_types.json":
            ids.add(str(json.loads(path.read_text(encoding="utf-8"))["id"]))
    return frozenset(ids)


def _known_profile(value: str) -> str:
    if value not in known_profile_ids():
        raise PydanticCustomError("unknown_profile", "unknown profile")
    return value


TenantId = Annotated[str, StringConstraints(pattern=TENANT_ID_PATTERN)]
ProfileId = Annotated[str, AfterValidator(_known_profile)]


class SettingsContent(BaseModel):
    """Operational settings. Secrets never belong here; they stay in the environment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    tenant_profiles: dict[TenantId, Annotated[list[ProfileId], Field(min_length=1)]] = Field(
        default_factory=dict
    )
    default_ttl_seconds: Annotated[StrictInt, Field(ge=MIN_TTL_SECONDS, le=MAX_TTL_SECONDS)] = (
        MAX_TTL_SECONDS
    )
    max_request_bytes: Annotated[StrictInt, Field(ge=MIN_REQUEST_BYTES)] = 262144
    strict_coverage: StrictBool = False


def _secret_like_fields(raw: dict[Any, Any], path: tuple[str, ...] = ()) -> list[str]:
    found: list[str] = []
    for key, value in raw.items():
        name = str(key)
        if _SECRET_NAME.search(name):
            found.append(".".join((*path, name[:64])))
        # Tenant IDs are data, not field names, so they are not screened.
        if isinstance(value, dict) and name != "tenant_profiles":
            found += _secret_like_fields(cast(dict[Any, Any], value), (*path, name[:64]))
    return found


def _label(location: tuple[int | str, ...]) -> str:
    parts: list[str] = []
    for index, part in enumerate(location):
        text = str(part)
        if (
            index == 1
            and location[0] == "tenant_profiles"
            and not re.match(TENANT_ID_PATTERN, text)
        ):
            text = "<invalid tenant id>"
        parts.append(text[:64])
    return ".".join(parts) or "settings"


def validate_settings(raw: object) -> SettingsContent:
    """Return validated content, or raise SettingsError naming each bad field and why."""
    if not isinstance(raw, dict):
        raise SettingsError("Invalid settings: settings: not_an_object")
    secrets = _secret_like_fields(cast(dict[Any, Any], raw))
    if secrets:
        items = [f"{name}: secret_field_not_allowed" for name in secrets[:_MAX_ERRORS]]
        raise SettingsError("Invalid settings: " + "; ".join(items))
    try:
        return SettingsContent.model_validate(raw)
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        items = [f"{_label(error['loc'])}: {error['type']}" for error in errors[:_MAX_ERRORS]]
        raise SettingsError("Invalid settings: " + "; ".join(items)) from None
