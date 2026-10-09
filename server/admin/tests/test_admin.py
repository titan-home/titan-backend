"""Tests for titan-admin create-owner (accounts.md, create the owner, criteria 1, 3)."""

import pytest

from titan_admin import main as admin


def answers(monkeypatch: pytest.MonkeyPatch, username: str, *passwords: str) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: username)
    replies = iter(passwords)
    monkeypatch.setattr(admin, "getpass", lambda prompt: next(replies))


def test_asks_for_the_username_and_twice_for_the_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers(monkeypatch, " owner ", "correct horse", "correct horse")

    assert admin.read_owner_credentials() == ("owner", "correct horse")


def test_refuses_passwords_that_do_not_match(monkeypatch: pytest.MonkeyPatch) -> None:
    answers(monkeypatch, "owner", "correct horse", "correct hose")

    with pytest.raises(admin.AdminError):
        admin.read_owner_credentials()


def test_refuses_an_empty_username(monkeypatch: pytest.MonkeyPatch) -> None:
    answers(monkeypatch, "  ", "correct horse", "correct horse")

    with pytest.raises(admin.AdminError):
        admin.read_owner_credentials()


def test_there_is_no_password_option() -> None:
    # Criterion 3: a password on the command line ends up in the shell history.
    with pytest.raises(SystemExit) as exit_info:
        admin.main(["create-owner", "--password", "correct horse"])

    assert exit_info.value.code == 2


def test_never_prints_the_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Criterion 3.
    answers(monkeypatch, "owner", "correct horse", "correct horse")

    async def save_owner(username: str, password: str) -> None:
        pass

    monkeypatch.setattr(admin, "save_owner", save_owner)
    admin.main(["create-owner"])

    output = capsys.readouterr()
    assert "owner" in output.out
    assert "correct horse" not in output.out + output.err
