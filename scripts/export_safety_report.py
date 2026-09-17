from __future__ import annotations

import json
from pathlib import Path

from outreach.safety import run_safety_evaluation


def main() -> None:
    output = Path("reports/safety-evaluation-v1.1.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(run_safety_evaluation(), indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
