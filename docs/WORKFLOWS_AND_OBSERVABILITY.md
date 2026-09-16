# Workflows, Notifications, and Observability

## Event processing

The prototype uses an explicit event record with tenant, type, aggregate, payload,
idempotency key, processing status, attempt count, availability time, and bounded failure
message. Duplicate publication returns the existing event.

Supported workflow examples include escalation notification, manual follow-up notification,
and mock EHR synchronization. Unknown or invalid events move to `retry_scheduled` with
exponential backoff and then to `failed` after the retry limit. Failures remain visible.

In a scaled deployment, the `events` table acts as a transactional outbox. Multiple consumers
claim rows with `FOR UPDATE SKIP LOCKED`. Every handler has its own idempotency key so a
crash after an external side effect cannot silently duplicate it.

## Tenant boundary

Events and notifications carry `hospital_id`. Tenant workers process only their hospital;
platform workers may process all hospitals. The same tenant restriction applies to APIs,
queue leases, retrieval, tools, EHR writes, analytics, and audit records.

## Notifications

The current adapter records an observable dashboard notification. Email and SMS adapters can
replace it without changing workflow policy. Delivery state, channel, recipient role,
timestamps, event link, and idempotency key are retained.

## Health and metrics

`GET /api/v1/metrics/system` reports queue depth, active capacity, cutoff-risk work, pending
and failed events, delivered notifications, and audit volume. Failed workflows degrade the
reported health state rather than being hidden.

Production telemetry should add API latency/error rates, scheduling latency, worker
heartbeats, stuck leases, EHR/provider latency, AI validation failures, model usage, estimated
cost, and correlation identifiers. Logs must avoid unnecessary patient content.