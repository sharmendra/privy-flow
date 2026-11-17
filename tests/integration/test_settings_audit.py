"""Settings audit rows hold safe metadata only."""

import importlib
from collections.abc import Callable
from typing import Any

import psycopg
import pytest
from sqlalchemy import create_engine

from tests.support.database import run_sql, to_psycopg_dsn
from tests.support.service_loader import load_service_app
from tests.support.settings_data import VALID

SECRET_CANARIES = ("canary-encryption-key-91c2", "canary-pepper-44d8", "canary-service-secret-0b7e")


@pytest.fixture
def san() -> Callable[[str], Any]:
    load_service_app("sanitization_service")
    return importlib.import_module


def _rows(url: str, query: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(to_psycopg_dsn(url), autocommit=True) as conn:
        return run_sql(conn, query).fetchall()


def test_import_writes_one_audit_row_with_actor_version_and_hash(
    san: Callable[[str], Any], migrated_database_url: str
) -> None:
    engine = create_engine(migrated_database_url)
    content = san("app.settings.validator").validate_settings(VALID)
    snapshot = san("app.settings.admin").apply_import(engine, content, "alice-ops")
    engine.dispose()
    rows = _rows(
        migrated_database_url, "SELECT version, action, actor, content_hash FROM settings_audit"
    )
    assert rows == [(snapshot.version, "import", "alice-ops", snapshot.content_hash)]


def test_each_import_of_new_content_adds_a_version_and_an_audit_row(
    san: Callable[[str], Any], migrated_database_url: str
) -> None:
    engine = create_engine(migrated_database_url)
    validator, admin = san("app.settings.validator"), san("app.settings.admin")
    admin.apply_import(engine, validator.validate_settings(VALID), "a")
    admin.apply_import(
        engine, validator.validate_settings({**VALID, "default_ttl_seconds": 900}), "b"
    )
    engine.dispose()
    assert _rows(migrated_database_url, "SELECT version FROM settings_snapshots ORDER BY 1") == [
        (1,),
        (2,),
    ]
    assert _rows(migrated_database_url, "SELECT actor FROM settings_audit ORDER BY id") == [
        ("a",),
        ("b",),
    ]


def test_record_export_writes_an_export_audit_row(
    san: Callable[[str], Any], migrated_database_url: str
) -> None:
    engine = create_engine(migrated_database_url)
    admin = san("app.settings.admin")
    imported = admin.apply_import(
        engine, san("app.settings.validator").validate_settings(VALID), "a"
    )
    exported = admin.record_export(engine, "bob-ops")
    engine.dispose()
    assert exported.content_hash == imported.content_hash
    rows = _rows(migrated_database_url, "SELECT action, actor FROM settings_audit ORDER BY id")
    assert rows == [("import", "a"), ("export", "bob-ops")]


def test_settings_rows_contain_no_secret_values_from_the_environment(
    san: Callable[[str], Any], migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRIVYFLOW_SAN_ENCRYPTION_KEY", SECRET_CANARIES[0])
    monkeypatch.setenv("PRIVYFLOW_SAN_PEPPER", SECRET_CANARIES[1])
    monkeypatch.setenv("PRIVYFLOW_SAN_SERVICE_SECRET", SECRET_CANARIES[2])
    engine = create_engine(migrated_database_url)
    content = san("app.settings.validator").validate_settings(VALID)
    san("app.settings.admin").apply_import(engine, content, "ops")
    engine.dispose()
    dump = repr(_rows(migrated_database_url, "SELECT * FROM settings_snapshots")) + repr(
        _rows(migrated_database_url, "SELECT * FROM settings_audit")
    )
    for canary in SECRET_CANARIES:
        assert canary not in dump
