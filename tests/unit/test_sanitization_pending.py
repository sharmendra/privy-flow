"""Pending Sanitization Service unit tests. Each is skipped until its feature exists.

Replace an entry with a real test when the feature is implemented; never delete an entry
without a test that covers it.
"""

import pytest

PENDING = [
    "detection confidence scores (the pilot recognizers report none)",
    "restore-reference is high entropy and unpredictable",
    "restore-reference is stored only as a digest",
    "mapping encryption round trip with unique nonce",
    "key version is stored and honored on decrypt",
    "expired mapping is rejected",
    "revoked mapping is rejected",
    "mapping is bound to tenant and request scope",
]


@pytest.mark.parametrize("capability", PENDING)
def test_pending(capability: str) -> None:
    pytest.skip(f"not implemented: Sanitization Service - {capability}")
