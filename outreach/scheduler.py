from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from outreach.enums import OutreachState
from outreach.models import AuditLog, OutreachTask


class DurableScheduler:
    """PostgreSQL-backed queue reservation and stale-lease recovery."""

    async def reserve(
        self,
        session: AsyncSession,
        *,
        hospital_id: uuid.UUID,
        worker_id: str,
        capacity: int,
        lease_seconds: int,
    ) -> list[OutreachTask]:
        now = datetime.now(UTC)
        async with session.begin():
            # Serialize capacity accounting per tenant while allowing hospitals
            # and workers to schedule independently.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:tenant))"),
                {"tenant": str(hospital_id)},
            )
            active = await session.scalar(
                select(func.count())
                .select_from(OutreachTask)
                .where(
                    OutreachTask.hospital_id == hospital_id,
                    OutreachTask.state == OutreachState.CALLING.value,
                    OutreachTask.lease_expires_at > now,
                )
            )
            available_capacity = max(0, capacity - int(active or 0))
            if available_capacity == 0:
                return []

            statement = (
                select(OutreachTask)
                .where(
                    OutreachTask.hospital_id == hospital_id,
                    OutreachTask.state.in_(
                        [
                            OutreachState.PENDING.value,
                            OutreachState.RETRY_SCHEDULED.value,
                            OutreachState.CALLBACK_SCHEDULED.value,
                        ]
                    ),
                    OutreachTask.available_at <= now,
                    OutreachTask.deadline > now,
                )
                .order_by(
                    OutreachTask.priority_score.desc(),
                    OutreachTask.deadline.asc(),
                    OutreachTask.id.asc(),
                )
                .limit(available_capacity)
                .with_for_update(skip_locked=True)
            )
            tasks = list((await session.scalars(statement)).all())
            lease_expiry = now + timedelta(seconds=lease_seconds)
            for task in tasks:
                task.state = OutreachState.CALLING.value
                task.lease_owner = worker_id
                task.lease_expires_at = lease_expiry
                task.attempt_count += 1
            return tasks

    async def heartbeat(
        self,
        session: AsyncSession,
        *,
        task_id: uuid.UUID,
        worker_id: str,
        lease_seconds: int,
    ) -> bool:
        result = await session.execute(
            update(OutreachTask)
            .where(
                OutreachTask.id == task_id,
                OutreachTask.lease_owner == worker_id,
                OutreachTask.state == OutreachState.CALLING.value,
            )
            .values(lease_expires_at=datetime.now(UTC) + timedelta(seconds=lease_seconds))
        )
        await session.commit()
        return bool(result.rowcount)

    async def recover_stale(self, session: AsyncSession, hospital_id: uuid.UUID) -> int:
        now = datetime.now(UTC)
        async with session.begin():
            tasks = list(
                (
                    await session.scalars(
                        select(OutreachTask)
                        .where(
                            OutreachTask.hospital_id == hospital_id,
                            OutreachTask.state == OutreachState.CALLING.value,
                            OutreachTask.lease_expires_at <= now,
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for task in tasks:
                task.state = OutreachState.RETRY_SCHEDULED.value
                task.available_at = now + timedelta(minutes=5)
                task.lease_owner = None
                task.lease_expires_at = None
                session.add(
                    AuditLog(
                        hospital_id=hospital_id,
                        actor_id=None,
                        action="queue.stale_lease_recovered",
                        resource_type="outreach_task",
                        resource_id=task.id,
                        occurred_at=now,
                        details={"recovery": "retry_in_5_minutes"},
                    )
                )
            return len(tasks)


durable_scheduler = DurableScheduler()
