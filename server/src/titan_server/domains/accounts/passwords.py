"""Password hashing with Argon2id (development rules, 11)."""


def hash_password(password: str) -> str:
    """Return the Argon2id hash of password, with its salt and parameters."""
    raise NotImplementedError


def verify_password(password_hash: str | None, password: str) -> bool:
    """Tell whether password matches password_hash; None means no such user.

    For None the answer is False, but only after hashing the password like for
    a real user, so the time of the answer does not tell whether a username
    exists (accounts.md, sign in, criterion 2).
    """
    raise NotImplementedError
