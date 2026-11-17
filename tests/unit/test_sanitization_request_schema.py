"""The sanitization request schema (SPEC 9.3): what is accepted and what is a 422."""

from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

GOOD = {"text": "Hello", "request_scope_id": "scope-1", "policy_id": "effective"}


@pytest.fixture(scope="module")
def schema(san: Callable[[str], Any]) -> Any:
    return san("app.schemas.sanitization").SanitizationRequest


def test_a_valid_request_is_accepted(schema: Any) -> None:
    request = schema.model_validate(GOOD)
    assert (request.text, request.request_scope_id, request.policy_id) == (
        "Hello",
        "scope-1",
        "effective",
    )


@pytest.mark.parametrize("text", [" ", "\n\t", "\r\n", "  x  "])
def test_whitespace_only_text_is_valid(schema: Any, text: str) -> None:
    assert schema.model_validate({**GOOD, "text": text}).text == text


def test_text_is_kept_exactly_as_sent(schema: Any) -> None:
    text = "  a\r\nbé \n"
    assert schema.model_validate({**GOOD, "text": text}).text == text


def test_empty_text_is_rejected(schema: Any) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate({**GOOD, "text": ""})


@pytest.mark.parametrize("text", [None, 5, ["a"], {"a": 1}, True])
def test_text_must_be_a_string(schema: Any, text: object) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate({**GOOD, "text": text})


@pytest.mark.parametrize("missing", ["text", "request_scope_id", "policy_id"])
def test_every_field_is_required(schema: Any, missing: str) -> None:
    body = {k: v for k, v in GOOD.items() if k != missing}
    with pytest.raises(ValidationError):
        schema.model_validate(body)


@pytest.mark.parametrize(
    "extra",
    [{"tenant_id": "tenant-test-a"}, {"profiles": ["hipaa"]}, {"profile_ids": ["gdpr"]}, {"x": 1}],
)
def test_unknown_fields_are_rejected_including_tenant_and_profiles(
    schema: Any, extra: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate({**GOOD, **extra})


@pytest.mark.parametrize(
    "scope", ["", "has space", "semi;colon", "x" * 129, "café", "a/b", "scope\n"]
)
def test_a_bad_request_scope_id_is_rejected(schema: Any, scope: str) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate({**GOOD, "request_scope_id": scope})


@pytest.mark.parametrize("scope", ["a", "scope-1", "A.b_c:d-e", "x" * 128, "0123"])
def test_a_good_request_scope_id_is_accepted(schema: Any, scope: str) -> None:
    assert schema.model_validate({**GOOD, "request_scope_id": scope}).request_scope_id == scope


def test_the_validation_error_does_not_repeat_the_text(schema: Any) -> None:
    with pytest.raises(ValidationError) as raised:
        schema.model_validate({**GOOD, "text": "", "request_scope_id": "Canary Person"})
    assert "Canary Person" not in str(raised.value.errors(include_input=False))
