"""Tests for the titan command's entry point."""

import pytest

from titan_cli.main import main


def test_version_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == "0.1.0"


@pytest.mark.parametrize("command", ["approve", "reject"])
@pytest.mark.parametrize("approval_id", ["5d0c7a3e", "not-an-id"])
def test_an_approval_id_must_be_a_full_uuid(command: str, approval_id: str) -> None:
    """Decision #136: titan chat prints the full id, and only it is taken."""
    with pytest.raises(SystemExit) as exit_info:
        main([command, approval_id])

    assert exit_info.value.code == 2
