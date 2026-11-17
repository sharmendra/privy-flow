"""The recognizers the service runs, and the one function that applies them."""

from collections.abc import Collection, Sequence

from app.detection.recognizers import (
    EMAIL,
    IN_PAN,
    PHONE,
    US_SSN,
    CardRecognizer,
    IpAddressRecognizer,
)
from app.detection.types import Detection, Recognizer

PILOT_RECOGNIZERS: tuple[Recognizer, ...] = (
    EMAIL,
    PHONE,
    CardRecognizer(),
    IN_PAN,
    IpAddressRecognizer(),
    US_SSN,
)


def covered_entity_types(
    recognizers: Sequence[Recognizer] = PILOT_RECOGNIZERS,
) -> frozenset[str]:
    """Entity types that have a recognizer. Profile types outside this set are not enforced."""
    return frozenset(r.entity_type for r in recognizers)


def detect(
    text: str,
    recognizers: Sequence[Recognizer] = PILOT_RECOGNIZERS,
    entity_types: Collection[str] | None = None,
) -> list[Detection]:
    """All detections from the recognizers, in text order. Overlaps are not resolved here."""
    found: list[Detection] = []
    for recognizer in recognizers:
        if entity_types is None or recognizer.entity_type in entity_types:
            found += recognizer.find(text)
    found.sort(key=lambda d: (d.start, d.end, d.entity_type))
    return found
