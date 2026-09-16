# 3–4 Day Prototype Plan

## Day 1 — operational foundation

- tenant-aware schema, RBAC, API skeleton;
- deterministic 30-patient queue simulation;
- explainable priority, capacity, retries, callbacks, campaign lifecycle;
- architecture, queue, and security documentation.

## Day 2 — end-to-end workflow

- discharge ingestion and eligibility;
- campaign CRUD and persistent queue leasing;
- mock EHR adapter and event outbox;
- operations console with campaign, queue, patient, and escalation views.

## Day 3 — safe AI and evaluation

- protocol retrieval constrained by tenant;
- structured triage schemas and validation;
- independent escalation assessments plus conservative consensus;
- documentation tool and mock EHR write;
- fixed safety dataset and confusion-matrix report.

## Day 4 — hardening and delivery

- failure/recovery and tenant-isolation tests;
- metrics, audit viewer, health states, and queue simulation controls;
- public deployment, demo data, architecture and AI usage docs;
- demo script/video checklist and explicit limitations.