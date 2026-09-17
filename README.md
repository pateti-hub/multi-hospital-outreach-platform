# Multi-Hospital Post-Discharge Outreach Platform

Public prototype for the Full Stack AI Engineer challenge. It coordinates
tenant-isolated discharge ingestion, campaigns, a capacity-aware outreach queue,
simulated calls, conservative clinical triage, human escalation, documentation,
and mock EHR updates.

> **Prototype only.** Synthetic data only; not approved for real patient care.
> This project does not claim HIPAA, SOC 2, or clinical certification.

## Implemented prototype foundation

- PostgreSQL-oriented healthcare and operations data model
- JWT demo authentication, RBAC, and backend tenant enforcement
- explainable queue priority scoring, deadline pressure, aging, and retry backoff
- deterministic 30-patient capacity-constrained queue simulation
- campaign lifecycle validation and operational queue metrics
- responsive operations console for campaigns, queue, patients, escalations and audit
- structured conservative triage with two independent assessment paths
- prompt-injection-resistant protocol red flags and human escalation
- controlled mock EHR observation writes and auditable workflow actions
- repeatable safety evaluation with confusion matrix and false-negative rate
- reviewer assignment, review, resolution, and patient operational timelines
- campaign workload estimates and a reproducible 240-patient synthetic feed generator
- Railway deployment configuration and health checks
- versioned hospital protocols, tenant-aware retrieval and AI usage tracing
- separated intake, triage, escalation-consensus, and documentation workflow
- idempotent persistent call records and background escalation notifications
- architecture, queue, and security documentation
- repeatable unit tests

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Operations console: `http://localhost:8000/`

API documentation: `http://localhost:8000/docs`

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
uvicorn outreach.main:app --reload
```

Demo authentication is deliberately evaluation-only. Set
`DEMO_AUTH_ENABLED=true`, request a short-lived token from
`POST /api/v1/auth/demo-token`, and use it as a bearer token.

## Design documents

- [Architecture](docs/ARCHITECTURE.md)
- [Queue design](docs/QUEUE_DESIGN.md)
- [Security and limitations](docs/SECURITY_AND_LIMITATIONS.md)
- [Data model](docs/DATA_MODEL.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Evaluator demo](docs/DEMO_GUIDE.md)
- [Knowledge and retrieval](docs/KNOWLEDGE_AND_RETRIEVAL.md)
- [Conversation and documentation workflow](docs/CONVERSATION_WORKFLOW.md)