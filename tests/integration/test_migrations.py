"""Alembic migrations for the Sanitization vault, run against a real PostgreSQL."""

import importlib
import uuid

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from psycopg import errors, sql
from sqlalchemy import create_engine, inspect

from tests.support.database import to_psycopg_dsn
from tests.support.migrations import downgrade, upgrade
from tests.support.service_loader import load_service_app

EXPECTED_COLUMNS = {
    "id",
    "tenant_id",
    "request_scope_id",
    "credential_digest",
    "ciphertext",
    "nonce",
    "encryption_alg",
    "key_version",
    "profiles",
    "created_at",
    "expires_at",
    "revoked_at",
    "deleted_at",
}


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_from_empty_database_creates_mapping_records(empty_database_url: str) -> None:
    assert _tables(empty_database_url) == set()
    upgrade(empty_database_url)
    assert "mapping_records" in _tables(empty_database_url)
    engine = create_engine(empty_database_url)
    try:
        columns = {c["name"] for c in inspect(engine).get_columns("mapping_records")}
    finally:
        engine.dispose()
    assert columns == EXPECTED_COLUMNS


def test_downgrade_then_upgrade_round_trips(empty_database_url: str) -> None:
    upgrade(empty_database_url)
    downgrade(empty_database_url)
    assert _tables(empty_database_url) <= {"alembic_version"}
    upgrade(empty_database_url)
    assert "mapping_records" in _tables(empty_database_url)


def test_migration_matches_the_orm_model(empty_database_url: str) -> None:
    upgrade(empty_database_url)
    load_service_app("sanitization_service")
    importlib.import_module("app.models")
    metadata = importlib.import_module("app.db.base").Base.metadata
    engine = create_engine(empty_database_url)
    try:
        with engine.connect() as connection:
            diff = compare_metadata(MigrationContext.configure(connection), metadata)
    finally:
        engine.dispose()
    assert diff == []


def test_indexes_support_tenant_scope_and_expiry_lookups(empty_database_url: str) -> None:
    upgrade(empty_database_url)
    engine = create_engine(empty_database_url)
    try:
        inspector = inspect(engine)
        indexed = [tuple(i["column_names"]) for i in inspector.get_indexes("mapping_records")]
        unique = [
            tuple(u["column_names"]) for u in inspector.get_unique_constraints("mapping_records")
        ]
    finally:
        engine.dispose()
    assert ("tenant_id", "request_scope_id") in indexed
    assert ("expires_at",) in indexed
    assert ("credential_digest",) in unique


def _insert(conn: psycopg.Connection[tuple[object, ...]], **overrides: object) -> None:
    row: dict[str, object] = {
        "id": uuid.uuid4(),
        "tenant_id": "tenant-test-a",
        "request_scope_id": "scope-1",
        "credential_digest": uuid.uuid4().bytes,
        "ciphertext": b"\x01\x02",
        "nonce": b"\x00" * 12,
        "encryption_alg": "AES-256-GCM",
        "key_version": 1,
        "profiles": "{}",
        "created_at": "2026-01-01T00:00:00+00",
        "expires_at": "2026-01-01T01:00:00+00",
    }
    row.update(overrides)
    columns = sql.SQL(", ").join(sql.Identifier(c) for c in row)
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in row)
    conn.execute(
        sql.SQL("INSERT INTO mapping_records ({}) VALUES ({})").format(columns, placeholders),
        list(row.values()),
    )


def test_database_rejects_rows_that_violate_constraints(empty_database_url: str) -> None:
    upgrade(empty_database_url)
    digest = b"\x07" * 32
    with psycopg.connect(to_psycopg_dsn(empty_database_url), autocommit=True) as conn:
        _insert(conn, credential_digest=digest)
        with pytest.raises(errors.UniqueViolation):
            _insert(conn, credential_digest=digest)
        with pytest.raises(errors.CheckViolation):
            _insert(conn, expires_at="2025-12-31T00:00:00+00")
        with pytest.raises(errors.CheckViolation):
            _insert(conn, nonce=b"\x00" * 11)
        with pytest.raises(errors.NotNullViolation):
            _insert(conn, tenant_id=None)


def test_runtime_role_has_least_privilege(empty_database_url: str, database_admin_url: str) -> None:
    from scripts.create_db_roles import drop_runtime_role, ensure_runtime_role

    role = f"pf_test_role_{uuid.uuid4().hex[:8]}"
    password = uuid.uuid4().hex
    ensure_runtime_role(empty_database_url, role, password)
    try:
        upgrade(empty_database_url, runtime_role=role)
        from sqlalchemy.engine import make_url

        runtime_url = make_url(empty_database_url).set(username=role, password=password)
        dsn = to_psycopg_dsn(runtime_url.render_as_string(hide_password=False))
        with psycopg.connect(dsn, autocommit=True) as conn:
            _insert(conn)
            assert conn.execute("SELECT count(*) FROM mapping_records").fetchone() == (1,)
            conn.execute("UPDATE mapping_records SET revoked_at = now()")
            with pytest.raises(errors.InsufficientPrivilege):
                conn.execute("DELETE FROM mapping_records")
            with pytest.raises(errors.InsufficientPrivilege):
                conn.execute("DROP TABLE mapping_records")
            with pytest.raises(errors.InsufficientPrivilege):
                conn.execute("CREATE TABLE sneaky (id int)")
    finally:
        drop_runtime_role(empty_database_url, role)
