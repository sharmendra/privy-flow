"""Which spans of a text to mask under a policy, and with which action.

Detections are filtered to the types the policy names before overlaps are resolved, so a
type nobody asked to mask can never hide one that was asked for.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from app.detection.overlap import resolve_overlaps
from app.detection.registry import PILOT_RECOGNIZERS, detect
from app.detection.types import Recognizer
from app.sanitization.policy import EffectivePolicy
from app.sanitization.profiles.loader import Action, load_entity_types


@dataclass(frozen=True, slots=True)
class MaskSpan:
    """A span to mask. It holds offsets only, never the text it covers."""

    entity_type: str
    start: int
    end: int
    action: Action


@lru_cache(maxsize=1)
def _priority() -> dict[str, int]:
    return {name: info.priority for name, info in load_entity_types().items()}


def plan_spans(
    text: str, policy: EffectivePolicy, recognizers: Sequence[Recognizer] | None = None
) -> list[MaskSpan]:
    """Spans to mask, in text order and without overlaps."""
    active = PILOT_RECOGNIZERS if recognizers is None else recognizers
    # Only look for types the policy names, so an unlisted type cannot hide a listed one.
    detections = detect(text, active, entity_types=policy.actions.keys())
    planned: list[MaskSpan] = []
    for span in resolve_overlaps(detections, _priority()):
        # If any span this one beat was redact, this span is redact too (the stricter action).
        redact = any(policy.actions[t] == "redact" for t in span.overlapped_types)
        planned.append(
            MaskSpan(span.entity_type, span.start, span.end, "redact" if redact else "placeholder")
        )
    return planned
