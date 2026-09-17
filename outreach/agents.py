from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from outreach.triage import TriageRequest, TriageResult, assess


class ConversationRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=160)
    patient_id: str
    transcript: str = Field(min_length=5, max_length=15_000)
    identity_verified: bool
    consent_to_continue: bool
    protocol_reference: str = "GENERAL-POST-DISCHARGE-v1"


class IntakeResult(BaseModel):
    disposition: Literal["completed", "declined", "callback_requested", "incomplete"]
    identity_verified: bool
    consent_to_continue: bool
    callback_requested: bool
    medication_concern: bool
    symptom_statements: list[str]
    unanswered_questions: list[str]


class DocumentationResult(BaseModel):
    summary: str
    patient_reported_symptoms: list[str]
    outreach_outcome: str
    triage_classification: str
    escalation_required: bool
    follow_up_actions: list[str]
    protocol_references: list[str]
    documentation_status: Literal["complete", "needs_human_review"]


class ConversationWorkflowResult(BaseModel):
    intake: IntakeResult
    triage: TriageResult
    documentation: DocumentationResult
    controlled_actions: list[str]


SYMPTOM_PHRASES = [
    "chest pain",
    "cannot breathe",
    "shortness of breath",
    "fever",
    "dizzy",
    "swelling",
    "severe bleeding",
    "worsening",
]


def run_conversation_workflow(request: ConversationRequest) -> ConversationWorkflowResult:
    """Run bounded intake, triage, consensus and documentation components."""
    text = request.transcript.lower()
    callback = "call me back" in text or "callback" in text
    medication_concern = "medication" in text or "medicine" in text
    symptoms = [phrase for phrase in SYMPTOM_PHRASES if phrase in text]

    if not request.identity_verified or not request.consent_to_continue:
        disposition = "declined"
    elif callback:
        disposition = "callback_requested"
    elif len(text.split()) < 5:
        disposition = "incomplete"
    else:
        disposition = "completed"

    intake = IntakeResult(
        disposition=disposition,
        identity_verified=request.identity_verified,
        consent_to_continue=request.consent_to_continue,
        callback_requested=callback,
        medication_concern=medication_concern,
        symptom_statements=symptoms,
        unanswered_questions=(
            ["Clinical reviewer clarification required"] if disposition == "incomplete" else []
        ),
    )

    triage_text = request.transcript
    if not request.identity_verified or not request.consent_to_continue:
        triage_text = (
            "Information is incomplete; clinical status is not sure because identity "
            "or consent was not confirmed."
        )
    triage = assess(
        TriageRequest(
            patient_id=request.patient_id,
            transcript=triage_text,
            protocol_reference=request.protocol_reference,
        )
    )

    actions = ["record_communication"]
    follow_up = []
    if callback:
        actions.append("schedule_callback")
        follow_up.append("Capture and honor the requested callback time.")
    if triage.escalation_required:
        actions.append("create_escalation")
        follow_up.append("Clinical reviewer assessment required.")
    actions.append("write_mock_ehr_documentation")

    summary = (
        f"Structured post-discharge outreach was {disposition}. "
        f"Triage classification: {triage.final_classification}. "
        f"Captured {len(symptoms)} protocol-relevant symptom statement(s)."
    )
    documentation = DocumentationResult(
        summary=summary,
        patient_reported_symptoms=symptoms,
        outreach_outcome=disposition,
        triage_classification=triage.final_classification,
        escalation_required=triage.escalation_required,
        follow_up_actions=follow_up,
        protocol_references=[request.protocol_reference],
        documentation_status=(
            "needs_human_review"
            if triage.escalation_required or triage.disagreement
            else "complete"
        ),
    )
    return ConversationWorkflowResult(
        intake=intake,
        triage=triage,
        documentation=documentation,
        controlled_actions=actions,
    )
