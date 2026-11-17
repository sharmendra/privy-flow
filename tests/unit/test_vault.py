"""The Vault: real credentials and encryption over an in-memory store, with a fake clock."""

import os
import uuid
from collections.abc import Callable
from typing import Any

import pytest

from tests.support.vault_fakes import FakeClock, InMemoryMappingStore

TENANT = "tenant-test-a"
SCOPE = "scope-1"
MAPPINGS = {"[EMAIL_001]": "canary.person@example.com", "[PHONE_001]": "+1 202-555-0199"}
PROFILES = {"profiles": [{"id": "gdpr", "version": 1}], "settings_version": 0}


class Env:
    def __init__(self, san: Callable[[str], Any], keys: dict[int, bytes], active: int = 1) -> None:
        self.repo = san("app.repositories.mapping_repository")
        self.errors = san("app.vault.errors")
        crypto = san("app.vault.crypto")
        self.pepper = os.urandom(32)
        self.clock = FakeClock()
        self.store = InMemoryMappingStore(self.repo.StoredMappingRecord)
        self.keyring = crypto.Keyring(keys, active)
        self.vault = san("app.vault.vault").Vault(self.store, self.keyring, self.pepper, self.clock)

    def put(self, tenant: str = TENANT, scope: str = SCOPE, ttl: int = 3600) -> Any:
        return self.vault.store(tenant, scope, MAPPINGS, PROFILES, ttl)


@pytest.fixture
def env(san: Callable[[str], Any]) -> Env:
    return Env(san, {1: os.urandom(32)})


def test_stored_mappings_come_back_for_the_matching_reference_tenant_and_scope(env: Env) -> None:
    stored = env.put()
    assert env.vault.retrieve(stored.reference, TENANT, SCOPE) == MAPPINGS


def test_stored_expiry_is_now_plus_the_ttl(env: Env) -> None:
    stored = env.put(ttl=900)
    assert (stored.expires_at - env.clock.now).total_seconds() == 900
    (row,) = env.store.rows.values()
    assert row.record.expires_at == stored.expires_at
    assert row.record.created_at == env.clock.now


def test_stored_record_holds_only_a_digest_and_ciphertext(env: Env) -> None:
    stored = env.put()
    (row,) = env.store.rows.values()
    record = row.record
    held = b"".join(
        [record.credential_digest, record.ciphertext, record.nonce]
        + [str(getattr(record, f)).encode() for f in ("tenant_id", "request_scope_id", "profiles")]
    )
    assert stored.reference.encode() not in held
    for secret in MAPPINGS.values():
        assert secret.encode() not in held
    assert record.encryption_alg == "AES-256-GCM"
    assert record.key_version == 1
    assert len(record.credential_digest) == 32


def test_two_stores_of_the_same_mappings_get_different_references_and_ciphertext(env: Env) -> None:
    first, second = env.put(), env.put()
    assert first.reference != second.reference
    ciphertexts = {r.record.ciphertext for r in env.store.rows.values()}
    assert len(ciphertexts) == 2


@pytest.mark.parametrize(
    ("tenant", "scope"),
    [("tenant-test-b", SCOPE), (TENANT, "scope-2"), ("tenant-test-b", "scope-2")],
    ids=["other_tenant", "other_scope", "other_both"],
)
def test_a_reference_does_not_work_for_another_tenant_or_scope(
    env: Env, tenant: str, scope: str
) -> None:
    stored = env.put()
    assert env.vault.retrieve(stored.reference, tenant, scope) is None


def test_unknown_and_malformed_references_return_none(env: Env) -> None:
    env.put()
    unknown = "pf1_" + "A" * 43
    for reference in (unknown, "", "garbage", "pf1_" + "A" * 42):
        assert env.vault.retrieve(reference, TENANT, SCOPE) is None


def test_expired_mapping_is_not_returned(env: Env) -> None:
    stored = env.put(ttl=60)
    env.clock.advance(59)
    assert env.vault.retrieve(stored.reference, TENANT, SCOPE) == MAPPINGS
    env.clock.advance(1)  # exactly at expiry: no longer valid
    assert env.vault.retrieve(stored.reference, TENANT, SCOPE) is None


def test_revoked_mapping_is_not_returned(env: Env) -> None:
    stored = env.put()
    assert env.vault.revoke(stored.reference, TENANT) is True
    assert env.vault.retrieve(stored.reference, TENANT, SCOPE) is None
    assert env.vault.revoke(stored.reference, TENANT) is False  # already revoked


def test_deleted_mapping_is_not_returned(env: Env) -> None:
    stored = env.put()
    assert env.vault.mark_deleted(stored.reference, TENANT) is True
    assert env.vault.retrieve(stored.reference, TENANT, SCOPE) is None
    assert env.vault.mark_deleted(stored.reference, TENANT) is False


def test_another_tenant_cannot_revoke_or_delete(env: Env) -> None:
    stored = env.put()
    assert env.vault.revoke(stored.reference, "tenant-test-b") is False
    assert env.vault.mark_deleted(stored.reference, "tenant-test-b") is False
    assert env.vault.retrieve(stored.reference, TENANT, SCOPE) == MAPPINGS


def test_revoking_a_malformed_reference_finds_nothing(env: Env) -> None:
    assert env.vault.revoke("nonsense", TENANT) is False
    assert env.vault.mark_deleted("nonsense", TENANT) is False


def test_revoking_one_reference_leaves_others_valid(env: Env) -> None:
    first, second = env.put(), env.put()
    env.vault.revoke(first.reference, TENANT)
    assert env.vault.retrieve(second.reference, TENANT, SCOPE) == MAPPINGS


def test_mappings_with_any_text_round_trip(env: Env) -> None:
    odd = {"[EMAIL_001]": "a\u0000b\r\n\ud800é\U0001f600", "[EMAIL_002]": ""}
    stored = env.vault.store(TENANT, SCOPE, odd, PROFILES, 3600)
    assert env.vault.retrieve(stored.reference, TENANT, SCOPE) == odd


Change = Callable[[Any], dict[str, Any]]
CHANGES: dict[str, Change] = {
    "ciphertext": lambda r: {"ciphertext": r.ciphertext[:-1] + bytes([r.ciphertext[-1] ^ 1])},
    "nonce": lambda r: {"nonce": bytes([r.nonce[0] ^ 1]) + r.nonce[1:]},
    "key_version": lambda r: {"key_version": 2},
    "unknown_key_version": lambda r: {"key_version": 99},
    "algorithm": lambda r: {"encryption_alg": "NONE"},
    "record_id": lambda r: {"id": uuid.uuid4()},
}


@pytest.mark.parametrize("change", CHANGES.values(), ids=list(CHANGES))
def test_a_row_modified_in_storage_fails_safely_instead_of_returning_data(
    san: Callable[[str], Any], change: Change
) -> None:
    env = Env(san, {1: os.urandom(32), 2: os.urandom(32)})
    stored = env.put()
    (row,) = env.store.rows.values()
    env.store.tamper(**change(row.record))
    with pytest.raises(env.errors.MappingIntegrityError):
        env.vault.retrieve(stored.reference, TENANT, SCOPE)


def test_a_row_moved_to_another_tenant_fails_safely(env: Env) -> None:
    stored = env.put()
    env.store.tamper(tenant_id="tenant-test-b")
    with pytest.raises(env.errors.MappingIntegrityError):
        env.vault.retrieve(stored.reference, "tenant-test-b", SCOPE)


def test_a_row_moved_to_another_scope_fails_safely(env: Env) -> None:
    stored = env.put()
    env.store.tamper(request_scope_id="scope-2")
    with pytest.raises(env.errors.MappingIntegrityError):
        env.vault.retrieve(stored.reference, TENANT, "scope-2")


def test_a_row_written_under_key_1_is_still_returned_after_the_keyring_gains_key_2(
    san: Callable[[str], Any],
) -> None:
    key1, key2 = os.urandom(32), os.urandom(32)
    env = Env(san, {1: key1})
    old = env.put()
    crypto = san("app.vault.crypto")
    rotated = san("app.vault.vault").Vault(
        env.store, crypto.Keyring({1: key1, 2: key2}, 2), env.pepper, env.clock
    )
    assert rotated.retrieve(old.reference, TENANT, SCOPE) == MAPPINGS
    new = rotated.store(TENANT, SCOPE, MAPPINGS, PROFILES, 3600)
    assert {r.record.key_version for r in env.store.rows.values()} == {1, 2}
    assert rotated.retrieve(new.reference, TENANT, SCOPE) == MAPPINGS


def test_a_keyring_missing_the_stored_key_version_fails_safely(san: Callable[[str], Any]) -> None:
    env = Env(san, {1: os.urandom(32)})
    stored = env.put()
    crypto = san("app.vault.crypto")
    without_v1 = san("app.vault.vault").Vault(
        env.store, crypto.Keyring({2: os.urandom(32)}, 2), env.pepper, env.clock
    )
    with pytest.raises(env.errors.MappingIntegrityError):
        without_v1.retrieve(stored.reference, TENANT, SCOPE)


def test_a_payload_that_decrypts_but_has_the_wrong_shape_is_rejected(
    san: Callable[[str], Any],
) -> None:
    env = Env(san, {1: os.urandom(32)})
    stored = env.put()
    (row,) = env.store.rows.values()
    crypto = san("app.vault.crypto")
    for bad in (b"not json", b"[]", b'{"v":2,"mappings":{}}', b'{"v":1,"mappings":{"a":1}}'):
        sealed = env.keyring.seal(bad, crypto.RecordBinding(row.record.id, TENANT, SCOPE))
        env.store.tamper(
            ciphertext=sealed.ciphertext, nonce=sealed.nonce, key_version=sealed.key_version
        )
        with pytest.raises(env.errors.MappingIntegrityError):
            env.vault.retrieve(stored.reference, TENANT, SCOPE)


def test_stored_mapping_repr_hides_the_reference(env: Env) -> None:
    stored = env.put()
    assert stored.reference not in repr(stored)
