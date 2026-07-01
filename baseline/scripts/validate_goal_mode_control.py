#!/usr/bin/env python3
"""Validate the Ember goal-mode control baseline family contract."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_CONTRACT_TEXT = [
    "BASELINE_COMPLETE for `ember_goal_mode_control`",
    "Goal mode is not completed by CLI evidence.",
    "C7 Goal Mode Uncheatable Form",
    "Lane GOAL-CHECKLIST-TRANSCRIPT",
    "Lane GOAL-PREMATURE-COMPLETION-REDTEAM",
    "Lane GOAL-SOURCE-STALE-SCOPE",
    "Lane GOAL-CONTINUATION-INTERRUPTION",
    "Lane GOAL-OPERATOR-ACCEPTANCE",
    "one-trial success",
    "negative-result-only proof",
    "static/docs-only proof",
    "local-only proof",
    "missing single-4090 ceiling",
    "missing operator acceptance",
    "never write or infer operator acceptance",
    "GOAL_MODE_BASELINE_COMPLETE",
    "These family completions do not complete the overall baseline.",
]

REQUIRED_REPORT_TEXT = [
    "BASELINE_COMPLETE for `ember_goal_mode_control`",
    "Goal mode is not completed by the CLI family.",
    "Required Goal-Mode Flow",
    "Required Goal-Mode Red-Team Rejections",
    "one-trial success",
    "static/docs-only proof",
    "local-only proof",
    "missing single-4090 ceiling",
    "missing operator acceptance",
    "GOAL_MODE_BASELINE_COMPLETE",
    "not overall `/baseline` completion",
]

REQUIRED_SOURCES = {
    "agent-openai-codex",
    "agent-anthropic-claude-code",
    "kosmos-ai-scientist",
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
    contract_path = root / "contracts" / "C6-C7-cli-goal-mode.md"
    report_path = root / "cli-goal-mode-baseline-v0.md"
    lock_path = root / "completion-lock.json"
    sources_path = root / "sources.jsonl"

    require_text(contract_path, REQUIRED_CONTRACT_TEXT, failures, "contract")
    require_text(report_path, REQUIRED_REPORT_TEXT, failures, "report")

    lock = read_json(lock_path) if lock_path.exists() else {}
    family = lock.get("mandatory_claim_families", {}).get("ember_goal_mode_control")
    if not isinstance(family, dict):
        failures.append({"code": "lock_family_missing"})
    else:
        expected_receipt = "receipts/goal-mode-validation-2026-06-29.json"
        checks = {
            "status": "BASELINE_COMPLETE",
            "contract_path": "contracts/C6-C7-cli-goal-mode.md",
            "report_path": "cli-goal-mode-baseline-v0.md",
            "verifier_receipt": expected_receipt,
        }
        for field, expected in checks.items():
            if family.get(field) != expected:
                failures.append({"code": "lock_field_mismatch", "field": field, "expected": expected, "actual": family.get(field)})
        for source_id in REQUIRED_SOURCES:
            if source_id not in family.get("source_rows", []):
                failures.append({"code": "lock_missing_source_row", "id": source_id})

    cli_family = lock.get("mandatory_claim_families", {}).get("ember_cli_runtime_reproducibility")
    if not isinstance(cli_family, dict) or cli_family.get("status") != "BASELINE_COMPLETE":
        failures.append({"code": "cli_family_not_complete_separately"})
    elif cli_family.get("verifier_receipt") != "receipts/cli-runtime-validation-2026-06-29.json":
        failures.append({"code": "cli_family_receipt_mismatch", "actual": cli_family.get("verifier_receipt")})

    if lock.get("status") == "BASELINE_COMPLETE":
        failures.append({"code": "overall_completed_by_goal_mode_proxy"})
    if lock.get("operator_acceptance") is not None:
        failures.append({"code": "operator_acceptance_must_not_be_agent_written"})

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
        "verdict": "GOAL_MODE_BASELINE_COMPLETE" if not failures else "GOAL_MODE_BASELINE_INCOMPLETE",
        "failure_count": len(failures),
        "failures": failures,
        "contract_path": str(contract_path),
        "report_path": str(report_path),
        "completion_limit": "This validates only the ember_goal_mode_control family. It does not complete the overall baseline or write operator acceptance.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())