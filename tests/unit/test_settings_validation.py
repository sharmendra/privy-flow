"""Settings validation and snapshot hashing. Pure logic: no database, no files."""

import importlib
from collections.abc import Callable
from typing import Any

import pytest

from tests.support.service_loader import load_service_app
from tests.support.settings_data import CANARY, INVALID_CASES, VALID, valid_content

KNOWN_PROFILES = {"gdpr", "india_dpdp", "hipaa", "pci_dss", "glba", "ccpa"}


@pytest.fixture
def validator() -> Any:
    load_service_app("sanitization_service")
    return importlib.import_module("app.settings.validator")


@pytest.fixture
def sanitization_import() -> Callable[[str], Any]:
    load_service_app("sanitization_service")
    return importlib.import_module


def test_valid_settings_load_with_defaults_applied(validator: Any) -> None:
    content = validator.validate_settings({"schema_version": 1})
    assert content.tenant_profiles == {}
    assert content.default_ttl_seconds == 3600
    assert content.max_request_bytes == 262144
    assert content.strict_coverage is False


def test_known_profile_ids_are_the_six_profile_files(validator: Any) -> None:
    assert validator.known_profile_ids() == KNOWN_PROFILES


def test_every_documented_profile_is_accepted_for_a_tenant(validator: Any) -> None:
    raw = valid_content(tenant_profiles={"tenant-test-a": sorted(KNOWN_PROFILES)})
    assert validator.validate_settings(raw).tenant_profiles["tenant-test-a"]


@pytest.mark.parametrize(
    ("case", "overrides", "field"), INVALID_CASES, ids=[c[0] for c in INVALID_CASES]
)
def test_invalid_settings_fail_naming_the_field_and_no_value(
    validator: Any, case: str, overrides: dict[str, Any], field: str
) -> None:
    with pytest.raises(validator.SettingsError) as raised:
        validator.validate_settings(valid_content(**overrides))
    message = str(raised.value)
    assert field in message
    assert CANARY not in message


def test_settings_that_are_not_an_object_fail_safely(validator: Any) -> None:
    with pytest.raises(validator.SettingsError):
        validator.validate_settings([CANARY])


def test_missing_schema_version_fails(validator: Any) -> None:
    raw = valid_content()
    del raw["schema_version"]
    with pytest.raises(validator.SettingsError, match="schema_version"):
        validator.validate_settings(raw)


def test_tenant_ids_that_look_like_secret_names_are_allowed(validator: Any) -> None:
    raw = valid_content(tenant_profiles={"my-key-tenant": ["gdpr"]})
    assert "my-key-tenant" in validator.validate_settings(raw).tenant_profiles


def test_content_hash_is_stable_and_ignores_key_order(
    sanitization_import: Callable[[str], Any],
) -> None:
    snapshot = sanitization_import("app.settings.snapshot")
    validator = sanitization_import("app.settings.validator")
    first = validator.validate_settings(VALID)
    reordered = validator.validate_settings(dict(reversed(list(VALID.items()))))
    assert snapshot.content_hash(first) == snapshot.content_hash(reordered)
    assert len(snapshot.content_hash(first)) == 64


def test_content_hash_treats_explicit_defaults_like_omitted_ones(
    sanitization_import: Callable[[str], Any],
) -> None:
    snapshot = sanitization_import("app.settings.snapshot")
    validator = sanitization_import("app.settings.validator")
    omitted = validator.validate_settings({"schema_version": 1})
    explicit = validator.validate_settings(
        {
            "schema_version": 1,
            "tenant_profiles": {},
            "default_ttl_seconds": 3600,
            "max_request_bytes": 262144,
            "strict_coverage": False,
        }
    )
    assert snapshot.content_hash(omitted) == snapshot.content_hash(explicit)


def test_content_hash_changes_when_content_changes(
    sanitization_import: Callable[[str], Any],
) -> None:
    snapshot = sanitization_import("app.settings.snapshot")
    validator = sanitization_import("app.settings.validator")
    base = validator.validate_settings(VALID)
    changed = validator.validate_settings(valid_content(default_ttl_seconds=900))
    assert snapshot.content_hash(base) != snapshot.content_hash(changed)
