"""The Vault: stores a request's mappings encrypted and returns them for a valid reference.

It combines credential generation, authenticated encryption and the repository. Storage
holds only the credential digest and ciphertext. The plaintext payload is the
placeholder-to-value map and nothing else; request text is never stored.
"""

import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from app.repositories.mapping_repository import MappingStore, NewMappingRecord
from app.vault.credentials import credential_digest, generate_reference, is_valid_reference
from app.vault.crypto import Keyring, RecordBinding, SealedPayload
from app.vault.errors import MappingIntegrityError

_PAYLOAD_VERSION = 1


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class StoredMapping:
    reference: str = field(repr=False)
    expires_at: datetime


class Vault:
    def __init__(
        self,
        store: MappingStore,
        keyring: Keyring,
        pepper: bytes,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._store = store
        self._keyring = keyring
        self._pepper = pepper
        self._clock = clock

    def store(
        self,
        tenant_id: str,
        request_scope_id: str,
        mappings: Mapping[str, str],
        profiles: dict[str, Any],
        ttl_seconds: int,
    ) -> StoredMapping:
        """Encrypt and store the mappings. Returns the new reference and its expiry."""
        record_id = uuid.uuid4()
        now = self._clock()
        expires_at = now + timedelta(seconds=ttl_seconds)
        reference = generate_reference()
        # ensure_ascii keeps the payload valid for any text, including lone surrogates.
        payload = json.dumps({"v": _PAYLOAD_VERSION, "mappings": dict(mappings)}).encode("utf-8")
        sealed = self._keyring.seal(payload, RecordBinding(record_id, tenant_id, request_scope_id))
        self._store.add(
            NewMappingRecord(
                id=record_id,
                tenant_id=tenant_id,
                request_scope_id=request_scope_id,
                credential_digest=self._digest(reference),
                ciphertext=sealed.ciphertext,
                nonce=sealed.nonce,
                encryption_alg=sealed.algorithm,
                key_version=sealed.key_version,
                profiles=profiles,
                created_at=now,
                expires_at=expires_at,
            )
        )
        return StoredMapping(reference, expires_at)

    def retrieve(
        self, reference: str, tenant_id: str, request_scope_id: str
    ) -> dict[str, str] | None:
        """The mappings for a reference, or None when no active record matches.

        None covers a malformed, unknown, expired, revoked, deleted, cross-tenant and
        cross-scope reference alike. A record that is found but fails authentication raises
        MappingIntegrityError.
        """
        if not is_valid_reference(reference):
            return None
        digest = self._digest(reference)
        record = self._store.find_active(digest, tenant_id, request_scope_id, self._clock())
        if record is None:
            return None
        sealed = SealedPayload(
            record.ciphertext, record.nonce, record.encryption_alg, record.key_version
        )
        plaintext = self._keyring.open(
            sealed, RecordBinding(record.id, record.tenant_id, record.request_scope_id)
        )
        return _parse_payload(plaintext)

    def revoke(self, reference: str, tenant_id: str) -> bool:
        """Revoke a reference of the tenant. False when none was found."""
        if not is_valid_reference(reference):
            return False
        return self._store.revoke(self._digest(reference), tenant_id, self._clock())

    def mark_deleted(self, reference: str, tenant_id: str) -> bool:
        """Mark the record deleted for retention. False when none was found."""
        if not is_valid_reference(reference):
            return False
        return self._store.mark_deleted(self._digest(reference), tenant_id, self._clock())

    def _digest(self, reference: str) -> bytes:
        return credential_digest(reference, self._pepper)


def _parse_payload(plaintext: bytes) -> dict[str, str]:
    try:
        loaded = json.loads(plaintext)
    except ValueError:
        raise MappingIntegrityError("stored mapping cannot be opened") from None
    if not isinstance(loaded, dict):
        raise MappingIntegrityError("stored mapping cannot be opened")
    payload = cast("dict[str, object]", loaded)
    mappings = payload.get("mappings")
    if payload.get("v") != _PAYLOAD_VERSION or not isinstance(mappings, dict):
        raise MappingIntegrityError("stored mapping cannot be opened")
    items = cast("dict[object, object]", mappings).items()
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in items):
        raise MappingIntegrityError("stored mapping cannot be opened")
    return cast("dict[str, str]", dict(items))
