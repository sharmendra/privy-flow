"""Shared fixtures and automatic suite markers."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.support.service_loader import load_service_app

SUITES = ("unit", "integration", "security", "evaluation", "e2e")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark each test with the suite named by its directory under tests/."""
    for item in items:
        parts = Path(str(item.fspath)).parts
        for suite in SUITES:
            if suite in parts[parts.index("tests") + 1 :]:
                item.add_marker(getattr(pytest.mark, suite))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _client_for(service: str) -> AsyncIterator[httpx.AsyncClient]:
    app: Any = load_service_app(service)
    if app is None:
        pytest.skip(f"{service} is not implemented yet (services/{service}/app/main.py missing)")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def sanitization_client() -> AsyncIterator[httpx.AsyncClient]:
    async for client in _client_for("sanitization_service"):
        yield client


@pytest.fixture
async def desanitization_client() -> AsyncIterator[httpx.AsyncClient]:
    async for client in _client_for("desanitization_service"):
        yield client


@pytest.fixture
def tenant_ids() -> tuple[str, str]:
    """Two distinct synthetic tenants for isolation tests."""
    return ("tenant-test-a", "tenant-test-b")
