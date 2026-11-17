"""Pending API, database and internal-API integration tests."""

import pytest

PENDING = [
    "Sanitization API: valid request returns sanitized text and restore-reference",
    "Sanitization API: invalid, oversized and unsupported-policy input fail safely",
    "Sanitization API: unauthenticated request is rejected",
    "Internal mapping API: only the De-sanitization Service identity is accepted",
    "Internal mapping API: scope, expiry and revocation are enforced",
    "De-sanitization API: valid restoration returns original text",
    "De-sanitization API: invalid, expired and revoked references fail safely",
    "Contract: internal API schema compatibility between the two services",
]


@pytest.mark.parametrize("scenario", PENDING)
def test_pending(scenario: str) -> None:
    pytest.skip(f"not implemented: {scenario}")
