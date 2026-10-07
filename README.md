# titan-backend

The TITAN backend: the HTTP API, the background worker, the agent with its built-in tools, and the `titan` CLI.

Part of TITAN, a self-hosted personal AI assistant, planner and tracker. The
product, architecture and rules shared by every TITAN repository are in the
`shared/` submodule ([titan-shared](shared/README.md)).

## Contents

- **api**: FastAPI; a chat turn is a LangGraph graph running the Claude Agent SDK with the node's tools; the autonomy policy and the audit log.
- **worker**: fires reminders, runs the morning plan and replanning, indexes notes for search.
- **Built-in tools**: one module per domain (tasks, calendar, reminders, notes and memory, trackers, notifications).
- **CLI** (`titan`): sign-in, chat, every domain, administration, over the HTTP API.
- **Database**: PostgreSQL with pgvector; migrations live here.

## Status

Build-plan stages 1 and 2 are done: the development stack, the owner,
`titan login` and `titan whoami`, and the agent end to end, where
`titan chat "add a task to buy milk"` streams the reply and the task is in
the database. Stage 3, the policy and the audit log, is next. See the
[build plan](shared/docs/roadmap/plan.md).

## Layout

| Folder | Package | Runs on |
|---|---|---|
| `server/` | `titan-server`: api, worker, domains, agent, admin commands | The node, in containers |
| `cli/` | `titan-cli`: the `titan` command | The owner's machines |

## Development

Needs [uv](https://docs.astral.sh/uv/). Then:

```sh
uv sync              # install both packages and the dev tools
uv run pytest        # tests
uv run titan --help  # the CLI
```

### Database tests

Tests that need PostgreSQL read `TITAN_TEST_DATABASE_URL`, a server where
they may create and drop databases; without it they are skipped (in CI they
fail instead). Each run creates a fresh database, applies every migration and
drops it at the end. A throwaway server in Docker:

```sh
docker run -d --name titan-test-db -p 127.0.0.1:55432:5432 \
  -e POSTGRES_PASSWORD=test pgvector/pgvector:0.8.6-pg18-trixie
export TITAN_TEST_DATABASE_URL=postgresql+psycopg://postgres:test@127.0.0.1:55432/postgres
uv run pytest
```

If Docker runs on another machine, forward the port over SSH first:
`ssh -N -L 55432:127.0.0.1:55432 <that machine>`.

### Migrations

Change the models, then let Alembic write the migration against a database
that is at the latest version, and read what it wrote:

```sh
export TITAN_DATABASE_URL=postgresql+psycopg://postgres:test@127.0.0.1:55432/<database>
uv run alembic revision --autogenerate -m "Added users and devices"
```

Migrations only go forward; there is no downgrade. The test
`test_migrations_match_the_models` fails when the models and the migrations
disagree.

### The stack

To run api and PostgreSQL in Docker, create the database password once, then
start the stack. The folder keeps the password private on the machine; the
file itself must be readable, because the containers run as another user.

For chat, the api also needs the OAuth token that `claude setup-token`
prints. `read -rs` takes it without echo and keeps it out of the shell
history; an empty file starts the stack without chat.

```sh
mkdir -m 700 .secrets
openssl rand -hex 32 > .secrets/db_password
chmod 644 .secrets/db_password
read -rs TOKEN && printf '%s\n' "$TOKEN" > .secrets/claude_token && unset TOKEN
chmod 644 .secrets/claude_token
docker compose up --build --wait
curl http://127.0.0.1:8000/health
```

`migrate` applies pending migrations before the api starts. To create the
owner, run the admin command in a one-off container; it asks for the username
and, twice and without echo, the password:

```sh
docker compose run --rm migrate titan-admin create-owner
```

`docker compose down` stops it; add `--volumes` to delete the database too.

### Talking to Claude

A chat turn runs Claude Code through the Agent SDK with the owner's
subscription ([decision #7](shared/docs/decisions/README.md#register)). The
api reads:

| Variable | What it is |
|---|---|
| `TITAN_CLAUDE_TOKEN_FILE` | A file holding the OAuth token that `claude setup-token` prints |
| `TITAN_STRONG_MODEL` | The model for conversation; `opus` unless set |
| `TITAN_DEFAULT_MAX_MESSAGE_LENGTH` | The longest chat message a user may send, in characters, unless the user set their own limit; 20000 unless set |

Claude Code starts with only the variables it needs, never the api's own
(`agent/clean_claude.py`). The regular tests never call Claude; they play
it with scripted replies.

## Getting the code

```sh
git clone --recurse-submodules https://github.com/titan-home/titan-backend.git
# after a pull:
git submodule update --init
```

## Licence

Released into the public domain under [the Unlicense](LICENSE).
