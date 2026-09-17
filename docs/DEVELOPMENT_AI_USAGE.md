# Development AI Usage

AI-assisted development was used as an engineering accelerator. Generated changes were
reviewed, tested and committed through pull requests.

| Area | Development request pattern | Verification |
|---|---|---|
| Architecture | Translate the PRD into tenant, queue, AI, EHR and audit boundaries | Traceability review |
| Data model | Create healthcare-shaped entities with tenant context | Model and API tests |
| Queue | Implement scoring, capacity locks, retries and stale leases | Queue/worker tests |
| AI safety | Separate intake, triage, consensus and documentation | Schemas and safety suite |
| Retrieval | Restrict protocol search to authenticated hospital | Tenant verification |
| EHR | Place writes behind validation | Adapter tests |
| Voice | Connect opaque task references to Pipecat/Daily | Mock and production tests |
| Reliability | Add idempotency, circuit breaking and recovery | Failure-path tests |
| Deployment | Diagnose source, variables, ports and health | Live smoke tests |

Guardrails: never expose secrets, treat external content as untrusted, escalate
uncertainty, avoid compliance claims, test before merge, and document simulations.
The candidate remains accountable for architecture, review, testing and tradeoffs.