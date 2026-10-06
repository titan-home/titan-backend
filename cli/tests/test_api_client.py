"""Tests that the generated API client matches shared/contracts/ (decision #93)."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
CLIENT = ROOT / "cli/src/titan_cli/client"
GENERATE = [
    *("openapi-python-client", "generate", "--meta", "none", "--fail-on-warning"),
    *("--path", "shared/contracts/openapi.json"),
    *("--config", "cli/openapi-client.yaml"),
]


def files(folder: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(folder)): path.read_bytes()
        for path in folder.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def test_the_client_is_generated_from_the_shared_contract(tmp_path: Path) -> None:
    # Inside a titan_cli package, so its imports become titan_cli.client.*.
    (tmp_path / "titan_cli").mkdir()
    (tmp_path / "titan_cli/__init__.py").touch()
    command = [*GENERATE, "--output-path", str(tmp_path / "titan_cli/client")]
    subprocess.run(  # noqa: S603  our own fixed command
        [sys.executable, "-m", "openapi_python_client", *command[1:]],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )

    assert files(tmp_path / "titan_cli/client") == files(CLIENT), (
        "The client differs from the contract; regenerate it with: uv run "
        + " ".join(
            [*GENERATE, "--output-path", "cli/src/titan_cli/client", "--overwrite"]
        )
    )
