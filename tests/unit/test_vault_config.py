"""Parsing the secret settings into a keyring and a pepper. Errors must name no value."""

import base64
import json
import os
from collections.abc import Callable
from typing import Any

import pytest

CANARY = "canary-secret-value-9c1d"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


@pytest.fixture(scope="module")
def config(san: Callable[[str], Any]) -> Any:
    return san("app.vault.config")


@pytest.fixture(scope="module")
def errors(san: Callable[[str], Any]) -> Any:
    return san("app.vault.errors")


def test_keyring_is_parsed_with_every_version_and_the_active_one(config: Any) -> None:
    raw = json.dumps({"1": _b64(os.urandom(32)), "2": _b64(os.urandom(32))})
    keyring = config.parse_keyring(raw, 2)
    assert keyring.active_version == 2
    assert "versions=[1, 2]" in repr(keyring)


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        "{}",
        '"a string"',
        json.dumps({"one": _b64(os.urandom(32))}),
        json.dumps({"-1": _b64(os.urandom(32))}),
        json.dumps({"1": 5}),
        json.dumps({"1": CANARY}),
        json.dumps({"1": _b64(os.urandom(16))}),
        json.dumps({"1": _b64(os.urandom(64))}),
    ],
    ids=[
        "not_json",
        "list",
        "empty",
        "string",
        "text_version",
        "negative_version",
        "non_text_key",
        "not_base64",
        "short_key",
        "long_key",
    ],
)
def test_invalid_keyring_is_rejected_without_echoing_values(
    config: Any, errors: Any, raw: str
) -> None:
    with pytest.raises(errors.VaultConfigError) as caught:
        config.parse_keyring(raw, 1)
    assert CANARY not in str(caught.value)
    assert raw not in str(caught.value)


def test_active_version_must_be_in_the_keyring(config: Any, errors: Any) -> None:
    with pytest.raises(errors.VaultConfigError):
        config.parse_keyring(json.dumps({"1": _b64(os.urandom(32))}), 2)


def test_pepper_of_32_bytes_or_more_is_accepted(config: Any) -> None:
    assert len(config.parse_pepper(_b64(os.urandom(32)))) == 32
    assert len(config.parse_pepper(_b64(os.urandom(48)))) == 48


@pytest.mark.parametrize("raw", ["", CANARY, _b64(os.urandom(31)), "!!!!"])
def test_invalid_pepper_is_rejected_without_echoing_values(
    config: Any, errors: Any, raw: str
) -> None:
    with pytest.raises(errors.VaultConfigError) as caught:
        config.parse_pepper(raw)
    assert CANARY not in str(caught.value)
