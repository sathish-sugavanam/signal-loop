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

The server foundation currently has no application models or migrations. Compose deliberately does not run migrations, so the user and uploaded-file models can be designed before Django creates any schema. See [PLAN.md](PLAN.md) for the roadmap.

## Agents

The agent harness in `agents/` runs three services next to the product: `agent-webhook` receives Linear webhooks into the `inbox_events` table, and the Celery `agent-worker` and `agent-beat` pick pending tasks from that table. They use their own `agents` database on the same PostgreSQL server, plus Redis as the Celery broker.

### First-time setup

1. Create the env file and fill in `LINEAR_WEBHOOK_SECRET` and the password in `DATABASE_URL`:

   ```sh
   cp agents/.env.example agents/.env
   ```

2. Start PostgreSQL and create the agents login and database. Use the same password as in `DATABASE_URL`:

   ```sh
   docker compose up -d db
   docker compose exec db psql -U signal_loop -d postgres \
     -c "CREATE ROLE agents LOGIN PASSWORD 'CHANGE_ME'" \
     -c "CREATE DATABASE agents OWNER agents"
   ```

3. Apply every migration, in order:

   ```sh
   for f in agents/migrations/*.sql; do
     docker compose exec -T db psql -U agents -d agents -v ON_ERROR_STOP=1 < "$f"
   done
   ```

4. Start the agent services:

   ```sh
   docker compose up -d --build agent-webhook agent-worker agent-beat
   ```

### Migrations

Migrations are plain SQL files in `agents/migrations/`, named `NNNN_description.sql` with a number that is never reused (`0001_inbox_events.sql`, `0002_...`). Nothing applies them automatically. Run each new file once, in number order:

```sh
docker compose exec -T db psql -U agents -d agents -v ON_ERROR_STOP=1 < agents/migrations/0002_example.sql
```

### Tests

```sh
cd agents
uv run pytest
```

The PostgreSQL integration tests are skipped unless `AGENTS_TEST_ADMIN_URL` points at a superuser login, for example with the Compose database running:

```sh
AGENTS_TEST_ADMIN_URL=postgresql://signal_loop:signal_loop@localhost:5432/postgres uv run pytest
```
