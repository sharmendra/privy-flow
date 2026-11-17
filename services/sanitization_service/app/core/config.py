"""Sanitization Service settings. Read from environment variables and an optional .env file."""

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_NAME = "sanitization"
SERVICE_VERSION = "0.1.0"
_DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PRIVYFLOW_SAN_", extra="ignore")

    # Runtime database role (least privilege). Migrations use a separate admin URL that the
    # running service never reads.
    database_url: SecretStr

    # Bootstrap settings: where the operational settings live. Never stored in the store itself.
    settings_backend: Literal["file", "db"] = Field(
        default="file", validation_alias="PRIVYFLOW_SETTINGS_BACKEND"
    )
    settings_file: Path | None = Field(default=None, validation_alias="PRIVYFLOW_SETTINGS_FILE")

    # Secrets for the vault and the public API. They come from the environment only and are
    # parsed and validated at startup (app.vault.config, app.core.auth). A missing or malformed
    # value leaves the service alive but not ready.
    api_keys: SecretStr  # JSON object: tenant ID to API key
    encryption_keys: SecretStr  # JSON object: key version to base64 AES-256 key
    active_key_version: int = Field(ge=1)
    credential_pepper: SecretStr  # base64, at least 32 bytes

    @field_validator("database_url")
    @classmethod
    def _postgresql_only(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("database_url must be a PostgreSQL URL")
        return value


def load_settings() -> Settings:
    env_file = os.environ.get("PRIVYFLOW_SAN_ENV_FILE", str(_DEFAULT_ENV_FILE))
    # Required fields are filled from the environment, which type checkers cannot see and
    # report as missing arguments, so the class is called through Any and the result typed.
    factory: Any = Settings
    settings: Settings = factory(_env_file=env_file)
    return settings
