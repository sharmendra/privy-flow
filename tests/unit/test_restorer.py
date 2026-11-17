"""Exact-placeholder restoration: the De-sanitization Service's pure logic."""

from collections.abc import Callable
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.support.leak import CANARIES

EMAIL, PHONE = CANARIES[1], CANARIES[2]
MAPPINGS = {"[EMAIL_001]": EMAIL, "[PHONE_001]": PHONE}
LIMIT = 1_048_576


@pytest.fixture
def restore(desan: Callable[[str], Any]) -> Callable[..., Any]:
    module = desan("app.restoration.restorer")

    def call(text: str, mappings: dict[str, str] | None = None, limit: int = LIMIT) -> Any:
        return module.restore(text, MAPPINGS if mappings is None else mappings, limit)

    return call


@pytest.fixture
def too_large(desan: Callable[[str], Any]) -> type[Exception]:
    error: type[Exception] = desan("app.restoration.restorer").OutputTooLargeError
    return error


def test_known_placeholders_are_replaced_and_counted(restore: Callable[..., Any]) -> None:
    result = restore("Mail [EMAIL_001], call [PHONE_001].")
    assert result.text == f"Mail {EMAIL}, call {PHONE}."
    assert (result.restored_count, result.unmatched_placeholder_count) == (2, 0)


def test_a_repeated_known_placeholder_is_restored_every_time(restore: Callable[..., Any]) -> None:
    result = restore("[EMAIL_001] and [EMAIL_001]")
    assert result.text == f"{EMAIL} and {EMAIL}"
    assert result.restored_count == 2


def test_text_without_placeholders_is_unchanged(restore: Callable[..., Any]) -> None:
    result = restore("nothing to restore \r\n here é 漢字")
    assert result.text == "nothing to restore \r\n here é 漢字"
    assert (result.restored_count, result.unmatched_placeholder_count) == (0, 0)


# (id, sanitized text, expected text, restored, unmatched)
CASES = [
    # Unknown: the right shape but not in the authorized mapping. Left alone and counted.
    ("unknown_number", "[EMAIL_002]", "[EMAIL_002]", 0, 1),
    ("unknown_type", "[SSN_001]", "[SSN_001]", 0, 1),
    ("unknown_repeated", "[PHONE_009] [PHONE_009]", "[PHONE_009] [PHONE_009]", 0, 2),
    ("unknown_next_to_known", "[EMAIL_001][EMAIL_009]", f"{EMAIL}[EMAIL_009]", 1, 1),
    # Altered: the shape is kept but the token is not exactly a mapped placeholder.
    ("altered_extra_digit", "[EMAIL_0001]", "[EMAIL_0001]", 0, 1),
    ("altered_suffix", "[EMAIL_001_001]", "[EMAIL_001_001]", 0, 1),
    ("altered_type", "[EMAILS_001]", "[EMAILS_001]", 0, 1),
    ("altered_number_grown", "[EMAIL_1001]", "[EMAIL_1001]", 0, 1),
    # Malformed look-alikes. They do not have the placeholder shape, so they are left alone and
    # not counted (SPEC 9.6).
    ("malformed_lowercase", "[email_001]", "[email_001]", 0, 0),
    ("malformed_short_number", "[EMAIL_01]", "[EMAIL_01]", 0, 0),
    ("malformed_hyphen", "[EMAIL-001]", "[EMAIL-001]", 0, 0),
    ("malformed_no_closing", "[EMAIL_001", "[EMAIL_001", 0, 0),
    ("malformed_no_opening", "EMAIL_001]", "EMAIL_001]", 0, 0),
    ("malformed_inner_space", "[ EMAIL_001]", "[ EMAIL_001]", 0, 0),
    ("malformed_no_number", "[EMAIL_]", "[EMAIL_]", 0, 0),
    ("malformed_round_brackets", "(EMAIL_001)", "(EMAIL_001)", 0, 0),
    ("malformed_split_by_space", "[EMAIL_001 ]", "[EMAIL_001 ]", 0, 0),
    # Redact markers are never restored and are not placeholders.
    ("redact_marker", "[EMAIL_REDACTED]", "[EMAIL_REDACTED]", 0, 0),
    # An exact placeholder inside other brackets is still an exact placeholder: the original
    # text held brackets around the value, so restoring it is the correct round trip.
    ("nested_brackets_restore_inner", "[[EMAIL_001]]", f"[{EMAIL}]", 1, 0),
    ("adjacent_known", "[EMAIL_001][PHONE_001]", f"{EMAIL}{PHONE}", 2, 0),
]


@pytest.mark.parametrize(
    ("text", "expected", "restored", "unmatched"),
    [c[1:] for c in CASES],
    ids=[c[0] for c in CASES],
)
def test_unknown_altered_and_malformed_placeholders_are_left_untouched(
    restore: Callable[..., Any], text: str, expected: str, restored: int, unmatched: int
) -> None:
    result = restore(text)
    assert result.text == expected
    assert (result.restored_count, result.unmatched_placeholder_count) == (restored, unmatched)


def test_an_empty_mapping_restores_nothing_and_counts_every_placeholder(
    restore: Callable[..., Any],
) -> None:
    result = restore("[EMAIL_001] [PHONE_001]", mappings={})
    assert result.text == "[EMAIL_001] [PHONE_001]"
    assert (result.restored_count, result.unmatched_placeholder_count) == (0, 2)


def test_a_restored_value_that_looks_like_a_placeholder_is_not_substituted(
    restore: Callable[..., Any],
) -> None:
    mappings = {"[EMAIL_001]": "[PHONE_001]", "[PHONE_001]": "SHOULD-NOT-APPEAR"}
    result = restore("[EMAIL_001]", mappings)
    assert result.text == "[PHONE_001]"
    assert result.restored_count == 1


def test_a_restored_value_can_not_join_with_the_text_around_it_into_a_placeholder(
    restore: Callable[..., Any],
) -> None:
    mappings = {"[EMAIL_001]": "_001]", "[PHONE_001]": "x"}
    result = restore("[PHONE[EMAIL_001]", mappings)
    assert result.text == "[PHONE_001]"
    assert result.restored_count == 1  # the joined text is not looked at again


def test_the_result_does_not_show_its_text_when_printed(restore: Callable[..., Any]) -> None:
    result = restore("[EMAIL_001]")
    assert EMAIL not in repr(result)
    assert EMAIL not in str(result)


# --- the output limit ---------------------------------------------------------------------------


def test_output_exactly_at_the_limit_is_accepted(restore: Callable[..., Any]) -> None:
    result = restore("[EMAIL_001]", {"[EMAIL_001]": "a" * 100}, limit=100)
    assert result.text == "a" * 100


def test_output_one_byte_over_the_limit_is_refused(
    restore: Callable[..., Any], too_large: type[Exception]
) -> None:
    with pytest.raises(too_large):
        restore("[EMAIL_001]", {"[EMAIL_001]": "a" * 101}, limit=100)


def test_the_limit_counts_bytes_not_characters(
    restore: Callable[..., Any], too_large: type[Exception]
) -> None:
    assert restore("é" * 50, limit=100).text == "é" * 50
    with pytest.raises(too_large):
        restore("é" * 51, limit=100)


def test_a_small_input_that_would_expand_hugely_is_refused_before_it_is_built(
    restore: Callable[..., Any], too_large: type[Exception]
) -> None:
    text = "[EMAIL_001]" * 100_000  # about 1 MB in, 10 GB out if it were built
    with pytest.raises(too_large):
        restore(text, {"[EMAIL_001]": "x" * 100_000}, limit=LIMIT)


# --- properties ---------------------------------------------------------------------------------

TYPES = st.sampled_from(["EMAIL", "PHONE", "FINANCIAL", "US_SSN", "IP_ADDRESS", "IN_PAN"])
# Values and literals may hold anything, including text that looks like a placeholder.
FRAGMENTS = ["a", "b", " ", "X", "0", "_", "-", "[", "]", "(", "\r\n", "\t", "é", "漢", "😀"] + [
    "[A_001]",
    "[EMAIL_009]",
    "[EMAIL_REDACTED]",
]
TEXT = st.lists(st.sampled_from(FRAGMENTS), max_size=8).map("".join)


@st.composite
def _documents(draw: st.DrawFn) -> tuple[str, str, dict[str, str]]:
    """(sanitized text, the original text, mappings). The sanitized text interleaves literal
    text with placeholders. The original is what the Sanitization Service would have received."""
    count = draw(st.integers(min_value=0, max_value=6))
    mappings: dict[str, str] = {}
    for number in range(1, count + 1):
        placeholder = f"[{draw(TYPES)}_{number:03d}]"
        mappings[placeholder] = draw(TEXT)
    names = list(mappings)
    sanitized: list[str] = []
    original: list[str] = []
    for _ in range(draw(st.integers(min_value=0, max_value=10))):
        literal = draw(TEXT)
        # The Sanitization Service never generates a placeholder that appears literally in the
        # input, so a literal never holds a mapped placeholder.
        if any(name in literal for name in names):
            literal = ""
        sanitized.append(literal)
        original.append(literal)
        if names:
            name = draw(st.sampled_from(names))
            sanitized.append(name)
            original.append(mappings[name])
    return "".join(sanitized), "".join(original), mappings


@settings(max_examples=300, deadline=None)
@given(document=_documents())
def test_property_restoring_the_sanitized_text_reproduces_the_original(
    desan: Callable[[str], Any], document: tuple[str, str, dict[str, str]]
) -> None:
    sanitized, original, mappings = document
    module = desan("app.restoration.restorer")
    result = module.restore(sanitized, mappings, 10 * LIMIT)
    assert result.text == original


@settings(max_examples=200, deadline=None)
@given(
    text=st.text(max_size=60),
    mappings=st.dictionaries(st.sampled_from(["[A_001]", "[B_002]"]), TEXT),
)
def test_property_text_outside_known_placeholders_is_never_changed(
    desan: Callable[[str], Any], text: str, mappings: dict[str, str]
) -> None:
    module = desan("app.restoration.restorer")
    result = module.restore(text, {}, 10 * LIMIT)
    assert result.text == text  # with no mapping nothing may change, whatever the text holds
    assert result.restored_count == 0
    full = module.restore(text, mappings, 10 * LIMIT)
    assert (
        full.restored_count + full.unmatched_placeholder_count == result.unmatched_placeholder_count
    )
