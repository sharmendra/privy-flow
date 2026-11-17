"""De-sanitization Service settings. Read from environment variables and an optional .env file.

This service has no database. It reaches mappings only through the Sanitization Service's
internal HTTP API, so no database setting exists here, and any database URL supplied in the
environment is ignored.
"""

import os
from pathlib import Path
from typing import Any

from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_NAME = "desanitization"
SERVICE_VERSION = "0.1.0"
_DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PRIVYFLOW_DESAN_", extra="ignore")

    sanitization_base_url: AnyHttpUrl


def load_settings() -> Settings:
    env_file = os.environ.get("PRIVYFLOW_DESAN_ENV_FILE", str(_DEFAULT_ENV_FILE))
    # Required fields are filled from the environment, which type checkers cannot see and
    # report as missing arguments, so the class is called through Any and the result typed.
    factory: Any = Settings
    settings: Settings = factory(_env_file=env_file)
    return settings
