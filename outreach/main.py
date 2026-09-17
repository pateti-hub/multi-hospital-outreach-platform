from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from math import ceil
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from outreach.agents import ConversationRequest, run_conversation_workflow
from outreach.config import get_settings
from outreach.database import close_database, initialize_database
from outreach.enums import CampaignStatus, EscalationStatus, Role
from outreach.ingestion import DischargeBatch, evaluate_eligibility
from outreach.operations import operations
from outreach.repository import postgres_repository
from outreach.safety import run_safety_evaluation
from outreach.security import (
    Principal,
    create_access_token,
    current_principal,
    enforce_tenant,
    require_roles,
)
from outreach.simulation import QueueSimulation
from outreach.triage import TriageRequest, assess
from outreach.voice import VoiceGatewayError, voice_gateway
from outreach.worker import run_worker_cycle, stop_worker, worker_loop
from outreach.workflows import workflow_processor


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker_task = None
    if get_settings().persistence_enabled:
        await initialize_database()
        await postgres_repository.seed_synthetic_foundation(simulation)
        await postgres_repository.seed_missing_clinical_records()
        if get_settings().background_workers_enabled:
            worker_task = asyncio.create_task(worker_loop())
    yield
    await stop_worker(worker_task)
    if get_settings().persistence_enabled:
        await close_database()


app = FastAPI(
    title="Multi-Hospital Post-Discharge Outreach Platform",
    version="0.1.0",
    description="Synthetic-data prototype. Not for clinical use.",
    lifespan=lifespan,
)


class DemoTokenRequest(BaseModel):
    hospital_slug: str
    role: Role


class CampaignTransitionRequest(BaseModel):
    current: CampaignStatus
    target: CampaignStatus


class HospitalCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    slug: str = Field(pattern=r"^[a-z0-9-]{2,80}$")
    timezone: str = "Asia/Kolkata"
    outbound_capacity: int = Field(default=10, ge=1, le=100)


class CampaignStatusRequest(BaseModel):
    status: CampaignStatus


class EscalationUpdateRequest(BaseModel):
    status: EscalationStatus
    assigned_to: str | None = Field(default=None, max_length=180)
    resolution: str | None = Field(default=None, max_length=2_000)


class CampaignCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=180)
    description: str = Field(min_length=3, max_length=1_000)
    clinical_window_hours: int = Field(ge=1, le=168)
    retry_limit: int = Field(default=3, ge=0, le=10)
    priority_weight: float = Field(default=1.0, ge=0.1, le=5)


class VoiceSessionRequest(BaseModel):
    task_id: uuid.UUID


DEMO_HOSPITALS = {
    "mercy-general": uuid.UUID("11111111-1111-4111-8111-111111111111"),
    "riverside-medical": uuid.UUID("22222222-2222-4222-8222-222222222222"),
}
simulation = QueueSimulation()
ALLOWED_TRANSITIONS = {
    CampaignStatus.DRAFT: {CampaignStatus.READY, CampaignStatus.CANCELLED},
    CampaignStatus.READY: {
        CampaignStatus.SCHEDULED,
        CampaignStatus.RUNNING,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.SCHEDULED: {
        CampaignStatus.RUNNING,
        CampaignStatus.PAUSED,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.RUNNING: {
        CampaignStatus.PAUSED,
        CampaignStatus.COMPLETED,
        CampaignStatus.FAILED,
    },
    CampaignStatus.PAUSED: {
        CampaignStatus.RUNNING,
        CampaignStatus.CANCELLED,
        CampaignStatus.FAILED,
    },
}
ESCALATION_TRANSITIONS = {
    EscalationStatus.OPEN: {EscalationStatus.ASSIGNED},
    EscalationStatus.ASSIGNED: {
        EscalationStatus.IN_REVIEW,
        EscalationStatus.OPEN,
    },
    EscalationStatus.IN_REVIEW: {
        EscalationStatus.WAITING_FOR_INFORMATION,
        EscalationStatus.RESOLVED,
        EscalationStatus.ASSIGNED,
    },
    EscalationStatus.WAITING_FOR_INFORMATION: {
        EscalationStatus.IN_REVIEW,
        EscalationStatus.RESOLVED,
    },
    EscalationStatus.RESOLVED: {EscalationStatus.CLOSED},
}


def scoped_snapshot(principal: Principal, snapshot: dict | None = None) -> dict:
    result = snapshot or simulation.snapshot()
    if principal.role == Role.PLATFORM_ADMIN:
        return result
    slug = next(
        (key for key, value in DEMO_HOSPITALS.items() if value == principal.hospital_id),
        None,
    )
    tasks = [task for task in result["tasks"] if task["hospital"] == slug]
    state_counts: dict[str, int] = {}
    for task in tasks:
        state_counts[task["state"]] = state_counts.get(task["state"], 0) + 1
    return {
        **result,
        "active_calls": state_counts.get("calling", 0),
        "state_counts": state_counts,
        "tasks": tasks,
    }


@app.get("/api/v1/health")
async def health() -> dict:
    failed_events = sum(event["status"] == "failed" for event in operations.events.values())
    result = {
        "status": "degraded" if failed_events else "healthy",
        "time": datetime.now(UTC).isoformat(),
        "components": {
            "api": "healthy",
            "queue_simulator": "healthy",
            "workflow_processor": "degraded" if failed_events else "healthy",
            "database": ("healthy" if get_settings().persistence_enabled else "disabled"),
            "background_worker": (
                "healthy" if get_settings().background_workers_enabled else "manual"
            ),
            "queue_execution": (
                "automatic" if get_settings().auto_queue_enabled else "evaluator_controlled"
            ),
            "authentication": (
                "supabase_and_local"
                if (
                    get_settings().supabase_auth_enabled
                    and get_settings().supabase_url
                    and get_settings().supabase_anon_key
                )
                else "misconfigured"
                if get_settings().supabase_auth_enabled
                else "local_signed_tokens"
            ),
            "streaming_voice": ("configured" if get_settings().voice_service_url else "simulator"),
        },
    }
    if get_settings().persistence_enabled:
        result["database_counts"] = await postgres_repository.counts()
    return result


@app.post("/api/v1/auth/demo-token")
def demo_token(request: DemoTokenRequest) -> dict:
    if not get_settings().demo_auth_enabled:
        raise HTTPException(status_code=404, detail="Demo authentication is disabled")
    hospital_id = None
    if request.role != Role.PLATFORM_ADMIN:
        hospital_id = DEMO_HOSPITALS.get(request.hospital_slug)
        if hospital_id is None:
            raise HTTPException(status_code=404, detail="Unknown demo hospital")
    principal = Principal(uuid.uuid4(), hospital_id, request.role)
    return {"access_token": create_access_token(principal), "token_type": "bearer"}


@app.get("/api/v1/me")
def me(principal: Principal = Depends(current_principal)) -> dict:
    return {
        "user_id": principal.user_id,
        "hospital_id": principal.hospital_id,
        "role": principal.role,
    }


@app.post("/api/v1/hospitals", status_code=201)
def create_hospital(
    request: HospitalCreate,
    _: Principal = Depends(require_roles(Role.PLATFORM_ADMIN)),
) -> dict:
    return {"id": uuid.uuid4(), **request.model_dump(), "ready": False}


@app.get("/api/v1/hospitals/{hospital_id}/queue")
def tenant_queue(
    hospital_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
) -> dict:
    enforce_tenant(principal, hospital_id)
    return scoped_snapshot(principal)


@app.get("/api/v1/simulation")
async def simulation_snapshot(principal: Principal = Depends(current_principal)) -> dict:
    if get_settings().persistence_enabled:
        hospital_id = None if principal.role == Role.PLATFORM_ADMIN else principal.hospital_id
        return await postgres_repository.queue_snapshot(hospital_id)
    return scoped_snapshot(principal)


@app.post("/api/v1/simulation/step")
async def step_simulation(
    principal: Principal = Depends(
        require_roles(Role.PLATFORM_ADMIN, Role.HOSPITAL_ADMIN, Role.CAMPAIGN_MANAGER)
    ),
) -> dict:
    if get_settings().persistence_enabled:
        if principal.hospital_id is None:
            raise HTTPException(
                status_code=422,
                detail="Select a hospital context to advance its queue",
            )
        return await postgres_repository.advance_queue(principal.hospital_id)
    return scoped_snapshot(principal, simulation.step())


@app.post("/api/v1/campaigns/validate-transition")
def validate_campaign_transition(
    request: CampaignTransitionRequest,
    _: Principal = Depends(require_roles(Role.HOSPITAL_ADMIN, Role.CAMPAIGN_MANAGER)),
) -> dict:
    if request.target not in ALLOWED_TRANSITIONS.get(request.current, set()):
        raise HTTPException(status_code=409, detail="Campaign transition is not allowed")
    return {"allowed": True, "from": request.current, "to": request.target}


@app.get("/api/v1/metrics/queue")
def queue_metrics(
    scope: Literal["tenant", "platform"] = "tenant",
    principal: Principal = Depends(current_principal),
) -> dict:
    if scope == "platform" and principal.role != Role.PLATFORM_ADMIN:
        raise HTTPException(status_code=403, detail="Platform metrics require platform admin")
    snapshot = scoped_snapshot(principal)
    queued = {"pending", "scheduled", "retry_scheduled", "callback_scheduled"}
    return {
        "scope": scope,
        "queue_depth": sum(
            value for state, value in snapshot["state_counts"].items() if state in queued
        ),
        "active_calls": snapshot["active_calls"],
        "capacity": snapshot["capacity"],
        "state_counts": snapshot["state_counts"],
    }


@app.get("/api/v1/hospitals")
async def list_hospitals(
    principal: Principal = Depends(current_principal),
) -> list[dict]:
    if get_settings().persistence_enabled:
        hospital_id = None if principal.role == Role.PLATFORM_ADMIN else principal.hospital_id
        return await postgres_repository.list_hospitals(hospital_id)
    rows = list(operations.hospitals.values())
    if principal.role == Role.PLATFORM_ADMIN:
        return rows
    return [row for row in rows if row["id"] == str(principal.hospital_id)]


@app.get("/api/v1/patients")
async def list_patients(
    principal: Principal = Depends(current_principal),
) -> list[dict]:
    if get_settings().persistence_enabled:
        hospital_id = None if principal.role == Role.PLATFORM_ADMIN else principal.hospital_id
        return await postgres_repository.list_patients(hospital_id)
    return operations.tenant_rows(list(operations.patients.values()), principal.hospital_id)


@app.get("/api/v1/patients/{patient_id}")
def patient_detail(patient_id: str, principal: Principal = Depends(current_principal)) -> dict:
    patient = operations.patients.get(patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    enforce_tenant(principal, uuid.UUID(patient["hospital_id"]))
    return {
        **patient,
        "timeline": operations.patient_timeline(patient_id),
        "calls": [call for call in operations.calls if call["patient_id"] == patient_id],
        "escalations": [
            item for item in operations.escalations.values() if item["patient_id"] == patient_id
        ],
    }


@app.get("/api/v1/campaigns")
async def list_campaigns(
    principal: Principal = Depends(current_principal),
) -> list[dict]:
    if get_settings().persistence_enabled:
        hospital_id = None if principal.role == Role.PLATFORM_ADMIN else principal.hospital_id
        return await postgres_repository.list_campaigns(hospital_id)
    return operations.tenant_rows(list(operations.campaigns.values()), principal.hospital_id)


@app.get("/api/v1/storage/status")
async def storage_status(
    _: Principal = Depends(require_roles(Role.PLATFORM_ADMIN, Role.HOSPITAL_ADMIN)),
) -> dict:
    if not get_settings().persistence_enabled:
        return {"mode": "in_memory", "database": "disabled"}
    return {
        "mode": "postgresql",
        "database": "healthy",
        "counts": await postgres_repository.counts(),
    }


@app.post("/api/v1/campaigns", status_code=201)
async def create_campaign(
    request: CampaignCreateRequest,
    principal: Principal = Depends(require_roles(Role.HOSPITAL_ADMIN, Role.CAMPAIGN_MANAGER)),
) -> dict:
    if principal.hospital_id is None:
        raise HTTPException(status_code=422, detail="A hospital context is required")
    if get_settings().persistence_enabled:
        try:
            return await postgres_repository.create_campaign(
                hospital_id=principal.hospital_id,
                actor_id=principal.user_id,
                values=request.model_dump(),
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    campaign_id = str(uuid.uuid4())
    campaign = {
        "id": campaign_id,
        "hospital_id": str(principal.hospital_id),
        **request.model_dump(),
        "status": CampaignStatus.DRAFT.value,
        "eligible_patients": 0,
        "completed": 0,
    }
    operations.campaigns[campaign_id] = campaign
    operations.record_audit(
        campaign["hospital_id"],
        principal.user_id,
        "campaign.created",
        "campaign",
        campaign_id,
    )
    return campaign


@app.get("/api/v1/campaigns/{campaign_id}/workload-estimate")
def campaign_workload_estimate(
    campaign_id: str, principal: Principal = Depends(current_principal)
) -> dict:
    campaign = operations.campaigns.get(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    enforce_tenant(principal, uuid.UUID(campaign["hospital_id"]))
    hospital = operations.hospitals[campaign["hospital_id"]]
    eligible = sum(
        patient["hospital_id"] == campaign["hospital_id"]
        and patient["outreach_status"] != "ineligible"
        for patient in operations.patients.values()
    )
    retry_factor = min(1.5, 0.35 * campaign["retry_limit"])
    expected_attempts = ceil(eligible * (1 + retry_factor))
    capacity = hospital["outbound_capacity"]
    return {
        "campaign_id": campaign_id,
        "eligible_patients": eligible,
        "expected_attempts": expected_attempts,
        "outbound_capacity": capacity,
        "minimum_call_waves": ceil(expected_attempts / capacity),
        "assumptions": {
            "retry_factor": retry_factor,
            "average_call_minutes": 6,
            "calling_window": hospital["calling_hours"],
        },
    }


@app.post("/api/v1/discharges/import", status_code=202)
async def import_discharges(
    request: DischargeBatch,
    principal: Principal = Depends(require_roles(Role.HOSPITAL_ADMIN)),
) -> dict:
    if principal.hospital_id is None:
        raise HTTPException(status_code=422, detail="A hospital context is required")
    if get_settings().persistence_enabled:
        return await postgres_repository.import_discharges(
            hospital_id=principal.hospital_id,
            actor_id=principal.user_id,
            records=request.records,
        )
    hospital_id = str(principal.hospital_id)
    existing = {
        patient["external_id"]
        for patient in operations.patients.values()
        if patient["hospital_id"] == hospital_id
    }
    imported = duplicates = ineligible = 0
    eligibility_results = []
    for record in request.records:
        if record.external_patient_id in existing:
            duplicates += 1
            continue
        eligible, reasons = evaluate_eligibility(record)
        patient_id = str(uuid.uuid4())
        operations.patients[patient_id] = {
            "id": patient_id,
            "hospital_id": hospital_id,
            "external_id": record.external_patient_id,
            "display_name": f"{record.name.given} {record.name.family}",
            "phone": record.phone,
            "care_setting": record.care_setting,
            "condition": ", ".join(record.condition_codes),
            "risk": record.risk.value,
            "discharged_at": record.discharged_at.isoformat(),
            "follow_up_deadline": record.follow_up_deadline.isoformat(),
            "communication_preference": record.preferred_language,
            "outreach_status": "pending" if eligible else "ineligible",
            "healthcare_context": {
                "encounter_id": record.encounter_id,
                "condition_codes": record.condition_codes,
                "discharge_instructions": record.discharge_instructions,
                "medication_summary": record.medication_summary,
            },
        }
        imported += 1
        ineligible += int(not eligible)
        eligibility_results.append(
            {
                "patient_id": patient_id,
                "external_patient_id": record.external_patient_id,
                "eligible": eligible,
                "reasons": reasons,
            }
        )
        existing.add(record.external_patient_id)
    batch_id = str(uuid.uuid4())
    operations.record_audit(
        hospital_id,
        principal.user_id,
        "discharge.batch_imported",
        "import_batch",
        batch_id,
        {"imported": imported, "duplicates": duplicates, "ineligible": ineligible},
    )
    return {
        "batch_id": batch_id,
        "received": len(request.records),
        "imported": imported,
        "duplicates": duplicates,
        "ineligible": ineligible,
        "eligibility_results": eligibility_results,
    }


@app.patch("/api/v1/campaigns/{campaign_id}/status")
async def update_campaign_status(
    campaign_id: str,
    request: CampaignStatusRequest,
    principal: Principal = Depends(require_roles(Role.HOSPITAL_ADMIN, Role.CAMPAIGN_MANAGER)),
) -> dict:
    if get_settings().persistence_enabled:
        if principal.hospital_id is None:
            raise HTTPException(status_code=422, detail="A hospital context is required")
        campaigns = await postgres_repository.list_campaigns(principal.hospital_id)
        campaign = next(
            (item for item in campaigns if item["id"] == campaign_id),
            None,
        )
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        current = CampaignStatus(campaign["status"])
        if request.status not in ALLOWED_TRANSITIONS.get(current, set()):
            raise HTTPException(status_code=409, detail="Campaign transition is not allowed")
        result = await postgres_repository.update_campaign_status(
            campaign_id=uuid.UUID(campaign_id),
            hospital_id=principal.hospital_id,
            actor_id=principal.user_id,
            status=request.status,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        return result
    campaign = operations.campaigns.get(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    enforce_tenant(principal, uuid.UUID(campaign["hospital_id"]))
    current = CampaignStatus(campaign["status"])
    if request.status not in ALLOWED_TRANSITIONS.get(current, set()):
        raise HTTPException(status_code=409, detail="Campaign transition is not allowed")
    campaign["status"] = request.status.value
    operations.record_audit(
        campaign["hospital_id"],
        principal.user_id,
        "campaign.status_changed",
        "campaign",
        campaign_id,
        {"from": current.value, "to": request.status.value},
    )
    return campaign


@app.get("/api/v1/escalations")
async def list_escalations(
    principal: Principal = Depends(current_principal),
) -> list[dict]:
    if get_settings().persistence_enabled:
        if principal.hospital_id is None:
            raise HTTPException(status_code=422, detail="A hospital context is required")
        return await postgres_repository.list_escalations(principal.hospital_id)
    return operations.tenant_rows(list(operations.escalations.values()), principal.hospital_id)


@app.patch("/api/v1/escalations/{escalation_id}")
async def update_escalation(
    escalation_id: str,
    request: EscalationUpdateRequest,
    principal: Principal = Depends(require_roles(Role.HOSPITAL_ADMIN, Role.CLINICAL_REVIEWER)),
) -> dict:
    if get_settings().persistence_enabled:
        if principal.hospital_id is None:
            raise HTTPException(status_code=422, detail="A hospital context is required")
        rows = await postgres_repository.list_escalations(principal.hospital_id)
        escalation = next(
            (item for item in rows if item["id"] == escalation_id),
            None,
        )
        if escalation is None:
            raise HTTPException(status_code=404, detail="Escalation not found")
        current = EscalationStatus(escalation["status"])
        if request.status not in ESCALATION_TRANSITIONS.get(current, set()):
            raise HTTPException(
                status_code=409,
                detail="Escalation transition is not allowed",
            )
        assigned_to = request.assigned_to or escalation["assigned_to"]
        if (
            request.status in {EscalationStatus.ASSIGNED, EscalationStatus.IN_REVIEW}
            and not assigned_to
        ):
            raise HTTPException(
                status_code=422,
                detail="A reviewer assignment is required",
            )
        if request.status == EscalationStatus.RESOLVED and not request.resolution:
            raise HTTPException(status_code=422, detail="Resolution is required")
        result = await postgres_repository.update_escalation(
            escalation_id=uuid.UUID(escalation_id),
            hospital_id=principal.hospital_id,
            actor_id=principal.user_id,
            status=request.status.value,
            assigned_to=assigned_to,
            resolution=request.resolution,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Escalation not found")
        return result
    escalation = operations.escalations.get(escalation_id)
    if escalation is None:
        raise HTTPException(status_code=404, detail="Escalation not found")
    enforce_tenant(principal, uuid.UUID(escalation["hospital_id"]))
    current = EscalationStatus(escalation["status"])
    if request.status not in ESCALATION_TRANSITIONS.get(current, set()):
        raise HTTPException(status_code=409, detail="Escalation transition is not allowed")
    assigned_to = request.assigned_to or escalation["assigned_to"]
    if (
        request.status in {EscalationStatus.ASSIGNED, EscalationStatus.IN_REVIEW}
        and not assigned_to
    ):
        raise HTTPException(status_code=422, detail="A reviewer assignment is required")
    if request.status == EscalationStatus.RESOLVED and not request.resolution:
        raise HTTPException(status_code=422, detail="Resolution is required")
    escalation.update(
        status=request.status.value,
        assigned_to=assigned_to,
        resolution=request.resolution,
        resolved_at=(
            datetime.now(UTC).isoformat()
            if request.status == EscalationStatus.RESOLVED
            else escalation.get("resolved_at")
        ),
    )
    operations.record_audit(
        escalation["hospital_id"],
        principal.user_id,
        "escalation.updated",
        "escalation",
        escalation_id,
        {
            **request.model_dump(mode="json"),
            "from": current.value,
            "to": request.status.value,
        },
    )
    return escalation


@app.get("/api/v1/protocols")
async def list_protocols(
    principal: Principal = Depends(current_principal),
) -> list[dict]:
    if principal.hospital_id is None:
        raise HTTPException(status_code=422, detail="A hospital context is required")
    if not get_settings().persistence_enabled:
        return []
    return await postgres_repository.list_protocols(principal.hospital_id)


@app.get("/api/v1/knowledge/search")
async def search_knowledge(
    q: str = Query(min_length=2, max_length=200),
    principal: Principal = Depends(current_principal),
) -> dict:
    if principal.hospital_id is None:
        raise HTTPException(status_code=422, detail="A hospital context is required")
    if not get_settings().persistence_enabled:
        return {"query": q, "sources": []}
    sources = await postgres_repository.search_knowledge(principal.hospital_id, q)
    return {
        "query": q,
        "tenant_id": str(principal.hospital_id),
        "sources": sources,
        "grounding_policy": (
            "Only active resources belonging to the authenticated hospital are returned."
        ),
    }


@app.get("/api/v1/ai-usage")
async def list_ai_usage(
    principal: Principal = Depends(require_roles(Role.PLATFORM_ADMIN, Role.HOSPITAL_ADMIN)),
) -> list[dict]:
    if not get_settings().persistence_enabled:
        return []
    hospital_id = None if principal.role == Role.PLATFORM_ADMIN else principal.hospital_id
    return await postgres_repository.list_ai_usage(hospital_id)


@app.post("/api/v1/triage")
async def run_triage(
    request: TriageRequest,
    principal: Principal = Depends(require_roles(Role.HOSPITAL_ADMIN, Role.CLINICAL_REVIEWER)),
) -> dict:
    patient = operations.patients.get(request.patient_id)
    if get_settings().persistence_enabled:
        patients = await postgres_repository.list_patients(principal.hospital_id)
        patient = next(
            (item for item in patients if item["id"] == request.patient_id),
            None,
        )
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    enforce_tenant(principal, uuid.UUID(patient["hospital_id"]))
    result = assess(request)
    if get_settings().persistence_enabled:
        ehr_record = await postgres_repository.create_triage_ehr_record(
            hospital_id=uuid.UUID(patient["hospital_id"]),
            patient_id=uuid.UUID(patient["id"]),
            actor_id=principal.user_id,
            payload=result.model_dump(mode="json"),
        )
        return {"triage": result, "mock_ehr_record": ehr_record}
    ehr_record = {
        "id": str(uuid.uuid4()),
        "hospital_id": patient["hospital_id"],
        "patient_id": patient["id"],
        "resource_type": "Observation",
        "status": "preliminary",
        "source": "structured-outreach-triage",
        "payload": result.model_dump(mode="json"),
        "created_at": datetime.now(UTC).isoformat(),
    }
    operations.ehr_records.append(ehr_record)
    operations.publish_event(
        hospital_id=patient["hospital_id"],
        event_type="ehr.sync_requested",
        aggregate_id=patient["id"],
        payload={"record_id": ehr_record["id"]},
        idempotency_key=f"ehr-sync:{ehr_record['id']}",
    )
    operations.record_audit(
        patient["hospital_id"],
        principal.user_id,
        "triage.completed",
        "patient",
        patient["id"],
        {
            "classification": result.final_classification,
            "escalation_required": result.escalation_required,
        },
    )
    return {"triage": result, "mock_ehr_record": ehr_record}


@app.post("/api/v1/conversations/simulate")
async def simulate_conversation(
    request: ConversationRequest,
    principal: Principal = Depends(
        require_roles(
            Role.HOSPITAL_ADMIN,
            Role.CAMPAIGN_MANAGER,
            Role.CLINICAL_REVIEWER,
        )
    ),
) -> dict:
    if principal.hospital_id is None:
        raise HTTPException(status_code=422, detail="A hospital context is required")
    patient = operations.patients.get(request.patient_id)
    if get_settings().persistence_enabled:
        patients = await postgres_repository.list_patients(principal.hospital_id)
        patient = next((item for item in patients if item["id"] == request.patient_id), None)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    enforce_tenant(principal, uuid.UUID(patient["hospital_id"]))

    result = run_conversation_workflow(request)
    payload = result.model_dump(mode="json")
    if get_settings().persistence_enabled:
        try:
            payload = await postgres_repository.save_conversation_workflow(
                hospital_id=principal.hospital_id,
                actor_id=principal.user_id,
                patient_id=uuid.UUID(request.patient_id),
                transcript=request.transcript,
                idempotency_key=request.idempotency_key,
                result=payload,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "workflow": payload,
        "safety_notice": (
            "Synthetic demonstration only. The workflow does not diagnose, prescribe, "
            "or change treatment."
        ),
    }


@app.post("/api/v1/voice/sessions")
async def create_voice_session(
    request: VoiceSessionRequest,
    principal: Principal = Depends(
        require_roles(
            Role.HOSPITAL_ADMIN,
            Role.CAMPAIGN_MANAGER,
            Role.CLINICAL_REVIEWER,
        )
    ),
) -> dict:
    settings = get_settings()
    if principal.hospital_id is None:
        raise HTTPException(status_code=422, detail="A hospital context is required")
    if not settings.voice_service_url:
        raise HTTPException(status_code=503, detail="Streaming voice is not configured")
    snapshot = await postgres_repository.queue_snapshot(principal.hospital_id)
    if not any(task["id"] == str(request.task_id) for task in snapshot["tasks"]):
        raise HTTPException(status_code=404, detail="Outreach task not found")
    try:
        return await voice_gateway.create_session(
            settings.voice_service_url,
            task_id=str(request.task_id),
        )
    except VoiceGatewayError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/v1/mock-ehr/records")
async def list_ehr_records(
    principal: Principal = Depends(current_principal),
) -> list[dict]:
    if get_settings().persistence_enabled:
        hospital_id = None if principal.role == Role.PLATFORM_ADMIN else principal.hospital_id
        return await postgres_repository.list_ehr_records(hospital_id)
    return operations.tenant_rows(operations.ehr_records, principal.hospital_id)


@app.get("/api/v1/audit")
async def list_audit_log(
    principal: Principal = Depends(current_principal),
) -> list[dict]:
    if get_settings().persistence_enabled:
        hospital_id = None if principal.role == Role.PLATFORM_ADMIN else principal.hospital_id
        return await postgres_repository.list_audit(hospital_id)
    return operations.tenant_rows(operations.audit_log, principal.hospital_id)


@app.get("/api/v1/evaluation/safety")
def safety_evaluation(
    _: Principal = Depends(
        require_roles(Role.PLATFORM_ADMIN, Role.HOSPITAL_ADMIN, Role.CLINICAL_REVIEWER)
    ),
) -> dict:
    return run_safety_evaluation()


@app.get("/api/v1/events")
def list_events(principal: Principal = Depends(current_principal)) -> list[dict]:
    return operations.tenant_rows(list(operations.events.values()), principal.hospital_id)


@app.post("/api/v1/workflows/process")
def process_workflows(
    principal: Principal = Depends(
        require_roles(Role.PLATFORM_ADMIN, Role.HOSPITAL_ADMIN, Role.CAMPAIGN_MANAGER)
    ),
) -> dict:
    hospital_id = None if principal.role == Role.PLATFORM_ADMIN else str(principal.hospital_id)
    return workflow_processor.process_pending(operations, hospital_id=hospital_id)


@app.post("/api/v1/workers/run-cycle")
async def run_background_cycle(
    _: Principal = Depends(
        require_roles(Role.PLATFORM_ADMIN, Role.HOSPITAL_ADMIN, Role.CAMPAIGN_MANAGER)
    ),
) -> dict:
    if not get_settings().persistence_enabled:
        raise HTTPException(status_code=409, detail="Persistent workers require PostgreSQL")
    return await run_worker_cycle()


@app.get("/api/v1/notifications")
async def list_notifications(
    principal: Principal = Depends(current_principal),
) -> list[dict]:
    if get_settings().persistence_enabled:
        hospital_id = None if principal.role == Role.PLATFORM_ADMIN else principal.hospital_id
        return await postgres_repository.list_notifications(hospital_id)
    return operations.tenant_rows(list(operations.notifications.values()), principal.hospital_id)


@app.get("/api/v1/metrics/system")
def system_metrics(principal: Principal = Depends(current_principal)) -> dict:
    events = operations.tenant_rows(list(operations.events.values()), principal.hospital_id)
    notifications = operations.tenant_rows(
        list(operations.notifications.values()), principal.hospital_id
    )
    queue = scoped_snapshot(principal)
    failed = sum(event["status"] == "failed" for event in events)
    pending = sum(event["status"] in {"pending", "retry_scheduled"} for event in events)
    cutoff_risk = sum(
        datetime.fromisoformat(task["deadline"]) <= datetime.now(UTC) + timedelta(hours=2)
        and task["state"] not in {"completed", "escalated"}
        for task in queue["tasks"]
    )
    return {
        "status": "degraded" if failed else "healthy",
        "queue_depth": sum(
            value
            for state, value in queue["state_counts"].items()
            if state in {"pending", "retry_scheduled", "callback_scheduled"}
        ),
        "active_calls": queue["active_calls"],
        "capacity": queue["capacity"],
        "cutoff_risk_tasks": cutoff_risk,
        "pending_events": pending,
        "failed_events": failed,
        "notifications_delivered": sum(item["status"] == "delivered" for item in notifications),
        "audit_records": len(operations.tenant_rows(operations.audit_log, principal.hospital_id)),
    }


static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=static_dir, html=True), name="operations-console")
