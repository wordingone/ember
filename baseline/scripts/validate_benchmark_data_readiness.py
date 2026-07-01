#!/usr/bin/env python3
"""Validate benchmark/data readiness for the Ember baseline.

This is a readiness verifier, not an Ember win verifier. It proves that the
baseline has enough pinned benchmark/data substrate to run meaningful governed
comparisons while preserving known execution gaps instead of hiding them.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_SOURCE_IDS = {
    "modded-nanogpt",
    "babylm-2026",
    "mlcommons-algoperf",
    "mle-bench",
    "mlagentbench",
    "ai-scientist",
    "sapient-hrm",
    "hrm-critical-frontier",
    "modded-nanotabpfn",
}

REQUIRED_PROTOCOL_TEXT = {
    "protocols/data-efficiency-frontier-v0.md": [
        "DE-LM-BABYLM",
        "DE-REASON-HRM",
        "DE-TABULAR-NANOTABPFN",
        "selected metric suite and threshold frozen before execution",
    ],
    "protocols/c5-zero-spend-subset-v0.md": [
        "MLAgentBench CLRS",
        "AI Scientist nanoGPT_lite",
        "data prep for nanoGPT_lite has passed",
        "CLRS executable smoke PASS",
        "three-seed upstream-baseline comparator PASS",
        "equal-budget deterministic patch comparator PASS",
        "nanoGPT_lite deterministic patch comparator PASS",
        "public-safe negative Ember-vs-nanoGPT trial validated",
        "owned engine candidate FAIL",
        "No Ember governed C5 improvement trial has been executed under it",
    ],
    "protocols/compute-spend-c5-baseline-readiness-v0.md": [
        "SMOKE AUTHORIZED, FULL BASELINE NOT AUTHORIZED",
        "C5-0A MLAgentBench CLRS: baseline-readiness PASS",
        "C5-0B AI Scientist nanoGPT_lite: baseline-readiness PASS",
    ],
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_sources(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            row["_line"] = line_no
            rows[row["id"]] = row
    return rows


def require_text(root: Path, failures: list[dict[str, Any]]) -> None:
    for rel, needles in REQUIRED_PROTOCOL_TEXT.items():
        path = root / rel
        if not path.exists():
            failures.append({"code": "protocol_missing", "path": rel})
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for needle in needles:
            if needle not in text:
                failures.append({"code": "protocol_missing_text", "path": rel, "needle": needle})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    failures: list[dict[str, Any]] = []
    sources = load_sources(root / "sources.jsonl") if (root / "sources.jsonl").exists() else {}
    missing_sources = sorted(REQUIRED_SOURCE_IDS - set(sources))
    if missing_sources:
        failures.append({"code": "required_benchmark_source_missing", "ids": missing_sources})
    for source_id in sorted(REQUIRED_SOURCE_IDS & set(sources)):
        row = sources[source_id]
        if not (row.get("access_date") or row.get("accessed")):
            failures.append({"code": "source_access_date_missing", "id": source_id})
        if not row.get("status"):
            failures.append({"code": "source_status_missing", "id": source_id})

    require_text(root, failures)

    external_path = root / "receipts/external-benchmark-import-validation-2026-06-30.json"
    external = read_json(external_path) if external_path.exists() else {}
    gap_ledger_path = root / "receipts/external-benchmark-gap-ledger-validation-2026-06-30.json"
    gap_ledger = read_json(gap_ledger_path) if gap_ledger_path.exists() else {}
    if external.get("verdict") != "EXTERNAL_BENCHMARK_EXECUTED_IMPORTS_READY":
        failures.append({"code": "external_benchmark_imports_not_ready", "actual": external.get("verdict")})
    if external.get("executed_receipt_count", 0) < 3:
        failures.append({"code": "external_executed_receipts_too_few", "actual": external.get("executed_receipt_count")})
    if gap_ledger.get("verdict") != "EXTERNAL_BENCHMARK_GAP_LEDGER_VALIDATED":
        failures.append({"code": "external_gap_ledger_not_validated", "actual": gap_ledger.get("verdict")})

    c5_readiness_path = root / "receipts/c5-baseline-readiness-2026-06-30.json"
    clrs_smoke_validation_path = root / "receipts/c5-mlagentbench-clrs-smoke-validation-2026-06-30.json"
    clrs_governed_validation_path = root / "receipts/c5-mlagentbench-clrs-governed-baseline-validation-2026-06-30.json"
    clrs_patch_validation_path = root / "receipts/c5-mlagentbench-clrs-deterministic-patch-comparator-validation-2026-06-30.json"
    c5_data_path = root / "receipts/c5-nanogpt-lite-data-prep-2026-06-29.json"
    c5_smoke_path = root / "receipts/c5-nanogpt-lite-smoke-2026-06-29.json"
    data_eff_path = root / "receipts/data-efficiency-validation-2026-06-29.json"
    sapient_path = root / "receipts/sapient-hrm-data-efficiency-frontier-2026-06-29.json"
    nanogpt_patch_validation_path = root / "receipts/c5-nanogpt-deterministic-patch-comparator-validation-2026-06-30.json"
    nanogpt_trial_validation_path = root / "receipts/c5-ember-vs-nanogpt-trial-validation-2026-06-30.json"
    owned_engine_tool_path = root / "receipts/owned-engine-tool-loop-2026-06-30.json"
    owned_engine_sft_validation_path = root / "receipts/owned-engine-sft-tool-loop-validation-2026-06-30.json"
    owned_engine_sft_repairs_path = root / "receipts/owned-engine-sft-repair-attempts-validation-2026-06-30.json"

    c5_readiness = read_json(c5_readiness_path) if c5_readiness_path.exists() else {}
    clrs_smoke_validation = read_json(clrs_smoke_validation_path) if clrs_smoke_validation_path.exists() else {}
    clrs_governed_validation = read_json(clrs_governed_validation_path) if clrs_governed_validation_path.exists() else {}
    clrs_patch_validation = read_json(clrs_patch_validation_path) if clrs_patch_validation_path.exists() else {}
    c5_data = read_json(c5_data_path) if c5_data_path.exists() else {}
    c5_smoke = read_json(c5_smoke_path) if c5_smoke_path.exists() else {}
    data_eff = read_json(data_eff_path) if data_eff_path.exists() else {}
    sapient = read_json(sapient_path) if sapient_path.exists() else {}
    nanogpt_patch_validation = read_json(nanogpt_patch_validation_path) if nanogpt_patch_validation_path.exists() else {}
    nanogpt_trial_validation = read_json(nanogpt_trial_validation_path) if nanogpt_trial_validation_path.exists() else {}
    owned_engine_tool = read_json(owned_engine_tool_path) if owned_engine_tool_path.exists() else {}
    owned_engine_sft_validation = read_json(owned_engine_sft_validation_path) if owned_engine_sft_validation_path.exists() else {}
    owned_engine_sft_repairs = read_json(owned_engine_sft_repairs_path) if owned_engine_sft_repairs_path.exists() else {}

    tasks = c5_readiness.get("tasks", {}) if isinstance(c5_readiness, dict) else {}
    clrs = tasks.get("C5-0A-MLAgentBench-CLRS", {}) if isinstance(tasks, dict) else {}
    nano = tasks.get("C5-0B-AI-Scientist-nanoGPT-lite", {}) if isinstance(tasks, dict) else {}
    if clrs.get("baseline_readiness") != "PASS":
        failures.append({"code": "clrs_readiness_not_pass", "actual": clrs.get("baseline_readiness")})
    for module in ("chex", "haiku", "optax", "clrs"):
        if clrs.get("modules", {}).get(module) is not True:
            failures.append({"code": "clrs_dependency_not_available", "module": module, "actual": clrs.get("modules", {}).get(module)})
    if clrs_smoke_validation.get("verdict") != "C5_MLAGENTBENCH_CLRS_SMOKE_VALIDATED":
        failures.append({"code": "clrs_smoke_validation_not_pass", "actual": clrs_smoke_validation.get("verdict")})
    if clrs_governed_validation.get("verdict") != "C5_MLAGENTBENCH_CLRS_GOVERNED_BASELINE_VALIDATED":
        failures.append({"code": "clrs_governed_baseline_validation_not_pass", "actual": clrs_governed_validation.get("verdict")})
    if clrs_patch_validation.get("verdict") != "C5_MLAGENTBENCH_CLRS_DETERMINISTIC_PATCH_COMPARATOR_VALIDATED":
        failures.append({"code": "clrs_deterministic_patch_comparator_validation_not_pass", "actual": clrs_patch_validation.get("verdict")})
    if nano.get("baseline_readiness") != "PASS":
        failures.append({"code": "nanogpt_lite_readiness_not_pass", "actual": nano.get("baseline_readiness")})
    if nano.get("torch", {}).get("cuda_available") is not True:
        failures.append({"code": "nanogpt_lite_cuda_not_available", "actual": nano.get("torch")})

    if c5_data.get("verdict") != "PASS" or c5_data.get("train_tokens", 0) <= 0 or c5_data.get("val_tokens", 0) <= 0:
        failures.append({"code": "c5_nanogpt_lite_data_prep_not_pass", "receipt": c5_data})
    for file_row in c5_data.get("files", []):
        if file_row.get("exists") is not True or not file_row.get("sha256") or file_row.get("size_bytes", 0) <= 0:
            failures.append({"code": "c5_data_file_not_pinned", "file": file_row})

    if c5_smoke.get("verdict") not in {"PASS", "SMOKE_PASS"}:
        failures.append({"code": "c5_nanogpt_lite_smoke_not_pass", "actual": c5_smoke.get("verdict")})
    if nanogpt_patch_validation.get("verdict") != "C5_NANOGPT_DETERMINISTIC_PATCH_COMPARATOR_VALIDATED":
        failures.append({"code": "c5_nanogpt_deterministic_patch_comparator_not_validated", "actual": nanogpt_patch_validation.get("verdict")})
    if nanogpt_patch_validation.get("delta_vs_upstream_pct", 0) <= 0:
        failures.append({"code": "c5_nanogpt_deterministic_patch_comparator_no_positive_delta", "actual": nanogpt_patch_validation.get("delta_vs_upstream_pct")})
    if nanogpt_trial_validation.get("verdict") != "C5_EMBER_VS_NANOGPT_TRIAL_NEGATIVE_EVIDENCE_VALIDATED":
        failures.append({"code": "c5_ember_vs_nanogpt_trial_negative_evidence_not_validated", "actual": nanogpt_trial_validation.get("verdict")})
    if data_eff.get("verdict") != "DATA_EFFICIENCY_BASELINE_COMPLETE":
        failures.append({"code": "data_efficiency_validator_not_pass", "actual": data_eff.get("verdict")})
    if sapient.get("verdict") not in {"PASS", "FRONTIER_ANCHOR_READY", "DATA_EFFICIENCY_FRONTIER_READY", "SOURCE_PINNED_SCOPE_LIMITED_NEEDS_RECORD_ADJUDICATION"}:
        failures.append({"code": "sapient_hrm_frontier_receipt_not_ready", "actual": sapient.get("verdict")})
    if owned_engine_tool.get("schema") != "owned_engine.tool_loop_candidate.v1":
        failures.append({"code": "owned_engine_tool_loop_receipt_missing_or_wrong_schema", "actual": owned_engine_tool.get("schema")})
    if owned_engine_tool.get("verdict") != "FAIL" or owned_engine_tool.get("returncode") != 2:
        failures.append({"code": "owned_engine_tool_loop_negative_evidence_not_recorded", "actual": {"verdict": owned_engine_tool.get("verdict"), "returncode": owned_engine_tool.get("returncode")}})
    combined_real_ember_log = str(owned_engine_tool.get("stdout_redacted", "")) + str(owned_engine_tool.get("stderr_redacted", ""))
    local_path_markers = [
        "B:" + "/" + "M" + "/" + "ember",
        "B:" + "\\" + "M" + "\\" + "ember",
        "C:" + "\\" + "tmp",
        "C:" + "/" + "tmp",
    ]
    if any(marker in combined_real_ember_log for marker in local_path_markers):
        failures.append({"code": "owned_engine_tool_loop_receipt_contains_absolute_local_path"})
    if owned_engine_sft_validation.get("verdict") != "OWNED_ENGINE_SFT_TOOL_LOOP_NEGATIVE_EVIDENCE_VALIDATED":
        failures.append({"code": "owned_engine_sft_tool_loop_validation_not_ready", "actual": owned_engine_sft_validation.get("verdict")})
    if owned_engine_sft_repairs.get("verdict") != "OWNED_ENGINE_SFT_REPAIR_ATTEMPTS_NEGATIVE_EVIDENCE_VALIDATED":
        failures.append({"code": "owned_engine_sft_repair_attempts_validation_not_ready", "actual": owned_engine_sft_repairs.get("verdict")})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "BENCHMARK_DATA_READINESS_BASELINE_READY" if not failures else "BENCHMARK_DATA_READINESS_INCOMPLETE",
        "failure_count": len(failures),
        "failures": failures,
        "source_count_checked": len(REQUIRED_SOURCE_IDS),
        "sources_checked": sorted(REQUIRED_SOURCE_IDS),
        "local_data_receipts": {
            "c5_mlagentbench_clrs_smoke": {
                "path": "receipts/c5-mlagentbench-clrs-smoke-validation-2026-06-30.json",
                "verdict": clrs_smoke_validation.get("verdict"),
                "completion_limit": clrs_smoke_validation.get("completion_limit"),
            },
            "c5_mlagentbench_clrs_governed_baseline": {
                "path": "receipts/c5-mlagentbench-clrs-governed-baseline-validation-2026-06-30.json",
                "verdict": clrs_governed_validation.get("verdict"),
                "completion_limit": clrs_governed_validation.get("completion_limit"),
            },
            "c5_mlagentbench_clrs_deterministic_patch_comparator": {
                "path": "receipts/c5-mlagentbench-clrs-deterministic-patch-comparator-validation-2026-06-30.json",
                "verdict": clrs_patch_validation.get("verdict"),
                "completion_limit": clrs_patch_validation.get("completion_limit"),
                "delta_vs_upstream_mean": clrs_patch_validation.get("delta_vs_upstream_mean"),
            },
            "c5_nanogpt_lite_data_prep": {
                "path": "receipts/c5-nanogpt-lite-data-prep-2026-06-29.json",
                "verdict": c5_data.get("verdict"),
                "train_tokens": c5_data.get("train_tokens"),
                "val_tokens": c5_data.get("val_tokens"),
            },
            "c5_nanogpt_lite_smoke": {
                "path": "receipts/c5-nanogpt-lite-smoke-2026-06-29.json",
                "verdict": c5_smoke.get("verdict"),
            },
            "c5_nanogpt_deterministic_patch_comparator": {
                "path": "receipts/c5-nanogpt-deterministic-patch-comparator-validation-2026-06-30.json",
                "verdict": nanogpt_patch_validation.get("verdict"),
                "delta_vs_upstream_pct": nanogpt_patch_validation.get("delta_vs_upstream_pct"),
                "completion_limit": nanogpt_patch_validation.get("completion_limit"),
            },
            "c5_ember_vs_nanogpt_trial": {
                "path": "receipts/c5-ember-vs-nanogpt-trial-validation-2026-06-30.json",
                "verdict": nanogpt_trial_validation.get("verdict"),
                "completion_limit": nanogpt_trial_validation.get("completion_limit"),
            },
            "nanogpt_lite": {
                "status": "UPSTREAM_AND_DETERMINISTIC_PATCH_COMPARATOR_EXECUTED_EMBER_TRIAL_NEGATIVE",
                "data_prep": c5_data.get("verdict"),
                "smoke": c5_smoke.get("verdict"),
                "deterministic_patch_validation": nanogpt_patch_validation.get("verdict"),
                "ember_vs_external_trial_validation": nanogpt_trial_validation.get("verdict"),
                "next_repair": "Run an actual Ember candidate under the same governed nanoGPT_lite receipt contract before any improvement claim.",
            },
            "owned_engine_tool_loop": {
                "path": "receipts/owned-engine-tool-loop-2026-06-30.json",
                "verdict": owned_engine_tool.get("verdict"),
                "returncode": owned_engine_tool.get("returncode"),
                "interpretation": "Owned checkpoint executed through the tool loop and failed to complete the task; this is negative evidence, not a comparator win.",
            },
            "owned_engine_sft_tool_loop": {
                "path": "receipts/owned-engine-sft-tool-loop-validation-2026-06-30.json",
                "verdict": owned_engine_sft_validation.get("verdict"),
                "summary": owned_engine_sft_validation.get("summary"),
                "interpretation": "Bounded SFT improved parsed tool-action behavior but still failed the heldout task; this is capability movement, not a win.",
            },
            "owned_engine_sft_repair_attempts": {
                "path": "receipts/owned-engine-sft-repair-attempts-validation-2026-06-30.json",
                "verdict": owned_engine_sft_repairs.get("verdict"),
                "summaries": owned_engine_sft_repairs.get("summaries"),
                "interpretation": "Five bounded repair attempts tested large-count generalization, turnwise next-action supervision, normalized copy-contract runtime, compositional target-path copying, and live-observation copying. v5/v6 reached the correct COUNT observation but still failed WRITE observation-copy.",
            },
        },
        "prior_external_benchmark_imports": {
            "path": "receipts/external-benchmark-import-validation-2026-06-30.json",
            "verdict": external.get("verdict"),
            "executed_receipt_count": external.get("executed_receipt_count"),
            "gap_ledger_validation": gap_ledger.get("verdict"),
        },
        "resolved_execution_gaps": {
            "mlagentbench_clrs": {
                "status": "UPSTREAM_AND_DETERMINISTIC_COMPARATORS_EXECUTED_NOT_EMBER_TRIAL",
                "readiness": clrs.get("baseline_readiness"),
                "smoke_validation": clrs_smoke_validation.get("verdict"),
                "governed_baseline_validation": clrs_governed_validation.get("verdict"),
                "deterministic_patch_comparator_validation": clrs_patch_validation.get("verdict"),
                "next_repair": "Run the predeclared Ember loop against the upstream and deterministic patch comparators before any improvement claim.",
            },
            "nanogpt_lite": {
                "status": "UPSTREAM_AND_DETERMINISTIC_PATCH_COMPARATOR_EXECUTED_EMBER_TRIAL_NEGATIVE",
                "data_prep": c5_data.get("verdict"),
                "smoke": c5_smoke.get("verdict"),
                "deterministic_patch_validation": nanogpt_patch_validation.get("verdict"),
                "ember_vs_external_trial_validation": nanogpt_trial_validation.get("verdict"),
                "next_repair": "Run an actual Ember candidate under the same governed nanoGPT_lite receipt contract before any improvement claim.",
            },
            "owned_engine_tool_loop": {
                "status": "OWNED_ENGINE_EXECUTED_FAILED_TOOL_LOOP",
                "receipt": "receipts/owned-engine-tool-loop-2026-06-30.json",
                "next_repair": "Train or repair the owned tool-agent candidate, then rerun this same governed agent-loop receipt path before any C5 win claim.",
            },
            "owned_engine_sft_tool_loop": {
                "status": "SFT_MOVED_TOOL_BEHAVIOR_STILL_FAILED_HELDOUT_TASK",
                "receipt": "receipts/owned-engine-sft-tool-loop-validation-2026-06-30.json",
                "next_repair": "Repair decoding/tool grammar or training distribution, then rerun the same heldout probe before any external C5 trial claim.",
            },
            "owned_engine_sft_repair_attempts": {
                "status": "REPAIR_ATTEMPTS_TESTED_STILL_FAILED_HELDOUT_TASK",
                "receipt": "receipts/owned-engine-sft-repair-attempts-validation-2026-06-30.json",
                "next_repair": "The next owned-engine loop attempt must replace short SFT patching with an architecture/runtime that reliably copies live tool observations into write actions before any longer GPU time.",
            }
        },
        "external_gap_ledger": {
            "path": "receipts/external-benchmark-gap-ledger-validation-2026-06-30.json",
            "verdict": gap_ledger.get("verdict"),
            "scope": "Blocked access/setup receipts are preserved outside completed-family evidence.",
        },
        "completion_limit": "This validates benchmark/data substrate readiness only. It is not an Ember win, not a completed governed benchmark suite, and not overall baseline completion.",
    }
    text = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
