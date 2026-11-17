"""Overlap rule D6: longest span wins, then higher type priority, then earliest start."""

import itertools
from collections.abc import Callable
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

TYPES = ["EMAIL", "PHONE", "FINANCIAL", "IP_ADDRESS", "US_SSN", "IN_PAN"]


@pytest.fixture(scope="module")
def mod(san: Callable[[str], Any]) -> Any:
    class Mod:
        detection = san("app.detection.types")
        overlap = san("app.detection.overlap")
        priority = {
            t.type: t.priority
            for t in san("app.sanitization.profiles.loader").load_entity_types().values()
        }  # noqa: E501

        def det(self, entity_type: str, start: int, end: int) -> Any:
            return self.detection.Detection(entity_type, start, end)

        def resolve(self, *spans: tuple[str, int, int]) -> list[tuple[str, int, int]]:
            winners = self.overlap.resolve_overlaps([self.det(*s) for s in spans], self.priority)
            return [(w.entity_type, w.start, w.end) for w in winners]

    return Mod()


def test_no_detections_resolve_to_nothing(mod: Any) -> None:
    assert mod.resolve() == []


def test_longest_span_wins_and_the_nested_span_is_dropped(mod: Any) -> None:
    assert mod.resolve(("PHONE", 5, 10), ("EMAIL", 0, 20)) == [("EMAIL", 0, 20)]


def test_a_longer_lower_priority_span_beats_a_shorter_higher_priority_one(mod: Any) -> None:
    assert mod.priority["FINANCIAL"] > mod.priority["PHONE"]
    assert mod.resolve(("FINANCIAL", 0, 10), ("PHONE", 0, 12)) == [("PHONE", 0, 12)]


def test_equal_length_goes_to_the_higher_priority_type(mod: Any) -> None:
    assert mod.resolve(("PHONE", 0, 10), ("FINANCIAL", 0, 10)) == [("FINANCIAL", 0, 10)]
    assert mod.resolve(("FINANCIAL", 0, 10), ("PHONE", 0, 10)) == [("FINANCIAL", 0, 10)]


def test_equal_length_and_priority_goes_to_the_earliest_start(mod: Any) -> None:
    assert mod.resolve(("PHONE", 5, 15), ("PHONE", 0, 10)) == [("PHONE", 0, 10)]


def test_partial_overlap_keeps_only_the_winner(mod: Any) -> None:
    assert mod.resolve(("EMAIL", 0, 12), ("PHONE", 8, 14)) == [("EMAIL", 0, 12)]


def test_adjacent_spans_do_not_overlap_and_both_survive(mod: Any) -> None:
    assert mod.resolve(("EMAIL", 0, 5), ("PHONE", 5, 10)) == [("EMAIL", 0, 5), ("PHONE", 5, 10)]


def test_separate_spans_are_returned_in_text_order(mod: Any) -> None:
    assert mod.resolve(("PHONE", 20, 25), ("EMAIL", 0, 5)) == [("EMAIL", 0, 5), ("PHONE", 20, 25)]


def test_identical_detections_collapse_to_one(mod: Any) -> None:
    assert mod.resolve(("EMAIL", 0, 5), ("EMAIL", 0, 5)) == [("EMAIL", 0, 5)]


def test_a_winner_records_the_types_it_displaced(mod: Any) -> None:
    winners = mod.overlap.resolve_overlaps(
        [mod.det("EMAIL", 0, 20), mod.det("PHONE", 5, 10), mod.det("IP_ADDRESS", 12, 18)],
        mod.priority,
    )
    (winner,) = winners
    assert winner.overlapped_types == {"EMAIL", "PHONE", "IP_ADDRESS"}


def test_a_winner_with_no_overlaps_records_only_its_own_type(mod: Any) -> None:
    (winner,) = mod.overlap.resolve_overlaps([mod.det("EMAIL", 0, 5)], mod.priority)
    assert winner.overlapped_types == {"EMAIL"}


def test_a_dropped_span_touching_two_winners_is_recorded_on_both(mod: Any) -> None:
    winners = mod.overlap.resolve_overlaps(
        [mod.det("EMAIL", 0, 10), mod.det("IN_PAN", 10, 20), mod.det("PHONE", 8, 12)],
        mod.priority,
    )
    assert [w.overlapped_types for w in winners] == [{"EMAIL", "PHONE"}, {"IN_PAN", "PHONE"}]


spans = st.lists(
    st.tuples(st.sampled_from(TYPES), st.integers(0, 40), st.integers(1, 15)).map(
        lambda t: (t[0], t[1], t[1] + t[2])
    ),
    max_size=12,
)


@given(spans)
def test_winners_never_overlap_each_other(mod: Any, raw: list[tuple[str, int, int]]) -> None:
    winners = mod.resolve(*raw)
    for a, b in itertools.combinations(winners, 2):
        assert a[2] <= b[1] or b[2] <= a[1]


@given(spans)
def test_every_detection_is_a_winner_or_overlaps_a_winner_that_is_not_shorter(
    mod: Any, raw: list[tuple[str, int, int]]
) -> None:
    winners = mod.resolve(*raw)
    for etype, start, end in raw:
        if (etype, start, end) in winners:
            continue
        assert any(
            w[1] < end and start < w[2] and (w[2] - w[1]) >= (end - start) for w in winners
        ), (etype, start, end)


@given(spans, st.randoms(use_true_random=False))
def test_result_does_not_depend_on_input_order(
    mod: Any, raw: list[tuple[str, int, int]], rng: Any
) -> None:
    shuffled = list(raw)
    rng.shuffle(shuffled)
    assert mod.resolve(*raw) == mod.resolve(*shuffled)
