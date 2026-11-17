"""Span-level detection metrics and dataset loading for the evaluation suite.

A prediction counts as correct only if entity type, start and end all match a gold span.
"""

import json
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Span = tuple[str, int, int]  # (entity_type, start, end)
Detector = Callable[[str], Iterable[Span]]

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "eval"
ENTITY_TYPES = (
    "PERSON",
    "EMAIL",
    "PHONE",
    "FINANCIAL",
    "BUSINESS_CONFIDENTIAL",
    "IN_AADHAAR",
    "IN_PAN",
    "IN_IFSC",
    "IP_ADDRESS",
    "US_SSN",
)


@dataclass(frozen=True)
class Example:
    id: str
    note: str
    text: str
    gold: frozenset[Span]


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    @property
    def false_positive_rate(self) -> float:
        """FP / (TP + FP): share of reported entities that are wrong (false discovery rate).

        True negatives are undefined for span detection, so the classic FP rate is not used.
        """
        return self.fp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def false_negative_rate(self) -> float:
        """FN / (TP + FN): share of real entities that were missed."""
        return self.fn / (self.tp + self.fn) if self.tp + self.fn else 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "false_positive_rate": self.false_positive_rate,
            "false_negative_rate": self.false_negative_rate,
        }


@dataclass
class Report:
    overall: Counts = field(default_factory=Counts)
    per_type: dict[str, Counts] = field(default_factory=lambda: defaultdict(Counts))
    negative_documents: int = 0
    negative_documents_with_detections: int = 0
    # Gold spans of types the detector cannot detect. They are counted, never scored.
    not_covered: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def negative_document_fp_rate(self) -> float:
        n = self.negative_documents
        return self.negative_documents_with_detections / n if n else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall.as_dict(),
            "per_type": {t: c.as_dict() for t, c in sorted(self.per_type.items())},
            "negative_documents": self.negative_documents,
            "negative_document_fp_rate": self.negative_document_fp_rate,
            "not_covered": dict(sorted(self.not_covered.items())),
        }


def resolve_span(text: str, entity_type: str, value: str, occurrence: int = 1) -> Span:
    """Find the nth occurrence of `value` in `text` and return its span."""
    start = -1
    for _ in range(occurrence):
        start = text.find(value, start + 1)
        if start < 0:
            raise ValueError(f"{value!r} occurrence {occurrence} not found in text")
    return (entity_type, start, start + len(value))


def load_dataset(path: Path = FIXTURES / "detection_dataset.jsonl") -> list[Example]:
    examples: list[Example] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        gold = frozenset(
            resolve_span(raw["text"], e["type"], e["text"], e.get("occurrence", 1))
            for e in raw["entities"]
        )
        examples.append(Example(raw["id"], raw.get("note", ""), raw["text"], gold))
    return examples


def evaluate(
    examples: Iterable[Example],
    detector: Detector,
    covered_types: Collection[str] | None = None,
) -> Report:
    """Score a detector. With `covered_types`, gold spans of other types are reported as not
    covered instead of being scored as misses; predictions are always scored."""
    report = Report()
    for ex in examples:
        predicted = frozenset(detector(ex.text))
        if not ex.gold:
            report.negative_documents += 1
            report.negative_documents_with_detections += bool(predicted)
        gold = ex.gold
        if covered_types is not None:
            for span in gold:
                if span[0] not in covered_types:
                    report.not_covered[span[0]] += 1
            gold = frozenset(span for span in gold if span[0] in covered_types)
        for span in predicted | gold:
            in_pred, in_gold = span in predicted, span in gold
            for counts in (report.overall, report.per_type[span[0]]):
                if in_pred and in_gold:
                    counts.tp += 1
                elif in_pred:
                    counts.fp += 1
                else:
                    counts.fn += 1
    return report


def load_thresholds(path: Path = FIXTURES / "thresholds.json") -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def threshold_failures(report: Report, thresholds: dict[str, Any]) -> list[str]:
    """Compare a report to approved thresholds. A null threshold is not yet approved: skip it."""
    failures: list[str] = []
    scopes: list[tuple[str, Counts, dict[str, float | None]]] = [
        ("overall", report.overall, thresholds.get("overall", {}))
    ]
    for etype, limits in thresholds.get("per_type", {}).items():
        if etype in report.not_covered:
            continue  # not covered is neither a pass nor a failure
        scopes.append((etype, report.per_type[etype], limits))
    for name, counts, limits in scopes:
        values = counts.as_dict()
        for metric, minimum in limits.items():
            if minimum is not None and values[metric] < minimum:
                failures.append(f"{name}.{metric}={values[metric]:.3f} < {minimum}")
    return failures
