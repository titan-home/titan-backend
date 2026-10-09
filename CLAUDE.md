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

A package per process in one uv workspace ([decision #85](shared/docs/decisions/README.md#register)):
`server/core/` is `titan-core` (the database, the domains and the
migrations), `server/api/` is `titan-api` (the HTTP API and the agent),
`server/admin/` is `titan-admin` (the commands run on the node, the
migrations among them), and `cli/` is `titan-cli` (the `titan` command, an
HTTP client only). `titan-api` and `titan-admin` each depend on `titan-core`;
`titan-core` never imports either of them, and `titan-admin` never imports
`titan-api` (`server/core/tests/test_layers.py`). Each image installs only
its own package and the core. `titan-cli` never imports any server package.
Its API client in `cli/src/titan_cli/client/` is generated from the contract
([decision #93](shared/docs/decisions/README.md#register)); never edit it by hand.

| What | Command |
|---|---|
| Install everything for development | `uv sync` |
| Format, lint | `uv run ruff format .`, `uv run ruff check .` |
| Types | `uv run mypy` |
| Tests | `uv run pytest` |
| Run the CLI | `uv run titan` |
| Export the API contract into `titan-shared` | `uv run python -m titan_api.contract > ../titan-shared/contracts/openapi.json` |
| Regenerate the CLI's API client from `shared/contracts/` | `uv run openapi-python-client generate --meta none --fail-on-warning --path shared/contracts/openapi.json --config cli/openapi-client.yaml --output-path cli/src/titan_cli/client --overwrite` |
| Write a migration from the models | `uv run alembic revision --autogenerate -m "..."` |
| Start api and PostgreSQL (needs Docker) | `docker compose up --build --wait` |
| Create the owner in the running stack | `docker compose run --rm migrate titan-admin create-owner` |

Database tests need `TITAN_TEST_DATABASE_URL`; see the README. On the node,
`titan-admin migrate` applies migrations.

`compose.yaml` is the development stack, built from source; it needs the
database password in `.secrets/db_password` (see the README). The node's
own compose file lives in `titan-node`.

uv takes no package version younger than 14 days (`exclude-newer` in
`pyproject.toml`).

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
4. If the API changed: the contract check against `shared/contracts/` passes:
   `uv run pytest server/api/tests/test_contract.py`.
5. If a migration was added: it applies to a fresh database and to one at the
   previous version.
6. If a tool changed: its access-check and undo tests pass.
7. If Markdown or the `shared/` pointer changed:
   `python3 shared/scripts/check_links.py .` prints nothing.
8. If `Dockerfile` or `compose.yaml` changed: `docker compose up --build --wait`
   brings the stack up healthy.
