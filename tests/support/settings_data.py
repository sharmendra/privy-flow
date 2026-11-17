"""Synthetic settings content and invalid variants for settings store tests."""

import copy
import json
from pathlib import Path
from typing import Any

CANARY = "canary-value-7f3a"

VALID: dict[str, Any] = {
    "schema_version": 1,
    "tenant_profiles": {
        "tenant-test-a": ["gdpr"],
        "tenant-test-b": ["gdpr", "hipaa"],
    },
    "default_ttl_seconds": 1800,
    "max_request_bytes": 65536,
    "strict_coverage": False,
}


def valid_content(**overrides: Any) -> dict[str, Any]:
    content = copy.deepcopy(VALID)
    content.update(overrides)
    return content


def write_settings_file(path: Path, content: dict[str, Any] | None = None) -> Path:
    path.write_text(json.dumps(content or VALID, indent=2), encoding="utf-8")
    return path


# (id, overrides applied to VALID, text that must appear in the error message)
INVALID_CASES: list[tuple[str, dict[str, Any], str]] = [
    ("unknown_key", {"surprise_setting": CANARY}, "surprise_setting"),
    (
        "unknown_profile",
        {"tenant_profiles": {"tenant-test-a": ["gdpr", CANARY]}},
        "tenant_profiles",
    ),
    ("empty_profile_list", {"tenant_profiles": {"tenant-test-a": []}}, "tenant-test-a"),
    ("malformed_tenant_id", {"tenant_profiles": {"Bad Tenant!": ["gdpr"]}}, "tenant_profiles"),
    ("ttl_above_maximum", {"default_ttl_seconds": 3601}, "default_ttl_seconds"),
    ("ttl_below_minimum", {"default_ttl_seconds": 59}, "default_ttl_seconds"),
    ("size_limit_below_floor", {"max_request_bytes": 1023}, "max_request_bytes"),
    ("wrong_type_flag", {"strict_coverage": CANARY}, "strict_coverage"),
    ("wrong_type_size", {"max_request_bytes": CANARY}, "max_request_bytes"),
    ("secret_encryption_key", {"encryption_key": CANARY}, "encryption_key"),
    ("secret_service_secret", {"service_secret": CANARY}, "service_secret"),
    ("secret_api_keys", {"api_keys": CANARY}, "api_keys"),
    ("secret_database_password", {"database_password": CANARY}, "database_password"),
    ("secret_pepper", {"pepper": CANARY}, "pepper"),
]
