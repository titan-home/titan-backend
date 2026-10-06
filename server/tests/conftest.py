"""Shared pytest settings for the server tests."""

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio only; the server never uses trio."""
    return "asyncio"
