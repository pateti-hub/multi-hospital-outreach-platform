from outreach.operations import OperationsStore
from outreach.workflows import WorkflowProcessor


def test_event_publication_is_idempotent() -> None:
    store = OperationsStore()
    hospital_id = next(iter(store.hospitals))
    first, created = store.publish_event(
        hospital_id=hospital_id,
        event_type="manual_follow_up.created",
        aggregate_id="task-1",
        payload={},
        idempotency_key="manual:task-1",
    )
    second, created_again = store.publish_event(
        hospital_id=hospital_id,
        event_type="manual_follow_up.created",
        aggregate_id="task-1",
        payload={},
        idempotency_key="manual:task-1",
    )
    assert created is True
    assert created_again is False
    assert first["id"] == second["id"]


def test_escalation_event_delivers_only_one_notification() -> None:
    store = OperationsStore()
    processor = WorkflowProcessor()
    result = processor.process_pending(store)
    processor.process_pending(store)
    assert result["completed"] == 1
    assert len(store.notifications) == 1
    notification = next(iter(store.notifications.values()))
    assert notification["recipient_role"] == "clinical_reviewer"
    assert notification["status"] == "delivered"


def test_unknown_event_has_explicit_retry_state() -> None:
    store = OperationsStore()
    hospital_id = next(iter(store.hospitals))
    event, _ = store.publish_event(
        hospital_id=hospital_id,
        event_type="unsupported.event",
        aggregate_id="unknown",
        payload={},
        idempotency_key="unsupported:1",
    )
    result = WorkflowProcessor().process_pending(store, hospital_id=hospital_id)
    assert result["retry_scheduled"] == 1
    assert event["status"] == "retry_scheduled"
    assert event["last_error"] == "Workflow validation failed"


def test_tenant_processor_does_not_consume_other_hospital() -> None:
    store = OperationsStore()
    processor = WorkflowProcessor()
    event = next(iter(store.events.values()))
    other_hospital = next(
        hospital_id for hospital_id in store.hospitals if hospital_id != event["hospital_id"]
    )
    result = processor.process_pending(store, hospital_id=other_hospital)
    assert result["selected"] == 0
    assert event["status"] == "pending"
