"""Tests that the layers depend on each other only in the allowed direction."""

import ast
from pathlib import Path

import titan_server.domains

FORBIDDEN = ("titan_server.api", "titan_server.agent")


def imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_domains_never_import_the_api_or_the_agent() -> None:
    domains = Path(titan_server.domains.__file__).parent
    offenders = [
        f"{path.relative_to(domains)} imports {module}"
        for path in sorted(domains.rglob("*.py"))
        for module in imported_modules(path)
        if module.startswith(FORBIDDEN)
    ]

    assert offenders == []
