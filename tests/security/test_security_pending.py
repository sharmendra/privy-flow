"""Pending security and privacy tests. Each is skipped until its feature exists."""

import pytest

PENDING = [
    "tenant isolation: tenant A cannot read or restore tenant B mappings",
    "authentication and authorization on every sensitive endpoint",
    "possession of a restore-reference alone never authorizes restoration",
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
