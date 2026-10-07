"""The connection to PostgreSQL, the base class of every table and migrations."""

import functools
import os
from pathlib import Path
from typing import Any

from alembic.config import Config
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    declared_attr,
    mapped_column,
)

MIGRATIONS = Path(__file__).parent / "migrations"


class Base(DeclarativeBase):
    """The base class of every table."""


# A column of an audited table: a change keeps its old value (decision #110)
active_history_mapped_column = functools.partial(mapped_column, active_history=True)


class Audited:
    """A table the audit log covers (decisions #108, #110).

    Adds the `version` counter that SQLAlchemy raises on every update. Every
    other column is declared with active_history_mapped_column, so a change
    keeps the old value even when it was never loaded; a test checks that
    none is missing.
    """

    version: Mapped[int] = active_history_mapped_column(server_default="1")

    @declared_attr.directive
    def __mapper_args__(cls: type[Base]) -> dict[str, Any]:
        return {"version_id_col": cls.__table__.c.version}


def database_url() -> URL:
    """Build the database URL from the environment.

    TITAN_DATABASE_URL has no password, for example
    `postgresql+psycopg://titan@db/titan`; the password is read from the file
    named by TITAN_DATABASE_PASSWORD_FILE (decision #77).
    """
    url = make_url(os.environ["TITAN_DATABASE_URL"])
    password_file = os.environ.get("TITAN_DATABASE_PASSWORD_FILE")
    if password_file:
        url = url.set(password=Path(password_file).read_text().strip())
    return url


def create_engine() -> AsyncEngine:
    """Connect to the database named by the environment."""
    return create_async_engine(database_url())


def alembic_config(url: URL) -> Config:
    """Alembic settings for migrating the database at url, without a config file."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.attributes["url"] = url
    return config
