from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from outreach.ingestion import DischargeImport, PatientName, evaluate_eligibility


def record(**overrides) -> DischargeImport:
    discharged = datetime.now(UTC) - timedelta(hours=2)
    values = {
        "external_patient_id": "SYN-IMPORT",
        "name": PatientName(given="Synthetic", family="Patient"),
        "phone": "+15551234567",
        "encounter_id": "ENC-1",
        "care_setting": "inpatient",
        "discharged_at": discharged,
        "follow_up_deadline": discharged + timedelta(hours=48),
        "condition_codes": ["Z48.81"],
        "discharge_instructions": "Use the approved discharge plan.",
        "risk": "moderate",
        "consent_for_outreach": True,
    }
    values.update(overrides)
    return DischargeImport(**values)


def test_eligible_discharge() -> None:
    assert evaluate_eligibility(record()) == (True, [])


def test_missing_consent_is_explainably_ineligible() -> None:
    eligible, reasons = evaluate_eligibility(record(consent_for_outreach=False))
    assert eligible is False
    assert reasons == ["outreach consent is not present"]


def test_deadline_must_follow_discharge() -> None:
    discharged = datetime.now(UTC)
    with pytest.raises(ValidationError):
        record(discharged_at=discharged, follow_up_deadline=discharged)
