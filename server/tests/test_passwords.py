"""Tests for password hashing (accounts.md, create the owner, criterion 2)."""

import argon2
import pytest

from titan_server.domains.accounts.passwords import hash_password, verify_password


def test_the_hash_is_argon2id_and_not_the_password() -> None:
    password_hash = hash_password("correct horse")

    assert password_hash.startswith("$argon2id$")
    assert "correct horse" not in password_hash


def test_the_same_password_hashes_differently_each_time() -> None:
    # A random salt in every hash: equal passwords cannot be spotted.
    assert hash_password("correct horse") != hash_password("correct horse")


def test_verify_accepts_the_right_password_only() -> None:
    password_hash = hash_password("correct horse")

    assert verify_password(password_hash, "correct horse")
    assert not verify_password(password_hash, "wrong horse")


def test_an_unknown_user_is_refused_after_the_same_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Sign in, criterion 2: no early answer for a username that does not exist.
    # Time itself is not measured (rules, 8); the test checks that Argon2 ran.
    calls = []
    real_verify = argon2.PasswordHasher.verify

    def counting_verify(
        self: argon2.PasswordHasher, password_hash: str, password: str
    ) -> bool:
        calls.append(password_hash)
        return real_verify(self, password_hash, password)

    monkeypatch.setattr(argon2.PasswordHasher, "verify", counting_verify)

    assert not verify_password(None, "correct horse")
    assert len(calls) == 1
    assert calls[0].startswith("$argon2id$")
