# Security, Safety, and Known Limitations

## Implemented foundations

- signed bearer tokens with explicit role and hospital context;
- role checks and backend tenant enforcement;
- tenant identifiers on patient-domain tables;
- secrets supplied through environment configuration;
- synthetic records only;
- bounded, explainable queue decisions;
- audit/event models and idempotency fields.

## Required before real patient use

This is a prototype and **does not claim HIPAA, SOC 2, or production compliance**.
Before real PHI is used, it needs enterprise identity, MFA, key rotation, managed secret
storage, PostgreSQL row-level security, encryption and backup policies, retention and
deletion controls, immutable audit storage, vendor agreements, threat modeling,
penetration testing, incident response, clinical governance, validated protocols, and
formal safety review.

Logs must avoid transcripts and identifiers by default. Access to transcripts, clinical
content, exports, and platform aggregates must be separately authorized and audited.

## Intentional prototype tradeoffs

- demo authentication is disabled by default and is evaluation-only;
- the first milestone uses an in-memory deterministic queue simulator;
- hospital creation is not yet persisted;
- the mock EHR, event worker, notifications, retrieval, AI agents, UI, and deployment
  are subsequent milestones;
- no real telephony is required for the core queue demonstration;
- clinical scenarios are synthetic and do not establish medical correctness.