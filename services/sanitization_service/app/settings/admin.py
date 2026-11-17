"""Settings writes for the command line tool. These need the settings admin database role.

The service's runtime role cannot run any of these: it has no INSERT on the settings tables.
Nothing here reads or writes secrets, and audit rows hold safe metadata only.
"""

import json
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from app.settings.snapshot import SettingsSnapshot, content_hash
from app.settings.store import DbSettingsStore
from app.settings.validator import SettingsContent


@dataclass(frozen=True)
class StoredSettings:
    version: int
    content_hash: str
    pretty: str


def render_pretty(content: SettingsContent) -> str:
    return json.dumps(content.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def latest_stored(engine: Engine) -> StoredSettings | None:
    """The newest stored snapshot as text, or None. It is not validated, so it can be diffed."""
    query = text(
        "SELECT version, content, content_hash FROM settings_snapshots "
        "ORDER BY version DESC LIMIT 1"
    )
    with engine.connect() as connection:
        row = connection.execute(query).first()
    if row is None:
        return None
    pretty = json.dumps(row.content, indent=2, sort_keys=True) + "\n"
    return StoredSettings(int(row.version), str(row.content_hash), pretty)


def apply_import(engine: Engine, content: SettingsContent, actor: str) -> SettingsSnapshot:
    """Append a new snapshot version and its audit row in one transaction."""
    digest = content_hash(content)
    payload = json.dumps(content.model_dump(mode="json"))
    with engine.begin() as connection:
        version = connection.execute(
            text("SELECT coalesce(max(version), 0) + 1 FROM settings_snapshots")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO settings_snapshots (version, content, content_hash, created_by) "
                "VALUES (:version, CAST(:content AS jsonb), :hash, :actor)"
            ),
            {"version": version, "content": payload, "hash": digest, "actor": actor},
        )
        _audit(connection, version, "import", actor, digest)
    return SettingsSnapshot(int(version), "db", digest, content)


def record_export(engine: Engine, actor: str) -> SettingsSnapshot:
    """Load the current snapshot, record that it was exported, and return it."""
    snapshot = DbSettingsStore(engine).load()
    with engine.begin() as connection:
        _audit(connection, snapshot.version, "export", actor, snapshot.content_hash)
    return snapshot


def _audit(connection: Connection, version: int, action: str, actor: str, digest: str) -> None:
    connection.execute(
        text(
            "INSERT INTO settings_audit (version, action, actor, content_hash) "
            "VALUES (:version, :action, :actor, :hash)"
        ),
        {"version": version, "action": action, "actor": actor, "hash": digest},
    )
