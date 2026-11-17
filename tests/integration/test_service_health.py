"""Liveness and readiness for both services."""

from typing import Any

import httpx
import pytest

from tests.conftest import AppFactory, client_for

OK = {"status": "ok"}
UNAVAILABLE = {"status": "unavailable"}


@pytest.mark.anyio
async def test_sanitization_liveness_returns_ok(sanitization_client: httpx.AsyncClient) -> None:
    response = await sanitization_client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == OK


@pytest.mark.anyio
async def test_sanitization_liveness_ok_when_settings_are_missing(
    sanitization_app_factory: AppFactory,
) -> None:
    app: Any = sanitization_app_factory({"PRIVYFLOW_SAN_DATABASE_URL": None})
    async with client_for(app) as client:
        assert (await client.get("/health/live")).status_code == 200


@pytest.mark.anyio
async def test_sanitization_readiness_ok_when_database_is_up(
    sanitization_app_factory: AppFactory, empty_database_url: str
) -> None:
    app: Any = sanitization_app_factory({"PRIVYFLOW_SAN_DATABASE_URL": empty_database_url})
    async with client_for(app) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == OK


@pytest.mark.anyio
async def test_sanitization_readiness_503_when_database_is_down(
    sanitization_client: httpx.AsyncClient,
) -> None:
    response = await sanitization_client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE


@pytest.mark.anyio
async def test_sanitization_readiness_503_when_settings_are_missing(
    sanitization_app_factory: AppFactory,
) -> None:
    app: Any = sanitization_app_factory({"PRIVYFLOW_SAN_DATABASE_URL": None})
    async with client_for(app) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE


@pytest.mark.anyio
async def test_sanitization_readiness_recovers_when_database_returns(
    sanitization_app_factory: AppFactory, empty_database_url: str, database_admin_url: str
) -> None:
    from tests.support.database import drop_database

    app: Any = sanitization_app_factory({"PRIVYFLOW_SAN_DATABASE_URL": empty_database_url})
    async with client_for(app) as client:
        assert (await client.get("/health/ready")).status_code == 200
        drop_database(database_admin_url, empty_database_url)
        assert (await client.get("/health/ready")).status_code == 503


@pytest.mark.anyio
async def test_desanitization_liveness_returns_ok(
    desanitization_client: httpx.AsyncClient,
) -> None:
    response = await desanitization_client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == OK


@pytest.mark.anyio
async def test_desanitization_readiness_ok_with_valid_configuration(
    desanitization_client: httpx.AsyncClient,
) -> None:
    response = await desanitization_client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == OK


@pytest.mark.anyio
@pytest.mark.parametrize("value", [None, "not-a-url", "ftp://example.com"])
async def test_desanitization_readiness_503_when_configuration_is_invalid(
    desanitization_app_factory: AppFactory, value: str | None
) -> None:
    app: Any = desanitization_app_factory({"PRIVYFLOW_DESAN_SANITIZATION_BASE_URL": value})
    async with client_for(app) as client:
        assert (await client.get("/health/live")).status_code == 200
        response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE
