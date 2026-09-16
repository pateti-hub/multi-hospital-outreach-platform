from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from outreach.config import get_settings
from outreach.enums import CampaignStatus, Role
from outreach.security import (
    Principal,
    create_access_token,
    current_principal,
    enforce_tenant,
    require_roles,
)
from outreach.simulation import QueueSimulation

app = FastAPI(
    title="Multi-Hospital Post-Discharge Outreach Platform",
    version="0.1.0",
    description="Synthetic-data prototype. Not for clinical use.",
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