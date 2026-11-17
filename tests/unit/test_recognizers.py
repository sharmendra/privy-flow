"""The six pilot recognizers (decision D1). Synthetic values only, in the ADR 0001 ranges."""

from collections.abc import Callable
from typing import Any

import pytest

Found = list[tuple[str, str]]


@pytest.fixture(scope="module")
def find(san: Callable[[str], Any]) -> Callable[[str], Found]:
    registry = san("app.detection.registry")

    def run(text: str) -> Found:
        return [(d.entity_type, text[d.start : d.end]) for d in registry.detect(text)]

    return run


def _cases(entity_type: str, values: list[str]) -> list[tuple[str, str]]:
    return [(entity_type, value) for value in values]


POSITIVES = [
    *_cases(
        "EMAIL",
        [
            "asha.verma@example.com",
            "ASHA.VERMA@EXAMPLE.COM",
            "a+tag@mail.example.org",
            "first_last-1@sub.domain.example.net",
        ],
    ),
    *_cases(
        "PHONE",
        [
            "+1 202-555-0143",
            "+12025550143",
            "+1 (202) 555-0143",
            "+91 98765 43210",
            "+44 7911 123456",
            "098765 43210",
            "(202) 555-0143",
            "202-555-0143",
            "202.555.0143",
        ],
    ),
    *_cases(
        "FINANCIAL",
        [
            "4111 1111 1111 1111",
            "4111-1111-1111-1111",
            "4111111111111111",
            "3782 822463 10005",
            "5555 5555 5555 4444",
        ],
    ),
    *_cases("IN_PAN", ["ABCDE1234F", "ZZZZZ9999Z"]),
    *_cases(
        "IP_ADDRESS",
        [
            "192.0.2.10",
            "198.51.100.7",
            "203.0.113.255",
            "0.0.0.0",
            "2001:db8::1",
            "2001:db8:0:0:0:0:0:1",
            "2001:DB8::8a2e:370:7334",
            "::1",
            "2001:db8::",
            "::ffff:192.0.2.1",
        ],
    ),
    *_cases("US_SSN", ["900-12-3456", "987 65 4321", "999-99-9999", "931-45-6789"]),
]

NEGATIVES = [
    # EMAIL
    "asha@@example..com",
    "user@localhost",
    "@example.com",
    "no address here",
    # PHONE
    "202-555-0143-B",
    "555-01",
    "12/03/2026",
    "2345 6789 0123",
    "234567890123",
    "+1 202",
    # FINANCIAL
    "1234567890123456",
    "4111 1111 1111 1112",
    "123456789012",
    "12345698765432",
    # IN_PAN
    "abcde1234f",
    "ABCDE12345",
    "ABCDE1234FG",
    "XABCDE1234F",
    # IP_ADDRESS
    "999.1.1.1",
    "192.0.2.256",
    "192.0.2.01",
    "192.0.2",
    "1.2.3.4.5",
    "v2.3.4-1234",
    "10:30:45",
    "00:1A:2B:3C:4D:5E",
    "std::string",
    "a:b:c",
    "::",
    ":::",
    # US_SSN
    "000-12-3456",
    "666-12-3456",
    "900-00-3456",
    "900-12-0000",
    "900-12-34567",
    "1900-12-3456",
    "900-12 3456",
    "900-12-3456-1",
]


@pytest.mark.parametrize(("entity_type", "value"), POSITIVES)
def test_recognizer_finds_a_valid_value_alone(
    find: Callable[[str], Found], entity_type: str, value: str
) -> None:
    assert find(value) == [(entity_type, value)]


@pytest.mark.parametrize(("entity_type", "value"), POSITIVES)
def test_recognizer_finds_a_valid_value_inside_a_sentence(
    find: Callable[[str], Found], entity_type: str, value: str
) -> None:
    assert (entity_type, value) in find(f"Please note {value} for the record.")


@pytest.mark.parametrize("text", NEGATIVES)
def test_recognizers_ignore_invalid_or_look_alike_values(
    find: Callable[[str], Found], text: str
) -> None:
    assert find(f"Note: {text} in a sentence.") == []
    assert find(text) == []


def test_sentence_final_punctuation_is_not_part_of_the_match(find: Callable[[str], Found]) -> None:
    assert find("Mail a@example.com.") == [("EMAIL", "a@example.com")]
    assert find("Host 192.0.2.10.") == [("IP_ADDRESS", "192.0.2.10")]
    assert find("Host 2001:db8::1.") == [("IP_ADDRESS", "2001:db8::1")]
    assert find("Host 2001:db8::1: up") == [("IP_ADDRESS", "2001:db8::1")]
    assert find("Call 202-555-0143.") == [("PHONE", "202-555-0143")]


def test_values_separated_only_by_commas_are_each_found(find: Callable[[str], Found]) -> None:
    found = find("a@example.com,+1 202-555-0171,192.0.2.1,900-12-3456")
    assert found == [
        ("EMAIL", "a@example.com"),
        ("PHONE", "+1 202-555-0171"),
        ("IP_ADDRESS", "192.0.2.1"),
        ("US_SSN", "900-12-3456"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Invoice 123 4111 1111 1111 1111 paid",
        "Card 4111 1111 1111 1111 123 ok",
        "Server 192.0.2.1 4111 1111 1111 1111",
    ],
)
def test_a_card_next_to_other_numbers_is_still_found(
    find: Callable[[str], Found], text: str
) -> None:
    """A neighbouring number must not swallow the card and make it fail the checksum."""
    assert ("FINANCIAL", "4111 1111 1111 1111") in find(text)
    assert [t for t, _ in find(text) if t == "FINANCIAL"] == ["FINANCIAL"]


def test_overlapping_card_windows_keep_the_earliest_longest_one(
    find: Callable[[str], Found],
) -> None:
    """Both 4111 1111 1111 1111 and 1111 1111 1111 1000 pass the checksum; only one is reported."""
    assert find("4111 1111 1111 1111 1000") == [("FINANCIAL", "4111 1111 1111 1111")]


def test_ipv4_inside_an_ipv6_address_is_one_detection(find: Callable[[str], Found]) -> None:
    assert find("x ::ffff:192.0.2.1 y") == [("IP_ADDRESS", "::ffff:192.0.2.1")]


def test_detection_offsets_are_character_offsets_in_non_ascii_text(
    san: Callable[[str], Any],
) -> None:
    text = "José Álvarez: jose.alvarez@example.com"
    (found,) = san("app.detection.registry").detect(text)
    assert (found.entity_type, text[found.start : found.end]) == (
        "EMAIL",
        "jose.alvarez@example.com",
    )


def test_each_recognizer_reports_only_its_own_type(san: Callable[[str], Any]) -> None:
    registry = san("app.detection.registry")
    for recognizer in registry.PILOT_RECOGNIZERS:
        for detection in recognizer.find("a@example.com 192.0.2.1 900-12-3456 ABCDE1234F"):
            assert detection.entity_type == recognizer.entity_type


def test_pilot_types_are_the_six_in_decision_d1(san: Callable[[str], Any]) -> None:
    covered = san("app.detection.registry").covered_entity_types()
    assert covered == {"EMAIL", "PHONE", "FINANCIAL", "IN_PAN", "IP_ADDRESS", "US_SSN"}


def test_detect_can_be_limited_to_some_entity_types(san: Callable[[str], Any]) -> None:
    registry = san("app.detection.registry")
    text = "a@example.com 192.0.2.1"
    only_ip = registry.detect(text, entity_types={"IP_ADDRESS"})
    assert [d.entity_type for d in only_ip] == ["IP_ADDRESS"]
    assert registry.detect(text, entity_types=set()) == []


def test_empty_text_has_no_detections(san: Callable[[str], Any]) -> None:
    assert san("app.detection.registry").detect("") == []


def test_detect_returns_detections_in_text_order(san: Callable[[str], Any]) -> None:
    registry = san("app.detection.registry")
    found = registry.detect("900-12-3456 then a@example.com then 192.0.2.1")
    assert [d.start for d in found] == sorted(d.start for d in found)


def test_large_input_with_no_matches_is_scanned_quickly(
    san: Callable[[str], Any],
) -> None:
    """Patterns are bounded, so long digit and word runs cannot cause catastrophic backtracking."""
    import time

    registry = san("app.detection.registry")
    text = ("1 " * 20000) + ("a" * 50000) + (":" * 20000) + ("9-" * 20000)
    start = time.perf_counter()
    registry.detect(text)
    assert time.perf_counter() - start < 5
