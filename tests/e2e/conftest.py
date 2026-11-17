"""Fixtures for the end-to-end suite: both services as separate processes over a real PostgreSQL.

`stack` is shared by the tests in a module that only add data under their own scope IDs.
`fresh_stack` is for tests that stop or restart a service or take the database away.
If no database is available the tests fail with the reason; they are never skipped.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.support.database import create_database, drop_database
from tests.support.migrations import upgrade
from tests.support.stack import Stack

ADMIN_URL_ENV = "PRIVYFLOW_TEST_DATABASE_URL"


def _admin_url(configured: str | None) -> str:
    if configured:
        return configured
    pytest.fail(
        f"No test database: set {ADMIN_URL_ENV} to a local PostgreSQL admin URL. "
        "The end-to-end suite does not use Testcontainers."
    )


@pytest.fixture(scope="module")
def e2e_admin_url() -> str:
    return _admin_url(os.environ.get(ADMIN_URL_ENV))


@pytest.fixture(scope="module")
def stack(e2e_admin_url: str, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    url = create_database(e2e_admin_url)
    try:
        upgrade(url)
        with Stack(url, e2e_admin_url, tmp_path_factory.mktemp("e2e")) as running:
            yield running
    finally:
        drop_database(e2e_admin_url, url)


@pytest.fixture
def fresh_stack(e2e_admin_url: str, tmp_path: Path) -> Iterator[Stack]:
    url = create_database(e2e_admin_url)
    try:
        upgrade(url)
        with Stack(url, e2e_admin_url, tmp_path) as running:
            yield running
    finally:
        drop_database(e2e_admin_url, url)
