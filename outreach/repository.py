from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from outreach.database import session_factory
from outreach.enums import OutreachState
from outreach.models import (
    Campaign,
    Discharge,
    Encounter,
    Hospital,
    OutreachTask,
    Patient,
    Protocol,
)
from outreach.operations import operations
from outreach.simulation import QueueSimulation


def _uuid(namespace: str, value: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{namespace}:{value}")


class PostgresRepository:
    async def seed_synthetic_foundation(self, simulation: QueueSimulation) -> None:
        """Seed only an empty database; repeated startup is idempotent."""
        async with session_factory()() as session:
            if await session.scalar(select(func.count()).select_from(Hospital)):
                return
            protocols: dict[str, Protocol] = {}
            campaigns: dict[str, Campaign] = {}
            for hospital_row in operations.hospitals.values():
                hospital_id = uuid.UUID(hospital_row["id"])
                session.add(
                    Hospital(
                        id=hospital_id,
                        name=hospital_row["name"],
                        slug=hospital_row["slug"],
                        timezone=hospital_row["timezone"],
                        outbound_capacity=hospital_row["outbound_capacity"],
                        status=hospital_row["status"],
                        configuration={
                            "calling_hours": hospital_row["calling_hours"],
                            "synthetic": True,
                        },
                    )
                )
                protocol = Protocol(
                    id=_uuid("protocol", hospital_row["slug"]),
                    hospital_id=hospital_id,
                    name="General post-discharge outreach",
                    version="1.0",
                    content={
                        "red_flags": [
                            "chest pain",
                            "cannot breathe",
                            "unconscious",
                            "severe bleeding",
                        ],
                        "source": "synthetic evaluator protocol",
                    },
                    active=True,
                )
                protocols[hospital_row["id"]] = protocol
                session.add(protocol)

                campaign_row = next(
                    item
                    for item in operations.campaigns.values()
                    if item["hospital_id"] == hospital_row["id"]
                )
                campaign = Campaign(
                    id=uuid.UUID(campaign_row["id"]),
                    hospital_id=hospital_id,
                    name=campaign_row["name"],
                    status=campaign_row["status"],
                    protocol_id=protocol.id,
                    eligibility_rules={"consent_required": True},
                    calling_window=hospital_row["calling_hours"],
                    priority_weight=1,
                    retry_limit=campaign_row["retry_limit"],
                )
                campaigns[hospital_row["id"]] = campaign
                session.add(campaign)

            for patient_row in operations.patients.values():
                hospital_id = uuid.UUID(patient_row["hospital_id"])
                patient_id = uuid.UUID(patient_row["id"])
                patient = Patient(
                    id=patient_id,
                    hospital_id=hospital_id,
                    external_id=patient_row["external_id"],
                    name={"text": patient_row["display_name"]},
                    telecom={"phone": patient_row["phone"]},
                    communication_preferences={"channel": patient_row["communication_preference"]},
                )
                encounter = Encounter(
                    id=_uuid("encounter", patient_row["id"]),
                    hospital_id=hospital_id,
                    patient_id=patient_id,
                    external_id=f"ENC-{patient_row['external_id']}",
                    care_setting=patient_row["care_setting"],
                    period_start=datetime.fromisoformat(patient_row["discharged_at"]),
                    period_end=datetime.fromisoformat(patient_row["discharged_at"]),
                    clinical_context={"condition": patient_row["condition"]},
                )
                discharge = Discharge(
                    id=_uuid("discharge", patient_row["id"]),
                    hospital_id=hospital_id,
                    patient_id=patient_id,
                    encounter_id=encounter.id,
                    discharged_at=datetime.fromisoformat(patient_row["discharged_at"]),
                    follow_up_deadline=datetime.fromisoformat(patient_row["follow_up_deadline"]),
                    conditions=[patient_row["condition"]],
                    medications=[],
                    care_plan={"synthetic": True},
                    risk_indicators=[patient_row["risk"]],
                )
                session.add_all([patient, encounter, discharge])

            for task in simulation.tasks:
                hospital = next(
                    row for row in operations.hospitals.values() if row["slug"] == task.hospital
                )
                patient = next(
                    row
                    for row in operations.patients.values()
                    if row["external_id"] == task.patient_ref
                )
                session.add(
                    OutreachTask(
                        id=_uuid("outreach-task", task.id),
                        hospital_id=uuid.UUID(hospital["id"]),
                        patient_id=uuid.UUID(patient["id"]),
                        discharge_id=_uuid("discharge", patient["id"]),
                        campaign_id=campaigns[hospital["id"]].id,
                        state=OutreachState.PENDING.value,
                        priority_score=int(task.priority),
                        attempt_count=0,
                        available_at=datetime.now(UTC),
                        deadline=task.deadline,
                        callback_at=None,
                        lease_owner=None,
                        lease_expires_at=None,
                        idempotency_key=f"seed:{task.id}",
                    )
                )
            await session.commit()

    async def counts(self) -> dict[str, int]:
        async with session_factory()() as session:
            return {
                "hospitals": int(
                    await session.scalar(select(func.count()).select_from(Hospital)) or 0
                ),
                "patients": int(
                    await session.scalar(select(func.count()).select_from(Patient)) or 0
                ),
                "campaigns": int(
                    await session.scalar(select(func.count()).select_from(Campaign)) or 0
                ),
                "outreach_tasks": int(
                    await session.scalar(select(func.count()).select_from(OutreachTask)) or 0
                ),
            }

    async def list_hospitals(self, hospital_id: uuid.UUID | None) -> list[dict]:
        async with session_factory()() as session:
            statement = select(Hospital)
            if hospital_id:
                statement = statement.where(Hospital.id == hospital_id)
            rows = list((await session.scalars(statement.order_by(Hospital.name))).all())
            return [
                {
                    "id": str(row.id),
                    "slug": row.slug,
                    "name": row.name,
                    "timezone": row.timezone,
                    "outbound_capacity": row.outbound_capacity,
                    "status": row.status,
                    "calling_hours": row.configuration.get("calling_hours", {}),
                }
                for row in rows
            ]

    async def list_patients(self, hospital_id: uuid.UUID | None) -> list[dict]:
        async with session_factory()() as session:
            statement = (
                select(Patient, Encounter, Discharge)
                .join(Encounter, Encounter.patient_id == Patient.id)
                .join(Discharge, Discharge.patient_id == Patient.id)
            )
            if hospital_id:
                statement = statement.where(Patient.hospital_id == hospital_id)
            rows = (await session.execute(statement.order_by(Discharge.discharged_at.desc()))).all()
            return [
                {
                    "id": str(patient.id),
                    "hospital_id": str(patient.hospital_id),
                    "external_id": patient.external_id,
                    "display_name": patient.name.get("text", "Synthetic patient"),
                    "phone": patient.telecom.get("phone"),
                    "care_setting": encounter.care_setting,
                    "condition": ", ".join(discharge.conditions),
                    "risk": discharge.risk_indicators[0],
                    "discharged_at": discharge.discharged_at.isoformat(),
                    "follow_up_deadline": discharge.follow_up_deadline.isoformat(),
                    "communication_preference": patient.communication_preferences.get(
                        "channel", "voice"
                    ),
                    "outreach_status": "pending",
                }
                for patient, encounter, discharge in rows
            ]

    async def list_campaigns(self, hospital_id: uuid.UUID | None) -> list[dict]:
        async with session_factory()() as session:
            statement = select(Campaign)
            if hospital_id:
                statement = statement.where(Campaign.hospital_id == hospital_id)
            rows = list((await session.scalars(statement.order_by(Campaign.name))).all())
            result = []
            for row in rows:
                eligible = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(Patient)
                        .where(Patient.hospital_id == row.hospital_id)
                    )
                    or 0
                )
                result.append(
                    {
                        "id": str(row.id),
                        "hospital_id": str(row.hospital_id),
                        "name": row.name,
                        "description": "Protocol-driven post-discharge outreach",
                        "status": row.status,
                        "eligible_patients": eligible,
                        "completed": 0,
                        "priority_weight": row.priority_weight,
                        "retry_limit": row.retry_limit,
                        "clinical_window_hours": 48,
                    }
                )
            return result


postgres_repository = PostgresRepository()
