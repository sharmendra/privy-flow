"""Shared fixtures and automatic suite markers."""

import os
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.support.desan_api import DesanApi, install_stub
from tests.support.desan_env import desanitization_env
from tests.support.sanitization_stub import SanitizationStub
from tests.support.service_loader import load_service_app
from tests.support.settings_data import valid_content, write_settings_file
from tests.support.vault_api import VaultApi, install_in_memory_vault
from tests.support.vault_env import sanitization_secret_env

SUITES = ("unit", "integration", "security", "evaluation", "e2e")

# Valid settings that need no real database. Tests override or remove entries as needed.
DEFAULT_SANITIZATION_ENV = {
    "PRIVYFLOW_SAN_DATABASE_URL": "postgresql+psycopg://nobody:nopass@127.0.0.1:1/none",
    **sanitization_secret_env(),
}
DEFAULT_DESANITIZATION_ENV = desanitization_env()


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
        if name.startswith(("PRIVYFLOW_SAN_", "PRIVYFLOW_DESAN_", "PRIVYFLOW_SETTINGS_")):
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
def sanitization_app_factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AppFactory:
    settings_file = write_settings_file(tmp_path / "default-settings.json")
    defaults = {**DEFAULT_SANITIZATION_ENV, "PRIVYFLOW_SETTINGS_FILE": str(settings_file)}
    return _factory("sanitization_service", defaults, monkeypatch)


@pytest.fixture
def desanitization_app_factory(monkeypatch: pytest.MonkeyPatch) -> AppFactory:
    return _factory("desanitization_service", DEFAULT_DESANITIZATION_ENV, monkeypatch)


@asynccontextmanager
async def client_for(
    app: Any, raise_app_exceptions: bool = True
) -> AsyncGenerator[httpx.AsyncClient]:
    """A client for an in-process app, with application startup and shutdown run."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    async with app.router.lifespan_context(app):
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


VaultApiFactory = Callable[..., AbstractAsyncContextManager[VaultApi]]


@pytest.fixture
def vault_api_factory(sanitization_app_factory: AppFactory, tmp_path: Path) -> VaultApiFactory:
    """Build the Sanitization app over an in-memory vault. `settings` overrides the test
    settings content, for example `default_ttl_seconds` or `max_request_bytes`."""

    @asynccontextmanager
    async def build(**settings: Any) -> AsyncGenerator[VaultApi]:
        env: dict[str, str | None] = {}
        if settings:
            path = write_settings_file(tmp_path / "api-settings.json", valid_content(**settings))
            env["PRIVYFLOW_SETTINGS_FILE"] = str(path)
        app = sanitization_app_factory(env)
        async with client_for(app) as client:
            store, clock, vault = install_in_memory_vault(app)
            yield VaultApi(app, client, store, clock, vault)

    return build


@pytest.fixture
async def vault_api(vault_api_factory: VaultApiFactory) -> AsyncIterator[VaultApi]:
    async with vault_api_factory() as api:
        yield api


DesanApiFactory = Callable[..., AbstractAsyncContextManager[DesanApi]]


@pytest.fixture
def desan_api_factory(desanitization_app_factory: AppFactory) -> DesanApiFactory:
    """Build the De-sanitization app over a stub of the Sanitization internal API. `env`
    entries override the default environment, for example `PRIVYFLOW_DESAN_MAX_OUTPUT_BYTES`."""

    @asynccontextmanager
    async def build(env: dict[str, str | None] | None = None) -> AsyncGenerator[DesanApi]:
        app = desanitization_app_factory(env)
        async with client_for(app) as client:
            stub = SanitizationStub()
            await install_stub(app, stub)
            yield DesanApi(app, client, stub)

    return build


@pytest.fixture
async def desan_api(desan_api_factory: DesanApiFactory) -> AsyncIterator[DesanApi]:
    async with desan_api_factory() as api:
        yield api
