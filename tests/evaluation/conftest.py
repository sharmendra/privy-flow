"""Evaluation fixtures."""

import pytest

from tests.support.eval_metrics import Detector


@pytest.fixture
def detector() -> Detector:
    """The Sanitization Service detector as a `text -> [(type, start, end)]` callable.

    Wire this to the real detection module in Phase 2, once its interface is approved.
    """
    pytest.skip("detection is not implemented yet (PLAN.md Phase 2)")
