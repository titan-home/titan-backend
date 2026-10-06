"""titan-admin: commands run on the node itself, never over the API."""

import argparse
import asyncio
import sys
from getpass import getpass

from alembic import command
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.db import alembic_config, create_engine, database_url
from titan_server.domains.accounts.models.user import MAX_USERNAME_LENGTH
from titan_server.domains.accounts.owner import (
    MIN_PASSWORD_LENGTH,
    OwnerExistsError,
    PasswordTooShortError,
    UsernameInvalidError,
    create_owner,
)


class AdminError(Exception):
    """A problem to show to whoever runs titan-admin, without a traceback."""


def read_owner_credentials() -> tuple[str, str]:
    """Ask for the username and, without echo and twice, the password."""
    username = input("Username: ").strip()
    if not username:
        raise AdminError("The username must not be empty.")
    password = getpass("Password: ")
    if getpass("Repeat the password: ") != password:
        raise AdminError("The passwords do not match.")
    return username, password


async def save_owner(username: str, password: str) -> None:
    """Create the owner in the database and commit."""
    engine = create_engine()
    try:
        async with AsyncSession(engine) as session, session.begin():
            await create_owner(session, username, password)
    except OwnerExistsError:
        raise AdminError("An owner already exists; nothing was changed.") from None
    except UsernameInvalidError:
        raise AdminError(
            f"The username needs 1 to {MAX_USERNAME_LENGTH} characters."
        ) from None
    except PasswordTooShortError:
        raise AdminError(
            f"The password needs at least {MIN_PASSWORD_LENGTH} characters."
        ) from None
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run the admin command it names."""
    parser = argparse.ArgumentParser(prog="titan-admin")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply every pending database migration")
    # No password option on purpose: it would end up in the shell history and
    # the process list (accounts.md, create the owner, criterion 3).
    commands.add_parser("create-owner", help="create the owner account")
    arguments = parser.parse_args(argv)

    try:
        if arguments.command == "migrate":
            command.upgrade(alembic_config(database_url()), "head")
        else:
            username, password = read_owner_credentials()
            asyncio.run(save_owner(username, password))
            print(f"Created the owner {username}.")
    except AdminError as error:
        sys.exit(f"titan-admin: {error}")
