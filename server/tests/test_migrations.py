"""Tests that the migrations build the schema the models describe."""

import uuid

import psycopg
from alembic import command
from sqlalchemy.engine import URL

from titan_server.db import alembic_config


def test_migrations_match_the_models(database: URL) -> None:
    # Fails when a model changed without a migration (or the other way round).
    command.check(alembic_config(database))


def test_entries_written_before_domains_are_in_tasks(
    unmigrated_database: URL,
) -> None:
    """Every tool before decision #119 was a tasks tool."""
    config = alembic_config(unmigrated_database)
    # The revision before audit entries kept their domain.
    command.upgrade(config, "7d3ba96d93ef")
    user_id, entry_id = uuid.uuid4(), uuid.uuid4()
    libpq = unmigrated_database.set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    with psycopg.connect(libpq) as connection:
        connection.execute(
            "INSERT INTO users (id, username, password_hash, is_owner)"
            " VALUES (%s, 'owner', 'hash', true)",
            (user_id,),
        )
        connection.execute(
            "INSERT INTO audit_entries"
            " (id, user_id, tool, summary, mode, action_class, status, input)"
            " VALUES (%s, %s, 'create_task', 'Creating a task: Buy milk',"
            " 'auto-undo', 'write-internal', 'done', '{}')",
            (entry_id, user_id),
        )

    command.upgrade(config, "head")

    with psycopg.connect(libpq) as connection:
        row = connection.execute(
            "SELECT domain FROM audit_entries WHERE id = %s", (entry_id,)
        ).fetchone()
    assert row == ("tasks",)
