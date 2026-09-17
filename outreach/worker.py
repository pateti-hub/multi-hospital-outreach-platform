from __future__ import annotations

import asyncio
import contextlib
import logging

from outreach.config import get_settings
from outreach.repository import postgres_repository

logger = logging.getLogger("outreach.worker")


async def worker_loop() -> None:
    """Continuously deliver persistent workflow side effects.

    Queue selection remains explicitly controllable in the evaluator simulation;
    this worker handles safe background effects and recovery.
    """
    settings = get_settings()
    while True:
        try:
            delivered = await postgres_repository.deliver_pending_escalation_notifications()
            if delivered:
                logger.info("Delivered %s escalation notification(s)", delivered)
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
