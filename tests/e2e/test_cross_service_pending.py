"""Pending cross-service end-to-end tests.

These run both services as separate processes and call them over HTTP only, because the
services cannot be imported into one process (see tests/support/service_loader.py).
"""

import pytest

PENDING = [
    "sanitize then restore returns the original supported input exactly",
    "invalid reference is rejected",
    "unauthorized caller is rejected",
    "missing mapping is handled safely",
    "Sanitization Service unavailable gives a safe 503",
    "database unavailable gives a safe error and no data loss",
    "service restart keeps stored mappings restorable",
    "concurrent sanitize and restore requests do not mix mappings",
    "tampered mapping or ciphertext is rejected",
    "replay attempt is handled per the documented policy",
]


@pytest.mark.parametrize("scenario", PENDING)
def test_pending(scenario: str) -> None:
    pytest.skip(f"not implemented: {scenario}")
