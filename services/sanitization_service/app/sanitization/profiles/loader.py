"""Compliance profile data files and the shared entity-type list.

Profiles are data (SPEC 9.9). Loading validates them and returns read-only objects. Error
messages name the file, the field and the kind of error, never a value from the file.
"""

import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StringConstraints
from pydantic import ValidationError as PydanticValidationError

from app.settings.validator import MAX_TTL_SECONDS, MIN_TTL_SECONDS, PROFILE_DATA_DIR, SettingsError

Action = Literal["placeholder", "redact"]
ENTITY_TYPES_FILE = "entity_types.json"
_MAX_ERRORS = 10


class ProfileError(SettingsError):
    """A profile or the entity-type list is missing, malformed or unknown."""


@dataclass(frozen=True)
class EntityTypeInfo:
    type: str
    priority: int  # breaks ties between overlapping spans of equal length (higher wins)
    pilot_recognizer: bool


@dataclass(frozen=True)
class Profile:
    id: str
    version: int
    max_ttl_seconds: int
    entities: Mapping[str, Action]

    def __post_init__(self) -> None:
        object.__setattr__(self, "entities", MappingProxyType(dict(self.entities)))


class _EntityTypeModel(BaseModel):
    type: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,40}$")]
    priority: StrictInt
    pilot_recognizer: StrictBool


class _EntityTypesFile(BaseModel):
    types: Annotated[list[_EntityTypeModel], Field(min_length=1)]


class _EntityRuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    action: Action


class _ProfileModel(BaseModel):
    id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,31}$")]
    version: Annotated[StrictInt, Field(ge=1)]
    max_ttl_seconds: Annotated[StrictInt, Field(ge=MIN_TTL_SECONDS, le=MAX_TTL_SECONDS)]
    entities: Annotated[list[_EntityRuleModel], Field(min_length=1)]


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise ProfileError(f"profile data file {path.name} not found") from None
    except (OSError, UnicodeDecodeError):
        raise ProfileError(f"profile data file {path.name} unreadable") from None
    except ValueError:
        raise ProfileError(f"profile data file {path.name} is not valid JSON") from None


def _describe(name: str, error: PydanticValidationError) -> str:
    errors = error.errors(include_url=False, include_context=False, include_input=False)
    items = [
        f"{'.'.join(str(part)[:64] for part in e['loc']) or 'file'}: {e['type']}"
        for e in errors[:_MAX_ERRORS]
    ]
    return f"Invalid profile data {name}: " + "; ".join(items)


def load_entity_types_from(directory: Path) -> Mapping[str, EntityTypeInfo]:
    path = directory / ENTITY_TYPES_FILE
    try:
        model = _EntityTypesFile.model_validate(_read_json(path))
    except PydanticValidationError as exc:
        raise ProfileError(_describe(path.name, exc)) from None
    types: dict[str, EntityTypeInfo] = {}
    for item in model.types:
        if item.type in types:
            raise ProfileError(f"Invalid profile data {path.name}: types: duplicate_type")
        types[item.type] = EntityTypeInfo(item.type, item.priority, item.pilot_recognizer)
    return MappingProxyType(types)


def load_profiles_from(directory: Path) -> Mapping[str, Profile]:
    known = load_entity_types_from(directory)
    profiles: dict[str, Profile] = {}
    for path in sorted(directory.glob("*.json")):
        if path.name == ENTITY_TYPES_FILE:
            continue
        try:
            model = _ProfileModel.model_validate(_read_json(path))
        except PydanticValidationError as exc:
            raise ProfileError(_describe(path.name, exc)) from None
        problem = _semantic_problem(path, model, known)
        if problem:
            raise ProfileError(f"Invalid profile data {path.name}: {problem}")
        profiles[model.id] = Profile(
            id=model.id,
            version=model.version,
            max_ttl_seconds=model.max_ttl_seconds,
            entities={rule.type: rule.action for rule in model.entities},
        )
    return MappingProxyType(profiles)


def _semantic_problem(path: Path, model: _ProfileModel, known: Mapping[str, EntityTypeInfo]) -> str:
    if model.id != path.stem:
        return "id: id_does_not_match_file_name"
    seen: set[str] = set()
    for rule in model.entities:
        if rule.type not in known:
            return "entities: unknown_entity_type"
        if rule.type in seen:
            return "entities: duplicate_entity_type"
        seen.add(rule.type)
    return ""


@lru_cache(maxsize=1)
def load_entity_types() -> Mapping[str, EntityTypeInfo]:
    return load_entity_types_from(PROFILE_DATA_DIR)


@lru_cache(maxsize=1)
def load_profiles() -> Mapping[str, Profile]:
    return load_profiles_from(PROFILE_DATA_DIR)


def get_profile(profile_id: str) -> Profile:
    profiles = load_profiles()
    if profile_id not in profiles:
        raise ProfileError("unknown profile")
    return profiles[profile_id]


def uncovered_types(profile: Profile, covered: Collection[str]) -> tuple[str, ...]:
    """Entity types the profile names that no recognizer can detect, sorted."""
    return tuple(sorted(t for t in profile.entities if t not in covered))
