"""How the Sanitization Service loads settings at startup, for both backends."""

import importlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine

from tests.conftest import AppFactory, client_for
from tests.support.settings_data import VALID, valid_content, write_settings_file

SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _modules(name: str) -> Any:
    return importlib.import_module(name)


def _import_into_database(url: str, raw: dict[str, Any]) -> None:
    engine = create_engine(url)
    try:
        content = _modules("app.settings.validator").validate_settings(raw)
        _modules("app.settings.admin").apply_import(engine, content, "test")
    finally:
        engine.dispose()


def _log_events(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, Any]]:
    formatter = _modules("app.core.logging").JsonFormatter()
    parsed = [
        json.loads(formatter.format(r)) for r in caplog.records if r.name.startswith("privyflow")
    ]
    return [line for line in parsed if line["event"] == event]


@pytest.mark.anyio
async def test_default_backend_is_file_and_startup_logs_version_and_hash_only(
    sanitization_app_factory: AppFactory, empty_database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    app = sanitization_app_factory({"PRIVYFLOW_SAN_DATABASE_URL": empty_database_url})
    async with client_for(app) as client:
        assert (await client.get("/health/ready")).status_code == 200
    (line,) = _log_events(caplog, "settings_loaded")
    assert line["settings_backend"] == "file"
    assert line["settings_version"] == 0
    assert SHA256.match(line["settings_hash"])
    assert set(line) == {
        "ts", "level", "event", "service", "version", "settings_backend",
        "settings_version", "settings_hash",
    }  # fmt: skip
    for text in ("tenant-test-a", "hipaa", "1800"):
        assert text not in json.dumps(line)


@pytest.mark.anyio
async def test_db_backend_starts_after_the_settings_are_imported(
    sanitization_app_factory: AppFactory,
    migrated_database_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    app = sanitization_app_factory(
        {"PRIVYFLOW_SAN_DATABASE_URL": migrated_database_url, "PRIVYFLOW_SETTINGS_BACKEND": "db"}
    )
    _import_into_database(migrated_database_url, VALID)
    async with client_for(app) as client:
        assert (await client.get("/health/ready")).status_code == 200
    (line,) = _log_events(caplog, "settings_loaded")
    assert (line["settings_backend"], line["settings_version"]) == ("db", 1)


@pytest.mark.anyio
@pytest.mark.parametrize("value", ["xml", "", "FILE2"])
async def test_invalid_backend_value_fails_startup_and_readiness(
    sanitization_app_factory: AppFactory, empty_database_url: str, value: str
) -> None:
    app = sanitization_app_factory(
        {"PRIVYFLOW_SAN_DATABASE_URL": empty_database_url, "PRIVYFLOW_SETTINGS_BACKEND": value}
    )
    async with client_for(app) as client:
        assert (await client.get("/health/live")).status_code == 200
        assert (await client.get("/health/ready")).status_code == 503
    assert app.state.settings_snapshot is None


@pytest.mark.anyio
async def test_missing_file_is_not_ready_and_does_not_fall_back_to_the_database(
    sanitization_app_factory: AppFactory, migrated_database_url: str, tmp_path: Path
) -> None:
    app = sanitization_app_factory(
        {
            "PRIVYFLOW_SAN_DATABASE_URL": migrated_database_url,
            "PRIVYFLOW_SETTINGS_FILE": str(tmp_path / "missing.json"),
        }
    )
    _import_into_database(migrated_database_url, VALID)  # valid settings exist in the database
    async with client_for(app) as client:
        assert (await client.get("/health/ready")).status_code == 503
    assert app.state.settings_snapshot is None


@pytest.mark.anyio
async def test_invalid_file_is_not_ready(
    sanitization_app_factory: AppFactory, empty_database_url: str, tmp_path: Path
) -> None:
    bad = write_settings_file(tmp_path / "bad.json", valid_content(default_ttl_seconds=999999))
    app = sanitization_app_factory(
        {"PRIVYFLOW_SAN_DATABASE_URL": empty_database_url, "PRIVYFLOW_SETTINGS_FILE": str(bad)}
    )
    async with client_for(app) as client:
        assert (await client.get("/health/ready")).status_code == 503


@pytest.mark.anyio
async def test_db_backend_without_a_snapshot_is_not_ready_and_does_not_use_the_file(
    sanitization_app_factory: AppFactory, migrated_database_url: str
) -> None:
    app = sanitization_app_factory(
        {"PRIVYFLOW_SAN_DATABASE_URL": migrated_database_url, "PRIVYFLOW_SETTINGS_BACKEND": "db"}
    )  # a valid default settings file exists, and must not be used
    async with client_for(app) as client:
        assert (await client.get("/health/ready")).status_code == 503
    assert app.state.settings_snapshot is None


@pytest.mark.anyio
async def test_db_backend_with_unreachable_database_is_not_ready(
    sanitization_app_factory: AppFactory,
) -> None:
    app = sanitization_app_factory({"PRIVYFLOW_SETTINGS_BACKEND": "db"})
    async with client_for(app) as client:
        assert (await client.get("/health/live")).status_code == 200
        assert (await client.get("/health/ready")).status_code == 503


@pytest.mark.anyio
async def test_settings_file_change_is_not_applied_until_restart(
    sanitization_app_factory: AppFactory, empty_database_url: str, tmp_path: Path
) -> None:
    path = write_settings_file(tmp_path / "live.json", VALID)
    env = {"PRIVYFLOW_SAN_DATABASE_URL": empty_database_url, "PRIVYFLOW_SETTINGS_FILE": str(path)}
    app = sanitization_app_factory(env)
    async with client_for(app) as client:
        before = app.state.settings_snapshot.content_hash
        write_settings_file(path, valid_content(default_ttl_seconds=900))
        assert (await client.get("/health/ready")).status_code == 200
        assert app.state.settings_snapshot.content_hash == before
    restarted = sanitization_app_factory(env)
    async with client_for(restarted):
        assert restarted.state.settings_snapshot.content_hash != before
        assert restarted.state.settings_snapshot.content.default_ttl_seconds == 900


@pytest.mark.anyio
async def test_switching_backend_gives_the_same_settings_for_a_tenant(
    sanitization_app_factory: AppFactory, migrated_database_url: str
) -> None:
    base = {"PRIVYFLOW_SAN_DATABASE_URL": migrated_database_url}
    file_app = sanitization_app_factory(base)
    async with client_for(file_app):
        from_file = file_app.state.settings_snapshot
    _import_into_database(migrated_database_url, VALID)
    db_app = sanitization_app_factory({**base, "PRIVYFLOW_SETTINGS_BACKEND": "db"})
    async with client_for(db_app):
        from_db = db_app.state.settings_snapshot
    assert from_file.content_hash == from_db.content_hash
    assert from_file.content.tenant_profiles["tenant-test-b"] == ["gdpr", "hipaa"]
    assert from_db.content.tenant_profiles["tenant-test-b"] == ["gdpr", "hipaa"]
