from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from outreach.config import get_settings
from outreach.database import close_database, initialize_database
from outreach.enums import CampaignStatus, EscalationStatus, Role
from outreach.ingestion import DischargeBatch, evaluate_eligibility
from outreach.operations import operations
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    if get_settings().persistence_enabled:
        await initialize_database()
    yield
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
def health() -> dict:
    return {
        "status": "healthy",
        "time": datetime.now(UTC).isoformat(),
        "components": {"api": "healthy", "queue_simulator": "healthy"},
    }


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
def simulation_snapshot(principal: Principal = Depends(current_principal)) -> dict:
    return scoped_snapshot(principal)


@app.post("/api/v1/simulation/step")
def step_simulation(
    principal: Principal = Depends(
        require_roles(Role.PLATFORM_ADMIN, Role.HOSPITAL_ADMIN, Role.CAMPAIGN_MANAGER)
    ),
) -> dict:
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
def list_hospitals(principal: Principal = Depends(current_principal)) -> list[dict]:
    rows = list(operations.hospitals.values())
    if principal.role == Role.PLATFORM_ADMIN:
        return rows
    return [row for row in rows if row["id"] == str(principal.hospital_id)]


@app.get("/api/v1/patients")
def list_patients(principal: Principal = Depends(current_principal)) -> list[dict]:
    return operations.tenant_rows(list(operations.patients.values()), principal.hospital_id)


@app.get("/api/v1/campaigns")
def list_campaigns(principal: Principal = Depends(current_principal)) -> list[dict]:
    return operations.tenant_rows(list(operations.campaigns.values()), principal.hospital_id)


@app.post("/api/v1/campaigns", status_code=201)
def create_campaign(
    request: CampaignCreateRequest,
    principal: Principal = Depends(require_roles(Role.HOSPITAL_ADMIN, Role.CAMPAIGN_MANAGER)),
) -> dict:
    if principal.hospital_id is None:
        raise HTTPException(status_code=422, detail="A hospital context is required")
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


@app.post("/api/v1/discharges/import", status_code=202)
def import_discharges(
    request: DischargeBatch,
    principal: Principal = Depends(require_roles(Role.HOSPITAL_ADMIN)),
) -> dict:
    if principal.hospital_id is None:
        raise HTTPException(status_code=422, detail="A hospital context is required")
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
def update_campaign_status(
    campaign_id: str,
    request: CampaignStatusRequest,
    principal: Principal = Depends(require_roles(Role.HOSPITAL_ADMIN, Role.CAMPAIGN_MANAGER)),
) -> dict:
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
def list_escalations(principal: Principal = Depends(current_principal)) -> list[dict]:
    return operations.tenant_rows(list(operations.escalations.values()), principal.hospital_id)


@app.patch("/api/v1/escalations/{escalation_id}")
def update_escalation(
    escalation_id: str,
    request: EscalationUpdateRequest,
    principal: Principal = Depends(require_roles(Role.HOSPITAL_ADMIN, Role.CLINICAL_REVIEWER)),
) -> dict:
    escalation = operations.escalations.get(escalation_id)
    if escalation is None:
        raise HTTPException(status_code=404, detail="Escalation not found")
    enforce_tenant(principal, uuid.UUID(escalation["hospital_id"]))
    if request.status == EscalationStatus.RESOLVED and not request.resolution:
        raise HTTPException(status_code=422, detail="Resolution is required")
    escalation.update(
        status=request.status.value,
        assigned_to=request.assigned_to,
        resolution=request.resolution,
    )
    operations.record_audit(
        escalation["hospital_id"],
        principal.user_id,
        "escalation.updated",
        "escalation",
        escalation_id,
        request.model_dump(mode="json"),
    )
    return escalation


@app.post("/api/v1/triage")
def run_triage(
    request: TriageRequest,
    principal: Principal = Depends(require_roles(Role.HOSPITAL_ADMIN, Role.CLINICAL_REVIEWER)),
) -> dict:
    patient = operations.patients.get(request.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    enforce_tenant(principal, uuid.UUID(patient["hospital_id"]))
    result = assess(request)
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


@app.get("/api/v1/mock-ehr/records")
def list_ehr_records(principal: Principal = Depends(current_principal)) -> list[dict]:
    return operations.tenant_rows(operations.ehr_records, principal.hospital_id)


@app.get("/api/v1/audit")
def list_audit_log(principal: Principal = Depends(current_principal)) -> list[dict]:
    return operations.tenant_rows(operations.audit_log, principal.hospital_id)


@app.get("/api/v1/evaluation/safety")
def safety_evaluation(
    _: Principal = Depends(
        require_roles(Role.PLATFORM_ADMIN, Role.HOSPITAL_ADMIN, Role.CLINICAL_REVIEWER)
    ),
) -> dict:
    return run_safety_evaluation()


static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=static_dir, html=True), name="operations-console")
