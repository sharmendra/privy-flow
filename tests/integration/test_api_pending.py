"""Pending API, database and internal-API integration tests."""

import pytest

PENDING = [
    "De-sanitization API: invalid, expired and revoked references fail safely",
]


@pytest.mark.parametrize("scenario", PENDING)
def test_pending(scenario: str) -> None:
    pytest.skip(f"not implemented: {scenario}")
