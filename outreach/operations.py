from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from outreach.enums import CampaignStatus, EscalationStatus, RiskLevel


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class OperationsStore:
    """Deterministic synthetic operational data for the deployed prototype."""

    hospitals: dict[str, dict] = field(default_factory=dict)
    campaigns: dict[str, dict] = field(default_factory=dict)
    patients: dict[str, dict] = field(default_factory=dict)
    escalations: dict[str, dict] = field(default_factory=dict)
    calls: list[dict] = field(default_factory=list)
    ehr_records: list[dict] = field(default_factory=list)
    audit_log: list[dict] = field(default_factory=list)
    events: dict[str, dict] = field(default_factory=dict)
    notifications: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.hospitals:
            return
        self._seed()

    def _seed(self) -> None:
        hospitals = [
            (
                "11111111-1111-4111-8111-111111111111",
                "mercy-general",
                "Mercy General Hospital",
                3,
            ),
            (
                "22222222-2222-4222-8222-222222222222",
                "riverside-medical",
                "Riverside Medical Center",
                4,
            ),
        ]
        for hospital_id, slug, name, capacity in hospitals:
            self.hospitals[hospital_id] = {
                "id": hospital_id,
                "slug": slug,
                "name": name,
                "timezone": "Asia/Kolkata",
                "calling_hours": {"start": "09:00", "end": "18:00"},
                "outbound_capacity": capacity,
                "status": "ready",
            }
            campaign_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{slug}:campaign"))
            self.campaigns[campaign_id] = {
                "id": campaign_id,
                "hospital_id": hospital_id,
                "name": "48-hour discharge follow-up",
                "description": "Medication, symptom, and follow-up check",
                "status": CampaignStatus.RUNNING.value,
                "eligible_patients": 15,
                "completed": 0,
                "priority_weight": 1.0,
                "retry_limit": 3,
                "clinical_window_hours": 48,
            }

        risks = list(RiskLevel)
        for index in range(30):
            hospital_id = hospitals[index % 2][0]
            patient_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"synthetic-patient:{index}"))
            risk = risks[index % len(risks)]
            discharged = datetime.now(UTC) - timedelta(hours=2 + index)
            self.patients[patient_id] = {
                "id": patient_id,
                "hospital_id": hospital_id,
                "external_id": f"SYN-{index + 1:04}",
                "display_name": f"Synthetic Patient {index + 1:02}",
                "phone": f"+1555000{index + 1:04}",
                "care_setting": "inpatient",
                "condition": ["Cardiac recovery", "Respiratory recovery", "General surgery"][
                    index % 3
                ],
                "risk": risk.value,
                "discharged_at": discharged.isoformat(),
                "follow_up_deadline": (discharged + timedelta(hours=48)).isoformat(),
                "communication_preference": "voice",
                "outreach_status": "pending",
            }

        patients = list(self.patients.values())
        outcomes = ["completed", "no_answer", "busy", "voicemail", "dropped", "callback"]
        for index, patient in enumerate(patients[:12]):
            campaign = next(
                item
                for item in self.campaigns.values()
                if item["hospital_id"] == patient["hospital_id"]
            )
            started_at = datetime.fromisoformat(patient["discharged_at"]) + timedelta(minutes=30)
            self.calls.append(
                {
                    "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"synthetic-call:{index}")),
                    "hospital_id": patient["hospital_id"],
                    "patient_id": patient["id"],
                    "campaign_id": campaign["id"],
                    "attempt": 1,
                    "outcome": outcomes[index % len(outcomes)],
                    "started_at": started_at.isoformat(),
                    "ended_at": (started_at + timedelta(minutes=4)).isoformat(),
                    "documentation_status": "complete",
                }
            )

        urgent_patient = next(
            patient for patient in self.patients.values() if patient["risk"] == "critical"
        )
        escalation_id = str(uuid.uuid4())
        self.escalations[escalation_id] = {
            "id": escalation_id,
            "hospital_id": urgent_patient["hospital_id"],
            "patient_id": urgent_patient["id"],
            "patient_name": urgent_patient["display_name"],
            "status": EscalationStatus.OPEN.value,
            "priority": "urgent",
            "trigger": "Patient reported worsening shortness of breath.",
            "evidence": ["worsening symptom", "protocol red flag"],
            "protocol_reference": "POST-DISCHARGE-CARDIAC-v1 §4.2",
            "consensus": {"rule_engine": "urgent", "secondary_assessor": "concerning"},
            "assigned_to": None,
            "created_at": now_iso(),
            "resolution": None,
        }
        self.publish_event(
            hospital_id=urgent_patient["hospital_id"],
            event_type="escalation.created",
            aggregate_id=escalation_id,
            payload={"priority": "urgent", "patient_id": urgent_patient["id"]},
            idempotency_key=f"seed-escalation:{escalation_id}",
        )

    def tenant_rows(self, rows: list[dict], hospital_id: uuid.UUID | None) -> list[dict]:
        if hospital_id is None:
            return rows
        return [row for row in rows if row.get("hospital_id") == str(hospital_id)]

    def record_audit(
        self,
        hospital_id: str,
        actor_id: uuid.UUID | None,
        action: str,
        resource_type: str,
        resource_id: str,
        details: dict | None = None,
    ) -> None:
        self.audit_log.append(
            {
                "id": str(uuid.uuid4()),
                "hospital_id": hospital_id,
                "actor_id": str(actor_id) if actor_id else "system",
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "details": details or {},
                "occurred_at": now_iso(),
            }
        )

    def publish_event(
        self,
        *,
        hospital_id: str,
        event_type: str,
        aggregate_id: str,
        payload: dict,
        idempotency_key: str,
    ) -> tuple[dict, bool]:
        existing = next(
            (
                event
                for event in self.events.values()
                if event["idempotency_key"] == idempotency_key
            ),
            None,
        )
        if existing:
            return existing, False
        event_id = str(uuid.uuid4())
        event = {
            "id": event_id,
            "hospital_id": hospital_id,
            "event_type": event_type,
            "aggregate_id": aggregate_id,
            "payload": payload,
            "idempotency_key": idempotency_key,
            "status": "pending",
            "attempt_count": 0,
            "available_at": now_iso(),
            "created_at": now_iso(),
            "processed_at": None,
            "last_error": None,
        }
        self.events[event_id] = event
        return event, True

    def patient_timeline(self, patient_id: str) -> list[dict]:
        patient = self.patients[patient_id]
        timeline = [
            {
                "type": "discharge",
                "occurred_at": patient["discharged_at"],
                "title": "Patient discharged",
                "details": {
                    "care_setting": patient["care_setting"],
                    "follow_up_deadline": patient["follow_up_deadline"],
                },
            }
        ]
        timeline.extend(
            {
                "type": "call",
                "occurred_at": call["started_at"],
                "title": f"Outreach attempt: {call['outcome'].replace('_', ' ')}",
                "details": call,
            }
            for call in self.calls
            if call["patient_id"] == patient_id
        )
        timeline.extend(
            {
                "type": "escalation",
                "occurred_at": escalation["created_at"],
                "title": f"Escalation: {escalation['status']}",
                "details": escalation,
            }
            for escalation in self.escalations.values()
            if escalation["patient_id"] == patient_id
        )
        timeline.extend(
            {
                "type": "ehr",
                "occurred_at": record["created_at"],
                "title": f"Mock EHR {record['resource_type']} written",
                "details": record,
            }
            for record in self.ehr_records
            if record["patient_id"] == patient_id
        )
        return sorted(timeline, key=lambda item: item["occurred_at"], reverse=True)


operations = OperationsStore()
