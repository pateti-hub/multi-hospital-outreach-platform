import uuid

from outreach.config import get_settings
from outreach.worker import run_worker_cycle


async def test_worker_cycle_advances_tenants_and_delivers_notifications(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTO_QUEUE_ENABLED", "true")
    get_settings.cache_clear()
    hospital_ids = [uuid.uuid4(), uuid.uuid4()]
    advanced: list[uuid.UUID] = []

    async def hospitals(_: None) -> list[dict]:
        return [{"id": str(item)} for item in hospital_ids]

    async def advance(hospital_id: uuid.UUID) -> dict:
        advanced.append(hospital_id)
        return {}

    async def deliver() -> int:
        return 3

    monkeypatch.setattr("outreach.worker.postgres_repository.list_hospitals", hospitals)
    monkeypatch.setattr("outreach.worker.postgres_repository.advance_queue", advance)
    monkeypatch.setattr(
        "outreach.worker.postgres_repository.deliver_pending_escalation_notifications",
        deliver,
    )

    result = await run_worker_cycle()
    assert advanced == hospital_ids
    assert result == {"hospitals_advanced": 2, "notifications_delivered": 3}
    get_settings.cache_clear()
