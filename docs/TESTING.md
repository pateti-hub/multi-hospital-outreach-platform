# Testing

## Unit and API tests

```bash
pip install -e '.[dev]'
ruff check .
pytest -q
```

Coverage includes authentication, tenant boundaries, ingestion, priority, retries,
campaign behavior, triage, escalation consensus, EHR validation, provider failures,
worker execution, notifications and voice response compatibility.

## Browser smoke test

```bash
cd e2e
npm install
npx playwright install chromium
npm test
```

Set `BASE_URL` to test another deployment. The smoke test verifies health, evaluation
access and every main dashboard section.

## Synthetic load check

```bash
python scripts/load_test.py --requests 100 --concurrency 10
```

The script performs authenticated read-only queue requests and reports successes,
failures, average latency, p95 and maximum latency. It must never use PHI.

## Safety regression

```bash
python scripts/export_safety_report.py
```

Any false negative should block submission until reviewed.