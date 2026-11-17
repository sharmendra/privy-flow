"""Create the encrypted mapping vault table.

Revision ID: 0001
Revises:
Create Date: 2026-11-17
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _grant_runtime_access() -> None:
    """Give the runtime role SELECT, INSERT and UPDATE only. Deletion is a soft marker."""
    role = context.config.get_main_option("runtime_role") or "privyflow_runtime"
    if not _ROLE_NAME.match(role):
        raise RuntimeError("runtime_role is not a valid role name")
    bind = op.get_bind()
    exists = bind.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
    if exists.first() is not None:
        quoted = bind.dialect.identifier_preparer.quote(role)
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON mapping_records TO {quoted}")


def upgrade() -> None:
    op.create_table(
        "mapping_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("request_scope_id", sa.Text(), nullable=False),
        sa.Column("credential_digest", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_alg", sa.Text(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("profiles", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_mapping_records_expiry_after_creation"
        ),
        sa.CheckConstraint("length(nonce) = 12", name="ck_mapping_records_nonce_96_bits"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("credential_digest"),
    )
    op.create_index(
        "ix_mapping_records_tenant_scope", "mapping_records", ["tenant_id", "request_scope_id"]
    )
    op.create_index("ix_mapping_records_expires_at", "mapping_records", ["expires_at"])
    _grant_runtime_access()


def downgrade() -> None:
    op.drop_index("ix_mapping_records_expires_at", table_name="mapping_records")
    op.drop_index("ix_mapping_records_tenant_scope", table_name="mapping_records")
    op.drop_table("mapping_records")
