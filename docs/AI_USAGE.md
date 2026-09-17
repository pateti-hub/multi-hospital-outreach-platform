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

`outreach.providers` defines provider-neutral interfaces for structured generation and
speech, a deterministic provider, and a bounded circuit breaker. Production adapters can
implement conversation generation, classification, speech-to-text, and text-to-speech
without changing clinical policy or authorization logic.

The deployed voice boundary uses a PHI-minimized Pipecat/Daily WebRTC session request.
Only the opaque outreach task reference is sent to the voice service; patient details remain
behind the authorized application API.
Every invocation should record provider, model, prompt version, purpose, latency,
validation result, token usage, estimated cost, and retrieval references without placing
unnecessary patient content in logs.

## Failure behavior

Malformed structured output receives bounded schema repair. Repeated failure becomes an
explicit manual-review task. Timeouts, rate limits, missing protocol evidence, disagreement,
and low confidence fail conservatively toward human review.