# Safety Evaluation

The fixed synthetic dataset covers routine, concerning, urgent, ambiguous,
incomplete-information, and adversarial instructions. Run it with:

```bash
python -c "from pprint import pprint; from outreach.safety import run_safety_evaluation; pprint(run_safety_evaluation())"
```

The API exposes the same report at `GET /api/v1/evaluation/safety` to authorized hospital
administrators and clinical reviewers.

Metrics include true positives, false positives, true negatives, false negatives, and the
false-negative rate. The expected baseline has zero false negatives. This result only
describes the small synthetic fixture and is **not evidence of clinical validity**.

Safety regressions should block deployment. New protocols, prompts, models, retrieval
changes, and consensus changes require rerunning the fixed suite and comparing results.