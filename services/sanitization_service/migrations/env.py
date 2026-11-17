"""Alembic environment. Runs as an admin role, never as the service's runtime role."""

import os

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config


def _database_url() -> str:
    url = config.get_main_option("sqlalchemy.url") or os.environ.get(
        "PRIVYFLOW_SAN_MIGRATION_DATABASE_URL"
    )
    if not url:
        raise RuntimeError("Set PRIVYFLOW_SAN_MIGRATION_DATABASE_URL to run migrations")
    return url


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported")
run_migrations_online()
