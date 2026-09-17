from __future__ import annotations

import uuid
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class EHRWriteRequest(BaseModel):
    hospital_id: uuid.UUID
    patient_id: uuid.UUID
    resource_type: Literal[
        "Communication",
        "Observation",
        "Task",
        "Encounter",
        "CarePlan",
    ]
    status: Literal["preliminary", "final", "requested", "completed"]
    source: str = Field(min_length=3, max_length=120)
    payload: dict


class EHRAdapter(Protocol):
    def validate_write(
        self,
        request: EHRWriteRequest,
        *,
        authorized_hospital_id: uuid.UUID,
    ) -> EHRWriteRequest: ...


class MockEHRAdapter:
    """Replaceable validation boundary for synthetic EHR operations."""

    def validate_write(
        self,
        request: EHRWriteRequest,
        *,
        authorized_hospital_id: uuid.UUID,
    ) -> EHRWriteRequest:
        if request.hospital_id != authorized_hospital_id:
            raise ValueError("EHR tenant boundary violation")
        if not request.payload:
            raise ValueError("EHR payload cannot be empty")
        return request


mock_ehr = MockEHRAdapter()
