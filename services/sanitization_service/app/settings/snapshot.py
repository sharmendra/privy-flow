"""An immutable settings snapshot with a content hash."""

import hashlib
import json
from dataclasses import dataclass

from app.settings.validator import SettingsContent


@dataclass(frozen=True)
class SettingsSnapshot:
    """Settings as loaded at startup. `version` is 0 for the file backend, which has none."""

    version: int
    backend: str
    content_hash: str
    content: SettingsContent


def canonical_json(content: SettingsContent) -> str:
    return json.dumps(content.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def content_hash(content: SettingsContent) -> str:
    """Hash of validated content, so key order and omitted defaults do not change it."""
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()
