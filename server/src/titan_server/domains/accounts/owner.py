"""Creating the owner: the first account, made on the node at install time."""

from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.domains.accounts.models import User

MIN_PASSWORD_LENGTH = 8


class OwnerExistsError(Exception):
    """An owner already exists; create-owner changes nothing."""


class UsernameInvalidError(Exception):
    """The username is empty or longer than MAX_USERNAME_LENGTH characters."""


class PasswordTooShortError(Exception):
    """The password is shorter than MIN_PASSWORD_LENGTH characters."""


async def create_owner(session: AsyncSession, username: str, password: str) -> User:
    """Add the owner with the hash of password to session and return it."""
    raise NotImplementedError
