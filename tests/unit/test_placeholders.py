"""Placeholder generation and span replacement (pilot phase 4).

Covers the `[TYPE_NNN]` format, collision avoidance, per-request consistency, text
preservation, and the in-memory round trip, including Hypothesis properties.
"""

from collections.abc import Callable, Sequence
from types import MappingProxyType
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.support.placeholders import PLACEHOLDER_SHAPE, restore_in_memory
from tests.support.settings_data import valid_content

EMAIL_A = "alice@example.com"
EMAIL_B = "bob@example.org"
PHONE_A = "+1 202-555-0143"


@pytest.fixture(scope="module")
def mod(san: Callable[[str], Any]) -> Any:
    class Mod:
        placeholders = san("app.sanitization.placeholders")
        sanitizer = san("app.sanitization.sanitizer")
        spans = san("app.sanitization.spans")
        policy = san("app.sanitization.policy")
        loader = san("app.sanitization.profiles.loader")
        validator = san("app.settings.validator")
        types = san("app.detection.types")

        def span(self, entity_type: str, start: int, end: int, action: str = "placeholder") -> Any:
            return self.spans.MaskSpan(entity_type, start, end, action)

        def policy_for(self, *profile_ids: str) -> Any:
            raw = valid_content(tenant_profiles={"tenant-test-a": list(profile_ids)})
            resolver = self.policy.PolicyResolver(self.validator.validate_settings(raw))
            return resolver.policy_for("tenant-test-a")

        def sanitize(self, text: str, *profile_ids: str) -> Any:
            return self.sanitizer.sanitize_text(text, self.policy_for(*(profile_ids or ("gdpr",))))

        def stub(self, entity_type: str, *offsets: tuple[int, int]) -> Any:
            detection = self.types.Detection

            class Stub:
                def __init__(self) -> None:
                    self.entity_type = entity_type

                def find(self, text: str) -> list[Any]:
                    return [detection(entity_type, s, e) for s, e in offsets]

            return Stub()

    return Mod()


def _where(text: str, value: str) -> tuple[int, int]:
    start = text.index(value)
    return start, start + len(value)


# ---- placeholder names -------------------------------------------------------------------


def test_the_first_placeholder_of_a_type_is_numbered_001(mod: Any) -> None:
    assert mod.placeholders.PlaceholderNamer("text").placeholder("EMAIL") == "[EMAIL_001]"


def test_placeholders_of_one_type_count_up_and_each_type_counts_alone(mod: Any) -> None:
    namer = mod.placeholders.PlaceholderNamer("text")
    assert [namer.placeholder("EMAIL"), namer.placeholder("EMAIL")] == [
        "[EMAIL_001]",
        "[EMAIL_002]",
    ]
    assert namer.placeholder("PHONE") == "[PHONE_001]"
    assert namer.placeholder("US_SSN") == "[US_SSN_001]"


def test_the_number_grows_past_three_digits_only_after_999(mod: Any) -> None:
    namer = mod.placeholders.PlaceholderNamer("text")
    names = [namer.placeholder("EMAIL") for _ in range(1001)]
    assert names[8] == "[EMAIL_009]"
    assert names[98] == "[EMAIL_099]"
    assert names[998] == "[EMAIL_999]"
    assert names[999] == "[EMAIL_1000]"
    assert names[1000] == "[EMAIL_1001]"
    assert len(set(names)) == 1001


def test_the_redact_marker_carries_no_counter(mod: Any) -> None:
    assert mod.placeholders.redact_marker("FINANCIAL") == "[FINANCIAL_REDACTED]"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("see [EMAIL_001] here", "[EMAIL_002]"),
        ("[EMAIL_001] and [EMAIL_002]", "[EMAIL_003]"),
        ("[EMAIL_002] only", "[EMAIL_001]"),
        ("[EMAIL_001][EMAIL_002][EMAIL_003]", "[EMAIL_004]"),
        ("[PHONE_001] is another type", "[EMAIL_001]"),
        ("[EMAIL_0001] has four digits so it is not the same text", "[EMAIL_001]"),
        ("[email_001] and [EMAIL_01] and EMAIL_001 are not placeholder-shaped", "[EMAIL_001]"),
    ],
)
def test_a_counter_skips_an_index_whose_placeholder_is_in_the_text(
    mod: Any, text: str, expected: str
) -> None:
    assert mod.placeholders.PlaceholderNamer(text).placeholder("EMAIL") == expected


def test_a_counter_skips_literal_placeholders_past_999(mod: Any) -> None:
    namer = mod.placeholders.PlaceholderNamer("[EMAIL_1000] [EMAIL_1001]")
    names = [namer.placeholder("EMAIL") for _ in range(1000)]
    assert "[EMAIL_1000]" not in names and "[EMAIL_1001]" not in names
    assert names[-1] == "[EMAIL_1002]"


# ---- replacing spans ---------------------------------------------------------------------


def test_a_span_is_replaced_and_the_text_around_it_is_kept(mod: Any) -> None:
    text = f"Write to {EMAIL_A} today."
    start, end = _where(text, EMAIL_A)
    result = mod.sanitizer.apply_spans(text, [mod.span("EMAIL", start, end)])
    assert result.sanitized_text == "Write to [EMAIL_001] today."
    assert dict(result.mappings) == {"[EMAIL_001]": EMAIL_A}
    assert result.entity_count == 1


def test_a_text_with_no_spans_is_returned_unchanged(mod: Any) -> None:
    result = mod.sanitizer.apply_spans("Nothing sensitive here.", [])
    assert result.sanitized_text == "Nothing sensitive here."
    assert dict(result.mappings) == {}
    assert result.entity_count == 0


@pytest.mark.parametrize("text", ["", " ", "  \n\t ", "\r\n\r\n"])
def test_empty_and_whitespace_only_text_pass_through_unchanged(mod: Any, text: str) -> None:
    for result in (mod.sanitize(text), mod.sanitizer.apply_spans(text, [])):
        assert result.sanitized_text == text
        assert dict(result.mappings) == {}
        assert result.entity_count == 0


def test_a_span_at_the_very_start_and_end_of_the_text(mod: Any) -> None:
    text = f"{EMAIL_A}{PHONE_A}"
    result = mod.sanitizer.apply_spans(
        text, [mod.span("EMAIL", 0, len(EMAIL_A)), mod.span("PHONE", len(EMAIL_A), len(text))]
    )
    assert result.sanitized_text == "[EMAIL_001][PHONE_001]"


def test_a_span_covering_the_whole_text(mod: Any) -> None:
    result = mod.sanitizer.apply_spans(EMAIL_A, [mod.span("EMAIL", 0, len(EMAIL_A))])
    assert result.sanitized_text == "[EMAIL_001]"
    assert dict(result.mappings) == {"[EMAIL_001]": EMAIL_A}


# ---- repeated values ---------------------------------------------------------------------


def test_repeated_identical_values_share_one_placeholder(mod: Any) -> None:
    text = f"{EMAIL_A} wrote to {EMAIL_B}, and {EMAIL_A} wrote again."
    result = mod.sanitize(text)
    assert result.sanitized_text == "[EMAIL_001] wrote to [EMAIL_002], and [EMAIL_001] wrote again."
    assert dict(result.mappings) == {"[EMAIL_001]": EMAIL_A, "[EMAIL_002]": EMAIL_B}
    assert result.entity_count == 3


def test_the_same_text_as_two_types_gets_two_placeholders(mod: Any) -> None:
    result = mod.sanitizer.apply_spans("ab ab", [mod.span("EMAIL", 0, 2), mod.span("PHONE", 3, 5)])
    assert dict(result.mappings) == {"[EMAIL_001]": "ab", "[PHONE_001]": "ab"}


def test_values_that_differ_only_in_case_are_not_merged(mod: Any) -> None:
    text = "A@example.com a@example.com"
    result = mod.sanitize(text)
    assert result.sanitized_text == "[EMAIL_001] [EMAIL_002]"


def test_the_same_value_in_two_requests_is_not_linked(mod: Any) -> None:
    both = mod.sanitize(f"{EMAIL_A} and {EMAIL_B}")
    alone = mod.sanitize(f"{EMAIL_B} only")
    assert both.sanitized_text == "[EMAIL_001] and [EMAIL_002]"
    # B was 002 in the first request. The second request knows nothing of the first.
    assert alone.sanitized_text == "[EMAIL_001] only"
    assert dict(alone.mappings) == {"[EMAIL_001]": EMAIL_B}
    assert mod.sanitize(f"{EMAIL_A} and {EMAIL_B}").sanitized_text == both.sanitized_text


def test_results_do_not_depend_on_what_was_sanitized_before(mod: Any) -> None:
    first = mod.sanitize(f"{EMAIL_A} {PHONE_A}")
    for _ in range(3):
        mod.sanitize(f"{EMAIL_B} {EMAIL_A} {PHONE_A} {PHONE_A}")
    assert mod.sanitize(f"{EMAIL_A} {PHONE_A}").sanitized_text == first.sanitized_text


# ---- redact ------------------------------------------------------------------------------


def test_a_redacted_span_becomes_a_marker_and_is_never_in_the_mappings(mod: Any) -> None:
    text = f"Mail {EMAIL_A} now"
    start, end = _where(text, EMAIL_A)
    result = mod.sanitizer.apply_spans(text, [mod.span("EMAIL", start, end, "redact")])
    assert result.sanitized_text == "Mail [EMAIL_REDACTED] now"
    assert dict(result.mappings) == {}
    assert result.entity_count == 1
    assert EMAIL_A not in repr(result.mappings)


def test_redacted_and_reversible_spans_mix_in_one_text(mod: Any) -> None:
    text = f"{EMAIL_A} {PHONE_A} {EMAIL_A}"
    result = mod.sanitizer.apply_spans(
        text,
        [
            mod.span("EMAIL", 0, len(EMAIL_A)),
            mod.span("PHONE", len(EMAIL_A) + 1, len(EMAIL_A) + 1 + len(PHONE_A), "redact"),
            mod.span("EMAIL", len(text) - len(EMAIL_A), len(text)),
        ],
    )
    assert result.sanitized_text == "[EMAIL_001] [PHONE_REDACTED] [EMAIL_001]"
    assert dict(result.mappings) == {"[EMAIL_001]": EMAIL_A}
    assert result.entity_count == 3


def test_redacted_values_do_not_use_up_placeholder_numbers(mod: Any) -> None:
    text = "aa bb cc"
    result = mod.sanitizer.apply_spans(
        text,
        [mod.span("EMAIL", 0, 2, "redact"), mod.span("EMAIL", 3, 5), mod.span("EMAIL", 6, 8)],
    )
    assert result.sanitized_text == "[EMAIL_REDACTED] [EMAIL_001] [EMAIL_002]"


# ---- collision with literal placeholder-like text -----------------------------------------


def test_a_detected_value_never_takes_a_placeholder_already_in_the_text(mod: Any) -> None:
    text = f"Keep [EMAIL_001] as written, hide {EMAIL_A}."
    result = mod.sanitize(text)
    assert result.sanitized_text == "Keep [EMAIL_001] as written, hide [EMAIL_002]."
    assert dict(result.mappings) == {"[EMAIL_002]": EMAIL_A}
    assert restore_in_memory(result.sanitized_text, result.mappings) == text


def test_literal_placeholders_for_other_types_do_not_shift_numbering(mod: Any) -> None:
    result = mod.sanitize(f"[PHONE_001] {EMAIL_A}")
    assert result.sanitized_text == "[PHONE_001] [EMAIL_001]"


def test_a_literal_placeholder_inside_a_masked_value_is_still_avoided(mod: Any) -> None:
    text = "x [EMAIL_001] y"
    result = mod.sanitizer.apply_spans(text, [mod.span("EMAIL", 2, 13)])
    assert result.sanitized_text == "x [EMAIL_002] y"
    assert restore_in_memory(result.sanitized_text, result.mappings) == text


def test_a_literal_redact_marker_is_left_alone_and_never_restored(mod: Any) -> None:
    text = f"[EMAIL_REDACTED] then {EMAIL_A}"
    result = mod.sanitize(text)
    assert result.sanitized_text == "[EMAIL_REDACTED] then [EMAIL_001]"
    assert restore_in_memory(result.sanitized_text, result.mappings) == text


def test_surrounding_brackets_do_not_form_a_second_placeholder(mod: Any) -> None:
    text = f"[{EMAIL_A}] and [[{PHONE_A}]]"
    result = mod.sanitize(text)
    assert result.sanitized_text == "[[EMAIL_001]] and [[[PHONE_001]]]"
    assert restore_in_memory(result.sanitized_text, result.mappings) == text


# ---- text outside spans is preserved -----------------------------------------------------


@pytest.mark.parametrize(
    "gap",
    [
        "\r\n",
        "\n",
        "\r",
        "\n\r",
        "\r\n\r\n",
        "  \t  ",
        "café 日本語 ",
        "\U0001f600 emoji ",
        "é combining ",
        "zero​width ",
        " nbsp line sep ",
        "\x00 nul and \x1f control ",
        'quote" back\\slash <tag> ',
    ],
)
def test_text_outside_the_spans_is_byte_identical(mod: Any, gap: str) -> None:
    head, tail = f"start{gap}", f"{gap}end"
    text = f"{head}{EMAIL_A}{gap}{PHONE_A}{tail}"
    a = (len(head), len(head) + len(EMAIL_A))
    b_start = a[1] + len(gap)
    b = (b_start, b_start + len(PHONE_A))
    result = mod.sanitizer.apply_spans(text, [mod.span("EMAIL", *a), mod.span("PHONE", *b)])
    expected = f"{head}[EMAIL_001]{gap}[PHONE_001]{tail}"
    assert result.sanitized_text.encode("utf-8") == expected.encode("utf-8")
    assert restore_in_memory(result.sanitized_text, result.mappings).encode("utf-8") == (
        text.encode("utf-8")
    )


def test_offsets_count_code_points_so_astral_characters_do_not_shift_spans(mod: Any) -> None:
    text = f"\U0001f600\U0001f600 {EMAIL_A} \U0001f600"
    result = mod.sanitize(text)
    assert result.sanitized_text == "\U0001f600\U0001f600 [EMAIL_001] \U0001f600"


def test_sanitizing_does_not_change_the_input_object(mod: Any) -> None:
    text = f"a {EMAIL_A} b"
    copy = str(text)
    mod.sanitize(text)
    assert text == copy


# ---- many entities -----------------------------------------------------------------------


def test_more_than_999_distinct_values_get_unique_placeholders(mod: Any) -> None:
    tokens = [f"v{i}" for i in range(1105)]
    text = " ".join(tokens)
    spans: list[Any] = []
    offset = 0
    for token in tokens:
        spans.append(mod.span("EMAIL", offset, offset + len(token)))
        offset += len(token) + 1
    result = mod.sanitizer.apply_spans(text, spans)
    assert len(result.mappings) == 1105
    assert "[EMAIL_999]" in result.mappings and "[EMAIL_1000]" in result.mappings
    assert result.entity_count == 1105
    assert restore_in_memory(result.sanitized_text, result.mappings) == text


# ---- invalid spans -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        [(0, 5), (3, 8)],  # overlap
        [(5, 8), (0, 3)],  # out of order
        [(0, 5), (0, 5)],  # duplicate
        [(4, 4)],  # empty
        [(6, 4)],  # reversed
        [(-1, 3)],  # before the text
        [(0, 99)],  # past the text
    ],
)
def test_spans_that_are_overlapping_unordered_empty_or_outside_the_text_are_rejected(
    mod: Any, bad: Sequence[tuple[int, int]]
) -> None:
    secret = "Canary Person"
    text = (secret + " ").ljust(20, "x")
    with pytest.raises(ValueError, match="span") as raised:
        mod.sanitizer.apply_spans(text, [mod.span("EMAIL", s, e) for s, e in bad])
    assert secret not in str(raised.value)


def test_touching_spans_are_allowed(mod: Any) -> None:
    result = mod.sanitizer.apply_spans("abcd", [mod.span("EMAIL", 0, 2), mod.span("PHONE", 2, 4)])
    assert result.sanitized_text == "[EMAIL_001][PHONE_001]"


# ---- the result carries no text when printed ---------------------------------------------


def test_the_result_does_not_print_text_or_values(mod: Any) -> None:
    result = mod.sanitize(f"Contact {EMAIL_A} please")
    printed = f"{result!r} {result}"
    assert EMAIL_A not in printed
    assert "Contact" not in printed
    assert "[EMAIL_001]" not in printed


def test_the_result_is_immutable(mod: Any) -> None:
    result = mod.sanitize(f"Contact {EMAIL_A}")
    with pytest.raises(AttributeError):
        result.sanitized_text = "x"
    with pytest.raises(TypeError):
        result.mappings["[EMAIL_002]"] = "x"


# ---- end to end through detection --------------------------------------------------------


def test_sanitize_text_detects_masks_and_keeps_the_rest(mod: Any) -> None:
    text = f"Hi\r\n{EMAIL_A}\r\ncall {PHONE_A} or {EMAIL_A}\r\nBye é"
    result = mod.sanitize(text)
    assert result.sanitized_text == "Hi\r\n[EMAIL_001]\r\ncall [PHONE_001] or [EMAIL_001]\r\nBye é"
    assert result.entity_count == 3
    assert restore_in_memory(result.sanitized_text, result.mappings) == text


def test_sanitize_text_follows_the_tenants_policy(mod: Any) -> None:
    text = "SSN 900-12-3456 mail a@example.com"
    assert mod.sanitize(text, "gdpr").sanitized_text == "SSN 900-12-3456 mail [EMAIL_001]"
    assert mod.sanitize(text, "gdpr", "hipaa").sanitized_text == "SSN [US_SSN_001] mail [EMAIL_001]"


def test_sanitize_text_applies_redact_from_the_policy(mod: Any) -> None:
    profile = mod.loader.Profile(
        id="custom",
        version=1,
        max_ttl_seconds=3600,
        entities=MappingProxyType({"EMAIL": "redact", "PHONE": "placeholder"}),
    )
    policy = mod.policy.resolve_policy([profile], 3600, frozenset())
    result = mod.sanitizer.sanitize_text(f"{EMAIL_A} {PHONE_A}", policy)
    assert result.sanitized_text == "[EMAIL_REDACTED] [PHONE_001]"
    assert dict(result.mappings) == {"[PHONE_001]": PHONE_A}


def test_sanitize_text_with_a_stub_recognizer_uses_the_given_recognizers(mod: Any) -> None:
    policy = mod.policy_for("gdpr")
    result = mod.sanitizer.sanitize_text("abcdef", policy, [mod.stub("EMAIL", (1, 3))])
    assert result.sanitized_text == "a[EMAIL_001]def"
    assert dict(result.mappings) == {"[EMAIL_001]": "bc"}


# ---- properties --------------------------------------------------------------------------

PIECES = [
    "a",
    "b",
    "Z",
    " ",
    "\n",
    "\r\n",
    "\r",
    "_",
    "0",
    "7",
    "[",
    "]",
    "é",
    "日",
    "\U0001f600",
    "​",
    "x@y.zz",
    "[EMAIL_001]",
    "[EMAIL_002]",
    "[PHONE_001]",
    "[US_SSN_001]",
    "[EMAIL_REDACTED]",
    "[EMAIL_1000]",
    "[EMAIL_0001]",
    "[email_001]",
]
TYPES = ["EMAIL", "PHONE", "US_SSN"]

texts = st.lists(st.sampled_from(PIECES), max_size=30).map("".join)


@st.composite
def text_and_spans(draw: st.DrawFn, redact: bool) -> tuple[str, list[tuple[str, int, int, str]]]:
    text = draw(texts)
    cuts = draw(
        st.lists(st.integers(0, len(text)), unique=True, max_size=14).map(sorted)
    )  # fmt: skip
    spans: list[tuple[str, int, int, str]] = []
    for start, end in zip(cuts[0::2], cuts[1::2], strict=False):
        entity_type = draw(st.sampled_from(TYPES))
        action = draw(st.sampled_from(["placeholder", "redact"])) if redact else "placeholder"
        spans.append((entity_type, start, end, action))
    return text, spans


@settings(max_examples=300, deadline=None)
@given(text_and_spans(redact=False))
def test_property_replacing_spans_then_restoring_returns_the_original_exactly(
    mod: Any, data: tuple[str, list[tuple[str, int, int, str]]]
) -> None:
    text, raw = data
    result = mod.sanitizer.apply_spans(text, [mod.span(*s) for s in raw])
    assert restore_in_memory(result.sanitized_text, result.mappings) == text
    assert result.entity_count == len(raw)


@settings(max_examples=300, deadline=None)
@given(text_and_spans(redact=True))
def test_property_restoring_leaves_exactly_the_redact_markers(
    mod: Any, data: tuple[str, list[tuple[str, int, int, str]]]
) -> None:
    text, raw = data
    result = mod.sanitizer.apply_spans(text, [mod.span(*s) for s in raw])
    expected: list[str] = []
    cursor = 0
    for entity_type, start, end, action in raw:
        expected.append(text[cursor:start])
        expected.append(f"[{entity_type}_REDACTED]" if action == "redact" else text[start:end])
        cursor = end
    expected.append(text[cursor:])
    assert restore_in_memory(result.sanitized_text, result.mappings) == "".join(expected)


@settings(max_examples=300, deadline=None)
@given(text_and_spans(redact=True))
def test_property_no_generated_placeholder_equals_placeholder_like_text_in_the_input(
    mod: Any, data: tuple[str, list[tuple[str, int, int, str]]]
) -> None:
    text, raw = data
    result = mod.sanitizer.apply_spans(text, [mod.span(*s) for s in raw])
    literal = set(PLACEHOLDER_SHAPE.findall(text))
    assert not literal & set(result.mappings)
    assert all(PLACEHOLDER_SHAPE.fullmatch(p) for p in result.mappings)


@settings(max_examples=300, deadline=None)
@given(text_and_spans(redact=False))
def test_property_one_placeholder_per_distinct_type_and_value(
    mod: Any, data: tuple[str, list[tuple[str, int, int, str]]]
) -> None:
    text, raw = data
    result = mod.sanitizer.apply_spans(text, [mod.span(*s) for s in raw])
    distinct = {(t, text[s:e]) for t, s, e, _ in raw}
    assert len(result.mappings) == len(distinct)
    assert {(p[1:].rsplit("_", 1)[0], v) for p, v in result.mappings.items()} == distinct


@settings(max_examples=200, deadline=None)
@given(texts)
def test_property_sanitizing_detected_text_round_trips(mod: Any, text: str) -> None:
    padded = f"{text} {EMAIL_A} {text} {PHONE_A} {EMAIL_A}"
    result = mod.sanitize(padded, "gdpr")
    assert restore_in_memory(result.sanitized_text, result.mappings) == padded
