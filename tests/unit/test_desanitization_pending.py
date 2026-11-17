"""Pending De-sanitization Service unit tests. Each is skipped until its feature exists."""

import pytest

PENDING = [
    "caller authentication",
    "caller authorization for restoration",
    "restore-reference format validation",
    "restoration replaces only exact placeholders from the mapping",
    "unknown and altered placeholders are left untouched",
    "expired reference is rejected",
    "revoked reference is rejected",
    "cross-tenant restoration is rejected",
    "restoration is exact for supported input",
]


@pytest.mark.parametrize("capability", PENDING)
def test_pending(capability: str) -> None:
    pytest.skip(f"not implemented: De-sanitization Service - {capability}")
