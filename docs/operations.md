# Operations

## Environment

Copy `.env.example` to `.env` before Compose startup. Change
`API_KEY_SALT` and `WORKSPACE_SESSION_SECRET` outside local development.
`LLM_API_KEY`, `LLM_BASE_URL`, `EMBEDDING_API_KEY`, and
`EMBEDDING_BASE_URL` are only needed by the corresponding evaluators.

Important settings include:

- `DATABASE_URL`: SQLAlchemy URL for PostgreSQL or SQLite.
- `REDIS_URL`: Celery broker/backend URL.
- `TRACE_MAX_FIELD_BYTES`: maximum inline trace field size.
- `TRACE_REDACTION_FIELD_NAMES`: JSON array of sensitive field names when
  loaded from an environment file.
- `WORKER_MAX_CONCURRENCY`: upper bound for worker concurrency.

## Start and stop

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
docker compose -f infra/docker-compose.yml up -d --build --wait
docker compose -f infra/docker-compose.yml ps
docker compose -f infra/docker-compose.yml logs -f api worker
docker compose -f infra/docker-compose.yml down
```

The API and Worker run `alembic upgrade head`. To inspect or apply a migration
manually:

```powershell
docker compose -f infra/docker-compose.yml exec api alembic current
docker compose -f infra/docker-compose.yml exec api alembic upgrade head
python -m alembic current
python -m alembic upgrade head
```

## Health checks

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health
Invoke-WebRequest http://127.0.0.1:8101/docs
Invoke-WebRequest http://127.0.0.1:8102/docs
Invoke-WebRequest http://127.0.0.1:8103/docs
docker compose -f infra/docker-compose.yml ps
```

## Troubleshooting

If API is unhealthy, inspect `docker compose ... logs api postgres redis` and
check that the database URL uses service name `postgres` and the Redis URL uses
service name `redis`. If the API starts but project requests return 404, verify
the project has been seeded; health only checks process availability.

If a run stays queued, inspect Worker logs and verify Redis connectivity. If an
agent case fails with `connection_error`, use an endpoint reachable from the
API container. If it fails with `protocol_error`, confirm the response is JSON
and includes `output`.

If a gate is `incomplete` or `indeterminate`, inspect the report for queued,
missing, not-run, or evaluator-error samples. These states are intentionally
not passing results.

For a clean local reset, stop Compose and remove its named volume:

```powershell
docker compose -f infra/docker-compose.yml down -v
docker compose -f infra/docker-compose.yml up -d --build --wait
```

This deletes local demo data. Do not use `-v` against a deployment database.
