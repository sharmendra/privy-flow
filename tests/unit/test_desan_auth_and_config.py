"""De-sanitization API key and service secret parsing, the authenticator and the settings."""

import json
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

KEY_A = "a" * 24
KEY_B = "b" * 24
SECRET = "s" * 32


@pytest.fixture
def auth(desan: Callable[[str], Any]) -> Any:
    return desan("app.core.auth")


@pytest.fixture
def config(desan: Callable[[str], Any]) -> Any:
    return desan("app.core.config")


def test_valid_api_keys_are_parsed_by_tenant(auth: Any) -> None:
    keys = auth.parse_api_keys(json.dumps({"tenant-one": KEY_A, "tenant-two": KEY_B}))
    assert keys == {"tenant-one": KEY_A, "tenant-two": KEY_B}


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        "{}",
        json.dumps({"Bad Tenant": KEY_A}),
        json.dumps({"tenant-one": "short"}),
        json.dumps({"tenant-one": 12345678901234567890123456}),
        json.dumps({"tenant-one": "é" * 30}),
        json.dumps({"tenant-one": KEY_A, "tenant-two": KEY_A}),
    ],
    ids=[
        "not_json",
        "list",
        "empty",
        "bad_tenant",
        "short_key",
        "non_string_key",
        "non_ascii_key",
        "shared_key",
    ],
)
def test_malformed_api_keys_are_refused_without_naming_a_value(auth: Any, raw: str) -> None:
    with pytest.raises(auth.ConfigError) as excinfo:
        auth.parse_api_keys(raw)
    assert KEY_A not in str(excinfo.value)


def test_a_valid_service_secret_is_accepted(auth: Any) -> None:
    assert auth.parse_service_secret(SECRET, [KEY_A]) == SECRET


@pytest.mark.parametrize(
    "secret",
    ["short", "has a space " + "x" * 30, "é" * 40, "tab\t" + "x" * 40, KEY_A + "x" * 20],
    ids=["short", "space", "non_ascii", "control_character", "equals_an_api_key"],
)
def test_a_weak_or_malformed_service_secret_is_refused(auth: Any, secret: str) -> None:
    with pytest.raises(auth.ConfigError):
        auth.parse_service_secret(secret, [KEY_A + "x" * 20])


def test_the_authenticator_finds_the_tenant_of_the_exact_key(auth: Any) -> None:
    authenticator = auth.ApiKeyAuthenticator({"tenant-one": KEY_A, "tenant-two": KEY_B})
    assert authenticator.tenant_for(KEY_B) == "tenant-two"
    assert authenticator.tenant_for(KEY_A) == "tenant-one"


@pytest.mark.parametrize("presented", [None, "", KEY_A[:-1], KEY_A + "x", KEY_A.upper(), SECRET])
def test_the_authenticator_rejects_anything_that_is_not_an_exact_key(
    auth: Any, presented: str | None
) -> None:
    assert auth.ApiKeyAuthenticator({"tenant-one": KEY_A}).tenant_for(presented) is None


def test_the_authenticator_does_not_show_keys_when_printed(auth: Any) -> None:
    authenticator = auth.ApiKeyAuthenticator({"tenant-one": KEY_A})
    assert KEY_A not in repr(authenticator)
    assert "tenant-one" not in repr(authenticator)


def test_settings_defaults_match_the_spec(
    config: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("PRIVYFLOW_DESAN_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.setenv("PRIVYFLOW_DESAN_SANITIZATION_BASE_URL", "http://127.0.0.1:8001")
    monkeypatch.setenv("PRIVYFLOW_DESAN_API_KEYS", json.dumps({"tenant-one": KEY_A}))
    monkeypatch.setenv("PRIVYFLOW_DESAN_SERVICE_SECRET", SECRET)
    settings = config.load_settings()
    assert settings.max_request_bytes == 262144
    assert settings.max_output_bytes == 1048576
    assert settings.internal_client_timeout_seconds == 3


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MAX_REQUEST_BYTES", "1023"),
        ("MAX_OUTPUT_BYTES", "1023"),
        ("INTERNAL_CLIENT_TIMEOUT_SECONDS", "0"),
        ("INTERNAL_CLIENT_TIMEOUT_SECONDS", "31"),
        ("INTERNAL_CLIENT_TIMEOUT_SECONDS", "soon"),
    ],
)
def test_settings_limits_outside_their_bounds_are_refused(
    config: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, name: str, value: str
) -> None:
    monkeypatch.setenv("PRIVYFLOW_DESAN_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.setenv("PRIVYFLOW_DESAN_SANITIZATION_BASE_URL", "http://127.0.0.1:8001")
    monkeypatch.setenv("PRIVYFLOW_DESAN_API_KEYS", json.dumps({"tenant-one": KEY_A}))
    monkeypatch.setenv("PRIVYFLOW_DESAN_SERVICE_SECRET", SECRET)
    monkeypatch.setenv(f"PRIVYFLOW_DESAN_{name}", value)
    with pytest.raises(ValidationError):
        config.load_settings()
