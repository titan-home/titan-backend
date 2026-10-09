"""Tests that the packages depend on each other only in the allowed direction.

In development every package is installed, so a wrong import would still
work here; this test catches it before an image that lacks the package does.
"""

import ast
import importlib.util
from pathlib import Path

# The api's own third-party packages: the admin image has none of them.
API_PACKAGES = ("fastapi", "starlette", "uvicorn", "claude_agent_sdk")


def package_folder(name: str) -> Path:
    """Find where a package lives without importing it."""
    spec = importlib.util.find_spec(name)
    assert spec is not None and spec.origin is not None, f"{name} is not installed"
    return Path(spec.origin).parent


def imported_modules(path: Path) -> set[str]:
    """Every module a Python file imports, read from its syntax tree."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def offenders(package: str, forbidden: tuple[str, ...]) -> list[str]:
    """Every import in a package of a top-level module it must not use."""
    folder = package_folder(package)
    return [
        f"{path.relative_to(folder)} imports {module}"
        for path in sorted(folder.rglob("*.py"))
        for module in imported_modules(path)
        if module.split(".")[0] in forbidden
    ]


def test_the_core_and_the_admin_commands_never_import_what_sits_above() -> None:
    assert offenders("titan_core", ("titan_api", "titan_admin", *API_PACKAGES)) == []
    assert offenders("titan_admin", ("titan_api", *API_PACKAGES)) == []
