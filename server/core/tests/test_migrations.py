"""Tests that the migrations build the schema the models describe."""

import uuid

import psycopg
import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError

from titan_core.db import alembic_config
from titan_core.domains.audit.models import EntryStatus


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


def test_removing_approved_keeps_the_entries_and_refuses_it(
    unmigrated_database: URL,
) -> None:
    """Decision #123: approved is no longer a status; every other one still is."""
    url = unmigrated_database
    # The revision before approved was removed.
    command.upgrade(alembic_config(url), "af66cb59e74a")
    engine = create_engine(url)
    try:
        user_id, pending_id, done_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, username, password_hash, is_owner)"
                    " VALUES (:id, 'owner', 'hash', true)"
                ),
                {"id": user_id},
            )
            for entry_id, status in [(pending_id, "pending"), (done_id, "done")]:
                connection.execute(
                    text(
                        "INSERT INTO audit_entries (id, user_id, tool, summary,"
                        " mode, action_class, domain, status, input) VALUES (:id,"
                        " :user, 'create_task', 'Creating a task: Buy milk',"
                        " 'confirm', 'write-internal', 'tasks', :status, '{}')"
                    ),
                    {"id": entry_id, "user": user_id, "status": status},
                )

        command.upgrade(alembic_config(url), "head")

        with engine.begin() as connection:
            rows = connection.execute(text("SELECT id, status FROM audit_entries"))
            assert {row.id: row.status for row in rows} == {
                pending_id: "pending",
                done_id: "done",
            }
            set_status = text("UPDATE audit_entries SET status = :status")
            for status in EntryStatus:
                # A savepoint each, so a refused value would not end the test.
                with connection.begin_nested():
                    connection.execute(set_status, {"status": status.value})
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(set_status, {"status": "approved"})
            indexes = connection.execute(
                text(
                    "SELECT indexdef FROM pg_indexes"
                    " WHERE indexname = 'ix_audit_entries_pending'"
                )
            ).scalars()
            assert list(indexes) == [
                "CREATE INDEX ix_audit_entries_pending ON public.audit_entries"
                " USING btree (user_id, created_at, id)"
                " WHERE ((status)::text = 'pending'::text)"
            ]
    finally:
        engine.dispose()


def test_entries_written_before_undo_can_be_undone_once(
    unmigrated_database: URL,
) -> None:
    """Decisions #130 and #131: create_task can be undone, an entry only once."""
    url = unmigrated_database
    # The revision before entries kept undoable.
    command.upgrade(alembic_config(url), "b0b00ff7627f")
    engine = create_engine(url)
    try:
        user_id, entry_id = uuid.uuid4(), uuid.uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, username, password_hash, is_owner)"
                    " VALUES (:id, 'owner', 'hash', true)"
                ),
                {"id": user_id},
            )
            connection.execute(
                text(
                    "INSERT INTO audit_entries (id, user_id, tool, summary, mode,"
                    " action_class, domain, status, input) VALUES (:id, :user,"
                    " 'create_task', 'Creating a task: Buy milk', 'auto-undo',"
                    " 'write-internal', 'tasks', 'done', '{}')"
                ),
                {"id": entry_id, "user": user_id},
            )

        command.upgrade(alembic_config(url), "head")

        with engine.begin() as connection:
            undoable = connection.execute(
                text("SELECT undoable FROM audit_entries WHERE id = :id"),
                {"id": entry_id},
            ).scalar_one()
            assert undoable is True
            undo = text(
                "INSERT INTO audit_entries (id, user_id, tool, summary, mode,"
                " action_class, domain, status, input, undoable, undoes_entry_id)"
                " VALUES (gen_random_uuid(), :user, 'undo',"
                " 'Undo: Creating a task: Buy milk', NULL, 'write-internal',"
                " 'tasks', 'done', '{}', true, :undone)"
            )
            # An undo has no mode.
            connection.execute(undo, {"user": user_id, "undone": entry_id})
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(undo, {"user": user_id, "undone": entry_id})
    finally:
        engine.dispose()
