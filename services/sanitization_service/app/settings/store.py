"""Settings backends. The rest of the service only sees `SettingsStore`."""

import json
from pathlib import Path
from typing import Protocol

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.settings.snapshot import SettingsSnapshot, content_hash
from app.settings.validator import SettingsError, validate_settings


class SettingsStore(Protocol):
    def load(self) -> SettingsSnapshot: ...


class FileSettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> SettingsSnapshot:
        try:
            raw_text = self._path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            raise SettingsError("settings file not found") from None
        except (OSError, UnicodeDecodeError):
            raise SettingsError("settings file unreadable") from None
        try:
            raw = json.loads(raw_text)
        except ValueError:
            raise SettingsError("settings file is not valid JSON") from None
        content = validate_settings(raw)
        return SettingsSnapshot(0, "file", content_hash(content), content)


class DbSettingsStore:
    """Reads the highest-version row of settings_snapshots with the runtime role."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def load(self) -> SettingsSnapshot:
        query = text(
            "SELECT version, content, content_hash FROM settings_snapshots "
            "ORDER BY version DESC LIMIT 1"
        )
        try:
            with self._engine.connect() as connection:
                row = connection.execute(query).first()
        except SQLAlchemyError:
            raise SettingsError("settings database unavailable") from None
        if row is None:
            raise SettingsError("no settings snapshot in the database")
        content = validate_settings(row.content)
        computed = content_hash(content)
        if row.content_hash != computed:
            raise SettingsError("stored settings hash does not match its content")
        return SettingsSnapshot(int(row.version), "db", computed, content)
