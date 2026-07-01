#!/usr/bin/env python3
"""Validate the B0 Modded-NanoGPT source-refresh receipt."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/b0-modded-nanogpt-source-refresh-2026-06-30.json"
EXPECTED = {
    "source_id": "modded-nanogpt",
    "benchmark": "NanoGPT speedrun track_1_short",
    "hardware": "8x NVIDIA H100",
    "target_val_loss": 3.28,
    "current_record_id": "84",
    "current_record_time_minutes": 1.320,
    "current_record_date": "2026-05-21",
    "current_record_log_path": "records/track_1_short/2026-05-19_FP8MLPUpProj/this_record/008bb79d-d5bc-4205-bd4e-5e4ae82e658c.txt",
    "contract_commit": "54c192a77bd0e3d2572a891e0a8a1b0ceeb957d7",
}
FORBIDDEN = ["C:" + "/" + "tmp", "C:" + "\\" + "tmp", "B:" + "/" + "M", "B:" + "\\" + "M", "C:" + "/" + "Users" + "/" + "Admin", "C:" + "\\" + "Users" + "\\" + "Admin"]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    path = root / RECEIPT
    receipt = read_json(path) if path.exists() else {}
    failures: list[dict[str, Any]] = []
    if receipt.get("schema") != "b0.modded_nanogpt.source_refresh.v1":
        failures.append({"code": "schema_mismatch", "actual": receipt.get("schema")})
    if receipt.get("verdict") != "B0_SOURCE_REFRESH_CURRENT_MATCHES_LOCKED_COMPARATOR":
        failures.append({"code": "verdict_mismatch", "actual": receipt.get("verdict")})
    for key, expected in EXPECTED.items():
        if receipt.get(key) != expected:
            failures.append({"code": "field_mismatch", "field": key, "expected": expected, "actual": receipt.get(key)})
    evidence = receipt.get("evidence", {}) if isinstance(receipt.get("evidence"), dict) else {}
    required_evidence = ["readme_url", "readme_target_quote", "readme_record_quote", "access_date"]
    for key in required_evidence:
        if not evidence.get(key):
            failures.append({"code": "evidence_field_missing", "field": key})
    limit = receipt.get("completion_limit", "")
    if "not an Ember run" not in limit or "not overall baseline completion" not in limit:
        failures.append({"code": "completion_limit_missing", "actual": limit})
    text = json.dumps(receipt, sort_keys=True)
    markers = [marker for marker in FORBIDDEN if marker in text]
    if markers:
        failures.append({"code": "receipt_contains_local_path_marker", "marker_count": len(markers)})
    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "B0_SOURCE_REFRESH_VALIDATED" if not failures else "B0_SOURCE_REFRESH_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": RECEIPT,
        "completion_limit": "This validates only current-source freshness for the B0 comparator. It is not an Ember run and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
