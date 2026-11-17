"""Tests of the evaluation metrics, using stub detectors."""

from hypothesis import given
from hypothesis import strategies as st

from tests.support.eval_metrics import (
    Example,
    Report,
    Span,
    evaluate,
    resolve_span,
    threshold_failures,
)

TEXT = "Asha Verma wrote to asha@example.com"
GOLD: frozenset[Span] = frozenset({("PERSON", 0, 10), ("EMAIL", 20, 36)})
EXAMPLES = [Example("a", "", TEXT, GOLD), Example("neg", "", "nothing here", frozenset())]


def test_perfect_detector_scores_one() -> None:
    report = evaluate(EXAMPLES, lambda text: GOLD if text == TEXT else [])
    assert report.overall.precision == report.overall.recall == report.overall.f1 == 1.0
    assert report.negative_document_fp_rate == 0.0


def test_empty_detector_has_zero_recall_and_no_false_positives() -> None:
    report = evaluate(EXAMPLES, lambda text: [])
    assert report.overall.recall == 0.0
    assert report.overall.false_negative_rate == 1.0
    assert report.overall.fp == 0


def test_wrong_type_or_boundary_counts_as_error() -> None:
    wrong: set[Span] = {("PERSON", 0, 4), ("PHONE", 20, 36)}
    report = evaluate(EXAMPLES[:1], lambda text: wrong)
    assert (report.overall.tp, report.overall.fp, report.overall.fn) == (0, 2, 2)


def test_per_type_breakdown() -> None:
    report = evaluate(EXAMPLES[:1], lambda text: {("PERSON", 0, 10)})
    assert report.per_type["PERSON"].recall == 1.0
    assert report.per_type["EMAIL"].recall == 0.0


def test_negative_document_false_positive_rate() -> None:
    report = evaluate(EXAMPLES, lambda text: {("PERSON", 0, 4)} if text == "nothing here" else [])
    assert report.negative_document_fp_rate == 1.0


def test_resolve_span_picks_nth_occurrence() -> None:
    assert resolve_span("ab ab", "X", "ab", 2) == ("X", 3, 5)


def test_threshold_failures_skip_null_and_flag_misses() -> None:
    report = evaluate(EXAMPLES[:1], lambda text: {("PERSON", 0, 10)})
    assert threshold_failures(report, {"overall": {"precision": None, "recall": None}}) == []
    failures = threshold_failures(report, {"overall": {"recall": 0.9}})
    assert failures == ["overall.recall=0.500 < 0.9"]


span_strategy = st.tuples(
    st.sampled_from(["PERSON", "EMAIL"]), st.integers(0, 50), st.integers(51, 99)
)


@given(
    gold=st.sets(span_strategy, max_size=8),
    predicted=st.sets(span_strategy, max_size=8),
)
def test_metrics_stay_within_bounds_and_counts_are_consistent(
    gold: set[Span], predicted: set[Span]
) -> None:
    example = Example("p", "", "x" * 100, frozenset(gold))
    report: Report = evaluate([example], lambda text: predicted)
    c = report.overall
    assert c.tp + c.fn == len(gold)
    assert c.tp + c.fp == len(predicted)
    for value in (c.precision, c.recall, c.f1, c.false_positive_rate, c.false_negative_rate):
        assert 0.0 <= value <= 1.0
