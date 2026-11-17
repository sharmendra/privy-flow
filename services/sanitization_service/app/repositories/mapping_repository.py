"""Rows of the mapping vault table.

Every read requires the credential digest, tenant and request scope to match, and the record to
be unexpired, unrevoked and undeleted. Time is passed in, so tests control it without sleeping.
The repository never sees plaintext: it stores and returns ciphertext only.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import ReturningUpdate

from app.models.mapping_record import MappingRecord


@dataclass(frozen=True, slots=True)
class NewMappingRecord:
    id: uuid.UUID
    tenant_id: str
    request_scope_id: str
    credential_digest: bytes = field(repr=False)
    ciphertext: bytes = field(repr=False)
    nonce: bytes
    encryption_alg: str
    key_version: int
    profiles: dict[str, Any]
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class StoredMappingRecord:
    id: uuid.UUID
    tenant_id: str
    request_scope_id: str
    ciphertext: bytes = field(repr=False)
    nonce: bytes
    encryption_alg: str
    key_version: int
    expires_at: datetime


class MappingStore(Protocol):
    """What the Vault needs from storage. The SQL repository and test doubles both fit."""

    def add(self, record: NewMappingRecord) -> None: ...

    def find_active(
        self, digest: bytes, tenant_id: str, request_scope_id: str, now: datetime
    ) -> StoredMappingRecord | None: ...

    def revoke(self, digest: bytes, tenant_id: str, now: datetime) -> bool: ...

    def mark_deleted(self, digest: bytes, tenant_id: str, now: datetime) -> bool: ...


class MappingRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, record: NewMappingRecord) -> None:
        with Session(self._engine) as session, session.begin():
            session.add(
                MappingRecord(
                    id=record.id,
                    tenant_id=record.tenant_id,
                    request_scope_id=record.request_scope_id,
                    credential_digest=record.credential_digest,
                    ciphertext=record.ciphertext,
                    nonce=record.nonce,
                    encryption_alg=record.encryption_alg,
                    key_version=record.key_version,
                    profiles=record.profiles,
                    created_at=record.created_at,
                    expires_at=record.expires_at,
                )
            )

    def find_active(
        self, digest: bytes, tenant_id: str, request_scope_id: str, now: datetime
    ) -> StoredMappingRecord | None:
        statement = select(MappingRecord).where(
            MappingRecord.credential_digest == digest,
            MappingRecord.tenant_id == tenant_id,
            MappingRecord.request_scope_id == request_scope_id,
            MappingRecord.expires_at > now,
            MappingRecord.revoked_at.is_(None),
            MappingRecord.deleted_at.is_(None),
        )
        with Session(self._engine) as session:
            row = session.execute(statement).scalar_one_or_none()
            if row is None:
                return None
            return StoredMappingRecord(
                id=row.id,
                tenant_id=row.tenant_id,
                request_scope_id=row.request_scope_id,
                ciphertext=bytes(row.ciphertext),
                nonce=bytes(row.nonce),
                encryption_alg=row.encryption_alg,
                key_version=row.key_version,
                expires_at=row.expires_at,
            )

    def revoke(self, digest: bytes, tenant_id: str, now: datetime) -> bool:
        """Mark the record revoked. True when an unrevoked record of this tenant was found."""
        statement = (
            update(MappingRecord)
            .where(
                MappingRecord.credential_digest == digest,
                MappingRecord.tenant_id == tenant_id,
                MappingRecord.revoked_at.is_(None),
            )
            .values(revoked_at=now)
            .returning(MappingRecord.id)
        )
        return self._run_update(statement)

    def mark_deleted(self, digest: bytes, tenant_id: str, now: datetime) -> bool:
        """Soft-delete for retention. True when an undeleted record of this tenant was found."""
        statement = (
            update(MappingRecord)
            .where(
                MappingRecord.credential_digest == digest,
                MappingRecord.tenant_id == tenant_id,
                MappingRecord.deleted_at.is_(None),
            )
            .values(deleted_at=now)
            .returning(MappingRecord.id)
        )
        return self._run_update(statement)

    def _run_update(self, statement: ReturningUpdate[uuid.UUID]) -> bool:
        with Session(self._engine) as session, session.begin():
            return session.execute(statement).first() is not None
