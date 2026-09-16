from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from outreach.config import get_settings
from outreach.main import app


def auth_headers(client: TestClient, hospital: str, role: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/demo-token",
        json={"hospital_slug": hospital, "role": role},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_health_is_public() -> None:
    assert TestClient(app).get("/api/v1/health").status_code == 200


def test_simulation_is_tenant_scoped(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    client = TestClient(app)
    headers = auth_headers(client, "mercy-general", "campaign_manager")
    response = client.get("/api/v1/simulation", headers=headers)
    assert response.status_code == 200
    assert response.json()["tasks"]
    assert {task["hospital"] for task in response.json()["tasks"]} == {"mercy-general"}
    get_settings.cache_clear()


def test_cross_tenant_queue_is_denied(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    client = TestClient(app)
    headers = auth_headers(client, "mercy-general", "hospital_admin")
    response = client.get(
        "/api/v1/hospitals/22222222-2222-4222-8222-222222222222/queue",
        headers=headers,
    )
    assert response.status_code == 403
    get_settings.cache_clear()


def test_patient_listing_is_tenant_scoped(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    client = TestClient(app)
    headers = auth_headers(client, "riverside-medical", "hospital_admin")
    response = client.get("/api/v1/patients", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) == 15
    assert {item["hospital_id"] for item in response.json()} == {
        "22222222-2222-4222-8222-222222222222"
    }
    get_settings.cache_clear()


def test_safety_evaluation_requires_authorized_role(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    client = TestClient(app)
    headers = auth_headers(client, "mercy-general", "campaign_manager")
    assert client.get("/api/v1/evaluation/safety", headers=headers).status_code == 403
    get_settings.cache_clear()


def test_discharge_import_is_validated_and_idempotent(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    client = TestClient(app)
    headers = auth_headers(client, "mercy-general", "hospital_admin")
    discharged = datetime.now(UTC) - timedelta(hours=2)
    payload = {
        "records": [
            {
                "external_patient_id": "IMPORT-TEST-001",
                "name": {"given": "Synthetic", "family": "Import"},
                "phone": "+15551234567",
                "encounter_id": "ENC-001",
                "care_setting": "inpatient",
                "discharged_at": discharged.isoformat(),
                "follow_up_deadline": (discharged + timedelta(hours=48)).isoformat(),
                "condition_codes": ["Z48.81"],
                "discharge_instructions": "Follow the approved care plan.",
                "medication_summary": ["Synthetic medication record"],
                "risk": "moderate",
                "consent_for_outreach": True,
                "preferred_language": "en",
            }
        ]
    }
    first = client.post("/api/v1/discharges/import", headers=headers, json=payload)
    second = client.post("/api/v1/discharges/import", headers=headers, json=payload)
    assert first.status_code == 202
    assert first.json()["imported"] == 1
    assert second.json()["duplicates"] == 1
    get_settings.cache_clear()


def test_workflow_and_notifications_are_tenant_scoped(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    client = TestClient(app)
    riverside = auth_headers(client, "riverside-medical", "hospital_admin")
    mercy = auth_headers(client, "mercy-general", "hospital_admin")
    result = client.post("/api/v1/workflows/process", headers=riverside)
    assert result.status_code == 200
    notifications = client.get("/api/v1/notifications", headers=riverside).json()
    assert notifications
    assert all(
        item["hospital_id"] == "22222222-2222-4222-8222-222222222222" for item in notifications
    )
    assert client.get("/api/v1/notifications", headers=mercy).json() == []
    get_settings.cache_clear()
