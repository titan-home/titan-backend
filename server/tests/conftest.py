"""Shared pytest settings for the server tests: asyncio and a real PostgreSQL."""

import os
import secrets
from collections.abc import AsyncIterator, Iterator

import psycopg
import pytest
from alembic import command
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from titan_server.db import alembic_config


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Run async tests on asyncio only; the server never uses trio."""
    return "asyncio"


@pytest.fixture(scope="session")
def database() -> Iterator[URL]:
    """Create an empty database, migrate it to the latest version, drop it after.

    TITAN_TEST_DATABASE_URL points to a PostgreSQL server where the user may
    create databases, for example
    `postgresql+psycopg://postgres:test@127.0.0.1:55432/postgres`.
    """
    server = os.environ.get("TITAN_TEST_DATABASE_URL")
    if not server:
        if os.environ.get("CI"):
            pytest.fail("TITAN_TEST_DATABASE_URL is not set in CI")
        pytest.skip("database tests need TITAN_TEST_DATABASE_URL (see README)")
    server_url = make_url(server)
    name = f"titan_test_{secrets.token_hex(4)}"
    libpq = server_url.set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    with psycopg.connect(libpq, autocommit=True) as connection:
        connection.execute(f"CREATE DATABASE {name}")
    url = server_url.set(database=name)
    try:
        command.upgrade(alembic_config(url), "head")
        yield url
    finally:
        with psycopg.connect(libpq, autocommit=True) as connection:
            connection.execute(f"DROP DATABASE {name} WITH (FORCE)")


@pytest.fixture
async def session(database: URL) -> AsyncIterator[AsyncSession]:
    """A session whose changes are rolled back after the test."""
    engine = create_async_engine(database)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        yield AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
        await transaction.rollback()
    await engine.dispose()
