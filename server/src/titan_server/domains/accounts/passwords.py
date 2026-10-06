"""Password hashing with Argon2id (development rules, 11)."""

import unicodedata

import argon2

# Hashing a huge password is a cheap way to load the server; no real
# password comes near this.
MAX_PASSWORD_LENGTH = 1024

_PASSWORD_HASHER = argon2.PasswordHasher()
_EMPTY_HASH = _PASSWORD_HASHER.hash("")


def hash_password(password: str) -> str:
    """Return the Argon2id hash of password, with its salt and parameters."""
    normalized_password = unicodedata.normalize("NFKD", password)
    return _PASSWORD_HASHER.hash(normalized_password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Tell whether password matches password_hash; None means no such user.

    For None the answer is False, but only after hashing the password like for
    a real user, so the time of the answer does not tell whether a username
    exists (accounts.md, sign in, criterion 2).
    """
    try:
        normalized_password = unicodedata.normalize("NFKD", password)
        if password_hash is not None:
            return _PASSWORD_HASHER.verify(password_hash, normalized_password)
        else:
            _PASSWORD_HASHER.verify(_EMPTY_HASH, normalized_password)
            return False
    except argon2.exceptions.VerifyMismatchError:
        return False
