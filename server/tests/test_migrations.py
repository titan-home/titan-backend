"""Tests that the migrations build the schema the models describe."""

from alembic import command
from sqlalchemy.engine import URL

from titan_server.db import alembic_config


def test_migrations_match_the_models(database: URL) -> None:
    # Fails when a model changed without a migration (or the other way round).
    command.check(alembic_config(database))
