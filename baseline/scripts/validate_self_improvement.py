#!/usr/bin/env python3
"""Validate the self-improvement baseline family contract."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_CONTRACT_TEXT = [
    "Status: BASELINE_COMPLETE for the `self_improvement_loop_sota` family only.",
    "Lane C5-MLE-BENCH",
    "Lane C5-MLAGENTBENCH-CLRS",
    "Lane C5-AI-SCIENTIST-NANOGPT",
    "Lane C5-AI-SCIENTIST-V2",
    "Lane C5-KOSMOS-SCIENTIFIC-DISCOVERY",
    "no self-graded victory",
    "no local C5-0 task result transferred into broad scientific-discovery or field-level claims",
    "compute-spend packet before launch",
    "SELF_IMPROVEMENT_BASELINE_COMPLETE",
    "This file's completion does not complete the overall baseline.",
]

REQUIRED_REPORT_TEXT = [
    "Status: BASELINE_COMPLETE for the `self_improvement_loop_sota` family only.",
    "mle-bench",
    "mlagentbench",
    "ai-scientist-v2",
    "kosmos-ai-scientist",
    "not overall `/baseline` completion",
]

REQUIRED_PROTOCOL_TEXT = [
    "C5-0A: MLAgentBench CLRS Local Improvement",
    "C5-0B: AI Scientist nanoGPT_lite Local Research Loop",
    "T0 is only an admission smoke",
    "Required Receipts",
]

REQUIRED_SOURCES = {
    "mle-bench": {"repo_commit": "507f92e1138bb6e40dac5c6ee7a6758e6424bf97"},
    "mlagentbench": {"repo_commit": "5d71205cc20a8e95d43aa7cb7120e89ca3323e31", "selected_task": "CLRS"},
    "ai-scientist": {"repo_commit": "1de1dbc1f4ee2c5f61e9c94348d55eb51d7fa2eb", "selected_task": "nanoGPT_lite/shakespeare_char"},
    "ai-scientist-v2": {"repo_commit": "96bd51617cfdbb494a9fc283af00fe090edfae48"},
    "kosmos-ai-scientist": {},
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
    contract_path = root / "contracts" / "C5-self-improvement-loop.md"
    report_path = root / "self-improvement-baseline-v0.md"
    protocol_path = root / "protocols" / "c5-zero-spend-subset-v0.md"
    lock_path = root / "completion-lock.json"
    sources_path = root / "sources.jsonl"

    require_text(contract_path, REQUIRED_CONTRACT_TEXT, failures, "contract")
    require_text(report_path, REQUIRED_REPORT_TEXT, failures, "report")
    require_text(protocol_path, REQUIRED_PROTOCOL_TEXT, failures, "protocol")

    lock = read_json(lock_path) if lock_path.exists() else {}
    family = lock.get("mandatory_claim_families", {}).get("self_improvement_loop_sota")
    if not isinstance(family, dict):
        failures.append({"code": "lock_family_missing"})
    else:
        expected_receipt = "receipts/self-improvement-validation-2026-06-29.json"
        checks = {
            "status": "BASELINE_COMPLETE",
            "contract_path": "contracts/C5-self-improvement-loop.md",
            "protocol_path": "protocols/c5-zero-spend-subset-v0.md",
            "report_path": "self-improvement-baseline-v0.md",
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
        "verdict": "SELF_IMPROVEMENT_BASELINE_COMPLETE" if not failures else "SELF_IMPROVEMENT_BASELINE_INCOMPLETE",
        "failure_count": len(failures),
        "failures": failures,
        "contract_path": str(contract_path),
        "report_path": str(report_path),
        "protocol_path": str(protocol_path),
        "completion_limit": "This validates only the self_improvement_loop_sota family. It does not complete the overall baseline.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())