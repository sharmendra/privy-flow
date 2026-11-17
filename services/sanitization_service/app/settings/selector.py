"""Pick the settings backend named at startup. There is never a fallback to the other one."""

from pathlib import Path

from sqlalchemy import Engine

from app.core.config import Settings
from app.settings.snapshot import SettingsSnapshot
from app.settings.store import DbSettingsStore, FileSettingsStore
from app.settings.validator import SettingsError

DEFAULT_SETTINGS_FILE = Path(__file__).resolve().parents[4] / "config" / "settings.json"


def load_snapshot(bootstrap: Settings, engine: Engine | None) -> SettingsSnapshot:
    """Load settings from the one backend the bootstrap settings select."""
    if bootstrap.settings_backend == "file":
        return FileSettingsStore(bootstrap.settings_file or DEFAULT_SETTINGS_FILE).load()
    if engine is None:
        raise SettingsError("settings database unavailable")
    return DbSettingsStore(engine).load()
