"""Fixtures for integration tests that need a real PostgreSQL (requires Docker)."""

from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Throwaway PostgreSQL container for tests that need a database."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed: run `uv sync --group integration`")
    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
    except Exception as exc:  # Docker unavailable or image pull failed
        pytest.skip(f"PostgreSQL container could not start: {exc}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()
