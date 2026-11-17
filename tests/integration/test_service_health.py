"""Startup and health checks for both services. Skipped until a service exists."""

import httpx
import pytest


@pytest.mark.anyio
async def test_sanitization_liveness(sanitization_client: httpx.AsyncClient) -> None:
    response = await sanitization_client.get("/health/live")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_sanitization_readiness_is_ok_or_unavailable(
    sanitization_client: httpx.AsyncClient,
) -> None:
    response = await sanitization_client.get("/health/ready")
    assert response.status_code in (200, 503)


@pytest.mark.anyio
async def test_desanitization_liveness(desanitization_client: httpx.AsyncClient) -> None:
    response = await desanitization_client.get("/health/live")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_desanitization_readiness_is_ok_or_unavailable(
    desanitization_client: httpx.AsyncClient,
) -> None:
    response = await desanitization_client.get("/health/ready")
    assert response.status_code in (200, 503)
