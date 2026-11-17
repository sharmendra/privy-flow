"""Turn the raw secret settings into a keyring and a pepper.

Errors name what is wrong, never a value.
"""

import base64
import binascii
import json
from typing import cast

from app.vault.crypto import KEY_BYTES, Keyring
from app.vault.errors import VaultConfigError

MIN_PEPPER_BYTES = 32


def _b64(value: object, what: str) -> bytes:
    if not isinstance(value, str):
        raise VaultConfigError(f"{what} must be base64 text")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise VaultConfigError(f"{what} is not valid base64") from None


def parse_keyring(raw: str, active_version: int) -> Keyring:
    """`raw` is a JSON object of key version to base64 AES-256 key."""
    try:
        loaded = json.loads(raw)
    except ValueError:
        raise VaultConfigError("encryption keys are not valid JSON") from None
    if not isinstance(loaded, dict) or not loaded:
        raise VaultConfigError("encryption keys must be a non-empty JSON object")
    keys: dict[int, bytes] = {}
    for version_text, encoded in cast("dict[str, object]", loaded).items():
        if not (version_text.isascii() and version_text.isdigit()):
            raise VaultConfigError("key versions must be positive integers")
        key = _b64(encoded, "an encryption key")
        if len(key) != KEY_BYTES:
            raise VaultConfigError("every encryption key must be 32 bytes")
        keys[int(version_text)] = key
    return Keyring(keys, active_version)


def parse_pepper(raw: str) -> bytes:
    pepper = _b64(raw, "the credential pepper")
    if len(pepper) < MIN_PEPPER_BYTES:
        raise VaultConfigError("the credential pepper must be at least 32 bytes")
    return pepper
