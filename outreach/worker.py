from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid

from outreach.config import get_settings
from outreach.repository import postgres_repository

logger = logging.getLogger("outreach.worker")


async def run_worker_cycle() -> dict[str, int]:
    settings = get_settings()
    advanced = 0
    if settings.auto_queue_enabled:
        hospitals = await postgres_repository.list_hospitals(None)
        for hospital in hospitals:
            await postgres_repository.advance_queue(uuid.UUID(hospital["id"]))
            advanced += 1
    delivered = await postgres_repository.deliver_pending_escalation_notifications()
    return {"hospitals_advanced": advanced, "notifications_delivered": delivered}


async def worker_loop() -> None:
    """Continuously deliver persistent workflow side effects.

    Queue selection remains explicitly controllable in the evaluator simulation;
    this worker handles safe background effects and recovery.
    """
    settings = get_settings()
    while True:
        try:
            result = await run_worker_cycle()
            if result["notifications_delivered"]:
                logger.info(
                    "Delivered %s operational notification(s)",
                    result["notifications_delivered"],
                )
        except Exception:
            # The operational state remains retryable in PostgreSQL. Avoid
            # logging patient content or connection credentials.
            logger.exception("Background workflow cycle failed")
        await asyncio.sleep(settings.worker_interval_seconds)


async def stop_worker(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
