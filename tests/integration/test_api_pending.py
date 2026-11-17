"""Pending API, database and internal-API integration tests."""

import pytest

PENDING = [
    "De-sanitization API: valid restoration returns original text",
    "De-sanitization API: invalid, expired and revoked references fail safely",
    "Contract: internal API schema compatibility between the two services",
]


@pytest.mark.parametrize("scenario", PENDING)
def test_pending(scenario: str) -> None:
    pytest.skip(f"not implemented: {scenario}")
