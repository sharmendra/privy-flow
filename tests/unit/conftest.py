"""Fixtures for unit tests of Sanitization Service logic."""

import importlib
from collections.abc import Callable
from typing import Any

import pytest

from tests.support.service_loader import load_service_app


@pytest.fixture(scope="module")
def san() -> Callable[[str], Any]:
    """Import a Sanitization Service module by name. Loaded once per test module."""
    load_service_app("sanitization_service")
    return importlib.import_module


@pytest.fixture(scope="module")
def desan() -> Callable[[str], Any]:
    """Import a De-sanitization Service module by name. Loaded once per test module."""
    load_service_app("desanitization_service")
    return importlib.import_module
