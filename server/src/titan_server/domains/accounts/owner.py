"""Creating the owner: the first account, made on the node at install time."""

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.domains.accounts.models import User
from titan_server.domains.accounts.models.user import MAX_USERNAME_LENGTH
from titan_server.domains.accounts.passwords import hash_password

MIN_PASSWORD_LENGTH = 8


class OwnerExistsError(Exception):
    """An owner already exists; create-owner changes nothing."""


class UsernameInvalidError(Exception):
    """The username is empty or longer than MAX_USERNAME_LENGTH characters."""


class PasswordTooShortError(Exception):
    """The password is shorter than MIN_PASSWORD_LENGTH characters."""


async def create_owner(session: AsyncSession, username: str, password: str) -> User:
    """Add the owner with the hash of password to session and return it."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordTooShortError

    username = username.strip()
    if not username or (len(username) > MAX_USERNAME_LENGTH):
        raise UsernameInvalidError

    if await session.scalar(select(exists().where(User.is_owner))):
        raise OwnerExistsError

    created_owner = User(
        username=username, password_hash=hash_password(password), is_owner=True
    )
    session.add(created_owner)
    return created_owner
