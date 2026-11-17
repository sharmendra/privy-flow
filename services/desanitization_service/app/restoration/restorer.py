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


def _grow(size: int, piece: str, max_output_bytes: int) -> int:
    """The output size after adding `piece`. Stops as soon as the limit is passed."""
    size += _size(piece)
    if size > max_output_bytes:
        raise OutputTooLargeError
    return size


def restore(
    sanitized: str, mappings: Mapping[str, str], max_output_bytes: int
) -> RestorationResult:
    parts: list[str] = []
    size = 0
    position = 0
    restored = 0
    unmatched = 0

    for match in PLACEHOLDER_SHAPE.finditer(sanitized):
        text_before = sanitized[position : match.start()]
        size = _grow(size, text_before, max_output_bytes)
        parts.append(text_before)

        token = match.group(0)
        value = mappings.get(token)
        if value is None:
            unmatched += 1
            replacement = token
        else:
            restored += 1
            replacement = value
        size = _grow(size, replacement, max_output_bytes)
        parts.append(replacement)
        position = match.end()

    tail = sanitized[position:]
    _grow(size, tail, max_output_bytes)
    parts.append(tail)
    return RestorationResult("".join(parts), restored, unmatched)
