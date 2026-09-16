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