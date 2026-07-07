#!/usr/bin/env python3
"""Preflight/run boundary for the first ScienceAgentBench A/B/C/deleted loop."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TICKET = "EMBER-SCIENCEAGENTBENCH-FIRST-LOOP"
SHA_CONVENTION = "bytes on disk/as fetched as-is; text hashes are UTF-8 encoded"
DEFAULT_BENCHMARK_ROOT = Path(r"<local-path>")
DEFAULT_FROZEN_ROWS = Path("receipts/ember-post-resident-discovery/scienceagentbench-admission-20260622T165317Z.frozen_rows.json")
DEFAULT_ADMISSION = Path("receipts/ember-post-resident-discovery/scienceagentbench-admission-20260622T165317Z.json")
DEFAULT_OUT_DIR = Path("receipts/ember-post-resident-discovery")
VISUAL_JUDGE_ENV = "OPENAI_API_KEY"
AZURE_VISUAL_JUDGE_ENVS = ["AZURE_OPENAI_KEY", "AZURE_OPENAI_API_VERSION", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT_NAME"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def module_available(name: str, extra_paths: list[Path] | None = None) -> bool:
    extra_paths = extra_paths or []
    for root in extra_paths:
        if (root / f"{name}.py").exists() or (root / name / "__init__.py").exists():
            return True
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:  # noqa: BLE001
        return False


def eval_imports(eval_path: Path) -> list[str]:
    text = eval_path.read_text(encoding="utf-8", errors="replace")
    imports: list[str] = []
    for match in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z0-9_\.]+)", text, re.MULTILINE):
        imports.append(match.group(1).split(".")[0])
    return sorted(set(imports))


def task_paths(benchmark_root: Path, row: dict[str, Any]) -> dict[str, Any]:
    eval_script = benchmark_root / "eval_programs" / str(row["eval_script_name"])
    dataset_name = str(row.get("dataset_folder_tree", "")).split("\n", 1)[0].replace("|--", "").strip()
    dataset_dir = benchmark_root / "datasets" / dataset_name if dataset_name else None
    return {
        "eval_script": eval_script,
        "dataset_dir": dataset_dir,
        "output_fname": row.get("output_fname"),
    }


def build_receipt(
    *,
    repo: Path,
    admission_path: Path,
    frozen_rows_path: Path,
    benchmark_root: Path,
    out: Path,
    budget_seconds: int,
    allow_paid_visual_judge: bool = False,
    max_visual_judge_calls: int = 0,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = env if env is not None else os.environ
    blocked_reasons: list[str] = []
    admission = load_json(admission_path) if admission_path.exists() else None
    frozen = load_json(frozen_rows_path) if frozen_rows_path.exists() else None
    rows = list((frozen or {}).get("rows", []))
    if not admission or admission.get("verdict") != "SCIENCEAGENTBENCH_ADMITTED":
        blocked_reasons.append("scienceagentbench_not_admitted")
    if not rows:
        blocked_reasons.append("frozen_rows_missing")
    if not benchmark_root.exists():
        blocked_reasons.append("benchmark_root_missing")

    row_checks: list[dict[str, Any]] = []
    visual_rows = 0
    missing_eval_scripts: list[str] = []
    missing_dataset_dirs: list[str] = []
    missing_modules: set[str] = set()
    runnable_nonvisual_rows = 0
    eval_programs_dir = benchmark_root / "eval_programs"
    visual_helper_path = eval_programs_dir / "gpt4_visual_judge.py"
    openai_key_present = bool(env.get(VISUAL_JUDGE_ENV))
    azure_key_present = all(bool(env.get(name)) for name in AZURE_VISUAL_JUDGE_ENVS)
    expected_visual_judge_calls = 0
    paid_visual_judge_configured = openai_key_present or azure_key_present
    paid_visual_judge_authorized = False

    for row in rows:
        paths = task_paths(benchmark_root, row)
        eval_script = paths["eval_script"]
        dataset_dir = paths["dataset_dir"]
        imports = eval_imports(eval_script) if eval_script.exists() else []
        requires_visual = "gpt4_visual_judge" in imports
        if requires_visual:
            visual_rows += 1
        local_missing = [name for name in imports if name not in {"os", "sys", "json", "math", "statistics", "pathlib", "typing"} and not module_available(name, [eval_programs_dir])]
        for name in local_missing:
            missing_modules.add(name)
        if not eval_script.exists():
            missing_eval_scripts.append(str(eval_script))
        if dataset_dir is not None and not dataset_dir.exists():
            missing_dataset_dirs.append(str(dataset_dir))
        if eval_script.exists() and dataset_dir is not None and dataset_dir.exists() and not requires_visual:
            runnable_nonvisual_rows += 1
        row_checks.append({
            "instance_id": row.get("instance_id"),
            "eval_script_name": row.get("eval_script_name"),
            "eval_script_exists": eval_script.exists(),
            "dataset_dir": str(dataset_dir) if dataset_dir else None,
            "dataset_dir_exists": bool(dataset_dir and dataset_dir.exists()),
            "output_fname": row.get("output_fname"),
            "imports": imports,
            "requires_gpt4_visual_judge": requires_visual,
            "missing_modules": local_missing,
        })

    if missing_eval_scripts:
        blocked_reasons.append("eval_script_missing")
    if missing_dataset_dirs:
        blocked_reasons.append("dataset_dir_missing")
    if visual_rows and not module_available("gpt4_visual_judge", [eval_programs_dir]):
        blocked_reasons.append("gpt4_visual_judge_module_missing")
    expected_visual_judge_calls = visual_rows * 4 * 3
    paid_visual_judge_authorized = allow_paid_visual_judge and max_visual_judge_calls >= expected_visual_judge_calls
    if visual_rows and not paid_visual_judge_configured:
        blocked_reasons.append("gpt4_visual_judge_openai_key_missing")
    if visual_rows and not allow_paid_visual_judge:
        blocked_reasons.append("paid_visual_judge_not_authorized")
    if visual_rows and allow_paid_visual_judge and max_visual_judge_calls < expected_visual_judge_calls:
        blocked_reasons.append("paid_visual_judge_call_cap_too_low")
    if missing_modules:
        blocked_reasons.append("python_dependency_missing")
    if runnable_nonvisual_rows < len(rows):
        blocked_reasons.append("full_frozen_slice_not_locally_runnable_without_visual_judge")

    # Candidate generation is deliberately not faked. This receipt only opens the loop when all frozen rows can be scored.
    equal_budget = {
        "declared_budget_seconds_per_arm_per_row": budget_seconds,
        "arms": ["A_null_or_template_baseline", "B_prior_operator", "C_resident_operator", "Deleted_operator"],
        "measured_execution": "not_run_preflight_blocked" if blocked_reasons else "ready_to_run",
        "budget_waived": False,
    }
    verdict = "SCIENCEAGENTBENCH_FIRST_LOOP_BLOCKED" if blocked_reasons else "SCIENCEAGENTBENCH_FIRST_LOOP_READY"
    goal_path = repo / "GOAL.md"
    receipt = {
        "ticket": TICKET,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "repo": str(repo),
        "goal_path": str(goal_path),
        "goal_source_sha256": sha256_file(goal_path) if goal_path.exists() else None,
        "sha_convention": SHA_CONVENTION,
        "admission_receipt": str(admission_path),
        "admission_receipt_sha256": sha256_file(admission_path) if admission_path.exists() else None,
        "frozen_rows_path": str(frozen_rows_path),
        "frozen_rows_sha256": sha256_file(frozen_rows_path) if frozen_rows_path.exists() else None,
        "benchmark_root": str(benchmark_root),
        "benchmark_root_exists": benchmark_root.exists(),
        "frozen_row_count": len(rows),
        "row_checks": row_checks,
        "blocked_reasons": sorted(set(blocked_reasons)),
        "missing_eval_scripts": missing_eval_scripts,
        "missing_dataset_dirs": missing_dataset_dirs,
        "missing_modules": sorted(missing_modules),
        "visual_judge_status": {
            "visual_rows": visual_rows,
            "module_available": module_available("gpt4_visual_judge", [eval_programs_dir]),
            "official_helper_path": str(visual_helper_path),
            "official_helper_exists": visual_helper_path.exists(),
            "official_helper_sha256": sha256_file(visual_helper_path) if visual_helper_path.exists() else None,
            "official_helper_source": "https://github.com/OSU-NLP-Group/ScienceAgentBench/blob/main/gpt4_visual_judge.py",
            "openai_key_env_checked": VISUAL_JUDGE_ENV,
            "openai_key_present": openai_key_present,
            "azure_envs_checked": AZURE_VISUAL_JUDGE_ENVS,
            "azure_key_present": azure_key_present,
            "paid_api_surface": True,
            "paid_visual_judge_authorized": allow_paid_visual_judge,
            "max_visual_judge_calls": max_visual_judge_calls,
            "expected_visual_judge_calls": expected_visual_judge_calls,
            "expected_call_formula": "visual_rows * 4 A/B/C/deleted arms * 3 samples per official score_figure call",
            "call_cap_sufficient": max_visual_judge_calls >= expected_visual_judge_calls,
            "configured_and_authorized": paid_visual_judge_configured and paid_visual_judge_authorized,
        },
        "candidate_safety": {
            "gold_programs_read_by_candidate": False,
            "gold_results_read_by_candidate": False,
            "private_labels_read_by_candidate": False,
            "candidate_generation_faked": False,
        },
        "equal_budget": equal_budget,
        "score_rows": [],
        "positive_delta": False,
        "deletion_sensitive": True,
        "native_operator_routing": {
            "selected": "scienceagentbench",
            "admission_state": "FIRST_LOOP_BLOCKED" if blocked_reasons else "FIRST_LOOP_READY",
            "reason": "ScienceAgentBench is admitted; first loop is blocked only by executable evaluator/dependency/candidate-generation requirements." if blocked_reasons else "ScienceAgentBench frozen rows are ready for the first equal-budget loop.",
        },
        "deleted_selector_routing": {
            "selected": None,
            "admission_state": "ROUTING_BLOCKED_DELETED_SELECTOR",
            "reason": "Deleting the native benchmark router prevents preserving ScienceAgentBench as the selected admitted target.",
        },
        "next_executable_command": (
            "Provide authorized visual-judge OpenAI/Azure configuration and rerun with --allow-paid-visual-judge --max-visual-judge-calls >= expected_visual_judge_calls; do not run paid visual judging without explicit budget authorization."
            if blocked_reasons else
            "Run A/B/C/deleted candidate generation and scoring for the frozen ScienceAgentBench rows."
        ),
        "code_vs_docs_metric": {
            "classification": "during-project ScienceAgentBench first-loop preflight receipt",
            "script_code_lines": len((repo / "scripts" / "ember_scienceagentbench_first_loop.py").read_text(encoding="utf-8").splitlines()) if (repo / "scripts" / "ember_scienceagentbench_first_loop.py").exists() else 0,
            "receipt_lines": 0,
        },
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
        "verdict": verdict,
    }
    receipt["code_vs_docs_metric"]["receipt_lines"] = len(json.dumps(receipt, indent=2, sort_keys=True).splitlines())
    write_json(out, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission", default=str(DEFAULT_ADMISSION))
    parser.add_argument("--frozen-rows", default=str(DEFAULT_FROZEN_ROWS))
    parser.add_argument("--benchmark-root", default=str(DEFAULT_BENCHMARK_ROOT))
    parser.add_argument("--budget-seconds", type=int, default=120)
    parser.add_argument("--allow-paid-visual-judge", action="store_true")
    parser.add_argument("--max-visual-judge-calls", type=int, default=0)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    repo = Path.cwd().resolve()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"scienceagentbench-first-loop-{ts}.json"
    if not out.is_absolute():
        out = repo / out
    receipt = build_receipt(
        repo=repo,
        admission_path=Path(args.admission),
        frozen_rows_path=Path(args.frozen_rows),
        benchmark_root=Path(args.benchmark_root),
        out=out,
        budget_seconds=args.budget_seconds,
        allow_paid_visual_judge=args.allow_paid_visual_judge,
        max_visual_judge_calls=args.max_visual_judge_calls,
    )
    print(json.dumps({
        "receipt": str(out),
        "verdict": receipt["verdict"],
        "blocked_reasons": receipt["blocked_reasons"],
        "visual_judge_status": receipt["visual_judge_status"],
        "next_executable_command": receipt["next_executable_command"],
    }, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] in {"SCIENCEAGENTBENCH_FIRST_LOOP_BLOCKED", "SCIENCEAGENTBENCH_FIRST_LOOP_READY"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
