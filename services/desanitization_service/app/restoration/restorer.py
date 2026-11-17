"""Exact-placeholder restoration (SPEC 9.6).

One pass, left to right, over the sanitized text. Only a token with the placeholder shape that
is a key of the authorized mapping is replaced. Everything else is left exactly as it was:
unknown and altered placeholders, malformed look-alikes and `[TYPE_REDACTED]` markers. A
restored value is never scanned again, so a value that looks like a placeholder is not
substituted. The output size is checked as the text is built, so a small input cannot make the
service build a huge string.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

# Every placeholder the Sanitization Service generates has this shape (SPEC 9.12): no bracket
# inside, so a generated placeholder can never be formed by joining text around a replacement.
PLACEHOLDER_SHAPE = re.compile(r"\[[A-Z][A-Z0-9_]*_[0-9]{3,}\]")


class OutputTooLargeError(Exception):
    """The restored text would be larger than the output limit."""


@dataclass(frozen=True, slots=True)
class RestorationResult:
    # Hidden from repr so printing or logging a result by mistake shows no text.
    text: str = field(repr=False)
    restored_count: int
    unmatched_placeholder_count: int


def _size(text: str) -> int:
    return len(text.encode("utf-8", "surrogatepass"))


def restore(
    sanitized: str, mappings: Mapping[str, str], max_output_bytes: int
) -> RestorationResult:
    parts: list[str] = []
    size = 0
    position = 0
    restored = 0
    unmatched = 0
    value_sizes: dict[str, int] = {}

    def add(piece: str, piece_size: int) -> None:
        nonlocal size
        size += piece_size
        if size > max_output_bytes:
            raise OutputTooLargeError
        parts.append(piece)

    for match in PLACEHOLDER_SHAPE.finditer(sanitized):
        literal = sanitized[position : match.start()]
        add(literal, _size(literal))
        token = match.group(0)
        value = mappings.get(token)
        if value is None:
            unmatched += 1
            add(token, len(token))
        else:
            restored += 1
            if value not in value_sizes:
                value_sizes[value] = _size(value)
            add(value, value_sizes[value])
        position = match.end()
    tail = sanitized[position:]
    add(tail, _size(tail))
    return RestorationResult("".join(parts), restored, unmatched)
