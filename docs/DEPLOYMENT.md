# Deployment

## Railway

The repository includes `railway.toml` and a root `Dockerfile`.

Required service variables:

```text
APP_SECRET=<random value of at least 24 characters; recommended>
DATABASE_URL=<Railway PostgreSQL asyncpg URL>
DEMO_AUTH_ENABLED=true
PERSISTENCE_ENABLED=true
ENVIRONMENT=production
```

Do not commit these values. The prototype dashboard requires evaluation-mode demo
authentication; a real deployment must replace it with enterprise identity and MFA.
When `APP_SECRET` is omitted, the application generates an ephemeral random signing key.
That is safe for a single prototype instance, but tokens are invalidated after every restart
and it must not be used for multi-replica deployments.

The health check is `/api/v1/health`. The container listens on port `8000`; Railway routes
its generated domain to the process. PostgreSQL tables are initialized for the prototype.
Managed migrations are required before production use.

## Local Docker

```bash
cp .env.example .env
docker compose up --build
```

Open `http://localhost:8000/` and API documentation at `http://localhost:8000/docs`.