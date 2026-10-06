"""The connection to PostgreSQL, the base class of every table and migrations."""

import os
from pathlib import Path

from alembic.config import Config
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase

MIGRATIONS = Path(__file__).parent / "migrations"


class Base(DeclarativeBase):
    """The base class of every table."""


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


def alembic_config(url: URL) -> Config:
    """Alembic settings for migrating the database at url, without a config file."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.attributes["url"] = url
    return config
