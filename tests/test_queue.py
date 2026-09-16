from datetime import UTC, datetime, timedelta

from outreach.enums import RiskLevel
from outreach.queue import PriorityInputs, calculate_priority, retry_delay_minutes
from outreach.simulation import QueueSimulation


def inputs(risk: RiskLevel, deadline_hours: int) -> PriorityInputs:
    now = datetime.now(UTC)
    return PriorityInputs(
        risk=risk,
        discharged_at=now - timedelta(hours=12),
        deadline=now + timedelta(hours=deadline_hours),
    )


def test_deadline_pressure_can_outrank_lower_urgency_work() -> None:
    now = datetime.now(UTC)
    near_deadline = calculate_priority(inputs(RiskLevel.MODERATE, 1), now)
    distant_deadline = calculate_priority(inputs(RiskLevel.MODERATE, 48), now)
    assert near_deadline > distant_deadline


def test_critical_risk_receives_more_weight() -> None:
    now = datetime.now(UTC)
    assert calculate_priority(inputs(RiskLevel.CRITICAL, 24), now) > calculate_priority(
        inputs(RiskLevel.LOW, 24), now
    )


def test_retry_backoff_and_manual_follow_up() -> None:
    assert retry_delay_minutes("busy", 1) == 15
    assert retry_delay_minutes("busy", 2) == 30
    assert retry_delay_minutes("busy", 3) is None


def test_simulation_never_exceeds_capacity() -> None:
    simulation = QueueSimulation(seed=7, capacity=3)
    for _ in range(40):
        snapshot = simulation.step()
        assert snapshot["active_calls"] <= snapshot["capacity"]
    assert snapshot["peak_concurrency"] == 3
