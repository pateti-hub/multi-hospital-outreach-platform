from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TriageRequest(BaseModel):
    patient_id: str
    transcript: str = Field(min_length=3, max_length=10_000)
    protocol_reference: str = Field(default="GENERAL-POST-DISCHARGE-v1")


class Assessment(BaseModel):
    assessor: str
    classification: Literal["routine", "concerning", "urgent", "uncertain"]
    indicators: list[str]
    evidence: list[str]
    protocol_reference: str
    confidence: float = Field(ge=0, le=1)
    escalate: bool


class TriageResult(BaseModel):
    patient_id: str
    assessments: list[Assessment]
    disagreement: bool
    final_classification: Literal["routine", "concerning", "urgent", "uncertain"]
    escalation_required: bool
    rationale: str


URGENT_TERMS = {
    "chest pain",
    "cannot breathe",
    "can't breathe",
    "unconscious",
    "severe bleeding",
    "stroke",
}
CONCERNING_TERMS = {
    "shortness of breath",
    "worsening",
    "fever",
    "dizzy",
    "missed medication",
    "swelling",
}
UNCERTAINTY_TERMS = {"not sure", "don't know", "confused", "cannot remember"}


def _matched(text: str, terms: set[str]) -> list[str]:
    return sorted(term for term in terms if term in text)


def assess(request: TriageRequest) -> TriageResult:
    """Conservative deterministic prototype of independent assessments."""
    text = request.transcript.lower()
    urgent = _matched(text, URGENT_TERMS)
    concerning = _matched(text, CONCERNING_TERMS)
    uncertain = _matched(text, UNCERTAINTY_TERMS)

    if urgent:
        rules_classification = "urgent"
    elif concerning:
        rules_classification = "concerning"
    elif uncertain or len(text.split()) < 5:
        rules_classification = "uncertain"
    else:
        rules_classification = "routine"

    # This second path deliberately uses different evidence weighting. In the
    # production design it can be a separately prompted/modelled classifier.
    if urgent:
        secondary_classification = "urgent"
    elif len(concerning) >= 2:
        secondary_classification = "urgent"
    elif concerning:
        secondary_classification = "concerning"
    elif uncertain:
        secondary_classification = "uncertain"
    else:
        secondary_classification = "routine"

    evidence = urgent + concerning + uncertain
    assessments = [
        Assessment(
            assessor="protocol_rule_engine",
            classification=rules_classification,
            indicators=evidence,
            evidence=[f"Transcript contains: {item}" for item in evidence],
            protocol_reference=request.protocol_reference,
            confidence=0.98 if urgent else 0.86,
            escalate=rules_classification != "routine",
        ),
        Assessment(
            assessor="independent_secondary_path",
            classification=secondary_classification,
            indicators=evidence,
            evidence=[f"Independent match: {item}" for item in evidence],
            protocol_reference=request.protocol_reference,
            confidence=0.9 if evidence else 0.78,
            escalate=secondary_classification != "routine",
        ),
    ]
    disagreement = rules_classification != secondary_classification
    severity = {"routine": 0, "uncertain": 1, "concerning": 2, "urgent": 3}
    final = max(
        (rules_classification, secondary_classification), key=lambda value: severity[value]
    )
    escalation_required = final != "routine" or disagreement
    return TriageResult(
        patient_id=request.patient_id,
        assessments=assessments,
        disagreement=disagreement,
        final_classification=final,
        escalation_required=escalation_required,
        rationale=(
            "Conservative consensus selects the highest-severity assessment; "
            "uncertainty or disagreement requires human review."
        ),
    )