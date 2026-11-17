"""API key authentication: tenant from the key, constant-time match, strict key list parsing."""

import json
from collections.abc import Callable
from typing import Any

import pytest

KEY_A = "a" * 32
KEY_B = "b" * 32


@pytest.fixture(scope="module")
def auth(san: Callable[[str], Any]) -> Any:
    return san("app.core.auth")


@pytest.fixture(scope="module")
def errors(san: Callable[[str], Any]) -> Any:
    return san("app.vault.errors")


def test_each_key_resolves_to_its_own_tenant(auth: Any) -> None:
    authenticator = auth.ApiKeyAuthenticator({"tenant-test-a": KEY_A, "tenant-test-b": KEY_B})
    assert authenticator.tenant_for(KEY_A) == "tenant-test-a"
    assert authenticator.tenant_for(KEY_B) == "tenant-test-b"


@pytest.mark.parametrize(
    "presented",
    [None, "", "wrong", KEY_A + "x", KEY_A[:-1], KEY_A.upper(), " " + KEY_A, "é" * 32],
)
def test_other_values_resolve_to_no_tenant(auth: Any, presented: str | None) -> None:
    assert auth.ApiKeyAuthenticator({"tenant-test-a": KEY_A}).tenant_for(presented) is None


def test_authenticator_repr_shows_no_tenant_or_key(auth: Any) -> None:
    text = repr(auth.ApiKeyAuthenticator({"tenant-test-a": KEY_A}))
    assert KEY_A not in text
    assert "tenant-test-a" not in text


def test_parse_accepts_a_valid_list(auth: Any) -> None:
    raw = json.dumps({"tenant-test-a": KEY_A, "tenant-test-b": KEY_B})
    assert auth.parse_api_keys(raw) == {"tenant-test-a": KEY_A, "tenant-test-b": KEY_B}


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        "{}",
        json.dumps({"Bad Tenant!": KEY_A}),
        json.dumps({"ab": KEY_A}),
        json.dumps({"tenant-test-a": "short"}),
        json.dumps({"tenant-test-a": 12345678901234567890123456}),
        json.dumps({"tenant-test-a": "é" * 30}),
        json.dumps({"tenant-test-a": KEY_A, "tenant-test-b": KEY_A}),
    ],
    ids=[
        "not_json",
        "list",
        "empty",
        "bad_tenant",
        "short_tenant",
        "short_key",
        "non_text_key",
        "non_ascii_key",
        "shared_key",
    ],
)
def test_parse_rejects_invalid_lists_without_echoing_keys(auth: Any, errors: Any, raw: str) -> None:
    with pytest.raises(errors.VaultConfigError) as caught:
        auth.parse_api_keys(raw)
    assert KEY_A not in str(caught.value)
    assert "tenant-test" not in str(caught.value)


def test_the_api_key_check_compares_against_every_key_without_an_early_exit(
    auth: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bytes] = []
    real = auth.hmac.compare_digest

    def counting(a: bytes, b: bytes) -> bool:
        calls.append(b)
        return bool(real(a, b))

    monkeypatch.setattr(auth.hmac, "compare_digest", counting)
    keys = {f"tenant-test-{n}": f"key-{n}-" + "k" * 30 for n in range(5)}
    authenticator = auth.ApiKeyAuthenticator(keys)
    assert authenticator.tenant_for(keys["tenant-test-0"]) == "tenant-test-0"  # first of five
    assert len(calls) == 5
    calls.clear()
    assert authenticator.tenant_for("nope") is None
    assert len(calls) == 5
