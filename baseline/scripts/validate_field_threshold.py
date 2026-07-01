#!/usr/bin/env python3
"""Validate the field-level contribution threshold document."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_AXES = ["FL-4090-1B", "FL-TRAIN-EFF", "FL-DATA-EFF", "FL-ARCH-GROW", "FL-SELF-IMPROVE", "FL-RUNTIME-GOV"]
REQUIRED_HEADERS = ["Required comparator", "Metric", "Threshold", "Constraints", "Budget", "Verifier", "Falsifier"]
DOWNGRADE_PHRASES = ["one governed trial", "one negative result", "static-only", "single-4090", "operator acceptance", "remote proof", "line endings"]


def validate(text: str) -> list[dict]:
    failures = []
    for phrase in REQUIRED_HEADERS:
        if phrase not in text:
            failures.append({"code": "missing_table_header", "value": phrase})
    for axis in REQUIRED_AXES:
        match = re.search(rf"\| {re.escape(axis)} \|(.+)", text)
        if not match:
            failures.append({"code": "missing_axis", "axis": axis})
            continue
        row = match.group(0)
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        if len(cells) < 9:
            failures.append({"code": "axis_row_too_short", "axis": axis, "cell_count": len(cells)})
            continue
        for idx, label in enumerate(["axis", "claim", "comparator", "metric", "threshold", "constraints", "budget", "verifier", "falsifier"]):
            if not cells[idx] or cells[idx] in {"-", "TBD", "TODO"}:
                failures.append({"code": "axis_cell_missing", "axis": axis, "cell": label})
    for phrase in DOWNGRADE_PHRASES:
        if phrase.lower() not in text.lower():
            failures.append({"code": "missing_downgrade_phrase", "value": phrase})
    if "This file's completion does not complete the overall baseline" not in text:
        failures.append({"code": "missing_noncompletion_boundary"})
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    text = args.threshold.read_text(encoding="utf-8-sig", errors="replace")
    failures = validate(text)
    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "FIELD_THRESHOLD_BASELINE_COMPLETE" if not failures else "FIELD_THRESHOLD_INVALID",
        "threshold_path": str(args.threshold),
        "failure_count": len(failures),
        "failures": failures,
        "completion_limit": "This validates only the field_level_contribution_threshold family. It does not complete the overall baseline.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
