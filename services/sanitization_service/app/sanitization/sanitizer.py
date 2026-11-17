"""Replacing the planned spans of a text with placeholders.

Pure logic: no database, no clock, no randomness, and no state between calls. Storing the
mappings and issuing a restore-reference are the vault's job (phase 5).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from app.detection.types import Recognizer
from app.sanitization.placeholders import PlaceholderNamer, redact_marker
from app.sanitization.policy import EffectivePolicy
from app.sanitization.spans import MaskSpan, plan_spans


@dataclass(frozen=True, slots=True)
class SanitizationResult:
    """The sanitized text and the reversible mappings. Both are sensitive, so neither is
    shown when the result is printed or logged by mistake."""

    sanitized_text: str = field(repr=False)
    mappings: Mapping[str, str] = field(repr=False)  # placeholder to original value
    entity_count: int  # masked spans, reversible and redacted

    def __post_init__(self) -> None:
        object.__setattr__(self, "mappings", MappingProxyType(dict(self.mappings)))


def _check_spans(text: str, spans: Sequence[MaskSpan]) -> None:
    cursor = 0
    for span in spans:
        if not 0 <= cursor <= span.start < span.end <= len(text):
            raise ValueError("invalid span: empty, outside the text, unordered or overlapping")
        cursor = span.end


def apply_spans(text: str, spans: Sequence[MaskSpan]) -> SanitizationResult:
    """Replace each span, keeping every character outside the spans as it was.

    Spans must be in text order, non-empty, inside the text and not overlapping; touching is
    allowed. A repeated value of the same type shares one placeholder within this call.
    `redact` spans become a marker and are never added to the mappings.
    """
    _check_spans(text, spans)
    namer = PlaceholderNamer(text)
    placeholders: dict[tuple[str, str], str] = {}
    mappings: dict[str, str] = {}
    parts: list[str] = []
    cursor = 0
    for span in spans:
        parts.append(text[cursor : span.start])
        if span.action == "redact":
            parts.append(redact_marker(span.entity_type))
        else:
            value = text[span.start : span.end]
            key = (span.entity_type, value)
            if key not in placeholders:
                placeholders[key] = namer.placeholder(span.entity_type)
                mappings[placeholders[key]] = value
            parts.append(placeholders[key])
        cursor = span.end
    parts.append(text[cursor:])
    return SanitizationResult("".join(parts), mappings, len(spans))


def sanitize_text(
    text: str, policy: EffectivePolicy, recognizers: Sequence[Recognizer] | None = None
) -> SanitizationResult:
    """Detect what the policy names and replace it. Empty text is accepted here and returned
    unchanged; rejecting it is the request schema's job."""
    return apply_spans(text, plan_spans(text, policy, recognizers))
