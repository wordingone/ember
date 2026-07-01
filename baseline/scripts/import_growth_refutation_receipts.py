#!/usr/bin/env python3
"""Summarize local growth-law receipt JSONL files for the baseline packet."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            row["_line"] = line_no
            rows.append(row)
    return rows


def summarize(label: str, path: Path) -> dict[str, Any]:
    rows = load_jsonl(path)
    counts = Counter(str(row.get("arm")) for row in rows)
    by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_arm[str(row.get("arm"))].append(row)
    verdicts = [row for row in rows if row.get("arm") == "verdict"]
    latest_by_arm = {}
    for arm, arm_rows in sorted(by_arm.items()):
        if arm == "verdict":
            continue
        latest = arm_rows[-1]
        latest_by_arm[arm] = {
            "round": latest.get("round"),
            "frontier_pass_at_1": latest.get("frontier_pass_at_1"),
            "verified_fraction": latest.get("verified_fraction"),
            "growth_event": latest.get("growth_event"),
            "n_growth_events": latest.get("n_growth_events"),
            "vram_fraction": latest.get("vram_fraction"),
            "round_wall_seconds": latest.get("round_wall_seconds"),
        }
    growth_events = [row for row in rows if row.get("growth_event") is True]
    max_vram = max((float(row.get("vram_fraction") or 0.0) for row in rows), default=0.0)
    result = verdicts[-1].get("result") if verdicts else None
    return {
        "label": label,
        "sha256": sha256(path),
        "row_count": len(rows),
        "arm_counts": dict(sorted(counts.items())),
        "latest_by_arm": latest_by_arm,
        "growth_event_count": len(growth_events),
        "max_reported_vram_fraction": round(max_vram, 6),
        "latest_verdict_result": result,
        "latest_verdict_round": verdicts[-1].get("round") if verdicts else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", nargs=2, metavar=("LABEL", "PATH"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    failures: list[dict[str, Any]] = []
    summaries = []
    for label, raw_path in args.input:
        path = Path(raw_path).resolve()
        if not path.exists():
            failures.append({"code": "input_missing", "label": label})
            continue
        try:
            summaries.append(summarize(label, path))
        except Exception as exc:
            failures.append({"code": "input_parse_failed", "label": label, "error": str(exc)})

    summary_by_label = {row["label"]: row for row in summaries}
    v4 = summary_by_label.get("v4_growth_run")
    if not v4:
        failures.append({"code": "v4_growth_run_missing"})
    else:
        if v4.get("arm_counts", {}).get("G", 0) < 12:
            failures.append({"code": "v4_g_arm_too_short", "actual": v4.get("arm_counts", {}).get("G")})
        if v4.get("growth_event_count", 0) < 1:
            failures.append({"code": "v4_growth_events_absent", "actual": v4.get("growth_event_count")})
        if str(v4.get("latest_verdict_result", "")).startswith("INCONCLUSIVE") is not True:
            failures.append({"code": "v4_unexpected_verdict", "actual": v4.get("latest_verdict_result")})

    v3 = summary_by_label.get("v3_matched_controls")
    if not v3:
        failures.append({"code": "v3_matched_controls_missing"})
    else:
        for arm in ("G", "F", "B0", "R"):
            if v3.get("arm_counts", {}).get(arm, 0) < 8:
                failures.append({"code": "v3_control_arm_too_short", "arm": arm, "actual": v3.get("arm_counts", {}).get(arm)})

    result = {
        "schema": "baseline.growth_refutation_import.v1",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "GROWTH_REFUTATION_RECEIPTS_IMPORTED" if not failures else "GROWTH_REFUTATION_RECEIPTS_IMPORT_FAILED",
        "failure_count": len(failures),
        "failures": failures,
        "inputs": summaries,
        "evidence_interpretation": {
            "v4_growth_arm": "The v4 growth arm executed 12 rounds and recorded real growth events, then ended with an insufficient-seed verdict rather than a win.",
            "v3_controls": "The v3 receipt contains matched G/F/B0/R control arms for eight rounds, but it used the earlier jam calibration and is not a v4 replacement.",
            "claim_status": "UNSATISFIED: the growth-law or keystone claim still needs matched v4 controls and enough seeds before any field-level architecture-growth claim.",
        },
        "next_repair": "Run matched v4 control arms or a complete multi-seed growth-law packet under the predeclared compute budget; do not recompute completed v3/v4 rows unless the parser identifies a concrete invalid row.",
        "completion_limit": "This imports and summarizes existing growth-law receipts only. It is negative/partial evidence, not an architecture-growth win and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
