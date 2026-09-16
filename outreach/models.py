"""Tenant-aware relational model for the prototype.

All patient-domain rows carry ``hospital_id`` even when it can be reached
through another relation. This deliberate duplication supports database row
level security and makes accidental cross-tenant queries easier to detect.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class Hospital(Base, IdMixin):
    __tablename__ = "hospitals"

    name: Mapped[str] = mapped_column(String(180), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    outbound_capacity: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="configuring", nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class TenantMixin:
    hospital_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("hospitals.id"), nullable=False, index=True
    )


class User(Base, IdMixin, TenantMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str] = mapped_column(String(180), nullable=False)
    __table_args__ = (Index("uq_user_tenant_email", "hospital_id", "email", unique=True),)


class Patient(Base, IdMixin, TenantMixin):
    __tablename__ = "patients"

    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[dict] = mapped_column(JSON, nullable=False)
    telecom: Mapped[dict] = mapped_column(JSON, nullable=False)
    communication_preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (
        Index("uq_patient_tenant_external", "hospital_id", "external_id", unique=True),
    )


class Encounter(Base, IdMixin, TenantMixin):
    __tablename__ = "encounters"

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    care_setting: Mapped[str] = mapped_column(String(80), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clinical_context: Mapped[dict] = mapped_column(JSON, default=dict)


class Discharge(Base, IdMixin, TenantMixin):
    __tablename__ = "discharges"

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    encounter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("encounters.id"), index=True)
    discharged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    follow_up_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    conditions: Mapped[list] = mapped_column(JSON, default=list)
    medications: Mapped[list] = mapped_column(JSON, default=list)
    care_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    risk_indicators: Mapped[list] = mapped_column(JSON, default=list)


class Protocol(Base, IdMixin, TenantMixin):
    __tablename__ = "protocols"

    name: Mapped[str] = mapped_column(String(180), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)


class Campaign(Base, IdMixin, TenantMixin):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(180), nullable=False)
    status: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    protocol_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("protocols.id"))
    eligibility_rules: Mapped[dict] = mapped_column(JSON, nullable=False)
    calling_window: Mapped[dict] = mapped_column(JSON, nullable=False)
    priority_weight: Mapped[int] = mapped_column(Integer, default=1)
    retry_limit: Mapped[int] = mapped_column(Integer, default=3)


class OutreachTask(Base, IdMixin, TenantMixin):
    __tablename__ = "outreach_tasks"

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    discharge_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("discharges.id"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"), index=True)
    state: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    priority_score: Mapped[int] = mapped_column(Integer, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    callback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(120))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    __table_args__ = (
        Index(
            "ix_queue_selection",
            "hospital_id",
            "state",
            "available_at",
            "priority_score",
            "deadline",
        ),
    )


class CallRecord(Base, IdMixin, TenantMixin):
    __tablename__ = "call_records"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outreach_tasks.id"), index=True)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transcript: Mapped[str | None] = mapped_column(Text)
    structured_result: Mapped[dict] = mapped_column(JSON, default=dict)
    documentation_status: Mapped[str] = mapped_column(String(40), default="pending")


class Escalation(Base, IdMixin, TenantMixin):
    __tablename__ = "escalations"

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("call_records.id"), index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    priority: Mapped[str] = mapped_column(String(30), index=True)
    trigger: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    consensus: Mapped[dict] = mapped_column(JSON, nullable=False)
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Event(Base, IdMixin, TenantMixin):
    __tablename__ = "events"

    event_type: Mapped[str] = mapped_column(String(100), index=True)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EHRRecord(Base, IdMixin, TenantMixin):
    __tablename__ = "ehr_records"

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    resource_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    source: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(Base, IdMixin, TenantMixin):
    __tablename__ = "notifications"

    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id"), index=True)
    channel: Mapped[str] = mapped_column(String(40))
    recipient_role: Mapped[str] = mapped_column(String(40), index=True)
    subject: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(40), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base, IdMixin, TenantMixin):
    __tablename__ = "audit_logs"

    actor_id: Mapped[uuid.UUID | None] = mapped_column()
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[uuid.UUID] = mapped_column(index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
