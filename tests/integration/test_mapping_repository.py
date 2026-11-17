"""The vault against a real PostgreSQL: stored rows, scoping, expiry, revocation and tampering.

Each test gets a new migrated database. If no database is available the test fails with the
reason; it is never skipped.
"""

import importlib
import re
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg.errors import CheckViolation, UniqueViolation

from tests.conftest import AppFactory, client_for
from tests.support.database import run_sql, to_psycopg_dsn
from tests.support.leak import CANARIES, assert_no_leak
from tests.support.service_loader import load_service_app
from tests.support.vault_env import API_KEYS, KEY_V1, KEY_V2, PEPPER, TENANT_A
from tests.support.vault_fakes import FakeClock

TENANT = "tenant-test-a"
SCOPE = "scope-db-1"
MAPPINGS = {"[EMAIL_001]": CANARIES[1], "[PHONE_001]": CANARIES[2]}
PROFILES = {"profiles": [{"id": "gdpr", "version": 1}], "settings_version": 0}


class Db:
    def __init__(self, url: str, keys: dict[int, bytes], active: int = 1) -> None:
        self.url = url
        self.clock = FakeClock()
        self.errors = importlib.import_module("app.vault.errors")
        self.crypto = importlib.import_module("app.vault.crypto")
        session = importlib.import_module("app.db.session")
        repo = importlib.import_module("app.repositories.mapping_repository")
        self.engine = session.create_db_engine(url)
        self.repository = repo.MappingRepository(self.engine)
        self.vault = self.vault_with(keys, active)

    def vault_with(self, keys: dict[int, bytes], active: int) -> Any:
        vault_module = importlib.import_module("app.vault.vault")
        return vault_module.Vault(
            self.repository, self.crypto.Keyring(keys, active), PEPPER, self.clock
        )

    def put(self, tenant: str = TENANT, scope: str = SCOPE, ttl: int = 3600) -> Any:
        return self.vault.store(tenant, scope, MAPPINGS, PROFILES, ttl)

    def sql(self, statement: str, params: tuple[object, ...] = ()) -> list[tuple[Any, ...]]:
        with psycopg.connect(to_psycopg_dsn(self.url), autocommit=True) as conn:
            cursor = run_sql(conn, statement, params)
            return cursor.fetchall() if cursor.description else []


@pytest.fixture
def db(migrated_database_url: str) -> Iterator[Db]:
    load_service_app("sanitization_service")
    handle = Db(migrated_database_url, {1: KEY_V1})
    try:
        yield handle
    finally:
        handle.engine.dispose()


def test_a_stored_mapping_is_returned_for_its_reference_tenant_and_scope(db: Db) -> None:
    stored = db.put()
    assert db.vault.retrieve(stored.reference, TENANT, SCOPE) == MAPPINGS


def test_no_column_of_the_stored_row_holds_a_plaintext_reference_or_value(db: Db) -> None:
    stored = db.put()
    with psycopg.connect(to_psycopg_dsn(db.url)) as conn:
        cursor = run_sql(conn, "SELECT * FROM mapping_records")
        columns = [c.name for c in cursor.description or []]
        (row,) = cursor.fetchall()
    rendered: list[bytes] = []
    for value in row:
        if isinstance(value, memoryview):
            rendered.append(value.tobytes())
        elif isinstance(value, bytes):
            rendered.append(value)
        else:
            rendered.append(str(value).encode())
    everything = b"\n".join(rendered)
    assert stored.reference.encode() not in everything
    assert stored.reference.removeprefix("pf1_").encode() not in everything
    for secret in (*MAPPINGS.values(), *MAPPINGS):
        assert secret.encode() not in everything
    by_name = dict(zip(columns, row, strict=True))
    assert by_name["encryption_alg"] == "AES-256-GCM"
    assert by_name["key_version"] == 1
    assert len(bytes(by_name["credential_digest"])) == 32
    assert len(bytes(by_name["nonce"])) == 12


def test_every_row_has_an_algorithm_and_a_key_version(db: Db) -> None:
    for _ in range(3):
        db.put()
    rows = db.sql("SELECT encryption_alg, key_version FROM mapping_records")
    assert len(rows) == 3
    assert all(alg == "AES-256-GCM" and version >= 1 for alg, version in rows)


def test_the_database_holds_only_a_digest_that_the_reference_hashes_to(db: Db) -> None:
    credentials = importlib.import_module("app.vault.credentials")
    stored = db.put()
    ((digest,),) = db.sql("SELECT credential_digest FROM mapping_records")
    assert bytes(digest) == credentials.credential_digest(stored.reference, PEPPER)


def test_profiles_and_settings_in_force_are_recorded_on_the_row(db: Db) -> None:
    db.put()
    ((profiles,),) = db.sql("SELECT profiles FROM mapping_records")
    assert profiles == PROFILES


@pytest.mark.parametrize(
    ("tenant", "scope"),
    [("tenant-test-b", SCOPE), (TENANT, "scope-other")],
    ids=["tenant", "scope"],
)
def test_another_tenant_or_scope_gets_nothing(db: Db, tenant: str, scope: str) -> None:
    stored = db.put()
    assert db.vault.retrieve(stored.reference, tenant, scope) is None


def test_expired_records_are_not_returned_and_the_clock_is_injected(db: Db) -> None:
    stored = db.put(ttl=60)
    db.clock.advance(59)
    assert db.vault.retrieve(stored.reference, TENANT, SCOPE) == MAPPINGS
    db.clock.advance(1)
    assert db.vault.retrieve(stored.reference, TENANT, SCOPE) is None


def test_revoked_records_are_not_returned(db: Db) -> None:
    stored = db.put()
    assert db.vault.revoke(stored.reference, TENANT) is True
    assert db.vault.retrieve(stored.reference, TENANT, SCOPE) is None
    assert db.vault.revoke(stored.reference, TENANT) is False
    ((revoked_at,),) = db.sql("SELECT revoked_at FROM mapping_records")
    assert revoked_at == db.clock.now


def test_deleted_records_are_not_returned_but_the_row_stays_for_retention(db: Db) -> None:
    stored = db.put()
    assert db.vault.mark_deleted(stored.reference, TENANT) is True
    assert db.vault.retrieve(stored.reference, TENANT, SCOPE) is None
    ((count, deleted_at),) = db.sql("SELECT count(*), max(deleted_at) FROM mapping_records")
    assert count == 1
    assert deleted_at == db.clock.now


def test_another_tenant_cannot_revoke_or_delete_a_record(db: Db) -> None:
    stored = db.put()
    assert db.vault.revoke(stored.reference, "tenant-test-b") is False
    assert db.vault.mark_deleted(stored.reference, "tenant-test-b") is False
    assert db.vault.retrieve(stored.reference, TENANT, SCOPE) == MAPPINGS


def test_a_row_written_under_key_1_still_opens_after_the_keyring_gains_key_2(db: Db) -> None:
    old = db.put()
    rotated = db.vault_with({1: KEY_V1, 2: KEY_V2}, active=2)
    assert rotated.retrieve(old.reference, TENANT, SCOPE) == MAPPINGS
    new = rotated.store(TENANT, SCOPE, MAPPINGS, PROFILES, 3600)
    versions = sorted(v for (v,) in db.sql("SELECT key_version FROM mapping_records"))
    assert versions == [1, 2]
    with pytest.raises(db.errors.MappingIntegrityError):
        db.vault.retrieve(new.reference, TENANT, SCOPE)  # a keyring without key 2 cannot open it
    assert rotated.retrieve(new.reference, TENANT, SCOPE) == MAPPINGS


def test_a_keyring_without_the_rows_key_version_fails_safely(db: Db) -> None:
    stored = db.put()
    only_v2 = db.vault_with({2: KEY_V2}, active=2)
    with pytest.raises(db.errors.MappingIntegrityError):
        only_v2.retrieve(stored.reference, TENANT, SCOPE)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE mapping_records SET"
        " ciphertext = set_byte(ciphertext, 0, get_byte(ciphertext, 0) # 1)",
        "UPDATE mapping_records SET nonce = set_byte(nonce, 0, get_byte(nonce, 0) # 1)",
        "UPDATE mapping_records SET key_version = 9",
        "UPDATE mapping_records SET encryption_alg = 'NONE'",
        "UPDATE mapping_records SET id = gen_random_uuid()",
    ],
    ids=["ciphertext", "nonce", "unknown_key_version", "algorithm", "record_id"],
)
def test_a_row_edited_in_the_database_fails_safely(db: Db, statement: str) -> None:
    stored = db.put()
    db.sql(statement)
    with pytest.raises(db.errors.MappingIntegrityError):
        db.vault.retrieve(stored.reference, TENANT, SCOPE)


def test_a_ciphertext_copied_between_rows_fails_safely(db: Db) -> None:
    first = db.put()
    second = db.vault.store(TENANT, SCOPE, {"[EMAIL_001]": "other@example.com"}, PROFILES, 3600)
    db.sql(
        "UPDATE mapping_records AS t SET"
        " ciphertext = (SELECT o.ciphertext FROM mapping_records o WHERE o.id <> t.id),"
        " nonce = (SELECT o.nonce FROM mapping_records o WHERE o.id <> t.id)"
    )
    with pytest.raises(db.errors.MappingIntegrityError):
        db.vault.retrieve(first.reference, TENANT, SCOPE)
    with pytest.raises(db.errors.MappingIntegrityError):
        db.vault.retrieve(second.reference, TENANT, SCOPE)


def test_a_row_moved_to_another_tenant_in_the_database_fails_safely(db: Db) -> None:
    stored = db.put()
    db.sql("UPDATE mapping_records SET tenant_id = 'tenant-test-b'")
    with pytest.raises(db.errors.MappingIntegrityError):
        db.vault.retrieve(stored.reference, "tenant-test-b", SCOPE)


def test_the_database_rejects_a_nonce_that_is_not_96_bits(db: Db) -> None:
    stored = db.put()
    assert stored.reference
    with pytest.raises(CheckViolation):
        db.sql("UPDATE mapping_records SET nonce = '\\x0102'::bytea")


def test_the_database_rejects_an_expiry_not_after_creation(db: Db) -> None:
    db.put()
    with pytest.raises(CheckViolation):
        db.sql("UPDATE mapping_records SET expires_at = created_at")


def test_the_database_rejects_a_duplicate_credential_digest(db: Db) -> None:
    db.put()
    with pytest.raises(UniqueViolation):
        db.sql(
            "INSERT INTO mapping_records (id, tenant_id, request_scope_id, credential_digest,"
            " ciphertext, nonce, encryption_alg, key_version, profiles, created_at, expires_at)"
            " SELECT gen_random_uuid(), tenant_id, request_scope_id, credential_digest,"
            " ciphertext, nonce, encryption_alg, key_version, profiles, created_at, expires_at"
            " FROM mapping_records"
        )


def test_the_credential_digest_has_a_unique_index_for_lookup(db: Db) -> None:
    indexes = db.sql(
        "SELECT indexdef FROM pg_indexes WHERE tablename = 'mapping_records' AND indexdef ILIKE %s",
        ("%UNIQUE%(credential_digest)%",),
    )
    assert len(indexes) == 1


@pytest.mark.anyio
async def test_the_api_stores_a_row_that_survives_an_app_restart(
    sanitization_app_factory: AppFactory, migrated_database_url: str
) -> None:
    env = {"PRIVYFLOW_SAN_DATABASE_URL": migrated_database_url}
    body = {
        "text": f"Mail {CANARIES[1]}",
        "request_scope_id": "scope-restart",
        "policy_id": "effective",
    }
    headers = {"X-API-Key": API_KEYS[TENANT_A]}
    first_app = sanitization_app_factory(env)
    async with client_for(first_app) as client:
        response = await client.post("/api/v1/sanitizations", json=body, headers=headers)
    assert response.status_code == 200
    reference = response.json()["restore_reference"]
    assert re.match(r"^pf1_[A-Za-z0-9_-]{43}$", reference)
    assert_no_leak(response.text)

    second_app = sanitization_app_factory(env)  # a new process-like start, same database
    async with client_for(second_app):
        assert second_app.state.vault.retrieve(reference, TENANT_A, "scope-restart") == {
            "[EMAIL_001]": CANARIES[1]
        }
        assert second_app.state.vault.retrieve(reference, TENANT_A, "scope-other") is None
    with psycopg.connect(to_psycopg_dsn(migrated_database_url)) as conn:
        rows = conn.execute(
            "SELECT tenant_id, request_scope_id, encryption_alg, key_version FROM mapping_records"
        ).fetchall()
    assert rows == [(TENANT_A, "scope-restart", "AES-256-GCM", 1)]
