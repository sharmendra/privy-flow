"""Placeholder text: `[TYPE_NNN]` for reversible values and `[TYPE_REDACTED]` for redacted ones.

The number is three digits, zero padded, and grows only past 999. Numbers are per type and
per request. A number is skipped when its placeholder already appears literally in the
input, so a generated placeholder never equals text the caller wrote.

A literal `[TYPE_REDACTED]` in the input is left alone. It is never restored, so it cannot
be mistaken for a mapping.
"""

import re

# Every generated placeholder has this shape. Used to find placeholder-like text in the input.
PLACEHOLDER_LIKE = re.compile(r"\[[A-Z][A-Z0-9_]*_[0-9]{3,}\]")


def redact_marker(entity_type: str) -> str:
    return f"[{entity_type}_REDACTED]"


class PlaceholderNamer:
    """Hands out placeholders for one request. It holds no state across requests."""

    def __init__(self, text: str) -> None:
        self._taken = frozenset(PLACEHOLDER_LIKE.findall(text))
        self._next: dict[str, int] = {}

    def placeholder(self, entity_type: str) -> str:
        number = self._next.get(entity_type, 1)
        while (candidate := f"[{entity_type}_{number:03d}]") in self._taken:
            number += 1
        self._next[entity_type] = number + 1
        return candidate
