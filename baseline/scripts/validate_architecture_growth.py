#!/usr/bin/env python3
"""Validate the architecture/growth baseline family contract."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_CONTRACT_TEXT = [
    "Status: BASELINE_COMPLETE for the `architecture_growth_keystone_sota` family only.",
    "Claim family: `architecture_growth_keystone_sota`.",
    "Lane AG-GROWTH-DELETION",
    "Lane AG-ATTENTION-MEMORY-RETRIEVAL",
    "Lane AG-DEEPSEEK-INFERENCE-TRANSFER",
    "Lane AG-LOWBIT-KERNEL-TRAINING",
    "fixed-size, scratch, random-growth, and iso-FLOP controls",
    "must lose the claimed gain when the mechanism is deleted or randomized",
    "cannot prove training speed, sample efficiency, 4090 >=1B feasibility, or keystone growth without same-axis measurement",
    "no inference-to-training transfer without same-axis measurement",
    "no forward-only kernel claim for full training speed",
    "compute-spend packet before launch",
    "ARCHITECTURE_GROWTH_BASELINE_COMPLETE",
    "This file's completion does not complete the overall baseline.",
]

REQUIRED_PROTOCOL_TEXT = [
    "Status: BASELINE_COMPLETE for the `architecture_growth_keystone_sota` family only.",
    "AG-DEEPSEEK-INFERENCE-TRANSFER",
    "AG-LOWBIT-KERNEL-TRAINING",
    "DSpark` is resolved as a DeepSeek DeepSpec draft-model algorithm",
    "Reject transfer unless the receipt measures the same model class",
    "Reject if the path lacks preserved quality, backward pass, optimizer state, or selected-hardware support.",
    "not overall `/baseline` completion",
]

REQUIRED_SOURCES = {
    "deepseek-deepspec-dspark": {"repo_commit": "6443750b5cc6317b9dfd6e971b272577281c8d1c"},
    "deepseek-open-infra-index": {},
    "bitnet": {"repo_commit": "01eb415772c342d9f20dc42772f1583ae1e5b102"},
}

GROWTH_IMPORT_RECEIPT = "receipts/growth-refutation-import-2026-06-30.json"


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


def require_text(path: Path, needles: list[str], failures: list[dict[str, Any]], label: str) -> None:
    if not path.exists():
        failures.append({"code": f"{label}_missing", "path": str(path)})
        return
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for needle in needles:
        if needle not in text:
            failures.append({"code": f"{label}_missing_required_text", "needle": needle})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    failures: list[dict[str, Any]] = []
    contract_path = root / "contracts" / "architecture-growth-keystone-sota.md"
    protocol_path = root / "protocols" / "inference-to-training-transfer-v0.md"
    lock_path = root / "completion-lock.json"
    sources_path = root / "sources.jsonl"
    growth_import_path = root / GROWTH_IMPORT_RECEIPT

    require_text(contract_path, REQUIRED_CONTRACT_TEXT, failures, "contract")
    require_text(protocol_path, REQUIRED_PROTOCOL_TEXT, failures, "protocol")

    lock = read_json(lock_path) if lock_path.exists() else {}
    family = lock.get("mandatory_claim_families", {}).get("architecture_growth_keystone_sota")
    if not isinstance(family, dict):
        failures.append({"code": "lock_family_missing"})
    else:
        expected_receipt = "receipts/architecture-growth-validation-2026-06-29.json"
        checks = {
            "status": "BASELINE_COMPLETE",
            "contract_path": "contracts/architecture-growth-keystone-sota.md",
            "protocol_path": "protocols/inference-to-training-transfer-v0.md",
            "verifier_receipt": expected_receipt,
        }
        for field, expected in checks.items():
            if family.get(field) != expected:
                failures.append({"code": "lock_field_mismatch", "field": field, "expected": expected, "actual": family.get(field)})
        for source_id in REQUIRED_SOURCES:
            if source_id not in family.get("source_rows", []):
                failures.append({"code": "lock_missing_source_row", "id": source_id})

    growth_import = read_json(growth_import_path) if growth_import_path.exists() else {}
    if growth_import.get("verdict") != "GROWTH_REFUTATION_RECEIPTS_IMPORTED":
        failures.append({"code": "growth_refutation_import_not_ready", "actual": growth_import.get("verdict")})
    labels = {row.get("label"): row for row in growth_import.get("inputs", []) if isinstance(row, dict)}
    v4 = labels.get("v4_growth_run", {})
    v3 = labels.get("v3_matched_controls", {})
    if v4.get("growth_event_count", 0) < 1 or v4.get("arm_counts", {}).get("G", 0) < 12:
        failures.append({"code": "growth_refutation_v4_growth_evidence_missing", "actual": v4})
    for arm in ("G", "F", "B0", "R"):
        if v3.get("arm_counts", {}).get(arm, 0) < 8:
            failures.append({"code": "growth_refutation_v3_control_missing", "arm": arm, "actual": v3.get("arm_counts", {}).get(arm)})

    sources = read_sources(sources_path) if sources_path.exists() else {}
    for source_id, required_fields in REQUIRED_SOURCES.items():
        row = sources.get(source_id)
        if not isinstance(row, dict):
            failures.append({"code": "source_row_missing", "id": source_id})
            continue
        if not row.get("access_date"):
            failures.append({"code": "source_access_date_missing", "id": source_id})
        for field, expected in required_fields.items():
            if row.get(field) != expected:
                failures.append({"code": "source_field_mismatch", "id": source_id, "field": field, "expected": expected, "actual": row.get(field)})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "ARCHITECTURE_GROWTH_BASELINE_COMPLETE" if not failures else "ARCHITECTURE_GROWTH_BASELINE_INCOMPLETE",
        "failure_count": len(failures),
        "failures": failures,
        "contract_path": str(contract_path),
        "protocol_path": str(protocol_path),
        "growth_refutation_import_receipt": GROWTH_IMPORT_RECEIPT,
        "growth_refutation_summary": {
            "v4_growth_event_count": v4.get("growth_event_count"),
            "v4_latest_verdict_result": v4.get("latest_verdict_result"),
            "v3_arm_counts": v3.get("arm_counts"),
            "claim_status": "UNSATISFIED until matched v4 controls and enough seeds support the growth claim",
        },
        "completion_limit": "This validates only the architecture_growth_keystone_sota family. It does not complete the overall baseline.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())