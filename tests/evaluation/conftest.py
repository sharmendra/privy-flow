"""Evaluation fixtures: the real pilot detector, as the evaluation harness expects it."""

import importlib
from collections.abc import Collection

import pytest

from tests.support.eval_metrics import Detector, Span
from tests.support.service_loader import load_service_app


@pytest.fixture(scope="module")
def covered_types() -> Collection[str]:
    """Entity types the pilot detector has a recognizer for."""
    load_service_app("sanitization_service")
    covered: Collection[str] = importlib.import_module(
        "app.detection.registry"
    ).covered_entity_types()
    return covered


@pytest.fixture(scope="module")
def detector(covered_types: Collection[str]) -> Detector:
    """All pilot recognizers over every covered type, with overlaps resolved by rule D6."""
    registry = importlib.import_module("app.detection.registry")
    overlap = importlib.import_module("app.detection.overlap")
    loader = importlib.import_module("app.sanitization.profiles.loader")
    priority = {name: info.priority for name, info in loader.load_entity_types().items()}

    def detect(text: str) -> list[Span]:
        winners = overlap.resolve_overlaps(registry.detect(text), priority)
        return [(w.entity_type, w.start, w.end) for w in winners]

    return detect
