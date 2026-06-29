#!/usr/bin/env python3
"""Validate and normalize one Ember baseline verdict receipt."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

ALLOWED = {"PASS", "FAIL", "INVALID-RUN"}
REQUIRED = ["claim_id", "verdict", "contract", "metric", "threshold", "evidence"]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("receipt root must be a JSON object")
    return data


def normalize(data: dict) -> dict:
    missing = [key for key in REQUIRED if key not in data]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")
    verdict = str(data["verdict"]).upper()
    if verdict not in ALLOWED:
        raise ValueError(f"invalid verdict {data['verdict']!r}; expected one of {sorted(ALLOWED)}")
    out = dict(data)
    out["verdict"] = verdict
    out.setdefault("generated_at", _dt.datetime.now(_dt.timezone.utc).isoformat())
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, help="JSON receipt to validate and normalize")
    parser.add_argument("--pretty", action="store_true", help="pretty-print output JSON")
    args = parser.parse_args(argv)

    if not args.receipt:
        parser.print_help()
        return 0

    try:
        out = normalize(load_json(args.receipt))
    except Exception as exc:
        print(f"INVALID-RUN: {exc}", file=sys.stderr)
        return 2

    json.dump(out, sys.stdout, indent=2 if args.pretty else None, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
