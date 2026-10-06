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

Build-plan stage 1 has started: the workspace skeleton and a health endpoint.
See the [build plan](shared/docs/roadmap/plan.md).

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

## Getting the code

```sh
git clone --recurse-submodules https://github.com/titan-home/titan-backend.git
# after a pull:
git submodule update --init
```

## Licence

Released into the public domain under [the Unlicense](LICENSE).
