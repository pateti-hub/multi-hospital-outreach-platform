import uuid

import pytest

from outreach.ehr import EHRWriteRequest, mock_ehr


def test_mock_ehr_enforces_authorized_tenant() -> None:
    hospital_id = uuid.uuid4()
    request = EHRWriteRequest(
        hospital_id=hospital_id,
        patient_id=uuid.uuid4(),
        resource_type="Observation",
        status="preliminary",
        source="test-triage",
        payload={"classification": "routine"},
    )

    assert mock_ehr.validate_write(request, authorized_hospital_id=hospital_id) == request
    with pytest.raises(ValueError, match="tenant boundary"):
        mock_ehr.validate_write(request, authorized_hospital_id=uuid.uuid4())


def test_mock_ehr_rejects_empty_payload() -> None:
    hospital_id = uuid.uuid4()
    request = EHRWriteRequest(
        hospital_id=hospital_id,
        patient_id=uuid.uuid4(),
        resource_type="Communication",
        status="final",
        source="test-documentation",
        payload={},
    )

    with pytest.raises(ValueError, match="cannot be empty"):
        mock_ehr.validate_write(request, authorized_hospital_id=hospital_id)
