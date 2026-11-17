"""Structured logging with a field allowlist.

Only the fields below can ever be written. Request bodies, headers, query strings and
exception messages have no way into a log line.
"""

import json
import logging
import sys
from datetime import UTC, datetime

from app.core.config import SERVICE_NAME, SERVICE_VERSION

LOGGER_NAME = f"privyflow.{SERVICE_NAME}"
ALLOWED_FIELDS = (
    "service",
    "version",
    "correlation_id",
    "method",
    "route",
    "status_code",
    "latency_ms",
    "outcome",
    "error_category",
    "settings_backend",
    "settings_version",
    "settings_hash",
)

logger = logging.getLogger(LOGGER_NAME)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        for field in ALLOWED_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        return json.dumps(payload, separators=(",", ":"))


def configure_logging() -> None:
    if any(isinstance(h.formatter, JsonFormatter) for h in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def log_event(event: str, level: int = logging.INFO, **fields: object) -> None:
    logger.log(
        level,
        event,
        extra={"service": SERVICE_NAME, "version": SERVICE_VERSION, **fields},
    )
