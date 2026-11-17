"""Shared fixtures and automatic suite markers."""

import os
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.support.service_loader import load_service_app

SUITES = ("unit", "integration", "security", "evaluation", "e2e")

# Valid settings that need no real database. Tests override or remove entries as needed.
DEFAULT_SANITIZATION_ENV = {
    "PRIVYFLOW_SAN_DATABASE_URL": "postgresql+psycopg://nobody:nopass@127.0.0.1:1/none",
}
DEFAULT_DESANITIZATION_ENV = {
    "PRIVYFLOW_DESAN_SANITIZATION_BASE_URL": "http://127.0.0.1:1",
}


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


@pytest.fixture(autouse=True)
def isolated_service_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Remove service settings from the environment and ignore any local .env file."""
    for name in list(os.environ):
        if name.startswith(("PRIVYFLOW_SAN_", "PRIVYFLOW_DESAN_")):
            monkeypatch.delenv(name)
    absent = str(tmp_path / "absent.env")
    monkeypatch.setenv("PRIVYFLOW_SAN_ENV_FILE", absent)
    monkeypatch.setenv("PRIVYFLOW_DESAN_ENV_FILE", absent)


AppFactory = Callable[..., Any]


def _factory(service: str, defaults: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> AppFactory:
    def build(env: dict[str, str | None] | None = None) -> Any:
        """Load a fresh app. `env` entries override the defaults; None removes a variable."""
        merged: dict[str, str | None] = {**defaults, **(env or {})}
        for name, value in merged.items():
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        app = load_service_app(service)
        if app is None:
            pytest.skip(f"{service} is not implemented yet")
        return app

    return build


@pytest.fixture
def sanitization_app_factory(monkeypatch: pytest.MonkeyPatch) -> AppFactory:
    return _factory("sanitization_service", DEFAULT_SANITIZATION_ENV, monkeypatch)


@pytest.fixture
def desanitization_app_factory(monkeypatch: pytest.MonkeyPatch) -> AppFactory:
    return _factory("desanitization_service", DEFAULT_DESANITIZATION_ENV, monkeypatch)


@asynccontextmanager
async def client_for(
    app: Any, raise_app_exceptions: bool = True
) -> AsyncGenerator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def sanitization_client(
    sanitization_app_factory: AppFactory,
) -> AsyncIterator[httpx.AsyncClient]:
    async with client_for(sanitization_app_factory()) as client:
        yield client


@pytest.fixture
async def desanitization_client(
    desanitization_app_factory: AppFactory,
) -> AsyncIterator[httpx.AsyncClient]:
    async with client_for(desanitization_app_factory()) as client:
        yield client


@pytest.fixture
def tenant_ids() -> tuple[str, str]:
    """Two distinct synthetic tenants for isolation tests."""
    return ("tenant-test-a", "tenant-test-b")
