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
the database. Stage 3, the policy and the audit log, is under way: every
tool call is in the audit log with what it changed and runs in the mode of
its action class, `titan policy` sets a user's own mode per domain, and
`titan approvals`, `titan approve` and `titan reject` decide the calls that
wait for approval, which expire when nobody decides them; `titan undo`
takes an action back from its audit entry, whose id `titan chat` prints
after a call that can be undone, and `titan log` lists the log, newest
first. See the [build plan](shared/docs/roadmap/plan.md).

## Layout

| Folder | Package | Runs on |
|---|---|---|
| `server/core/` | `titan-core`: the database, the domains and the migrations, shared by the server packages | The node, inside each image |
| `server/api/` | `titan-api`: the HTTP API and the agent | The node, in the `api` image |
| `server/admin/` | `titan-admin`: the commands run on the node, the migrations among them | The node, in the `admin` image |
| `cli/` | `titan-cli`: the `titan` command | The owner's machines |

## Development

Needs [uv](https://docs.astral.sh/uv/). Then:

```sh
uv sync              # install every package and the dev tools
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
(`server/api/src/titan_api/agent/clean_claude.py`). The regular tests never
call Claude; they play it with scripted replies.

### Paged lists

Lists, such as the approval requests, are paged by a cursor
([decision #124](shared/docs/decisions/README.md#register)); the api reads:

| Variable | What it is |
|---|---|
| `TITAN_DEFAULT_MAX_PAGE_SIZE` | The most items one page of a list holds; a larger `limit` is capped to it; 100 unless set |

### Approval requests

A call that waits for approval expires when nobody decides it in time, and
then never runs
([decision #125](shared/docs/decisions/README.md#register)). It is marked
expired, and its thread told, when it is next approved or rejected or when
its thread gets a new turn; until then the list leaves it out. The api reads:

| Variable | What it is |
|---|---|
| `TITAN_DEFAULT_APPROVAL_EXPIRY_HOURS` | How long a request waits, counted from when it was made, so a change applies to requests already waiting; 24 unless set |

### Password guessing

After 10 failed sign-ins within 15 minutes from one client address for one
username, that pair is refused with `429` and `Retry-After` for 15 minutes
from the 10th failure, then starts with a clean count; other addresses and
other accounts are not affected ([decision #27](shared/docs/decisions/README.md#register)). The
count lives in the api's memory, so it starts over when the api restarts.
The client address is the connection's, or `X-Forwarded-For` when the
connection comes from one of our own proxies. The api reads:

| Variable | What it is |
|---|---|
| `TITAN_TRUSTED_PROXIES` | Our own proxies, such as the node's nginx: addresses or networks, comma-separated, for example the node's nginx at `172.31.250.2`; trust single addresses rather than whole networks, so no other container can claim a client's address; empty or unset trusts none. An entry that is not an address or network stops the api from starting |

The development stack sets none: it has no proxy in front of the api.

## Images

CI publishes two images, one per process, when a version tag `vX.Y.Z`, or a
pre-release such as `vX.Y.Z-rc.1`, is pushed; the image tag drops the `v`:

| Image | Dockerfile target | Runs |
|---|---|---|
| `ghcr.io/titan-home/titan-api` | `api` | the HTTP API and the agent |
| `ghcr.io/titan-home/titan-admin` | `admin` | `titan-admin`: the migrations, creating the owner |

Each is built for `linux/amd64`, with an attestation that it was built from
the tagged commit by this repository's workflow
([decisions #143–#147](shared/docs/decisions/README.md#register)); a pull
request only builds them. Nodes pull them by digest and never build them. To
check an image's origin, with the digest from the workflow's summary:

```sh
gh attestation verify oci://ghcr.io/titan-home/<image>@sha256:<digest> \
  --repo titan-home/titan-backend \
  --signer-workflow titan-home/titan-backend/.github/workflows/images.yml \
  --source-ref refs/tags/<tag> --source-digest <commit> \
  --deny-self-hosted-runners
```

## Getting the code

```sh
git clone --recurse-submodules https://github.com/titan-home/titan-backend.git
# after a pull:
git submodule update --init
```

## Licence

Released into the public domain under [the Unlicense](LICENSE).
