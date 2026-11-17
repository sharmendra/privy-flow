"""The pilot corpus used by the end-to-end suite holds synthetic data only."""

import json
import re
from pathlib import Path

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "pilot" / "corpus.jsonl"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
RESERVED_DOMAINS = {"example.com", "example.org", "example.net"}
US_PHONE = re.compile(r"\+1 202-555-(\d{4})|\(202\) 555-(\d{4})")
IPV4 = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")


def _rows() -> list[dict[str, str]]:
    with CORPUS.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_the_corpus_parses_and_has_unique_ids_and_notes() -> None:
    rows = _rows()
    assert len(rows) >= 8
    assert len({r["id"] for r in rows}) == len(rows)
    assert all(set(r) == {"id", "note", "text"} and r["note"] for r in rows)


def test_every_email_uses_a_reserved_domain() -> None:
    domains = {m.group(1).lower() for r in _rows() for m in EMAIL.finditer(r["text"])}
    assert domains
    assert domains <= RESERVED_DOMAINS


def test_every_us_phone_number_is_in_the_fictional_range() -> None:
    """The reserved fictional block is 555-0100 to 555-0199."""
    numbers = [int(m.group(1) or m.group(2)) for r in _rows() for m in US_PHONE.finditer(r["text"])]
    assert numbers
    assert all(100 <= n <= 199 for n in numbers)


def test_every_ipv4_address_is_in_a_documentation_range() -> None:
    for row in _rows():
        for match in IPV4.finditer(row["text"]):
            assert match.group(0).startswith("192.0.2."), row["id"]


def test_ssn_and_card_values_are_documented_test_values() -> None:
    text = "\n".join(r["text"] for r in _rows())
    assert re.findall(r"\b\d{3}-\d{2}-\d{4}\b", text) == ["900-12-3456"]
    assert set(re.findall(r"\b(?:\d{4} ){3}\d{4}\b", text)) <= {
        "4111 1111 1111 1111",
        "5555 5555 5555 4444",
    }
