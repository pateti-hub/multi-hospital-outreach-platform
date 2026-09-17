# Requirements Traceability

This maps the challenge requirements to the deployed synthetic prototype.
“Implemented” does not mean clinically certified.

| Area | Prototype evidence | Status |
|---|---|---|
| Multi-tenancy and RBAC | signed identities, hospital context, backend authorization | Implemented |
| Hospital configuration | timezone, calling window, contacts and capacity | Implemented |
| Healthcare data | Patient, Encounter, Discharge, Protocol and EHR-shaped records | Implemented |
| Discharge ingestion | validated, explainable and idempotent batch API | Implemented |
| Campaigns | lifecycle, controls and workload estimate | Implemented |
| Queue | risk/deadline scoring, fairness, callbacks and retry backoff | Implemented |
| Concurrency | tenant advisory lock, leases and `SKIP LOCKED` | Implemented |
| Recovery | stale lease, expired window and manual follow-up handling | Implemented |
| Simulation | 30 mixed patients with constrained capacity | Implemented |
| Background work | separately deployable autonomous multi-tenant worker runtime | Implemented |
| AI architecture | intake, triage, two assessments, consensus and documentation | Implemented |
| Controlled tools | auth, validation, idempotency, execution and audit | Implemented |
| Escalations | assignment, review, resolution, evidence and notifications | Implemented |
| Mock EHR | validated replaceable adapter and structured writes | Implemented |
| Observability | health, metrics, AI traces, events and audit | Implemented |
| Safety evaluation | fixed dataset, confusion matrix and false-negative rate | Implemented |
| Provider abstraction | structured-AI/speech interfaces and circuit breaker | Implemented |
| Production auth path | optional Supabase bearer-token validation | Implemented |
| Streaming voice | Pipecat/Daily WebRTC gateway with expiring sessions | Implemented |
| PSTN outbound calls | requires a configured SIP/telephony account | Optional enhancement |
| Email/SMS | dashboard delivery; external adapters not configured | Optional enhancement |
| Real EHR | replaceable mock adapter | Intentionally mocked |
| Compliance | production security roadmap | Not claimed |

## Demonstrated journey

Hospital → discharge ingestion → campaign eligibility → priority queue → capacity
reservation → simulated call/conversation → structured triage → conservative consensus →
human escalation → documentation → mock EHR → notification → dashboard and audit.

## Real-patient boundary

Real use requires clinical validation, enterprise MFA, deployed database RLS, immutable
audit retention, encryption and backup policies, vendor agreements, incident response,
penetration testing, clinical governance, and formal privacy/compliance review.