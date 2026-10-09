"""Tests that every error is answered as application/problem+json."""

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, SecretStr

from titan_api.problems import add_problem_handlers

pytestmark = pytest.mark.anyio


class Secret(BaseModel):
    password: SecretStr
    count: int


def make_app() -> FastAPI:
    app = FastAPI()
    add_problem_handlers(app)

    @app.get("/unauthorized")
    async def unauthorized() -> None:
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})

    @app.post("/secret")
    async def secret(body: Secret) -> None:
        pass

    return app


async def request(method: str, path: str, **kwargs: object) -> httpx.Response:
    transport = httpx.ASGITransport(app=make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)  # type: ignore[arg-type]


async def test_an_http_error_is_a_problem() -> None:
    response = await request("GET", "/unauthorized")

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "type": "about:blank",
        "title": "Unauthorized",
        "status": 401,
    }


async def test_an_unknown_path_is_a_problem() -> None:
    response = await request("GET", "/nowhere")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


async def test_invalid_input_names_the_fields_but_not_the_values() -> None:
    response = await request(
        "POST", "/secret", json={"password": ["hunter2-secret"], "count": "many"}
    )

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert "hunter2-secret" not in response.text
    assert "many" not in response.text
    fields = {error["field"] for error in response.json()["errors"]}
    assert fields == {"body.password", "body.count"}
