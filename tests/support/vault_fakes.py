"""Test doubles at the storage boundary of the vault.

`InMemoryMappingStore` stands in for PostgreSQL so the Vault's real cryptography, scoping and
expiry logic can run without a database. It applies the same rules as the SQL repository. The
SQL repository itself is tested against a real PostgreSQL in tests/integration.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


class FakeClock:
    """A clock the test moves by hand, so expiry never needs a sleep."""

    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@dataclass
class _Row:
    record: Any  # NewMappingRecord
    revoked_at: datetime | None = None
    deleted_at: datetime | None = None


class InMemoryMappingStore:
    def __init__(self, stored_record_type: Any) -> None:
        # The StoredMappingRecord class from the service under test.
        self.stored_record_type = stored_record_type
        self.rows: dict[uuid.UUID, _Row] = {}

    def add(self, record: Any) -> None:
        self.rows[record.id] = _Row(record)

    def _match(self, digest: bytes, tenant_id: str) -> list[_Row]:
        return [
            r
            for r in self.rows.values()
            if r.record.credential_digest == digest and r.record.tenant_id == tenant_id
        ]

    def find_active(
        self, digest: bytes, tenant_id: str, request_scope_id: str, now: datetime
    ) -> Any | None:
        for row in self._match(digest, tenant_id):
            rec = row.record
            if (
                rec.request_scope_id == request_scope_id
                and rec.expires_at > now
                and row.revoked_at is None
                and row.deleted_at is None
            ):
                return self.stored_record_type(
                    id=rec.id,
                    tenant_id=rec.tenant_id,
                    request_scope_id=rec.request_scope_id,
                    ciphertext=rec.ciphertext,
                    nonce=rec.nonce,
                    encryption_alg=rec.encryption_alg,
                    key_version=rec.key_version,
                    expires_at=rec.expires_at,
                )
        return None

    def revoke(self, digest: bytes, tenant_id: str, now: datetime) -> bool:
        for row in self._match(digest, tenant_id):
            if row.revoked_at is None:
                row.revoked_at = now
                return True
        return False

    def mark_deleted(self, digest: bytes, tenant_id: str, now: datetime) -> bool:
        for row in self._match(digest, tenant_id):
            if row.deleted_at is None:
                row.deleted_at = now
                return True
        return False

    def tamper(self, **changes: Any) -> None:
        """Rewrite fields of the only stored record, as a database writer could."""
        (row,) = self.rows.values()
        values = {f: getattr(row.record, f) for f in row.record.__slots__}
        values.update(changes)
        row.record = type(row.record)(**values)
