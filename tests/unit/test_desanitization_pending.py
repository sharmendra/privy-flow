"""Pending De-sanitization Service unit tests. Each is skipped until its feature exists."""

import pytest

PENDING = [
    "expired reference is rejected",
    "revoked reference is rejected",
    "cross-tenant restoration is rejected",
]


@pytest.mark.parametrize("capability", PENDING)
def test_pending(capability: str) -> None:
    pytest.skip(f"not implemented: De-sanitization Service - {capability}")
