#!/usr/bin/env python3
"""Validate the training-efficiency baseline family contract."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_TEXT = [
    "Status: BASELINE_COMPLETE for the `training_efficiency_sota` family only.",
    "Claim family: `training_efficiency_sota`.",
    "modded-nanogpt",
    "54c192a77bd0e3d2572a891e0a8a1b0ceeb957d7",
    "record ID: `84`",
    "8x NVIDIA H100",
    "target validation loss: `3.28`",
    "observed final validation loss: `3.2802`",
    "checked log train time: `83855` ms",
    "Lane TE-RAW-SOTA",
    "Lane TE-4090-PARETO",
    "This lane is invalid until `single_4090_ge_1b_foundation_ceiling` is complete.",
    "no hidden hosted compute",
    "no post-hoc target change",
    "no benchmark substitution after seeing results",
    "compute-spend packet before launch",
    "TRAINING_EFFICIENCY_BASELINE_COMPLETE",
    "This file's completion does not complete the overall baseline.",
    "B0 source refresh validated",
]

REQUIRED_REFRESH_RECEIPT = "receipts/b0-modded-nanogpt-source-refresh-2026-06-30.json"
REQUIRED_REFRESH_VALIDATION = "receipts/b0-modded-nanogpt-source-refresh-validation-2026-06-30.json"

REQUIRED_SOURCE = {
    "id": "modded-nanogpt",
    "commit": "54c192a77bd0e3d2572a891e0a8a1b0ceeb957d7",
    "hardware": "8x NVIDIA H100",
    "record_id": "84",
    "record_time_ms_from_log": 83855,
    "target_val_loss": 3.28,
    "observed_final_val_loss": 3.2802,
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_sources(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                rows[row["id"]] = row
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    contract_path = root / "contracts" / "B0-modded-nanogpt-training-efficiency.md"
    lock_path = root / "completion-lock.json"
    sources_path = root / "sources.jsonl"
    failures: list[dict[str, Any]] = []

    if not contract_path.exists():
        failures.append({"code": "contract_missing", "path": str(contract_path)})
        text = ""
    else:
        text = contract_path.read_text(encoding="utf-8-sig", errors="replace")
        for needle in REQUIRED_TEXT:
            if needle not in text:
                failures.append({"code": "contract_missing_required_text", "needle": needle})

    lock = read_json(lock_path) if lock_path.exists() else {}
    family = lock.get("mandatory_claim_families", {}).get("training_efficiency_sota")
    if not isinstance(family, dict):
        failures.append({"code": "lock_family_missing"})
    else:
        expected_receipt = "receipts/training-efficiency-validation-2026-06-29.json"
        checks = {
            "status": "BASELINE_COMPLETE",
            "contract_path": "contracts/B0-modded-nanogpt-training-efficiency.md",
            "protocol_path": "protocols/protocol-v0.md",
            "verifier_receipt": expected_receipt,
        }
        for field, expected in checks.items():
            if family.get(field) != expected:
                failures.append({"code": "lock_field_mismatch", "field": field, "expected": expected, "actual": family.get(field)})
        for source_id in ("modded-nanogpt", "mlcommons-algoperf"):
            if source_id not in family.get("source_rows", []):
                failures.append({"code": "lock_missing_source_row", "id": source_id})

    refresh_path = root / REQUIRED_REFRESH_RECEIPT
    refresh_validation_path = root / REQUIRED_REFRESH_VALIDATION
    refresh = read_json(refresh_path) if refresh_path.exists() else {}
    refresh_validation = read_json(refresh_validation_path) if refresh_validation_path.exists() else {}
    if refresh.get("verdict") != "B0_SOURCE_REFRESH_CURRENT_MATCHES_LOCKED_COMPARATOR":
        failures.append({"code": "source_refresh_receipt_not_current", "actual": refresh.get("verdict")})
    if refresh_validation.get("verdict") != "B0_SOURCE_REFRESH_VALIDATED":
        failures.append({"code": "source_refresh_validation_not_pass", "actual": refresh_validation.get("verdict")})

    sources = read_sources(sources_path) if sources_path.exists() else {}
    modnano = sources.get("modded-nanogpt")
    if not isinstance(modnano, dict):
        failures.append({"code": "source_row_missing", "id": "modded-nanogpt"})
    else:
        for field, expected in REQUIRED_SOURCE.items():
            if modnano.get(field) != expected:
                failures.append({"code": "source_field_mismatch", "field": field, "expected": expected, "actual": modnano.get(field)})
        if not modnano.get("access_date"):
            failures.append({"code": "source_access_date_missing", "id": "modded-nanogpt"})
    if "mlcommons-algoperf" not in sources:
        failures.append({"code": "source_row_missing", "id": "mlcommons-algoperf"})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "TRAINING_EFFICIENCY_BASELINE_COMPLETE" if not failures else "TRAINING_EFFICIENCY_BASELINE_INCOMPLETE",
        "failure_count": len(failures),
        "failures": failures,
        "contract_path": str(contract_path),
        "source_refresh_receipt": REQUIRED_REFRESH_RECEIPT,
        "source_refresh_validation": REQUIRED_REFRESH_VALIDATION,
        "completion_limit": "This validates only the training_efficiency_sota family. It does not complete the overall baseline.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())