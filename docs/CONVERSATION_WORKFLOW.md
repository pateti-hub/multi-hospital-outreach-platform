# Controlled Conversation and Documentation Workflow

The prototype exposes `POST /api/v1/conversations/simulate` so evaluators can run
the complete clinical-AI workflow without depending on a telephony provider.
Inputs and records are synthetic only.

## Responsibility boundaries

1. **Voice intake** verifies identity and consent, detects callback requests,
   captures bounded symptom statements, and records incomplete interactions.
2. **Clinical triage** produces a validated structured result against the
   selected hospital protocol.
3. **Escalation consensus** combines independent rule and evidence assessments.
   Uncertainty or disagreement is escalated conservatively.
4. **Documentation** creates a structured summary, observations, protocol
   references, follow-up actions, and review status.

The workflow produces requested actions, not direct database commands. The
backend validates tenant access, patient existence, outreach state, and
idempotency before it records a call, writes a mock EHR Communication resource,
or creates an escalation.

## Reliability and observability

- An idempotency key prevents duplicate call records and side effects.
- Each agent stage writes a separate AI-usage trace.
- The final action and outcome are written to the audit trail.
- Escalations are converted into idempotent dashboard notifications by a
  persistent background worker.
- Callback requests enter `callback_scheduled`; completed and escalated calls
  release their queue lease.
- A clinical escalation always takes precedence over a callback request.

## Safety constraints

The workflow does not diagnose, prescribe, change medication, or override
hospital rules. Patient text is treated as untrusted evidence and cannot alter
authorization or safety policy. Missing consent, incomplete information,
protocol red flags, and assessment disagreement use conservative escalation.

## Example

```json
{
  "idempotency_key": "demo-conversation-001",
  "patient_id": "<tenant patient UUID>",
  "transcript": "I have severe chest pain and cannot breathe.",
  "identity_verified": true,
  "consent_to_continue": true,
  "protocol_reference": "GENERAL-POST-DISCHARGE-v1"
}
```