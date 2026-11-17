"""Create the settings store tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-17
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_TABLES = ("settings_snapshots", "settings_audit")


def _grant(option: str, default: str, privileges: str) -> None:
    """Grant on both settings tables to a role, if that role exists."""
    role = context.config.get_main_option(option) or default
    if not _ROLE_NAME.match(role):
        raise RuntimeError(f"{option} is not a valid role name")
    bind = op.get_bind()
    exists = bind.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
    if exists.first() is None:
        return
    quoted = bind.dialect.identifier_preparer.quote(role)
    for table in _TABLES:
        op.execute(f"GRANT {privileges} ON {table} TO {quoted}")


def upgrade() -> None:
    op.create_table(
        "settings_snapshots",
        sa.Column("version", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_settings_snapshots_version_positive"),
        sa.PrimaryKeyConstraint("version"),
    )
    op.create_table(
        "settings_audit",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('import', 'export', 'activate')", name="ck_settings_audit_action"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # The service reads settings. The admin role can append rows, never edit or delete them.
    _grant("runtime_role", "privyflow_runtime", "SELECT")
    _grant("settings_admin_role", "privyflow_settings_admin", "SELECT, INSERT")


def downgrade() -> None:
    op.drop_table("settings_audit")
    op.drop_table("settings_snapshots")
