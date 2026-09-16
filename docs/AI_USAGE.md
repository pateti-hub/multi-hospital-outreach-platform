# AI Architecture and Usage

## Separation of responsibilities

1. **Voice Intake** follows a versioned protocol and captures patient-reported facts.
2. **Clinical Triage** transforms only relevant conversation evidence into a validated schema.
3. **Escalation Assessors** use independent reasoning paths.
4. **Consensus** selects the highest-severity result and escalates disagreement or uncertainty.
5. **Documentation** produces a structured summary for a controlled mock EHR operation.

The current public prototype implements deterministic versions of triage, two assessment
paths, conservative consensus, and structured documentation. This keeps the safety
evaluation reproducible without relying on an external model.

## Controlled tool boundary

AI-requested operations follow:

```text
request → authentication → tenant authorization → schema validation
→ business rules → idempotency check → execution → audit → result
```

Agents never receive SQL access. Patient content and retrieved documents are treated as
untrusted evidence and cannot override authorization, escalation rules, or system policy.

## Provider abstraction

Production adapters should expose separate interfaces for conversation generation,
structured generation, classification, retrieval, speech-to-text, and text-to-speech.
Every invocation should record provider, model, prompt version, purpose, latency,
validation result, token usage, estimated cost, and retrieval references without placing
unnecessary patient content in logs.

## Failure behavior

Malformed structured output receives bounded schema repair. Repeated failure becomes an
explicit manual-review task. Timeouts, rate limits, missing protocol evidence, disagreement,
and low confidence fail conservatively toward human review.