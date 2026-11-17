"""Fixtures for tests that need a real PostgreSQL.

The admin database comes from PRIVYFLOW_TEST_DATABASE_URL when it is set (an explicit
opt-in to a local PostgreSQL), otherwise from a Testcontainers PostgreSQL, which needs
Docker. If neither is available the test fails with the reason. It is never skipped, so a
missing database cannot look like a pass.
"""

import os
from collections.abc import Iterator

import pytest

from tests.support.database import create_database, drop_database
from tests.support.migrations import upgrade

ADMIN_URL_ENV = "PRIVYFLOW_TEST_DATABASE_URL"


@pytest.fixture(scope="session")
def database_admin_url() -> Iterator[str]:
    """SQLAlchemy URL of a role that can create databases."""
    configured = os.environ.get(ADMIN_URL_ENV)
    if configured:
        yield configured
        return
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.fail(f"No test database: set {ADMIN_URL_ENV} or run `uv sync --group integration`")
    container = PostgresContainer("postgres:16-alpine")
    try:
        container.start()
    except Exception as exc:
        pytest.fail(f"No test database: set {ADMIN_URL_ENV} or start Docker ({type(exc).__name__})")
    try:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5432)
        yield (
            f"postgresql+psycopg://{container.username}:{container.password}"
            f"@{host}:{port}/{container.dbname}"
        )
    finally:
        container.stop()


@pytest.fixture
def empty_database_url(database_admin_url: str) -> Iterator[str]:
    """A new empty database for one test, dropped afterwards."""
    url = create_database(database_admin_url)
    try:
        yield url
    finally:
        drop_database(database_admin_url, url)


@pytest.fixture
def migrated_database_url(empty_database_url: str) -> str:
    """A new database with every migration applied."""
    upgrade(empty_database_url)
    return empty_database_url
