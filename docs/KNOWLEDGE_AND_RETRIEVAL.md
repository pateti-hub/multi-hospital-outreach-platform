# Clinical Knowledge and Tenant-Aware Retrieval

Each hospital owns versioned protocols and knowledge resources. The deployed prototype
seeds a synthetic red-flag protocol and outreach operating guidance for each tenant.

`GET /api/v1/knowledge/search?q=...` derives the tenant from the authenticated token and
queries only active resources with the same `hospital_id`. Responses preserve title,
resource type, version, source reference, and a bounded snippet. The API never accepts a
tenant identifier from the search request.

Retrieved text is untrusted evidence. It cannot modify authorization, system policy,
controlled-tool schemas, or deterministic red-flag rules. Patient messages and documents
that contain instructions such as “ignore previous rules” remain content rather than
executable policy.

The prototype uses deterministic lexical retrieval because the dataset is small. A scaled
version can add tenant-partitioned embeddings with the same metadata filter and a mandatory
post-retrieval tenant assertion. Retrieval quality should be evaluated independently from
triage safety.

Only task-specific excerpts should be sent to a model. Full patient histories and complete
hospital knowledge collections must not be loaded indiscriminately.