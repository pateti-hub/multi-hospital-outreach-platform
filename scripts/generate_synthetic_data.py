#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from outreach.synthetic import generate_discharge_feed


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic discharge records")
    parser.add_argument("--count", type=int, default=240)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--output", type=Path, default=Path("synthetic-discharges.json"))
    args = parser.parse_args()
    payload = {
        "notice": "Synthetic data only. Contains no real patient information.",
        "records": generate_discharge_feed(args.count, args.seed),
    }
    args.output.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {len(payload['records'])} synthetic records to {args.output}")


if __name__ == "__main__":
    main()
