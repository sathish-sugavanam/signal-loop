# Signal Loop

Signal Loop is a customer intelligence platform for product and engineering teams. It will preserve customer evidence, make that evidence searchable, and help teams understand what customers need before deciding what to build.

## Current stack

- Python and Django
- PostgreSQL
- Docker
- OpenAI APIs for conversational answers
- React for the frontend (deferred)

## Run locally

The local stack runs Django and PostgreSQL in Docker.

```sh
docker compose up --build
```

Once both services are ready, confirm the server is responding:

```sh
curl http://localhost:8000/health/
```

It returns:

```json
{"status":"ok"}
```

Stop the stack with `docker compose down`. The PostgreSQL data volume is retained. To remove it as well, run `docker compose down --volumes`.

## Development commands

Install the pinned Python dependencies and check the Django configuration:

```sh
uv sync
uv run python manage.py check
```

Dependencies are pinned in `pyproject.toml`; `uv.lock` records the full resolved dependency set.

The server foundation currently has no application models or migrations. The first schema discussion will determine the user and uploaded-file models before those are introduced. See [PLAN.md](PLAN.md) for the roadmap.
