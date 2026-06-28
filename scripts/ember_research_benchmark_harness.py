#!/usr/bin/env python3
"""Admit or block a docs/research/journal benchmark for Ember MVP goal-clear loops."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from receipt_write import checked_write

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
TICKET = "EMBER-RESEARCH-BENCHMARK-ADMISSION"
ADMITTED_RESEARCH_BENCHMARK_IDS = {
    "ScienceAgentBench",
    "D3-Gym",
    "SciReplicate-Bench",
    "ResearchBench",
    "PaperBench",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _operator_routes_research(operator_receipt: dict[str, Any]) -> bool:
    action = operator_receipt.get("selected_next_action", {})
    return bool(
        operator_receipt.get("verdict") == "SELF_GROWTH_OPERATOR_READY"
        and operator_receipt.get("manual_selection") is False
        and action.get("kind") == "stronger_external_benchmark"
        and action.get("benchmark_family") == "research_journal"
    )


def _task_count(tasks_path: Path, errors: list[str]) -> int:
    try:
        tasks = _load_json(tasks_path)
    except json.JSONDecodeError:
        errors.append("tasks_path.invalid_json")
        return 0
    rows = tasks.get("tasks")
    if not isinstance(rows, list) or not rows:
        errors.append("tasks_path.no_tasks")
        return 0
    return len(rows)


def build_admission_receipt(manifest_path: Path, operator_receipt_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    missing: list[str] = []
    manifest = _load_json(manifest_path)
    operator_receipt = _load_json(operator_receipt_path)

    tasks_path = Path(str(manifest.get("tasks_path", "")))
    evaluator_path = Path(str(manifest.get("evaluator_path", "")))

    if manifest.get("benchmark_id") not in ADMITTED_RESEARCH_BENCHMARK_IDS:
        errors.append("benchmark_id.not_admitted_research_benchmark")
    if manifest.get("family") != "research_journal":
        errors.append("family.not_research_journal")
    if not manifest.get("source_url"):
        errors.append("source_url.missing")
    if not manifest.get("license_or_access_basis"):
        errors.append("license_or_access_basis.missing")
    if manifest.get("heldout_frozen") is not True:
        errors.append("heldout_frozen")
    if not manifest.get("scoring_metric"):
        errors.append("scoring_metric.missing")
    requires_docker = manifest.get("requires_docker") is True
    if requires_docker and manifest.get("docker_daemon_ready") is not True:
        errors.append("docker_daemon.not_ready")
        missing.append("docker_daemon")
    if not tasks_path.exists():
        errors.append("tasks_path.missing")
        missing.append("tasks_path")
        task_count = 0
        tasks_sha256 = None
    else:
        task_count = _task_count(tasks_path, errors)
        tasks_sha256 = _sha256(tasks_path)
    if not evaluator_path.exists():
        errors.append("evaluator_path.missing")
        missing.append("evaluator_path")
        evaluator_sha256 = None
    else:
        evaluator_sha256 = _sha256(evaluator_path)

    operator_routed = _operator_routes_research(operator_receipt)
    if not operator_routed:
        errors.append("operator.not_research_routed")

    real_external_ready = not errors
    return {
        "ticket": TICKET,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "manifest_path": str(manifest_path),
        "operator_receipt_path": str(operator_receipt_path),
        "benchmark_id": manifest.get("benchmark_id"),
        "benchmark_family": manifest.get("family"),
        "source_url": manifest.get("source_url"),
        "license_or_access_basis": manifest.get("license_or_access_basis"),
        "heldout_frozen": manifest.get("heldout_frozen") is True,
        "scoring_metric": manifest.get("scoring_metric"),
        "requires_docker": requires_docker,
        "docker_daemon_ready": manifest.get("docker_daemon_ready") is True,
        "tasks_path": str(tasks_path),
        "tasks_sha256": tasks_sha256,
        "task_count": task_count,
        "evaluator_path": str(evaluator_path),
        "evaluator_sha256": evaluator_sha256,
        "operator_routed": operator_routed,
        "manual_selection": False,
        "real_external_heldout_ready": real_external_ready,
        "missing_artifacts": missing,
        "errors": errors,
        "required_next_receipts": [
            "research-external-heldout-a-b-c-cycle",
            "research-score-rows",
            "operator-deletion-test",
            "readiness",
        ],
        "verdict": "RESEARCH_BENCHMARK_ADMITTED" if real_external_ready else "RESEARCH_BENCHMARK_BLOCKED",
    }


def validate_admission_receipt(receipt: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if receipt.get("ticket") != TICKET:
        errors.append("ticket")
    if receipt.get("verdict") not in {"RESEARCH_BENCHMARK_ADMITTED", "RESEARCH_BENCHMARK_BLOCKED"}:
        errors.append("verdict")
    if receipt.get("benchmark_family") != "research_journal":
        errors.append("benchmark_family")
    if receipt.get("operator_routed") is not True:
        errors.append("operator_routed")
    if receipt.get("manual_selection") is not False:
        errors.append("manual_selection")
    if receipt.get("verdict") == "RESEARCH_BENCHMARK_ADMITTED":
        if receipt.get("real_external_heldout_ready") is not True:
            errors.append("real_external_heldout_ready")
        if receipt.get("task_count", 0) <= 0:
            errors.append("task_count")
        if not receipt.get("tasks_sha256"):
            errors.append("tasks_sha256")
        if not receipt.get("evaluator_sha256"):
            errors.append("evaluator_sha256")
        if receipt.get("errors"):
            errors.append("errors")
    return errors


def write_admission_receipt(out_path: Path, manifest_path: Path, operator_receipt_path: Path) -> dict[str, Any]:
    receipt = build_admission_receipt(manifest_path, operator_receipt_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out_path), receipt)
    return receipt


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--manifest")
    ap.add_argument("--operator-receipt")
    ap.add_argument("--out")
    args = ap.parse_args()

    if args.selftest:
        import ember_research_benchmark_harness_selftest

        return ember_research_benchmark_harness_selftest.main()

    if not (args.manifest and args.operator_receipt and args.out):
        ap.print_help()
        return 1

    receipt = write_admission_receipt(Path(args.out), Path(args.manifest), Path(args.operator_receipt))
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"] == "RESEARCH_BENCHMARK_ADMITTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
