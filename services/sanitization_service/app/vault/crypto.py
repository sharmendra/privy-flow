"""AES-256-GCM sealing of mapping payloads, with a keyring by version.

Uses the `cryptography` package only. Each seal draws a fresh 96-bit random nonce. The
associated data binds the record id, tenant, request scope and key version, so a ciphertext
copied to another row, tenant or scope, or relabeled with another key version, fails to open.
"""

import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.vault.errors import MappingIntegrityError, VaultConfigError

ALGORITHM = "AES-256-GCM"
KEY_BYTES = 32
NONCE_BYTES = 12


@dataclass(frozen=True, slots=True)
class RecordBinding:
    """What a ciphertext is bound to. All three parts and the key version are authenticated."""

    record_id: uuid.UUID
    tenant_id: str
    request_scope_id: str


@dataclass(frozen=True, slots=True)
class SealedPayload:
    ciphertext: bytes = field(repr=False)
    nonce: bytes
    algorithm: str
    key_version: int


def _associated_data(binding: RecordBinding, key_version: int) -> bytes:
    # JSON of a list is unambiguous: no value can run into the next one.
    parts = [str(binding.record_id), binding.tenant_id, binding.request_scope_id, key_version]
    return json.dumps(parts, separators=(",", ":")).encode("utf-8")


class Keyring:
    """Keys by version. New data is sealed with the active version; any held version opens."""

    def __init__(self, keys: Mapping[int, bytes], active_version: int) -> None:
        if not keys or any(len(key) != KEY_BYTES for key in keys.values()):
            raise VaultConfigError("every encryption key must be 32 bytes")
        if any(version < 1 for version in keys):
            raise VaultConfigError("key versions must be positive integers")
        if active_version not in keys:
            raise VaultConfigError("the active key version is not in the keyring")
        self._keys = dict(keys)
        self.active_version = active_version

    def __repr__(self) -> str:
        return f"Keyring(versions={sorted(self._keys)}, active={self.active_version})"

    def seal(self, plaintext: bytes, binding: RecordBinding) -> SealedPayload:
        version = self.active_version
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = AESGCM(self._keys[version]).encrypt(
            nonce, plaintext, _associated_data(binding, version)
        )
        return SealedPayload(ciphertext, nonce, ALGORITHM, version)

    def open(self, sealed: SealedPayload, binding: RecordBinding) -> bytes:
        key = self._keys.get(sealed.key_version)
        if sealed.algorithm != ALGORITHM or key is None or len(sealed.nonce) != NONCE_BYTES:
            raise MappingIntegrityError("stored mapping cannot be opened")
        try:
            return AESGCM(key).decrypt(
                sealed.nonce, sealed.ciphertext, _associated_data(binding, sealed.key_version)
            )
        except InvalidTag:
            raise MappingIntegrityError("stored mapping cannot be opened") from None
