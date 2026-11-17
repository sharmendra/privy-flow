"""Pending security and privacy tests. Each is skipped until its feature exists."""

import pytest

PENDING = [
    "replay protection where one-time use applies",
    "rate limiting",
    "no sensitive values in traces and metrics",
]


@pytest.mark.parametrize("requirement", PENDING)
def test_pending(requirement: str) -> None:
    pytest.skip(f"not implemented: {requirement}")
