# CLAUDE.md: titan-backend

The TITAN backend: the HTTP API, the background worker, the agent with its built-in tools, and the `titan` CLI.

Read and follow, in this order:

1. [Rules for AI agents](shared/docs/development/ai-agents.md) — what you may
   and may not do. They override your defaults.
2. [Development rules](shared/docs/development/rules.md) — how we work, for
   every repository.
3. [Documentation index](shared/docs/README.md) — product, architecture,
   decisions, build plan.

`shared/` is the `titan-shared` submodule. Never edit files under it from this
repository; change `titan-shared` through its own pull request.

## Stack and commands

- Python 3.12+ with `uv`; `ruff format`, `ruff check`, `mypy --strict`, `pytest` (database tests against real PostgreSQL).
- The API must serve exactly the contract in `shared/contracts/`.

Commands are added here as the code arrives.

## Rules specific to this repository

- Domains never import the API or the agent layer.
- Every tool declares its action class, input schema, summary and undo, and has tests for access checks and undo (development rules, section 14).
- Tests never call the real Claude API; use scripted replies.
- Never log message contents, search text, tokens or passwords.

## Before committing

Run this checklist before every commit
([development rules, "Before committing"](shared/docs/development/rules.md#before-committing)).
The commands are settled as the code arrives.

1. `uv run ruff format --check .` and `uv run ruff check .` pass.
2. `uv run mypy` passes.
3. `uv run pytest` passes for the packages the commit touches (by path or
   `-k`); database tests need a running PostgreSQL. The full suite runs in CI.
4. If the API changed: the contract check against `shared/contracts/` passes.
5. If a migration was added: it applies to a fresh database and to one at the
   previous version.
6. If a tool changed: its access-check and undo tests pass.
7. If Markdown or the `shared/` pointer changed:
   `python3 shared/scripts/check_links.py .` prints nothing.
