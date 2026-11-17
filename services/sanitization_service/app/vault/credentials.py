"""Restore-references and their lookup digests.

A reference is `pf1_` plus 43 URL-safe characters: 32 bytes (256 bits) from `secrets`. Only an
HMAC-SHA-256 digest keyed with a server-side pepper is stored, so a copy of the database holds
nothing that can be presented as a reference. Lookup is by that digest. The pepper is secret,
so an attacker cannot learn digest bytes by timing lookups of guessed references.
"""

import hashlib
import hmac
import re
import secrets

REFERENCE_PREFIX = "pf1_"
REFERENCE_PATTERN = re.compile(r"^pf1_[A-Za-z0-9_-]{43}$")
_REFERENCE_BYTES = 32


def generate_reference() -> str:
    return REFERENCE_PREFIX + secrets.token_urlsafe(_REFERENCE_BYTES)


def is_valid_reference(value: str) -> bool:
    return REFERENCE_PATTERN.fullmatch(value) is not None


def credential_digest(reference: str, pepper: bytes) -> bytes:
    """The 32-byte digest stored for lookup. The reference must have a valid format."""
    return hmac.new(pepper, reference.encode("ascii"), hashlib.sha256).digest()
