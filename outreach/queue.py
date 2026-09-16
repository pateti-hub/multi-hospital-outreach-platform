from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from outreach.enums import RiskLevel

RISK_POINTS = {
    RiskLevel.LOW: 10.0,
    RiskLevel.MODERATE: 30.0,
    RiskLevel.HIGH: 60.0,
    RiskLevel.CRITICAL: 100.0,
}


@dataclass(frozen=True)
class PriorityInputs:
    risk: RiskLevel
    discharged_at: datetime
    deadline: datetime
    campaign_weight: float = 1.0
    attempts: int = 0
    callback_at: datetime | None = None
    last_attempt_at: datetime | None = None


def calculate_priority(inputs: PriorityInputs, now: datetime | None = None) -> float:
    """Calculate an explainable score; larger values are selected first."""
    now = now or datetime.now(UTC)
    hours_old = max(0.0, (now - inputs.discharged_at).total_seconds() / 3600)
    hours_left = (inputs.deadline - now).total_seconds() / 3600
    if hours_left <= 0:
        deadline_points = 120.0
    elif hours_left <= 2:
        deadline_points = 90.0
    elif hours_left <= 6:
        deadline_points = 60.0
    elif hours_left <= 24:
        deadline_points = 35.0
    else:
        deadline_points = max(0.0, 24.0 - hours_left / 6)

    callback_points = 0.0
    if inputs.callback_at:
        callback_seconds = (inputs.callback_at - now).total_seconds()
        callback_points = 70.0 if callback_seconds <= 0 else 40.0 if callback_seconds <= 1800 else 0

    recent_penalty = 0.0
    if inputs.last_attempt_at:
        minutes = (now - inputs.last_attempt_at).total_seconds() / 60
        recent_penalty = 80.0 if minutes < 30 else 25.0 if minutes < 120 else 0

    raw = (
        RISK_POINTS[inputs.risk]
        + deadline_points
        + min(30.0, hours_old * 0.75)
        + callback_points
        + min(18.0, inputs.attempts * 6.0)
        - recent_penalty
    )
    return round(raw * max(0.1, inputs.campaign_weight), 2)


def retry_delay_minutes(outcome: str, attempt_count: int) -> int | None:
    """Return outcome-aware backoff; None means manual follow-up."""
    if attempt_count >= 3:
        return None
    base = {
        "busy": 15,
        "no_answer": 60,
        "voicemail": 180,
        "dropped": 10,
        "network_failure": 5,
    }.get(outcome, 30)
    return min(720, base * (2 ** max(0, attempt_count - 1)))