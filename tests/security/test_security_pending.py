"""Pending security and privacy tests. Each is skipped until its feature exists."""

import pytest

PENDING = [
    "tenant isolation: tenant A cannot read or restore tenant B mappings",
    "authentication and authorization on every sensitive endpoint",
    "expiry and revocation are enforced",
    "replay protection where one-time use applies",
    "rate limiting",
    "De-sanitization Service cannot reach the Sanitization database",
    "no sensitive values in logs",
    "no sensitive values in error responses",
    "no sensitive values in traces and metrics",
]


@pytest.mark.parametrize("requirement", PENDING)
def test_pending(requirement: str) -> None:
    pytest.skip(f"not implemented: {requirement}")
