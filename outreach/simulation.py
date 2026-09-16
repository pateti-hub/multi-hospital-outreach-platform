from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from outreach.enums import OutreachState, RiskLevel
from outreach.queue import PriorityInputs, calculate_priority, retry_delay_minutes


@dataclass
class SimulatedTask:
    id: str
    patient_ref: str
    hospital: str
    risk: RiskLevel
    discharged_at: datetime
    deadline: datetime
    state: OutreachState = OutreachState.PENDING
    attempts: int = 0
    callback_at: datetime | None = None
    priority: float = 0
    last_outcome: str | None = None


class QueueSimulation:
    outcomes = [
        "completed",
        "completed",
        "completed",
        "no_answer",
        "busy",
        "voicemail",
        "dropped",
        "callback",
        "escalated",
    ]

    def __init__(self, seed: int = 42, capacity: int = 3) -> None:
        self.random = random.Random(seed)
        self.capacity = capacity
        self.peak_concurrency = 0
        self.now = datetime.now(UTC)
        self.tasks = self._make_tasks(30)

    def _make_tasks(self, count: int) -> list[SimulatedTask]:
        risks = [RiskLevel.LOW, RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.CRITICAL]
        result = []
        for index in range(count):
            discharged = self.now - timedelta(hours=self.random.randint(1, 48))
            task = SimulatedTask(
                id=f"task-{index + 1:03}",
                patient_ref=f"SYN-{index + 1:04}",
                hospital="mercy-general" if index % 2 == 0 else "riverside-medical",
                risk=self.random.choices(risks, weights=[45, 30, 20, 5], k=1)[0],
                discharged_at=discharged,
                deadline=discharged + timedelta(hours=self.random.choice([24, 48, 72])),
            )
            task.priority = self._priority(task)
            result.append(task)
        return result

    def _priority(self, task: SimulatedTask) -> float:
        return calculate_priority(
            PriorityInputs(
                risk=task.risk,
                discharged_at=task.discharged_at,
                deadline=task.deadline,
                attempts=task.attempts,
                callback_at=task.callback_at,
            ),
            self.now,
        )

    def step(self) -> dict:
        # Complete work reserved in the previous tick. Keeping CALLING as a
        # durable state makes capacity usage visible and crash recovery testable.
        for task in [item for item in self.tasks if item.state == OutreachState.CALLING]:
            self._complete_call(task)

        eligible = [
            task
            for task in self.tasks
            if task.state
            in {
                OutreachState.PENDING,
                OutreachState.RETRY_SCHEDULED,
                OutreachState.CALLBACK_SCHEDULED,
            }
            and (task.callback_at is None or task.callback_at <= self.now)
        ]
        for task in sorted(eligible, key=lambda item: item.priority, reverse=True)[: self.capacity]:
            task.state = OutreachState.CALLING
            task.attempts += 1
            task.callback_at = None

        self.peak_concurrency = max(
            self.peak_concurrency,
            sum(task.state == OutreachState.CALLING for task in self.tasks),
        )

        self.now += timedelta(minutes=15)
        return self.snapshot()

    def _complete_call(self, task: SimulatedTask) -> None:
        outcome = self.random.choice(self.outcomes)
        task.last_outcome = outcome
        if outcome == "completed":
            task.state = OutreachState.COMPLETED
        elif outcome == "escalated":
            task.state = OutreachState.ESCALATED
        elif outcome == "callback":
            task.callback_at = self.now + timedelta(minutes=30)
            task.state = OutreachState.CALLBACK_SCHEDULED
        else:
            delay = retry_delay_minutes(outcome, task.attempts)
            if delay is None:
                task.state = OutreachState.MANUAL_FOLLOW_UP
            else:
                task.callback_at = self.now + timedelta(minutes=delay)
                task.state = OutreachState.RETRY_SCHEDULED
        task.priority = self._priority(task)

    def snapshot(self) -> dict:
        counts: dict[str, int] = {}
        for task in self.tasks:
            counts[task.state.value] = counts.get(task.state.value, 0) + 1
        return {
            "simulated_time": self.now.isoformat(),
            "capacity": self.capacity,
            "active_calls": counts.get(OutreachState.CALLING.value, 0),
            "peak_concurrency": self.peak_concurrency,
            "state_counts": counts,
            "tasks": [
                {
                    **asdict(task),
                    "risk": task.risk.value,
                    "state": task.state.value,
                    "discharged_at": task.discharged_at.isoformat(),
                    "deadline": task.deadline.isoformat(),
                    "callback_at": task.callback_at.isoformat() if task.callback_at else None,
                }
                for task in sorted(self.tasks, key=lambda item: item.priority, reverse=True)
            ],
        }
