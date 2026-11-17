"""De-sanitization Service settings. Read from environment variables and an optional .env file.

This service has no database. It reaches mappings only through the Sanitization Service's
internal HTTP API, so no database setting exists here, and any database URL supplied in the
environment is ignored. It has no settings store either (PLAN_PILOT, "Excluded"): its few
operational values live here, in its own environment.
"""

import os
from pathlib import Path
from typing import Any

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_NAME = "desanitization"
SERVICE_VERSION = "0.1.0"
DEFAULT_MAX_REQUEST_BYTES = 262144
DEFAULT_MAX_OUTPUT_BYTES = 1048576
DEFAULT_INTERNAL_CLIENT_TIMEOUT_SECONDS = 3.0
_DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PRIVYFLOW_DESAN_", extra="ignore")

    sanitization_base_url: AnyHttpUrl

    # Secrets come from the environment only. A missing or malformed value leaves the service
    # alive but not ready.
    api_keys: SecretStr  # JSON object: tenant ID to this service's own client API key
    service_secret: SecretStr  # presented to the Sanitization internal API (decision D3)

    # Limits (SPEC 9.2 and 9.6).
    max_request_bytes: int = Field(default=DEFAULT_MAX_REQUEST_BYTES, ge=1024)
    max_output_bytes: int = Field(default=DEFAULT_MAX_OUTPUT_BYTES, ge=1024)
    internal_client_timeout_seconds: float = Field(
        default=DEFAULT_INTERNAL_CLIENT_TIMEOUT_SECONDS, gt=0, le=30
    )


def load_settings() -> Settings:
    env_file = os.environ.get("PRIVYFLOW_DESAN_ENV_FILE", str(_DEFAULT_ENV_FILE))
    # Required fields are filled from the environment, which type checkers cannot see and
    # report as missing arguments, so the class is called through Any and the result typed.
    factory: Any = Settings
    settings: Settings = factory(_env_file=env_file)
    return settings
