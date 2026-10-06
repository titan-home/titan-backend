"""titan-admin: commands run on the node itself, never over the API."""

import argparse

from alembic import command

from titan_server.db import alembic_config, database_url


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run the admin command it names."""
    parser = argparse.ArgumentParser(prog="titan-admin")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply every pending database migration")
    parser.parse_args(argv)

    command.upgrade(alembic_config(database_url()), "head")
