"""The encrypted mapping vault table. Only digests and ciphertext are ever stored."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, LargeBinary, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MappingRecord(Base):
    __tablename__ = "mapping_records"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_mapping_records_expiry_after_creation"),
        CheckConstraint("length(nonce) = 12", name="ck_mapping_records_nonce_96_bits"),
        Index("ix_mapping_records_tenant_scope", "tenant_id", "request_scope_id"),
        Index("ix_mapping_records_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    request_scope_id: Mapped[str] = mapped_column(Text, nullable=False)
    credential_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_alg: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    profiles: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
