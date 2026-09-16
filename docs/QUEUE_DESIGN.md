# Queue Design

## State machine

Tasks move through `PENDING`, `SCHEDULED`, `CALLING`, `CONNECTED`, terminal call
outcomes, `RETRY_SCHEDULED`, `CALLBACK_SCHEDULED`, `ESCALATED`,
`MANUAL_FOLLOW_UP`, or `FAILED`. Dropped calls retain their prior structured context.

## Priority

The explainable score is:

```text
(risk + deadline pressure + age + callback urgency + retry urgency
 - recent-attempt penalty) * campaign weight
```

Clinical deadline pressure rises sharply inside 24, 6, and 2 hours. Expired windows
receive the highest deadline score and should be surfaced for manual handling rather
than silently discarded. Age adds bounded fairness so lower-risk work cannot starve.
Due callbacks receive a strong boost, while recent attempts are penalized.

## Capacity and duplicate prevention

The simulator has a strict global capacity and exposes active and peak concurrency.
The persistent scheduler design uses one transaction to:

1. lock the hospital capacity row;
2. count unexpired leases;
3. select eligible tasks ordered by score and deadline using
   `FOR UPDATE SKIP LOCKED`;
4. assign a unique lease owner and expiry;
5. commit reservations before making external calls.

Unique idempotency keys prevent duplicate calls and duplicate outcome side effects.

## Retries and callbacks

- network failure: 5 minutes, exponential backoff;
- dropped call: 10 minutes;
- busy: 15 minutes;
- no answer: 60 minutes;
- voicemail: 180 minutes;
- maximum three attempts, then `MANUAL_FOLLOW_UP`.

Backoff is also constrained by tenant calling hours, patient preferences, and the
clinical cutoff. Requested callbacks use `CALLBACK_SCHEDULED` and are not returned to
the generic queue until due.

## Recovery

Workers renew leases with heartbeats. A recovery job identifies expired leases, writes
an audit event, releases capacity, and schedules a safe retry or manual follow-up.
Campaign pause stops new reservations but does not terminate active calls. Resume
recalculates eligibility and priority.