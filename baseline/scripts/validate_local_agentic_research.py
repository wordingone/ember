#!/usr/bin/env python3
"""Validate the local-agentic research baseline family contract."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_CONTRACT_TEXT = [
    "Status: BASELINE_COMPLETE for the `local_agentic_research_sota` family only.",
    "Lane LAR-CODEX-LOCAL-OPERATOR",
    "Lane LAR-EXTERNAL-CODING-AGENT-B",
    "Lane LAR-HERMES-NEMO-OPERATOR",
    "Lane LAR-ML-RESEARCH-BENCHMARKS",
    "Lane LAR-NONAGENT-SCRIPTED-SEARCH",
    "no-recompute justification",
    "Long jobs require a compute-spend packet",
    "negative-result preservation",
    "LOCAL_AGENTIC_RESEARCH_BASELINE_COMPLETE",
    "This file's completion does not complete the overall baseline.",
]

REQUIRED_REPORT_TEXT = [
    "Status: BASELINE_COMPLETE for the `local_agentic_research_sota` family only.",
    "OpenAI Codex",
    "external coding agent B-class agent",
    "Hermes/NemoClaw-class agent",
    "no-recompute decision log",
    "not overall `/baseline` completion",
]

REQUIRED_SOURCES = {
    "agent-openai-codex": {},
    "agent-anthropic-claude-code": {},
    "agent-nvidia-nemo-agent-toolkit": {},
    "mle-bench": {},
    "mlagentbench": {},
    "ai-scientist-v2": {},
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
    contract_path = root / "contracts" / "C8-agent-loop-baselines.md"
    report_path = root / "agent-loop-baselines-v0.md"
    lock_path = root / "completion-lock.json"
    sources_path = root / "sources.jsonl"

    require_text(contract_path, REQUIRED_CONTRACT_TEXT, failures, "contract")
    require_text(report_path, REQUIRED_REPORT_TEXT, failures, "report")

    lock = read_json(lock_path) if lock_path.exists() else {}
    family = lock.get("mandatory_claim_families", {}).get("local_agentic_research_sota")
    if not isinstance(family, dict):
        failures.append({"code": "lock_family_missing"})
    else:
        expected_receipt = "receipts/local-agentic-research-validation-2026-06-29.json"
        checks = {
            "status": "BASELINE_COMPLETE",
            "contract_path": "contracts/C8-agent-loop-baselines.md",
            "report_path": "agent-loop-baselines-v0.md",
            "verifier_receipt": expected_receipt,
        }
        for field, expected in checks.items():
            if family.get(field) != expected:
                failures.append({"code": "lock_field_mismatch", "field": field, "expected": expected, "actual": family.get(field)})
        for source_id in REQUIRED_SOURCES:
            if source_id not in family.get("source_rows", []):
                failures.append({"code": "lock_missing_source_row", "id": source_id})

    sources = read_sources(sources_path) if sources_path.exists() else {}
    for source_id in REQUIRED_SOURCES:
        row = sources.get(source_id)
        if not isinstance(row, dict):
            failures.append({"code": "source_row_missing", "id": source_id})
            continue
        if not (row.get("access_date") or row.get("accessed")):
            failures.append({"code": "source_access_date_missing", "id": source_id})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "LOCAL_AGENTIC_RESEARCH_BASELINE_COMPLETE" if not failures else "LOCAL_AGENTIC_RESEARCH_BASELINE_INCOMPLETE",
        "failure_count": len(failures),
        "failures": failures,
        "contract_path": str(contract_path),
        "report_path": str(report_path),
        "completion_limit": "This validates only the local_agentic_research_sota family. It does not complete the overall baseline.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())