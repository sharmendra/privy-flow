"""AES-256-GCM sealing, the keyring and key versions. Real cryptography with test-time keys."""

import dataclasses
import os
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

BINDING_ARGS = (uuid.UUID(int=1), "tenant-test-a", "scope-1")


@pytest.fixture(scope="module")
def crypto(san: Callable[[str], Any]) -> Any:
    return san("app.vault.crypto")


@pytest.fixture(scope="module")
def errors(san: Callable[[str], Any]) -> Any:
    return san("app.vault.errors")


@pytest.fixture
def binding(crypto: Any) -> Any:
    return crypto.RecordBinding(*BINDING_ARGS)


@pytest.fixture
def keyring(crypto: Any) -> Any:
    return crypto.Keyring({1: os.urandom(32)}, active_version=1)


def test_seal_then_open_returns_the_plaintext(keyring: Any, binding: Any) -> None:
    sealed = keyring.seal(b'{"mappings":{"[EMAIL_001]":"a@example.com"}}', binding)
    assert keyring.open(sealed, binding) == b'{"mappings":{"[EMAIL_001]":"a@example.com"}}'


@given(st.binary(max_size=2048))
def test_property_round_trip_for_any_plaintext(crypto: Any, plaintext: bytes) -> None:
    keyring = crypto.Keyring({1: os.urandom(32)}, active_version=1)
    binding = crypto.RecordBinding(*BINDING_ARGS)
    assert keyring.open(keyring.seal(plaintext, binding), binding) == plaintext


@given(st.binary(min_size=8, max_size=512))
def test_property_ciphertext_never_contains_the_plaintext(crypto: Any, plaintext: bytes) -> None:
    keyring = crypto.Keyring({1: os.urandom(32)}, active_version=1)
    sealed = keyring.seal(plaintext, crypto.RecordBinding(*BINDING_ARGS))
    assert plaintext not in sealed.ciphertext


def test_sealed_payload_records_algorithm_nonce_size_and_key_version(
    crypto: Any, keyring: Any, binding: Any
) -> None:
    sealed = keyring.seal(b"x", binding)
    assert sealed.algorithm == "AES-256-GCM"
    assert len(sealed.nonce) == 12
    assert sealed.key_version == 1


def test_nonce_is_unique_across_10000_encryptions(keyring: Any, binding: Any) -> None:
    nonces = {keyring.seal(b"same plaintext", binding).nonce for _ in range(10_000)}
    assert len(nonces) == 10_000


def test_same_plaintext_gives_different_ciphertext_each_time(keyring: Any, binding: Any) -> None:
    assert keyring.seal(b"x", binding).ciphertext != keyring.seal(b"x", binding).ciphertext


def _flip(data: bytes, index: int = 0) -> bytes:
    return data[:index] + bytes([data[index] ^ 0x01]) + data[index + 1 :]


@pytest.mark.parametrize("position", ["first", "middle", "last"])
def test_tampered_ciphertext_is_rejected(
    keyring: Any, binding: Any, errors: Any, position: str
) -> None:
    sealed = keyring.seal(b"a payload long enough to flip a byte in the middle", binding)
    index = {"first": 0, "middle": len(sealed.ciphertext) // 2, "last": -1}[position]
    index = index % len(sealed.ciphertext)
    bad = dataclasses.replace(sealed, ciphertext=_flip(sealed.ciphertext, index))
    with pytest.raises(errors.MappingIntegrityError):
        keyring.open(bad, binding)


def test_truncated_ciphertext_is_rejected(keyring: Any, binding: Any, errors: Any) -> None:
    sealed = keyring.seal(b"payload", binding)
    with pytest.raises(errors.MappingIntegrityError):
        keyring.open(dataclasses.replace(sealed, ciphertext=sealed.ciphertext[:-1]), binding)


def test_tampered_nonce_is_rejected(keyring: Any, binding: Any, errors: Any) -> None:
    sealed = keyring.seal(b"payload", binding)
    with pytest.raises(errors.MappingIntegrityError):
        keyring.open(dataclasses.replace(sealed, nonce=_flip(sealed.nonce)), binding)


@pytest.mark.parametrize("nonce", [b"", b"short", b"x" * 13])
def test_a_nonce_of_the_wrong_length_is_rejected(
    keyring: Any, binding: Any, errors: Any, nonce: bytes
) -> None:
    sealed = keyring.seal(b"payload", binding)
    with pytest.raises(errors.MappingIntegrityError):
        keyring.open(dataclasses.replace(sealed, nonce=nonce), binding)


def test_tampered_key_version_is_rejected_even_when_that_version_exists(
    crypto: Any, binding: Any, errors: Any
) -> None:
    keyring = crypto.Keyring({1: os.urandom(32), 2: os.urandom(32)}, active_version=1)
    sealed = keyring.seal(b"payload", binding)
    with pytest.raises(errors.MappingIntegrityError):
        keyring.open(dataclasses.replace(sealed, key_version=2), binding)


def test_unknown_key_version_fails_safely(keyring: Any, binding: Any, errors: Any) -> None:
    sealed = keyring.seal(b"payload", binding)
    with pytest.raises(errors.MappingIntegrityError):
        keyring.open(dataclasses.replace(sealed, key_version=99), binding)


def test_unknown_algorithm_fails_safely(keyring: Any, binding: Any, errors: Any) -> None:
    sealed = keyring.seal(b"payload", binding)
    with pytest.raises(errors.MappingIntegrityError):
        keyring.open(dataclasses.replace(sealed, algorithm="AES-128-CBC"), binding)


@pytest.mark.parametrize(
    "other",
    [
        (uuid.UUID(int=2), "tenant-test-a", "scope-1"),
        (uuid.UUID(int=1), "tenant-test-b", "scope-1"),
        (uuid.UUID(int=1), "tenant-test-a", "scope-2"),
    ],
    ids=["record_id", "tenant", "scope"],
)
def test_changed_associated_data_is_rejected(
    crypto: Any, keyring: Any, binding: Any, errors: Any, other: tuple[Any, str, str]
) -> None:
    sealed = keyring.seal(b"payload", binding)
    with pytest.raises(errors.MappingIntegrityError):
        keyring.open(sealed, crypto.RecordBinding(*other))


def test_associated_data_cannot_be_confused_by_moving_text_between_fields(
    crypto: Any, keyring: Any, errors: Any
) -> None:
    sealed = keyring.seal(b"payload", crypto.RecordBinding(uuid.UUID(int=1), "ab", "c"))
    with pytest.raises(errors.MappingIntegrityError):
        keyring.open(sealed, crypto.RecordBinding(uuid.UUID(int=1), "a", "bc"))


def test_a_row_sealed_under_version_1_opens_after_the_keyring_gains_version_2(
    crypto: Any, binding: Any
) -> None:
    key1, key2 = os.urandom(32), os.urandom(32)
    old = crypto.Keyring({1: key1}, active_version=1)
    sealed = old.seal(b"written under v1", binding)
    rotated = crypto.Keyring({1: key1, 2: key2}, active_version=2)
    assert rotated.open(sealed, binding) == b"written under v1"
    assert rotated.seal(b"new", binding).key_version == 2


def test_a_keyring_without_the_old_version_cannot_open_old_rows(
    crypto: Any, binding: Any, errors: Any
) -> None:
    sealed = crypto.Keyring({1: os.urandom(32)}, 1).seal(b"payload", binding)
    only_v2 = crypto.Keyring({2: os.urandom(32)}, 2)
    with pytest.raises(errors.MappingIntegrityError):
        only_v2.open(sealed, binding)


def test_a_different_key_of_the_same_version_cannot_open_the_row(
    crypto: Any, binding: Any, errors: Any
) -> None:
    sealed = crypto.Keyring({1: os.urandom(32)}, 1).seal(b"payload", binding)
    with pytest.raises(errors.MappingIntegrityError):
        crypto.Keyring({1: os.urandom(32)}, 1).open(sealed, binding)


@pytest.mark.parametrize(
    ("keys", "active"),
    [
        ({}, 1),
        ({1: b"short"}, 1),
        ({1: b"x" * 33}, 1),
        ({0: b"x" * 32}, 0),
        ({1: b"x" * 32}, 2),
    ],
    ids=["empty", "short_key", "long_key", "version_zero", "active_missing"],
)
def test_keyring_rejects_invalid_configuration(
    crypto: Any, errors: Any, keys: dict[int, bytes], active: int
) -> None:
    with pytest.raises(errors.VaultConfigError):
        crypto.Keyring(keys, active)


def test_keyring_repr_shows_versions_only(crypto: Any) -> None:
    key = b"K" * 32
    text = repr(crypto.Keyring({1: key}, 1))
    assert "K" * 8 not in text
    assert "versions=[1]" in text


def test_integrity_error_message_names_nothing_sensitive(
    keyring: Any, binding: Any, errors: Any
) -> None:
    sealed = keyring.seal(b"CANARY-PLAINTEXT", binding)
    with pytest.raises(errors.MappingIntegrityError) as caught:
        keyring.open(dataclasses.replace(sealed, ciphertext=_flip(sealed.ciphertext)), binding)
    assert "CANARY" not in str(caught.value)
    assert str(caught.value) == "stored mapping cannot be opened"
