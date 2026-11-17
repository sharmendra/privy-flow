"""Tests of the harness helpers themselves."""

from pathlib import Path

import pytest

from tests.support.leak import CANARIES, assert_no_leak
from tests.support.service_loader import load_service_app, service_exists


def test_assert_no_leak_passes_on_clean_output() -> None:
    assert_no_leak("request completed in 12 ms")


@pytest.mark.parametrize("canary", CANARIES)
def test_assert_no_leak_detects_each_canary(canary: str) -> None:
    with pytest.raises(AssertionError) as excinfo:
        assert_no_leak(f"processing {canary} now")
    assert canary not in str(excinfo.value)


def test_missing_service_loads_as_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PRIVYFLOW_SERVICES_DIR", str(tmp_path))
    assert not service_exists("sanitization_service")
    assert load_service_app("sanitization_service") is None
