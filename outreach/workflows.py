from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from outreach.operations import OperationsStore, now_iso


class WorkflowProcessor:
    """Idempotent prototype event consumer with explicit retry state."""

    max_attempts = 3

    def process_pending(
        self,
        store: OperationsStore,
        limit: int = 25,
        hospital_id: str | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        candidates = [
            event
            for event in store.events.values()
            if event["status"] in {"pending", "retry_scheduled"}
            and datetime.fromisoformat(event["available_at"]) <= now
            and (hospital_id is None or event["hospital_id"] == hospital_id)
        ][:limit]
        completed = failed = retried = 0
        for event in candidates:
            event["attempt_count"] += 1
            try:
                self._dispatch(store, event)
                event["status"] = "completed"
                event["processed_at"] = now_iso()
                event["last_error"] = None
                completed += 1
            except (KeyError, ValueError) as error:
                # Store a bounded operational message, not raw external content.
                event["last_error"] = "Workflow validation failed"
                if event["attempt_count"] >= self.max_attempts:
                    event["status"] = "failed"
                    failed += 1
                else:
                    delay = 2 ** event["attempt_count"]
                    event["status"] = "retry_scheduled"
                    event["available_at"] = (now + timedelta(minutes=delay)).isoformat()
                    retried += 1
                store.record_audit(
                    event["hospital_id"],
                    None,
                    "workflow.processing_failed",
                    "event",
                    event["id"],
                    {"error_type": type(error).__name__, "status": event["status"]},
                )
        return {
            "selected": len(candidates),
            "completed": completed,
            "retry_scheduled": retried,
            "failed": failed,
        }

    def _dispatch(self, store: OperationsStore, event: dict) -> None:
        handlers = {
            "escalation.created": self._notify_escalation,
            "manual_follow_up.created": self._notify_manual_follow_up,
            "ehr.sync_requested": self._sync_ehr,
        }
        handler = handlers.get(event["event_type"])
        if handler is None:
            raise ValueError("Unsupported event type")
        handler(store, event)

    def _notification(
        self,
        store: OperationsStore,
        event: dict,
        *,
        channel: str,
        recipient_role: str,
        subject: str,
    ) -> None:
        idempotency_key = f"notification:{event['id']}:{channel}:{recipient_role}"
        if any(item["idempotency_key"] == idempotency_key for item in store.notifications.values()):
            return
        notification_id = str(uuid.uuid4())
        store.notifications[notification_id] = {
            "id": notification_id,
            "hospital_id": event["hospital_id"],
            "event_id": event["id"],
            "channel": channel,
            "recipient_role": recipient_role,
            "subject": subject,
            "status": "delivered",
            "idempotency_key": idempotency_key,
            "created_at": now_iso(),
            "delivered_at": now_iso(),
        }
        store.record_audit(
            event["hospital_id"],
            None,
            "notification.delivered",
            "notification",
            notification_id,
            {"channel": channel, "recipient_role": recipient_role},
        )

    def _notify_escalation(self, store: OperationsStore, event: dict) -> None:
        if event["aggregate_id"] not in store.escalations:
            raise KeyError("Escalation does not exist")
        self._notification(
            store,
            event,
            channel="dashboard",
            recipient_role="clinical_reviewer",
            subject="Urgent post-discharge escalation",
        )

    def _notify_manual_follow_up(self, store: OperationsStore, event: dict) -> None:
        self._notification(
            store,
            event,
            channel="dashboard",
            recipient_role="campaign_manager",
            subject="Manual follow-up required",
        )

    def _sync_ehr(self, store: OperationsStore, event: dict) -> None:
        record_id = event["payload"]["record_id"]
        record = next(item for item in store.ehr_records if item["id"] == record_id)
        record["status"] = "final"
        record["synced_at"] = now_iso()
        store.record_audit(
            event["hospital_id"],
            None,
            "ehr.sync_completed",
            "ehr_record",
            record_id,
        )


workflow_processor = WorkflowProcessor()
