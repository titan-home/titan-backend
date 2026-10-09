"""Tests for the health endpoint."""

import httpx
import pytest

from titan_api.app import create_app


@pytest.mark.anyio
async def test_health_answers_ok() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_not_in_the_contract() -> None:
    assert "/health" not in create_app().openapi()["paths"]
