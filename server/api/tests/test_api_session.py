"""Tests that a route's database work is committed before the answer is sent."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from titan_api.dependencies import Session

pytestmark = pytest.mark.anyio


@pytest.fixture
async def app(database: URL) -> AsyncIterator[FastAPI]:
    app = FastAPI()
    app.state.engine = create_async_engine(database)
    async with app.state.engine.begin() as connection:
        await connection.execute(text("CREATE TABLE probe (value text)"))
        await connection.execute(text("CREATE TABLE parent (id int PRIMARY KEY)"))
        await connection.execute(
            text(
                "CREATE TABLE child (id int REFERENCES parent (id)"
                " DEFERRABLE INITIALLY DEFERRED)"
            )
        )

    @app.post("/succeeds")
    async def succeeds(session: Session) -> None:
        await session.execute(text("INSERT INTO probe VALUES ('succeeds')"))

    @app.post("/raises")
    async def raises(session: Session) -> None:
        await session.execute(text("INSERT INTO probe VALUES ('raises')"))
        raise HTTPException(status_code=400)

    @app.post("/fails-at-commit")
    async def fails_at_commit(session: Session) -> None:
        await session.execute(text("INSERT INTO probe VALUES ('fails-at-commit')"))
        # The deferred foreign key is checked only when the transaction commits.
        await session.execute(text("INSERT INTO child VALUES (1)"))

    yield app
    async with app.state.engine.begin() as connection:
        await connection.execute(text("DROP TABLE probe, child, parent"))
    await app.state.engine.dispose()


async def call(app: FastAPI, path: str) -> int:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return (await client.post(path)).status_code


async def stored(app: FastAPI) -> list[str]:
    async with app.state.engine.connect() as connection:
        result = await connection.execute(text("SELECT value FROM probe"))
        return list(result.scalars())


async def test_a_route_that_returns_is_committed(app: FastAPI) -> None:
    assert await call(app, "/succeeds") == 200
    assert await stored(app) == ["succeeds"]


async def test_a_route_that_raises_is_rolled_back(app: FastAPI) -> None:
    assert await call(app, "/raises") == 400
    assert await stored(app) == []


async def test_a_failed_commit_is_not_answered_with_success(app: FastAPI) -> None:
    assert await call(app, "/fails-at-commit") == 500
    assert await stored(app) == []
