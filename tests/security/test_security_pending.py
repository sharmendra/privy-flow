"""Pending security and privacy tests. Each is skipped until its feature exists."""

import pytest

PENDING = [
    "tenant isolation: tenant A cannot read or restore tenant B mappings",
    "authentication and authorization on every sensitive endpoint",
    "restore-reference entropy and unpredictability",
    "possession of a restore-reference alone never authorizes restoration",
    "only a digest of the restore-reference is stored",
    "mapping is encrypted at rest and plaintext never appears in the database",
    "ciphertext tampering is detected and rejected",
    "key version handling and rotation",
    "expiry and revocation are enforced",
    "replay protection where one-time use applies",
    "rate limiting",
    "internal API authentication",
    "De-sanitization Service cannot reach the Sanitization database",
    "no sensitive values in logs",
    "no sensitive values in error responses",
    "no sensitive values in traces and metrics",
    "unauthorized callers cannot learn whether a mapping exists",
]


@pytest.mark.parametrize("requirement", PENDING)
def test_pending(requirement: str) -> None:
    pytest.skip(f"not implemented: {requirement}")
