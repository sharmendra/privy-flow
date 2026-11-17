"""Run the Sanitization Service Alembic migrations from tests."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from tests.support.service_loader import services_dir


def alembic_config(
    url: str, runtime_role: str | None = None, settings_admin_role: str | None = None
) -> Config:
    root = services_dir() / "sanitization_service"
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(Path(root / "migrations")))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    if runtime_role is not None:
        config.set_main_option("runtime_role", runtime_role)
    if settings_admin_role is not None:
        config.set_main_option("settings_admin_role", settings_admin_role)
    return config


def upgrade(
    url: str,
    revision: str = "head",
    runtime_role: str | None = None,
    settings_admin_role: str | None = None,
) -> None:
    command.upgrade(alembic_config(url, runtime_role, settings_admin_role), revision)


def downgrade(
    url: str,
    revision: str = "base",
    runtime_role: str | None = None,
    settings_admin_role: str | None = None,
) -> None:
    command.downgrade(alembic_config(url, runtime_role, settings_admin_role), revision)
