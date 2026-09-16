from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from outreach.enums import RiskLevel


class PatientName(BaseModel):
    given: str = Field(min_length=1, max_length=100)
    family: str = Field(min_length=1, max_length=100)


class DischargeImport(BaseModel):
    external_patient_id: str = Field(min_length=1, max_length=120)
    name: PatientName
    phone: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    encounter_id: str = Field(min_length=1, max_length=120)
    care_setting: str = Field(min_length=2, max_length=80)
    discharged_at: datetime
    follow_up_deadline: datetime
    condition_codes: list[str] = Field(min_length=1, max_length=20)
    discharge_instructions: str = Field(min_length=3, max_length=5_000)
    medication_summary: list[str] = Field(default_factory=list, max_length=30)
    risk: RiskLevel
    consent_for_outreach: bool
    preferred_language: str = Field(default="en", max_length=20)

    @field_validator("follow_up_deadline")
    @classmethod
    def deadline_after_discharge(cls, value: datetime, info) -> datetime:
        discharged_at = info.data.get("discharged_at")
        if discharged_at and value <= discharged_at:
            raise ValueError("follow_up_deadline must be after discharged_at")
        return value


class DischargeBatch(BaseModel):
    records: list[DischargeImport] = Field(min_length=1, max_length=500)


def evaluate_eligibility(record: DischargeImport) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not record.consent_for_outreach:
        reasons.append("outreach consent is not present")
    if record.follow_up_deadline <= datetime.now(record.follow_up_deadline.tzinfo):
        reasons.append("clinical follow-up window has expired")
    return not reasons, reasons
