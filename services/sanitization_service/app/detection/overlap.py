"""Overlap rule D6: the longest span wins; ties go to the higher entity-type priority, then
the earliest start. Shorter overlapping spans are dropped but remembered, so the winner can
take the most restrictive action among everything it overlapped (SPEC 9.9).
"""

from bisect import bisect_right
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.detection.types import Detection


@dataclass(frozen=True, slots=True)
class ResolvedSpan:
    entity_type: str
    start: int
    end: int
    overlapped_types: frozenset[str]  # this span's type and the type of every span it overlapped


def _winners_overlapping(winners: list[Detection], starts: list[int], span: Detection) -> list[int]:
    """Indexes of winners that overlap `span`. Winners are disjoint and sorted by start, so
    none before the one that starts at or before `span` can reach it."""
    index = max(bisect_right(starts, span.start) - 1, 0)
    hits: list[int] = []
    while index < len(winners) and winners[index].start < span.end:
        if winners[index].end > span.start:
            hits.append(index)
        index += 1
    return hits


def resolve_overlaps(
    detections: Iterable[Detection], priority: Mapping[str, int]
) -> list[ResolvedSpan]:
    ordered = sorted(
        (d for d in detections if d.end > d.start),
        key=lambda d: (-(d.end - d.start), -priority.get(d.entity_type, 0), d.start, d.entity_type),
    )
    winners: list[Detection] = []
    starts: list[int] = []
    dropped: list[Detection] = []
    for span in ordered:
        if _winners_overlapping(winners, starts, span):
            dropped.append(span)
        else:
            position = bisect_right(starts, span.start)
            winners.insert(position, span)
            starts.insert(position, span.start)
    overlapped = [{w.entity_type} for w in winners]
    for span in dropped:
        for index in _winners_overlapping(winners, starts, span):
            overlapped[index].add(span.entity_type)
    return [
        ResolvedSpan(w.entity_type, w.start, w.end, frozenset(types))
        for w, types in zip(winners, overlapped, strict=True)
    ]
