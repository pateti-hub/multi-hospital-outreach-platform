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

## Version 1.0 baseline

| Metric | Result |
|---|---:|
| Cases | 10 |
| True positives | 8 |
| False positives | 0 |
| True negatives | 2 |
| False negatives | 0 |
| False-negative rate | 0.0 |

The two assessment paths may disagree. Consensus selects the higher-severity result
and routes disagreement or uncertainty to human review.

Safety regressions should block deployment. New protocols, prompts, models, retrieval
changes, and consensus changes require rerunning the fixed suite and comparing results.