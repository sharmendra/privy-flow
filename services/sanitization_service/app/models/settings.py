"""Settings store tables. The service reads them; only the admin role writes them."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Identity, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SettingsSnapshotRecord(Base):
    """Append-only: one row per imported settings version."""

    __tablename__ = "settings_snapshots"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_settings_snapshots_version_positive"),
    )

    version: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)


class SettingsAuditRecord(Base):
    """Safe metadata about settings changes. Never holds settings values or secrets."""

    __tablename__ = "settings_audit"
    __table_args__ = (
        CheckConstraint(
            "action IN ('import', 'export', 'activate')", name="ck_settings_audit_action"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
