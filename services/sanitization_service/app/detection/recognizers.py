"""The pilot recognizers (decision D1): EMAIL, PHONE, FINANCIAL, IN_PAN, IP_ADDRESS, US_SSN.

All are deterministic patterns with a checksum or range check where one exists. Every pattern
is anchored so a scan stays linear on long input. Detection is best effort: formats outside
the ones documented in SPEC 9.11 are not found.
"""

import ipaddress
import re
from collections.abc import Callable, Sequence

from app.detection.types import Detection

_NOT_ALNUM_BEFORE = r"(?<![A-Za-z0-9])"
_NOT_ALNUM_AFTER = r"(?![A-Za-z0-9])"


def _drop_contained(spans: set[tuple[int, int]]) -> list[tuple[int, int]]:
    """Keep only spans that are not inside a longer span, in text order."""
    kept: list[tuple[int, int]] = []
    for start, end in sorted(spans, key=lambda s: (s[0], -s[1])):
        if not kept or end > kept[-1][1]:
            kept.append((start, end))
    return kept


class PatternRecognizer:
    """One or more regular expressions, each match optionally confirmed by a check."""

    def __init__(
        self,
        entity_type: str,
        patterns: Sequence[str],
        accept: Callable[[str], bool] | None = None,
    ) -> None:
        self._entity_type = entity_type
        self._patterns = [re.compile(p, re.ASCII) for p in patterns]
        self._accept = accept

    @property
    def entity_type(self) -> str:
        return self._entity_type

    def find(self, text: str) -> list[Detection]:
        spans: set[tuple[int, int]] = set()
        for pattern in self._patterns:
            for match in pattern.finditer(text):
                if self._accept is None or self._accept(match.group(0)):
                    spans.add((match.start(), match.end()))
        return [Detection(self._entity_type, s, e) for s, e in _drop_contained(spans)]


EMAIL = PatternRecognizer(
    "EMAIL",
    [
        r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@"
        r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}"
    ],
)

_PHONE_START = r"(?<![\w.+-])"
_PHONE_END = r"(?![\w-])"
PHONE = PatternRecognizer(
    "PHONE",
    [
        # +1 with a ten digit number
        _PHONE_START + r"\+1[ .-]?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}" + _PHONE_END,
        # other country codes, as three groups of digits (+91 98765 43210, +44 7911 123456)
        _PHONE_START + r"\+\d{1,3}[ -]?\d{4,5}[ -]?\d{4,6}" + _PHONE_END,
        # ten digit numbers written 202-555-0143, 202.555.0143 or (202) 555-0143
        _PHONE_START + r"(?:\(\d{3}\)[ ]?|\d{3}[-. ])\d{3}[-.]\d{4}" + _PHONE_END,
        # Indian national format with the leading 0 (098765 43210)
        _PHONE_START + r"0\d{5}[ -]?\d{5}" + _PHONE_END,
    ],
)

IN_PAN = PatternRecognizer(
    "IN_PAN",
    [_NOT_ALNUM_BEFORE + r"[A-Z]{5}[0-9]{4}[A-Z]" + _NOT_ALNUM_AFTER],
)


def _valid_ssn(value: str) -> bool:
    """Reject the area, group and serial values that are never issued."""
    return value[0:3] not in ("000", "666") and value[4:6] != "00" and value[7:11] != "0000"


US_SSN = PatternRecognizer(
    "US_SSN",
    [r"(?<![\w-])[0-9]{3}([- ])[0-9]{2}\1[0-9]{4}(?![\w-])"],
    accept=_valid_ssn,
)

_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
_IPV4 = re.compile(rf"(?<![\w.])(?:{_OCTET}\.){{3}}{_OCTET}(?!\w|\.[0-9])", re.ASCII)
_IPV6_CANDIDATE = re.compile(r"(?<![\w.])[0-9A-Fa-f:.]{3,}(?!\w)", re.ASCII)


class IpAddressRecognizer:
    """IPv4 with strict octets, and IPv6 confirmed by the standard library parser."""

    entity_type = "IP_ADDRESS"

    def find(self, text: str) -> list[Detection]:
        v6: list[tuple[int, int]] = []
        for match in _IPV6_CANDIDATE.finditer(text):
            candidate = match.group(0)
            if ":" not in candidate:
                continue
            for stripped in (candidate, candidate.rstrip("."), candidate.rstrip(".:")):
                if _is_ipv6(stripped):
                    v6.append((match.start(), match.start() + len(stripped)))
                    break
        spans = set(v6)
        for match in _IPV4.finditer(text):
            if not any(s < match.end() and match.start() < e for s, e in v6):
                spans.add((match.start(), match.end()))
        return [Detection(self.entity_type, s, e) for s, e in sorted(spans)]


def _is_ipv6(value: str) -> bool:
    if not any(c in "0123456789abcdefABCDEF" for c in value):
        return False
    try:
        ipaddress.IPv6Address(value)
    except ValueError:
        return False
    return True


_DIGIT_RUN = re.compile(r"(?<![0-9])[0-9]+(?:[ -][0-9]+)*", re.ASCII)
_DIGIT_GROUP = re.compile(r"[0-9]+", re.ASCII)
_CARD_MIN_DIGITS = 13
_CARD_MAX_DIGITS = 19
_CARD_MIN_GROUP = 4

Group = tuple[int, int]  # offsets of one run of digits


def luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


class CardRecognizer:
    """Payment card numbers: 13 to 19 digits that pass the Luhn check.

    Digits may be split into groups by single spaces or hyphens, each group at least four
    digits when there is more than one. Every window of groups in a run of digits is tried, so
    a neighbouring number does not hide a card by making the whole run fail the checksum.
    """

    entity_type = "FINANCIAL"

    def find(self, text: str) -> list[Detection]:
        found: list[Detection] = []
        for run in _DIGIT_RUN.finditer(text):
            groups = [
                (run.start() + g.start(), run.start() + g.end())
                for g in _DIGIT_GROUP.finditer(run.group(0))
            ]
            found += self._cards_in_run(text, groups)
        return found

    def _cards_in_run(self, text: str, groups: list[Group]) -> list[Detection]:
        candidates: list[tuple[int, int, int]] = []  # (digit count, first group, last group)
        for first in range(len(groups)):
            digits = 0
            for last in range(first, len(groups)):
                if last > first and (_short(groups[first]) or _short(groups[last])):
                    break
                digits += groups[last][1] - groups[last][0]
                if digits > _CARD_MAX_DIGITS:
                    break
                if digits >= _CARD_MIN_DIGITS and _checksum_ok(text, groups[first], groups[last]):
                    candidates.append((digits, first, last))
        taken: set[int] = set()
        chosen: list[Detection] = []
        for _, first, last in sorted(candidates, key=lambda c: (-c[0], c[1])):
            used = set(range(first, last + 1))
            if used & taken:
                continue
            taken |= used
            chosen.append(Detection(self.entity_type, groups[first][0], groups[last][1]))
        return sorted(chosen, key=lambda d: d.start)


def _short(group: Group) -> bool:
    return group[1] - group[0] < _CARD_MIN_GROUP


def _checksum_ok(text: str, first: Group, last: Group) -> bool:
    window = text[first[0] : last[1]]
    return luhn_valid("".join(c for c in window if c in "0123456789"))
