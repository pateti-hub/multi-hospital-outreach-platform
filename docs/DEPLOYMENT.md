# Deployment

## Railway

The repository includes `railway.toml` and a root `Dockerfile`.

Required service variables:

```text
APP_SECRET=<random value of at least 24 characters; recommended>
DATABASE_URL=<Railway PostgreSQL asyncpg URL>
DEMO_AUTH_ENABLED=true
PERSISTENCE_ENABLED=true
BACKGROUND_WORKERS_ENABLED=true
AUTO_QUEUE_ENABLED=true
ENVIRONMENT=production
```

Optional Supabase authentication:

```text
SUPABASE_AUTH_ENABLED=true
SUPABASE_URL=<project URL>
SUPABASE_ANON_KEY=<public anonymous key>
VOICE_SERVICE_URL=<Pipecat/Daily voice service URL>
```

Do not commit these values. Supabase authorization reads only administrator-controlled
`app_metadata.role` and `app_metadata.hospital_id`; user-editable metadata is ignored.
Evaluation-mode demo authentication should be disabled outside a synthetic evaluation.
When `APP_SECRET` is omitted, the application generates an ephemeral random signing key.
That is safe for a single prototype instance, but tokens are invalidated after every restart
and it must not be used for multi-replica deployments.

The health check is `/api/v1/health`. The container listens on port `8000`; Railway routes
its generated domain to the process. PostgreSQL tables are initialized for the prototype.
Managed migrations are required before production use.

Standard Supabase `postgresql://` and legacy `postgres://` connection strings are normalized
to SQLAlchemy's asyncpg driver. `sslmode=require` is also normalized to asyncpg's `ssl`
parameter. `DATABASE_URL` is required for persistence. Supabase URL and anonymous key
are used only when external token validation is explicitly enabled.

## Local Docker

```bash
cp .env.example .env
docker compose up --build
```

Open `http://localhost:8000/` and API documentation at `http://localhost:8000/docs`.

## Separate queue worker

For independently scalable execution, deploy the same repository as a second Railway
service using `Dockerfile.worker`. Give it the same `DATABASE_URL` and set:

```text
PERSISTENCE_ENABLED=true
BACKGROUND_WORKERS_ENABLED=true
AUTO_QUEUE_ENABLED=true
WORKER_INTERVAL_SECONDS=30
```

On the API service set `BACKGROUND_WORKERS_ENABLED=false` and
`AUTO_QUEUE_ENABLED=false`. PostgreSQL advisory locks, row leases, and idempotency
still protect against duplicate execution when worker replicas overlap.