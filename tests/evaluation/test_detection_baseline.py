"""Run the real detector over the dataset, write a report, and enforce approved thresholds."""

import json

from tests.support.eval_metrics import (
    Detector,
    evaluate,
    load_dataset,
    load_thresholds,
    threshold_failures,
)
from tests.support.service_loader import REPO_ROOT


def test_detection_quality(detector: Detector) -> None:
    report = evaluate(load_dataset(), detector)
    out = REPO_ROOT / "reports" / "detection_eval.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    assert threshold_failures(report, load_thresholds()) == []
