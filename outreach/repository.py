from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from outreach.database import session_factory
from outreach.ehr import EHRWriteRequest, mock_ehr
from outreach.enums import CampaignStatus, OutreachState
from outreach.ingestion import DischargeImport, evaluate_eligibility
from outreach.models import (
    AIUsage,
    AuditLog,
    CallRecord,
    Campaign,
    Discharge,
    EHRRecord,
    Encounter,
    Escalation,
    Event,
    Hospital,
    KnowledgeResource,
    Notification,
    OutreachTask,
    Patient,
    Protocol,
)
from outreach.operations import operations
from outreach.queue import retry_delay_minutes
from outreach.scheduler import durable_scheduler
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
                await session.flush()
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
                await session.flush()

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
                await session.flush()

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
                session.add(patient)
                await session.flush()
                session.add(encounter)
                await session.flush()
                session.add(discharge)
                await session.flush()

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

    async def seed_missing_clinical_records(self) -> None:
        """Add versioned knowledge and escalation fixtures to existing databases."""
        async with session_factory()() as session, session.begin():
            if not await session.scalar(select(func.count()).select_from(KnowledgeResource)):
                hospitals = list((await session.scalars(select(Hospital))).all())
                for hospital in hospitals:
                    resources = [
                        (
                            "Post-discharge red-flag protocol",
                            "protocol",
                            (
                                "Escalate chest pain, inability to breathe, unconsciousness, "
                                "stroke signs, severe bleeding, rapid deterioration, or "
                                "meaningful uncertainty to a clinical reviewer immediately."
                            ),
                            "GENERAL-POST-DISCHARGE-v1 §4",
                        ),
                        (
                            "Outreach operating guidance",
                            "operations",
                            (
                                "Verify the patient can speak safely, collect protocol-driven "
                                "responses, do not diagnose or change medication, and document "
                                "callback requests using the patient's hospital timezone."
                            ),
                            "OUTREACH-OPERATIONS-v1 §2",
                        ),
                    ]
                    for title, resource_type, content, source in resources:
                        session.add(
                            KnowledgeResource(
                                hospital_id=hospital.id,
                                title=title,
                                resource_type=resource_type,
                                content=content,
                                source_reference=source,
                                version="1.0",
                                active=True,
                                created_at=datetime.now(UTC),
                            )
                        )

            if not await session.scalar(select(func.count()).select_from(Escalation)):
                for source in operations.escalations.values():
                    patient_id = uuid.UUID(source["patient_id"])
                    task = await session.scalar(
                        select(OutreachTask).where(OutreachTask.patient_id == patient_id).limit(1)
                    )
                    if task is None:
                        continue
                    call = CallRecord(
                        hospital_id=task.hospital_id,
                        task_id=task.id,
                        outcome="escalated",
                        started_at=datetime.fromisoformat(source["created_at"]),
                        ended_at=datetime.fromisoformat(source["created_at"]),
                        transcript=None,
                        structured_result={
                            "evidence": source["evidence"],
                            "synthetic": True,
                        },
                        documentation_status="complete",
                    )
                    session.add(call)
                    await session.flush()
                    session.add(
                        Escalation(
                            id=uuid.UUID(source["id"]),
                            hospital_id=task.hospital_id,
                            call_id=call.id,
                            patient_id=patient_id,
                            status=source["status"],
                            priority=source["priority"],
                            trigger=source["trigger"],
                            evidence={
                                "indicators": source["evidence"],
                                "protocol_reference": source["protocol_reference"],
                            },
                            consensus=source["consensus"],
                            assigned_user_id=None,
                            resolution=None,
                            resolved_at=None,
                        )
                    )

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

    async def create_campaign(
        self,
        *,
        hospital_id: uuid.UUID,
        actor_id: uuid.UUID,
        values: dict,
    ) -> dict:
        async with session_factory()() as session, session.begin():
            protocol_id = await session.scalar(
                select(Protocol.id)
                .where(Protocol.hospital_id == hospital_id, Protocol.active.is_(True))
                .limit(1)
            )
            if protocol_id is None:
                raise ValueError("Hospital has no active outreach protocol")
            campaign = Campaign(
                hospital_id=hospital_id,
                name=values["name"],
                status=CampaignStatus.DRAFT.value,
                protocol_id=protocol_id,
                eligibility_rules={"consent_required": True},
                calling_window={"start": "09:00", "end": "18:00"},
                priority_weight=max(1, round(values["priority_weight"])),
                retry_limit=values["retry_limit"],
            )
            session.add(campaign)
            await session.flush()
            session.add(
                AuditLog(
                    hospital_id=hospital_id,
                    actor_id=actor_id,
                    action="campaign.created",
                    resource_type="campaign",
                    resource_id=campaign.id,
                    occurred_at=datetime.now(UTC),
                    details={"clinical_window_hours": values["clinical_window_hours"]},
                )
            )
            return {
                "id": str(campaign.id),
                "hospital_id": str(hospital_id),
                **values,
                "status": campaign.status,
                "eligible_patients": 0,
                "completed": 0,
            }

    async def update_campaign_status(
        self,
        *,
        campaign_id: uuid.UUID,
        hospital_id: uuid.UUID,
        actor_id: uuid.UUID,
        status: CampaignStatus,
    ) -> dict | None:
        async with session_factory()() as session, session.begin():
            campaign = await session.scalar(
                select(Campaign)
                .where(
                    Campaign.id == campaign_id,
                    Campaign.hospital_id == hospital_id,
                )
                .with_for_update()
            )
            if campaign is None:
                return None
            previous = campaign.status
            campaign.status = status.value
            session.add(
                AuditLog(
                    hospital_id=hospital_id,
                    actor_id=actor_id,
                    action="campaign.status_changed",
                    resource_type="campaign",
                    resource_id=campaign.id,
                    occurred_at=datetime.now(UTC),
                    details={"from": previous, "to": status.value},
                )
            )
            return {
                "id": str(campaign.id),
                "hospital_id": str(hospital_id),
                "name": campaign.name,
                "status": campaign.status,
            }

    async def import_discharges(
        self,
        *,
        hospital_id: uuid.UUID,
        actor_id: uuid.UUID,
        records: list[DischargeImport],
    ) -> dict:
        batch_id = uuid.uuid4()
        imported = duplicates = ineligible = 0
        results = []
        async with session_factory()() as session, session.begin():
            for record in records:
                exists = await session.scalar(
                    select(Patient.id).where(
                        Patient.hospital_id == hospital_id,
                        Patient.external_id == record.external_patient_id,
                    )
                )
                if exists:
                    duplicates += 1
                    continue
                eligible, reasons = evaluate_eligibility(record)
                patient = Patient(
                    hospital_id=hospital_id,
                    external_id=record.external_patient_id,
                    name={
                        "given": record.name.given,
                        "family": record.name.family,
                        "text": f"{record.name.given} {record.name.family}",
                    },
                    telecom={"phone": record.phone},
                    communication_preferences={
                        "channel": "voice",
                        "language": record.preferred_language,
                    },
                )
                session.add(patient)
                await session.flush()
                encounter = Encounter(
                    hospital_id=hospital_id,
                    patient_id=patient.id,
                    external_id=record.encounter_id,
                    care_setting=record.care_setting,
                    period_start=record.discharged_at,
                    period_end=record.discharged_at,
                    clinical_context={"condition_codes": record.condition_codes},
                )
                session.add(encounter)
                await session.flush()
                session.add(
                    Discharge(
                        hospital_id=hospital_id,
                        patient_id=patient.id,
                        encounter_id=encounter.id,
                        discharged_at=record.discharged_at,
                        follow_up_deadline=record.follow_up_deadline,
                        conditions=record.condition_codes,
                        medications=record.medication_summary,
                        care_plan={
                            "instructions": record.discharge_instructions,
                            "eligible": eligible,
                            "ineligibility_reasons": reasons,
                        },
                        risk_indicators=[record.risk.value],
                    )
                )
                imported += 1
                ineligible += int(not eligible)
                results.append(
                    {
                        "patient_id": str(patient.id),
                        "external_patient_id": record.external_patient_id,
                        "eligible": eligible,
                        "reasons": reasons,
                    }
                )
            session.add(
                AuditLog(
                    hospital_id=hospital_id,
                    actor_id=actor_id,
                    action="discharge.batch_imported",
                    resource_type="import_batch",
                    resource_id=batch_id,
                    occurred_at=datetime.now(UTC),
                    details={
                        "imported": imported,
                        "duplicates": duplicates,
                        "ineligible": ineligible,
                    },
                )
            )
        return {
            "batch_id": str(batch_id),
            "received": len(records),
            "imported": imported,
            "duplicates": duplicates,
            "ineligible": ineligible,
            "eligibility_results": results,
        }

    async def queue_snapshot(self, hospital_id: uuid.UUID | None) -> dict:
        async with session_factory()() as session:
            statement = (
                select(OutreachTask, Patient, Discharge, Hospital)
                .join(Patient, Patient.id == OutreachTask.patient_id)
                .join(Discharge, Discharge.id == OutreachTask.discharge_id)
                .join(Hospital, Hospital.id == OutreachTask.hospital_id)
            )
            if hospital_id:
                statement = statement.where(OutreachTask.hospital_id == hospital_id)
            rows = (
                await session.execute(
                    statement.order_by(
                        OutreachTask.priority_score.desc(),
                        OutreachTask.deadline.asc(),
                    )
                )
            ).all()
            call_statement = select(CallRecord).order_by(CallRecord.ended_at.desc())
            if hospital_id:
                call_statement = call_statement.where(CallRecord.hospital_id == hospital_id)
            latest_outcomes: dict[uuid.UUID, str] = {}
            for call in (await session.scalars(call_statement)).all():
                latest_outcomes.setdefault(call.task_id, call.outcome)
            tasks = [
                {
                    "id": str(task.id),
                    "patient_ref": patient.external_id,
                    "hospital": hospital.slug,
                    "risk": discharge.risk_indicators[0],
                    "discharged_at": discharge.discharged_at.isoformat(),
                    "deadline": task.deadline.isoformat(),
                    "state": task.state,
                    "attempts": task.attempt_count,
                    "callback_at": (task.callback_at.isoformat() if task.callback_at else None),
                    "priority": task.priority_score,
                    "last_outcome": latest_outcomes.get(task.id),
                }
                for task, patient, discharge, hospital in rows
            ]
            counts: dict[str, int] = {}
            for task in tasks:
                counts[task["state"]] = counts.get(task["state"], 0) + 1
            capacity = 0
            if hospital_id:
                capacity = int(
                    await session.scalar(
                        select(Hospital.outbound_capacity).where(Hospital.id == hospital_id)
                    )
                    or 0
                )
            else:
                capacity = int(
                    await session.scalar(select(func.sum(Hospital.outbound_capacity))) or 0
                )
            return {
                "simulated_time": datetime.now(UTC).isoformat(),
                "capacity": capacity,
                "active_calls": counts.get(OutreachState.CALLING.value, 0),
                "peak_concurrency": capacity,
                "state_counts": counts,
                "tasks": tasks,
            }

    async def advance_queue(self, hospital_id: uuid.UUID) -> dict:
        async with session_factory()() as session:
            await durable_scheduler.recover_stale(session, hospital_id)
        async with session_factory()() as session:
            await durable_scheduler.recover_expired(session, hospital_id)
        await self._complete_active(hospital_id)
        async with session_factory()() as session:
            capacity = int(
                await session.scalar(
                    select(Hospital.outbound_capacity).where(Hospital.id == hospital_id)
                )
                or 0
            )
        async with session_factory()() as session:
            await durable_scheduler.reserve(
                session,
                hospital_id=hospital_id,
                worker_id="prototype-simulator",
                capacity=capacity,
                lease_seconds=90,
            )
        return await self.queue_snapshot(hospital_id)

    async def _complete_active(self, hospital_id: uuid.UUID) -> None:
        now = datetime.now(UTC)
        async with session_factory()() as session, session.begin():
            tasks = list(
                (
                    await session.scalars(
                        select(OutreachTask)
                        .where(
                            OutreachTask.hospital_id == hospital_id,
                            OutreachTask.state == OutreachState.CALLING.value,
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            outcomes = ["completed", "no_answer", "busy", "voicemail", "dropped"]
            for task in tasks:
                outcome = outcomes[(task.id.int + task.attempt_count) % len(outcomes)]
                delay = retry_delay_minutes(outcome, task.attempt_count)
                if outcome == "completed":
                    task.state = OutreachState.COMPLETED.value
                elif delay is None:
                    task.state = OutreachState.MANUAL_FOLLOW_UP.value
                else:
                    task.state = OutreachState.RETRY_SCHEDULED.value
                    task.available_at = now + timedelta(minutes=delay)
                    task.callback_at = task.available_at
                task.lease_owner = None
                task.lease_expires_at = None
                session.add(
                    CallRecord(
                        hospital_id=hospital_id,
                        task_id=task.id,
                        outcome=outcome,
                        started_at=now,
                        ended_at=now,
                        transcript=None,
                        structured_result={
                            "source": "deterministic_call_simulator",
                            "attempt": task.attempt_count,
                            "outcome": outcome,
                        },
                        documentation_status="simulated",
                    )
                )
                event = Event(
                    hospital_id=hospital_id,
                    event_type=f"call.{outcome}",
                    aggregate_id=task.id,
                    payload={"attempt": task.attempt_count, "outcome": outcome},
                    idempotency_key=f"outcome:{task.id}:{task.attempt_count}",
                    occurred_at=now,
                    processed_at=now,
                )
                session.add(event)
                if task.state == OutreachState.MANUAL_FOLLOW_UP.value:
                    session.add(
                        Event(
                            hospital_id=hospital_id,
                            event_type="manual_follow_up.created",
                            aggregate_id=task.id,
                            payload={"reason": "maximum_retries"},
                            idempotency_key=f"manual-follow-up:{task.id}",
                            occurred_at=now,
                            processed_at=now,
                        )
                    )

    async def create_triage_ehr_record(
        self,
        *,
        hospital_id: uuid.UUID,
        patient_id: uuid.UUID,
        actor_id: uuid.UUID,
        payload: dict,
    ) -> dict:
        now = datetime.now(UTC)
        write = mock_ehr.validate_write(
            EHRWriteRequest(
                hospital_id=hospital_id,
                patient_id=patient_id,
                resource_type="Observation",
                status="preliminary",
                source="structured-outreach-triage",
                payload=payload,
            ),
            authorized_hospital_id=hospital_id,
        )
        async with session_factory()() as session, session.begin():
            record = EHRRecord(
                hospital_id=write.hospital_id,
                patient_id=write.patient_id,
                resource_type=write.resource_type,
                status=write.status,
                source=write.source,
                payload=write.payload,
                created_at=now,
                synced_at=None,
            )
            session.add(record)
            await session.flush()
            session.add(
                AuditLog(
                    hospital_id=hospital_id,
                    actor_id=actor_id,
                    action="triage.completed",
                    resource_type="patient",
                    resource_id=patient_id,
                    occurred_at=now,
                    details={
                        "classification": payload["final_classification"],
                        "escalation_required": payload["escalation_required"],
                    },
                )
            )
            session.add(
                AIUsage(
                    hospital_id=hospital_id,
                    patient_id=patient_id,
                    agent="clinical_triage",
                    provider="deterministic",
                    model="protocol-consensus-v1",
                    prompt_version="triage-1.0",
                    purpose="post_discharge_triage",
                    latency_ms=0,
                    input_tokens=None,
                    output_tokens=None,
                    estimated_cost_usd="0",
                    success=True,
                    validation_status="valid",
                    created_at=now,
                )
            )
            return {
                "id": str(record.id),
                "hospital_id": str(hospital_id),
                "patient_id": str(patient_id),
                "resource_type": record.resource_type,
                "status": record.status,
                "source": record.source,
                "payload": payload,
                "created_at": now.isoformat(),
            }

    async def list_ehr_records(self, hospital_id: uuid.UUID | None) -> list[dict]:
        async with session_factory()() as session:
            statement = select(EHRRecord)
            if hospital_id:
                statement = statement.where(EHRRecord.hospital_id == hospital_id)
            rows = list(
                (await session.scalars(statement.order_by(EHRRecord.created_at.desc()))).all()
            )
            return [
                {
                    "id": str(row.id),
                    "hospital_id": str(row.hospital_id),
                    "patient_id": str(row.patient_id),
                    "resource_type": row.resource_type,
                    "status": row.status,
                    "source": row.source,
                    "payload": row.payload,
                    "created_at": row.created_at.isoformat(),
                    "synced_at": row.synced_at.isoformat() if row.synced_at else None,
                }
                for row in rows
            ]

    async def list_protocols(self, hospital_id: uuid.UUID) -> list[dict]:
        async with session_factory()() as session:
            rows = list(
                (
                    await session.scalars(
                        select(Protocol)
                        .where(
                            Protocol.hospital_id == hospital_id,
                            Protocol.active.is_(True),
                        )
                        .order_by(Protocol.name)
                    )
                ).all()
            )
            return [
                {
                    "id": str(row.id),
                    "hospital_id": str(row.hospital_id),
                    "name": row.name,
                    "version": row.version,
                    "content": row.content,
                    "active": row.active,
                }
                for row in rows
            ]

    async def search_knowledge(
        self, hospital_id: uuid.UUID, query: str, limit: int = 5
    ) -> list[dict]:
        terms = [term for term in query.lower().split() if len(term) >= 3][:6]
        async with session_factory()() as session:
            statement = select(KnowledgeResource).where(
                KnowledgeResource.hospital_id == hospital_id,
                KnowledgeResource.active.is_(True),
            )
            rows = list((await session.scalars(statement)).all())
            ranked = sorted(
                rows,
                key=lambda row: sum(term in f"{row.title} {row.content}".lower() for term in terms),
                reverse=True,
            )
            return [
                {
                    "id": str(row.id),
                    "title": row.title,
                    "resource_type": row.resource_type,
                    "snippet": row.content[:500],
                    "source_reference": row.source_reference,
                    "version": row.version,
                }
                for row in ranked[:limit]
                if not terms or any(term in f"{row.title} {row.content}".lower() for term in terms)
            ]

    async def list_escalations(self, hospital_id: uuid.UUID) -> list[dict]:
        async with session_factory()() as session:
            rows = (
                await session.execute(
                    select(Escalation, Patient, CallRecord)
                    .join(Patient, Patient.id == Escalation.patient_id)
                    .join(CallRecord, CallRecord.id == Escalation.call_id)
                    .where(Escalation.hospital_id == hospital_id)
                    .order_by(Escalation.resolved_at.asc().nullsfirst())
                )
            ).all()
            return [
                {
                    "id": str(row.id),
                    "hospital_id": str(row.hospital_id),
                    "patient_id": str(row.patient_id),
                    "patient_name": patient.name.get("text", "Synthetic patient"),
                    "status": row.status,
                    "priority": row.priority,
                    "trigger": row.trigger,
                    "evidence": row.evidence.get("indicators", []),
                    "protocol_reference": row.evidence.get("protocol_reference", "unknown"),
                    "consensus": row.consensus,
                    "assigned_to": row.evidence.get("assigned_to"),
                    "created_at": call.started_at.isoformat(),
                    "resolution": row.resolution,
                    "resolved_at": (row.resolved_at.isoformat() if row.resolved_at else None),
                }
                for row, patient, call in rows
            ]

    async def update_escalation(
        self,
        *,
        escalation_id: uuid.UUID,
        hospital_id: uuid.UUID,
        actor_id: uuid.UUID,
        status: str,
        assigned_to: str | None,
        resolution: str | None,
    ) -> dict | None:
        async with session_factory()() as session, session.begin():
            row = await session.scalar(
                select(Escalation)
                .where(
                    Escalation.id == escalation_id,
                    Escalation.hospital_id == hospital_id,
                )
                .with_for_update()
            )
            if row is None:
                return None
            previous = row.status
            evidence = dict(row.evidence)
            if assigned_to:
                evidence["assigned_to"] = assigned_to
            row.evidence = evidence
            row.status = status
            row.resolution = resolution
            if status == "resolved":
                row.resolved_at = datetime.now(UTC)
            session.add(
                AuditLog(
                    hospital_id=hospital_id,
                    actor_id=actor_id,
                    action="escalation.updated",
                    resource_type="escalation",
                    resource_id=row.id,
                    occurred_at=datetime.now(UTC),
                    details={"from": previous, "to": status},
                )
            )
        rows = await self.list_escalations(hospital_id)
        return next((item for item in rows if item["id"] == str(escalation_id)), None)

    async def list_ai_usage(self, hospital_id: uuid.UUID | None) -> list[dict]:
        async with session_factory()() as session:
            statement = select(AIUsage)
            if hospital_id:
                statement = statement.where(AIUsage.hospital_id == hospital_id)
            rows = list(
                (
                    await session.scalars(statement.order_by(AIUsage.created_at.desc()).limit(250))
                ).all()
            )
            return [
                {
                    "id": str(row.id),
                    "hospital_id": str(row.hospital_id),
                    "agent": row.agent,
                    "provider": row.provider,
                    "model": row.model,
                    "prompt_version": row.prompt_version,
                    "purpose": row.purpose,
                    "latency_ms": row.latency_ms,
                    "success": row.success,
                    "validation_status": row.validation_status,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    async def save_conversation_workflow(
        self,
        *,
        hospital_id: uuid.UUID,
        actor_id: uuid.UUID,
        patient_id: uuid.UUID,
        transcript: str,
        idempotency_key: str,
        result: dict,
    ) -> dict:
        key_digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
        event_key = f"conversation:{hospital_id}:{key_digest}"
        async with session_factory()() as session, session.begin():
            existing = await session.scalar(select(Event).where(Event.idempotency_key == event_key))
            if existing:
                return existing.payload["result"]
            task = await session.scalar(
                select(OutreachTask)
                .where(
                    OutreachTask.hospital_id == hospital_id,
                    OutreachTask.patient_id == patient_id,
                )
                .order_by(OutreachTask.deadline.desc())
                .limit(1)
                .with_for_update()
            )
            if task is None:
                raise ValueError("Patient has no outreach task")
            # Recheck after the task lock so concurrent requests with the same
            # key cannot both create external side effects.
            existing = await session.scalar(select(Event).where(Event.idempotency_key == event_key))
            if existing:
                return existing.payload["result"]
            now = datetime.now(UTC)
            ehr_write = mock_ehr.validate_write(
                EHRWriteRequest(
                    hospital_id=hospital_id,
                    patient_id=patient_id,
                    resource_type="Communication",
                    status="final",
                    source="documentation-agent",
                    payload=result["documentation"],
                ),
                authorized_hospital_id=hospital_id,
            )
            call = CallRecord(
                hospital_id=hospital_id,
                task_id=task.id,
                outcome=result["intake"]["disposition"],
                started_at=now,
                ended_at=now,
                transcript=transcript,
                structured_result=result,
                documentation_status=result["documentation"]["documentation_status"],
            )
            session.add(call)
            await session.flush()

            if result["triage"]["escalation_required"]:
                task.state = OutreachState.ESCALATED.value
            elif result["intake"]["callback_requested"]:
                task.state = OutreachState.CALLBACK_SCHEDULED.value
                task.callback_at = now + timedelta(hours=1)
                task.available_at = task.callback_at
            else:
                task.state = OutreachState.COMPLETED.value
            task.lease_owner = None
            task.lease_expires_at = None

            ehr = EHRRecord(
                hospital_id=ehr_write.hospital_id,
                patient_id=ehr_write.patient_id,
                resource_type=ehr_write.resource_type,
                status=ehr_write.status,
                source=ehr_write.source,
                payload=ehr_write.payload,
                created_at=now,
                synced_at=now,
            )
            session.add(ehr)

            if result["triage"]["escalation_required"]:
                session.add(
                    Escalation(
                        hospital_id=hospital_id,
                        call_id=call.id,
                        patient_id=patient_id,
                        status="open",
                        priority=(
                            "urgent"
                            if result["triage"]["final_classification"] == "urgent"
                            else "high"
                        ),
                        trigger=result["triage"]["rationale"],
                        evidence={
                            "indicators": result["documentation"]["patient_reported_symptoms"],
                            "protocol_reference": result["documentation"]["protocol_references"][0],
                        },
                        consensus={
                            "assessments": result["triage"]["assessments"],
                            "disagreement": result["triage"]["disagreement"],
                        },
                        assigned_user_id=None,
                        resolution=None,
                        resolved_at=None,
                    )
                )

            for agent in [
                "voice_intake",
                "clinical_triage",
                "escalation_consensus",
                "documentation",
            ]:
                session.add(
                    AIUsage(
                        hospital_id=hospital_id,
                        patient_id=patient_id,
                        agent=agent,
                        provider="deterministic",
                        model="bounded-workflow-v1",
                        prompt_version=f"{agent}-1.0",
                        purpose="post_discharge_conversation",
                        latency_ms=0,
                        input_tokens=None,
                        output_tokens=None,
                        estimated_cost_usd="0",
                        success=True,
                        validation_status="valid",
                        created_at=now,
                    )
                )
            session.add(
                Event(
                    hospital_id=hospital_id,
                    event_type="conversation.completed",
                    aggregate_id=call.id,
                    payload={"result": result},
                    idempotency_key=event_key,
                    occurred_at=now,
                    processed_at=now,
                )
            )
            session.add(
                AuditLog(
                    hospital_id=hospital_id,
                    actor_id=actor_id,
                    action="conversation.workflow_completed",
                    resource_type="call_record",
                    resource_id=call.id,
                    occurred_at=now,
                    details={
                        "outcome": call.outcome,
                        "escalation_required": result["triage"]["escalation_required"],
                    },
                )
            )
        return result

    async def deliver_pending_escalation_notifications(self) -> int:
        delivered = 0
        async with session_factory()() as session, session.begin():
            escalations = list(
                (
                    await session.scalars(
                        select(Escalation).where(
                            Escalation.status.in_(["open", "assigned", "in_review"])
                        )
                    )
                ).all()
            )
            for escalation in escalations:
                key = f"escalation-notification:{escalation.id}:dashboard"
                if await session.scalar(
                    select(Notification.id).where(Notification.idempotency_key == key)
                ):
                    continue
                now = datetime.now(UTC)
                event = Event(
                    hospital_id=escalation.hospital_id,
                    event_type="escalation.notification_requested",
                    aggregate_id=escalation.id,
                    payload={"priority": escalation.priority},
                    idempotency_key=f"event:{key}",
                    occurred_at=now,
                    processed_at=now,
                )
                session.add(event)
                await session.flush()
                session.add(
                    Notification(
                        hospital_id=escalation.hospital_id,
                        event_id=event.id,
                        channel="dashboard",
                        recipient_role="clinical_reviewer",
                        subject="Post-discharge escalation requires review",
                        status="delivered",
                        idempotency_key=key,
                        created_at=now,
                        delivered_at=now,
                    )
                )
                delivered += 1
            manual_tasks = list(
                (
                    await session.scalars(
                        select(OutreachTask).where(
                            OutreachTask.state == OutreachState.MANUAL_FOLLOW_UP.value
                        )
                    )
                ).all()
            )
            for task in manual_tasks:
                key = f"manual-follow-up-notification:{task.id}:dashboard"
                if await session.scalar(
                    select(Notification.id).where(Notification.idempotency_key == key)
                ):
                    continue
                now = datetime.now(UTC)
                event = await session.scalar(
                    select(Event)
                    .where(
                        Event.hospital_id == task.hospital_id,
                        Event.aggregate_id == task.id,
                        Event.event_type == "manual_follow_up.created",
                    )
                    .limit(1)
                )
                if event is None:
                    event = Event(
                        hospital_id=task.hospital_id,
                        event_type="manual_follow_up.created",
                        aggregate_id=task.id,
                        payload={"reason": "maximum_retries_or_deadline"},
                        idempotency_key=f"manual-follow-up:{task.id}",
                        occurred_at=now,
                        processed_at=now,
                    )
                    session.add(event)
                    await session.flush()
                session.add(
                    Notification(
                        hospital_id=task.hospital_id,
                        event_id=event.id,
                        channel="dashboard",
                        recipient_role="campaign_manager",
                        subject="Manual patient follow-up required",
                        status="delivered",
                        idempotency_key=key,
                        created_at=now,
                        delivered_at=now,
                    )
                )
                delivered += 1
        return delivered

    async def list_notifications(self, hospital_id: uuid.UUID | None) -> list[dict]:
        async with session_factory()() as session:
            statement = select(Notification)
            if hospital_id:
                statement = statement.where(Notification.hospital_id == hospital_id)
            rows = list(
                (
                    await session.scalars(
                        statement.order_by(Notification.created_at.desc()).limit(250)
                    )
                ).all()
            )
            return [
                {
                    "id": str(row.id),
                    "hospital_id": str(row.hospital_id),
                    "event_id": str(row.event_id),
                    "channel": row.channel,
                    "recipient_role": row.recipient_role,
                    "subject": row.subject,
                    "status": row.status,
                    "created_at": row.created_at.isoformat(),
                    "delivered_at": (row.delivered_at.isoformat() if row.delivered_at else None),
                }
                for row in rows
            ]

    async def list_audit(self, hospital_id: uuid.UUID | None) -> list[dict]:
        async with session_factory()() as session:
            statement = select(AuditLog)
            if hospital_id:
                statement = statement.where(AuditLog.hospital_id == hospital_id)
            rows = list(
                (
                    await session.scalars(
                        statement.order_by(AuditLog.occurred_at.desc()).limit(500)
                    )
                ).all()
            )
            return [
                {
                    "id": str(row.id),
                    "hospital_id": str(row.hospital_id),
                    "actor_id": str(row.actor_id) if row.actor_id else "system",
                    "action": row.action,
                    "resource_type": row.resource_type,
                    "resource_id": str(row.resource_id),
                    "occurred_at": row.occurred_at.isoformat(),
                    "details": row.details,
                }
                for row in rows
            ]


postgres_repository = PostgresRepository()
