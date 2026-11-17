"""Pending Sanitization Service unit tests. Each is skipped until its feature exists.

Replace an entry with a real test when the feature is implemented; never delete an entry
without a test that covers it.
"""

import pytest

PENDING = [
    "detection confidence scores (the pilot recognizers report none)",
]


@pytest.mark.parametrize("capability", PENDING)
def test_pending(capability: str) -> None:
    pytest.skip(f"not implemented: Sanitization Service - {capability}")
