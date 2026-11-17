"""Integrity checks for the synthetic, manually annotated detection dataset."""

import re

from tests.support.eval_metrics import ENTITY_TYPES, load_dataset, load_thresholds

EXAMPLES = load_dataset()
SAFE_EMAIL_DOMAINS = ("example.com", "example.org", "example.net")


def test_ids_are_unique() -> None:
    ids = [e.id for e in EXAMPLES]
    assert len(ids) == len(set(ids))


def test_every_required_entity_type_is_covered() -> None:
    covered = {span[0] for e in EXAMPLES for span in e.gold}
    assert covered == set(ENTITY_TYPES)


def test_spans_are_valid_for_their_text() -> None:
    for e in EXAMPLES:
        for _type, start, end in e.gold:
            assert 0 <= start < end <= len(e.text), e.id


def test_includes_negative_repeated_and_overlapping_examples() -> None:
    assert sum(1 for e in EXAMPLES if not e.gold) >= 5
    assert any(e.id.startswith("multi-") for e in EXAMPLES)
    overlapping = [
        e
        for e in EXAMPLES
        if any(a != b and a[1] < b[2] and b[1] < a[2] for a in e.gold for b in e.gold)
    ]
    assert overlapping


def test_only_reserved_example_email_domains_are_used() -> None:
    for e in EXAMPLES:
        for _type, start, end in (s for s in e.gold if s[0] == "EMAIL"):
            domain = e.text[start:end].lower().rsplit("@", 1)[1]
            assert domain in SAFE_EMAIL_DOMAINS, e.id


def test_us_phone_numbers_use_the_fictional_555_range() -> None:
    for e in EXAMPLES:
        for etype, start, end in e.gold:
            value = e.text[start:end]
            if etype == "PHONE" and value.startswith("+1"):
                assert re.search(r"555-01\d\d$", value), e.id


def test_thresholds_file_covers_every_entity_type() -> None:
    assert set(load_thresholds()["per_type"]) == set(ENTITY_TYPES)
