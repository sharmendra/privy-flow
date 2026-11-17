"""Run the real detector over the dataset, write a report, and enforce approved thresholds."""

import json
from collections.abc import Collection

from tests.support.eval_metrics import (
    Detector,
    evaluate,
    load_dataset,
    load_thresholds,
    threshold_failures,
)
from tests.support.service_loader import REPO_ROOT

OUT_OF_PILOT = {"PERSON", "BUSINESS_CONFIDENTIAL", "IN_AADHAAR", "IN_IFSC"}


def test_detection_quality(detector: Detector, covered_types: Collection[str]) -> None:
    report = evaluate(load_dataset(), detector, covered_types)
    out = REPO_ROOT / "reports" / "detection_eval.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    assert threshold_failures(report, load_thresholds()) == []


def test_only_pilot_types_are_scored_and_the_rest_are_reported_as_not_covered(
    detector: Detector, covered_types: Collection[str]
) -> None:
    report = evaluate(load_dataset(), detector, covered_types)
    assert set(report.not_covered) == OUT_OF_PILOT
    assert all(count > 0 for count in report.not_covered.values())
    scored = {t for t, c in report.per_type.items() if c.tp + c.fn > 0}
    assert scored == set(covered_types)
    assert OUT_OF_PILOT.isdisjoint(scored)


def test_types_outside_the_pilot_are_not_counted_as_misses(
    detector: Detector, covered_types: Collection[str]
) -> None:
    report = evaluate(load_dataset(), detector, covered_types)
    for name in OUT_OF_PILOT:
        assert report.per_type[name].fn == 0


def test_a_threshold_on_a_not_covered_type_is_neither_a_pass_nor_a_failure(
    detector: Detector, covered_types: Collection[str]
) -> None:
    report = evaluate(load_dataset(), detector, covered_types)
    assert threshold_failures(report, {"per_type": {"PERSON": {"recall": 0.9}}}) == []


def test_the_report_file_lists_not_covered_types(
    detector: Detector, covered_types: Collection[str]
) -> None:
    report = evaluate(load_dataset(), detector, covered_types).as_dict()
    assert set(report["not_covered"]) == OUT_OF_PILOT
    assert set(report["per_type"]) >= set(covered_types)


NEW_EXAMPLE_PREFIXES = ("ip-", "ssn-", "card-adjacent-")
NEW_NEGATIVES = {"neg-05", "neg-07", "neg-08", "neg-09"}


def test_examples_written_for_the_ip_ssn_and_card_recognizers_are_found_exactly(
    detector: Detector,
) -> None:
    checked = 0
    for example in load_dataset():
        if example.id.startswith(NEW_EXAMPLE_PREFIXES) or example.id in NEW_NEGATIVES:
            assert set(detector(example.text)) == example.gold, example.id
            checked += 1
    assert checked == 12
