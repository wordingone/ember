#!/usr/bin/env python3
"""Validate the data-efficiency baseline family contract."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_CONTRACT_TEXT = [
    "Status: BASELINE_COMPLETE for the `data_efficiency_sota` family only.",
    "Claim family: `data_efficiency_sota`.",
    "Lane DE-LM-BABYLM",
    "Lane DE-REASON-HRM",
    "Lane DE-TABULAR-NANOTABPFN",
    "10000000",
    "100000000",
    "epoch limit: `10`",
    "27M parameters, 1000 training samples, no pretraining/CoT data",
    "0.92 minutes",
    "81x over 74.32 minute baseline",
    "22x fewer synthetic datasets",
    "no cross-lane transfer without a separate same-axis receipt",
    "no conversion of data-efficiency into raw training-speed or 4090 >=1B feasibility",
    "compute-spend packet before launch",
    "DATA_EFFICIENCY_BASELINE_COMPLETE",
    "This file's completion does not complete the overall baseline.",
]

REQUIRED_PROTOCOL_TEXT = [
    "Status: BASELINE_COMPLETE for the `data_efficiency_sota` family only.",
    "DE-LM-BABYLM",
    "DE-REASON-HRM",
    "DE-TABULAR-NANOTABPFN",
    "Each result is lane-local unless a separate same-axis receipt proves transfer.",
    "not overall `/baseline` completion",
]

REQUIRED_SOURCES = {
    "babylm-2026": {
        "evaluator_commit": "02b56cbc8185de1462da195b54877b4be153fbfe",
        "site_commit": "2142c4c2b222b392cdc5c576d7ceede987453725",
        "strict_small_words": 10000000,
        "strict_words": 100000000,
        "epoch_limit": 10,
    },
    "sapient-hrm": {},
    "hrm-critical-frontier": {},
    "modded-nanotabpfn": {
        "repo_commit": "687cfd9b5777bd6b1139fb7a3448417de4021497",
        "upstream_repo_commit": "07a5fb75a9894f4ac2818315b0ca1b60a97e7cb5",
    },
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
    contract_path = root / "contracts" / "data-efficiency-frontier-v0.md"
    protocol_path = root / "protocols" / "data-efficiency-frontier-v0.md"
    lock_path = root / "completion-lock.json"
    sources_path = root / "sources.jsonl"

    require_text(contract_path, REQUIRED_CONTRACT_TEXT, failures, "contract")
    require_text(protocol_path, REQUIRED_PROTOCOL_TEXT, failures, "protocol")

    lock = read_json(lock_path) if lock_path.exists() else {}
    family = lock.get("mandatory_claim_families", {}).get("data_efficiency_sota")
    if not isinstance(family, dict):
        failures.append({"code": "lock_family_missing"})
    else:
        expected_receipt = "receipts/data-efficiency-validation-2026-06-29.json"
        checks = {
            "status": "BASELINE_COMPLETE",
            "contract_path": "contracts/data-efficiency-frontier-v0.md",
            "protocol_path": "protocols/data-efficiency-frontier-v0.md",
            "verifier_receipt": expected_receipt,
        }
        for field, expected in checks.items():
            if family.get(field) != expected:
                failures.append({"code": "lock_field_mismatch", "field": field, "expected": expected, "actual": family.get(field)})
        for source_id in REQUIRED_SOURCES:
            if source_id not in family.get("source_rows", []):
                failures.append({"code": "lock_missing_source_row", "id": source_id})

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
        "verdict": "DATA_EFFICIENCY_BASELINE_COMPLETE" if not failures else "DATA_EFFICIENCY_BASELINE_INCOMPLETE",
        "failure_count": len(failures),
        "failures": failures,
        "contract_path": str(contract_path),
        "protocol_path": str(protocol_path),
        "completion_limit": "This validates only the data_efficiency_sota family. It does not complete the overall baseline.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())