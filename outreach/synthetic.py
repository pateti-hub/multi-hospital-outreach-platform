from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta


def generate_discharge_feed(count: int = 240, seed: int = 2026) -> list[dict]:
    """Create reproducible, clearly synthetic FHIR-shaped discharge records."""
    if not 1 <= count <= 500:
        raise ValueError("count must be between 1 and 500")
    randomizer = random.Random(seed)
    conditions = [
        ("I50.9", "Heart failure follow-up"),
        ("J18.9", "Pneumonia recovery"),
        ("Z48.81", "Post-surgical care"),
        ("E11.9", "Diabetes management"),
    ]
    risks = ["low", "moderate", "high", "critical"]
    records = []
    now = datetime.now(UTC).replace(microsecond=0)
    for index in range(count):
        discharged_at = now - timedelta(hours=randomizer.randint(1, 72))
        window = randomizer.choice([24, 48, 72])
        condition_code, instruction = randomizer.choice(conditions)
        records.append(
            {
                "resourceType": "Bundle",
                "type": "collection",
                "synthetic": True,
                "patient": {
                    "resourceType": "Patient",
                    "identifier": f"SYN-BULK-{index + 1:04}",
                    "name": {
                        "given": f"Synthetic{index + 1:04}",
                        "family": "Patient",
                    },
                    "telecom": {"phone": f"+15551{index + 1:06}"},
                    "communication": {"language": randomizer.choice(["en", "es", "hi"])},
                },
                "encounter": {
                    "resourceType": "Encounter",
                    "identifier": f"ENC-BULK-{index + 1:04}",
                    "class": randomizer.choice(["inpatient", "emergency", "observation"]),
                    "period": {"end": discharged_at.isoformat()},
                },
                "condition": {
                    "resourceType": "Condition",
                    "code": condition_code,
                },
                "carePlan": {
                    "resourceType": "CarePlan",
                    "instruction": instruction,
                    "followUpDeadline": (discharged_at + timedelta(hours=window)).isoformat(),
                },
                "risk": randomizer.choices(risks, weights=[45, 30, 20, 5], k=1)[0],
                "expectedOutreachOutcome": randomizer.choice(
                    [
                        "completed",
                        "no_answer",
                        "busy",
                        "voicemail",
                        "dropped",
                        "callback",
                        "escalated",
                    ]
                ),
            }
        )
    return records
