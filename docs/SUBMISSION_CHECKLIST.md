# One-Time Submission Checklist

## Required deliverables

- [x] Public application and source repositories
- [x] README, setup, environment and deployment instructions
- [x] Database, mock EHR, queue simulation and tests
- [x] Architecture and queue design
- [x] Fixed safety dataset and report
- [x] AI and development-AI usage documentation
- [x] Assumptions, limitations and requirements traceability
- [x] Demo script and evaluator access
- [ ] Upload the supplied MP4 demo file

## Final verification

```bash
pip install -e '.[dev]'
ruff check .
pytest -q
python scripts/export_safety_report.py
python scripts/load_test.py
```

- [ ] Public URL and `/api/v1/health` work
- [ ] No secrets, `.env`, virtual environment or real PHI are uploaded
- [ ] Both repositories are public
- [ ] Demo video plays
- [ ] Limitations remain explicit
- [ ] Submit only once after every item is checked