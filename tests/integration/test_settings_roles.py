"""Migration 0002 and the database roles around the settings tables."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import psycopg
import pytest
from psycopg import errors
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from scripts.create_db_roles import drop_role, ensure_role
from tests.support.database import run_sql, to_psycopg_dsn
from tests.support.migrations import downgrade, upgrade

SNAPSHOT_COLUMNS = {"version", "content", "content_hash", "created_at", "created_by"}
AUDIT_COLUMNS = {"id", "version", "action", "actor", "content_hash", "created_at"}
INSERT_SNAPSHOT = (
    "INSERT INTO settings_snapshots (version, content, content_hash, created_by) "
    "VALUES (%s, '{}', 'h', 'tester')"
)
INSERT_AUDIT = (
    "INSERT INTO settings_audit (version, action, actor, content_hash) "
    "VALUES (1, 'import', 'tester', 'h')"
)


@dataclass
class Roles:
    database_url: str
    runtime_dsn: str
    admin_dsn: str


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _columns(url: str, table: str) -> set[str]:
    engine = create_engine(url)
    try:
        return {c["name"] for c in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


@pytest.fixture
def roles(empty_database_url: str) -> Iterator[Roles]:
    suffix = uuid.uuid4().hex[:8]
    runtime, admin = f"pf_test_runtime_{suffix}", f"pf_test_admin_{suffix}"
    passwords = {runtime: uuid.uuid4().hex, admin: uuid.uuid4().hex}
    for name, password in passwords.items():
        ensure_role(empty_database_url, name, password)
    upgrade(empty_database_url, runtime_role=runtime, settings_admin_role=admin)

    def dsn(name: str) -> str:
        url = make_url(empty_database_url).set(username=name, password=passwords[name])
        return to_psycopg_dsn(url.render_as_string(hide_password=False))

    try:
        yield Roles(empty_database_url, dsn(runtime), dsn(admin))
    finally:
        for name in (runtime, admin):
            drop_role(empty_database_url, name)


def test_upgrade_creates_the_settings_tables(empty_database_url: str) -> None:
    upgrade(empty_database_url)
    assert {"settings_snapshots", "settings_audit", "mapping_records"} <= _tables(
        empty_database_url
    )
    assert _columns(empty_database_url, "settings_snapshots") == SNAPSHOT_COLUMNS
    assert _columns(empty_database_url, "settings_audit") == AUDIT_COLUMNS


def test_downgrade_to_first_revision_drops_only_the_settings_tables(
    empty_database_url: str,
) -> None:
    upgrade(empty_database_url)
    downgrade(empty_database_url, "0001")
    tables = _tables(empty_database_url)
    assert "mapping_records" in tables
    assert not {"settings_snapshots", "settings_audit"} & tables


def test_full_downgrade_then_upgrade_round_trips(empty_database_url: str) -> None:
    upgrade(empty_database_url)
    downgrade(empty_database_url)
    assert _tables(empty_database_url) <= {"alembic_version"}
    upgrade(empty_database_url)
    assert {"settings_snapshots", "settings_audit"} <= _tables(empty_database_url)


def test_audit_action_is_limited_to_known_values(empty_database_url: str) -> None:
    upgrade(empty_database_url)
    with psycopg.connect(to_psycopg_dsn(empty_database_url), autocommit=True) as conn:
        conn.execute(INSERT_AUDIT)
        with pytest.raises(errors.CheckViolation):
            conn.execute(INSERT_AUDIT.replace("'import'", "'tamper'"))


@pytest.mark.parametrize("table", ["settings_snapshots", "settings_audit"])
def test_runtime_role_can_read_but_not_change_settings(roles: Roles, table: str) -> None:
    with psycopg.connect(roles.runtime_dsn, autocommit=True) as conn:
        assert run_sql(conn, f"SELECT count(*) FROM {table}").fetchone() == (0,)
        for statement in (
            INSERT_SNAPSHOT % 1 if table == "settings_snapshots" else INSERT_AUDIT,
            f"UPDATE {table} SET content_hash = 'x'",
            f"DELETE FROM {table}",
            f"TRUNCATE {table}",
        ):
            with pytest.raises(errors.InsufficientPrivilege):
                run_sql(conn, statement)


def test_settings_admin_can_append_and_read_but_not_edit_or_delete(roles: Roles) -> None:
    with psycopg.connect(roles.admin_dsn, autocommit=True) as conn:
        run_sql(conn, INSERT_SNAPSHOT % 1)
        conn.execute(INSERT_AUDIT)
        assert conn.execute("SELECT count(*) FROM settings_snapshots").fetchone() == (1,)
        for table in ("settings_snapshots", "settings_audit"):
            with pytest.raises(errors.InsufficientPrivilege):
                run_sql(conn, f"UPDATE {table} SET content_hash = 'x'")
            with pytest.raises(errors.InsufficientPrivilege):
                run_sql(conn, f"DELETE FROM {table}")


def test_settings_admin_has_no_access_to_mapping_records(roles: Roles) -> None:
    with psycopg.connect(roles.admin_dsn, autocommit=True) as conn:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("SELECT count(*) FROM mapping_records")
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("DELETE FROM mapping_records")


def test_runtime_role_still_has_vault_access_after_the_second_migration(roles: Roles) -> None:
    with psycopg.connect(roles.runtime_dsn, autocommit=True) as conn:
        assert conn.execute("SELECT count(*) FROM mapping_records").fetchone() == (0,)
