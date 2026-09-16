# Healthcare and Operational Data Model

The relational model separates hospitals, users, patients, encounters, discharges,
protocols, campaigns, outreach tasks, call records, escalations, events, audit records,
and mock EHR resources.

Every patient-domain and operational row carries an explicit `hospital_id`. This supports
tenant-scoped indexes and PostgreSQL row-level-security policies rather than relying on
frontend filtering. External identifiers are unique within a hospital, not globally.

FHIR-shaped prototype resources include:

- `Patient`: identifier, human name, telecom and communication preference;
- `Encounter`: care setting and period;
- `Condition`: coded discharge condition;
- `CarePlan`: discharge instructions and follow-up deadline;
- `Observation`: structured patient-reported triage result;
- `Communication`: outreach attempt and outcome;
- `Task`: queue work, callback, manual follow-up or escalation.

Exact FHIR compliance is intentionally outside the prototype scope. The mock EHR adapter
is replaceable and AI components can only request validated operations through controlled
application services.

Generate 240 reproducible synthetic discharge bundles with:

```bash
python scripts/generate_synthetic_data.py --count 240 --output synthetic-discharges.json
```

Generated files are synthetic and must not be confused with real patient data.