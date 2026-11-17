"""Integrity checks for the synthetic, manually annotated detection dataset."""

import ipaddress
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


def test_ip_addresses_use_only_the_reserved_documentation_ranges() -> None:
    allowed = [
        ipaddress.ip_network(n)
        for n in (
            "192.0.2.0/24",
            "198.51.100.0/24",
            "203.0.113.0/24",
            "2001:db8::/32",
            "::ffff:0:0/96",
        )
    ]
    seen = 0
    for e in EXAMPLES:
        for etype, start, end in e.gold:
            if etype == "IP_ADDRESS":
                address = ipaddress.ip_address(e.text[start:end])
                assert any(address in network for network in allowed), e.id
                if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                    assert address.ipv4_mapped in allowed[0], e.id
                seen += 1
    assert seen >= 6


def test_ssn_values_use_areas_the_ssa_never_issues() -> None:
    seen = 0
    for e in EXAMPLES:
        for etype, start, _end in e.gold:
            if etype == "US_SSN":
                area = int(e.text[start : start + 3])
                assert 900 <= area <= 999, e.id
                seen += 1
    assert seen >= 4


def test_the_dataset_has_ip_and_ssn_negatives() -> None:
    ids = {e.id for e in EXAMPLES if not e.gold}
    assert {"neg-07", "neg-08", "neg-09"} <= ids


def test_thresholds_file_covers_every_entity_type() -> None:
    assert set(load_thresholds()["per_type"]) == set(ENTITY_TYPES)
