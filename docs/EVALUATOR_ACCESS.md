# Evaluator Access

Application: `https://multi-hospital-outreach-production.up.railway.app`

The console uses synthetic evaluation access. Switch hospitals in the header to
demonstrate tenant-scoped views. API documentation is available at `/docs`.

Request a short-lived API token with:

```http
POST /api/v1/auth/demo-token
Content-Type: application/json

{"hospital_slug":"mercy-general","role":"hospital_admin"}
```

Recommended order: overview, tenant switch, queue, campaigns, patients, conversation,
WebRTC session, escalation review, mock EHR, audit, safety evaluation, and system health.

Do not enter real patient information.