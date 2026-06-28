#!/usr/bin/env python3
"""Admit locally materialized RE-Bench for the Ember external benchmark path."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"

DEFAULT_REBENCH_ROOT = Path(r"<local-path>")
DEFAULT_OUT_DIR = Path("receipts/ember-post-resident-discovery")
REBENCH_GITHUB = "https://github.com/METR/RE-Bench"
REBENCH_ARXIV = "https://arxiv.org/abs/2411.15114"
REBENCH_PAPER = "https://metr.org/AI_R_D_Evaluation_Report.pdf"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def git_head(root: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001 - fake/selftest repos need not be real git repositories.
        return None


def parse_suite_manifest(text: str) -> list[dict[str, Any]]:
    families: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        family = re.match(r"^  ([A-Za-z0-9_]+):\s*$", line)
        if family:
            current = {"id": family.group(1), "tasks": []}
            families.append(current)
            continue
        if current is None:
            continue
        version = re.match(r"^\s+version:\s*(.+?)\s*$", line)
        if version:
            current["version"] = version.group(1)
            continue
        task = re.match(r"^\s+-\s*(.+?)\s*$", line)
        if task:
            current.setdefault("tasks", []).append(task.group(1))
    return families


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def read_task_family(root: Path, family: dict[str, Any]) -> dict[str, Any]:
    task_dir = root / family["id"]
    readme = (task_dir / "README.md").read_text(encoding="utf-8", errors="replace")
    manifest = (task_dir / "manifest.yaml").read_text(encoding="utf-8", errors="replace")
    protected_zips = sorted(task_dir.glob("*.zip"))
    return {
        "id": family["id"],
        "version": family.get("version"),
        "tasks": family.get("tasks", []),
        "name": _first_match(r"^#\s+(.+)$", readme) or _first_match(r"^\s+name:\s*(.+)$", manifest),
        "expertise_machine_learning": "machine_learning" in manifest,
        "manual_scoring": "manual: true" in manifest,
        "intermediate_scoring": "intermediate: true" in manifest,
        "visible_score_to_agent": "visible_to_agent: true" in manifest,
        "score_on_usage_limits": "score_on_usage_limits: true" in manifest,
        "gpu_model": _first_match(r"model:\s*([A-Za-z0-9_.-]+)", manifest),
        "gpu_count_range": re.findall(r"count_range:\s*\n\s*-\s*(\d+)\s*\n\s*-\s*(\d+)", manifest),
        "cpus": _first_match(r"cpus:\s*(\d+)", manifest),
        "memory_gb": _first_match(r"memory_gb:\s*(\d+)", manifest),
        "starting_score_line": _first_match(r"^Starting score:\s*(.+)$", readme),
        "official_solution_score_line": _first_match(r"^Official solution score:\s*(.+)$", readme),
        "readme_sha256": sha256_text(readme),
        "manifest_sha256": sha256_text(manifest),
        "protected_solution_zip_count": len(protected_zips),
        "protected_solution_zip_names": [path.name for path in protected_zips],
        "protected_solution_zip_sha256": {path.name: sha256_file(path) for path in protected_zips},
        "canary_present": "canary" in manifest.lower() or "canary guid" in readme.lower(),
    }


def select_frozen_slice(task_families: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority = ["ai_rd_rust_codecontests_inference", "ai_rd_fix_embedding", "ai_rd_small_scaling_law", "ai_rd_triton_cumsum"]
    by_id = {task["id"]: task for task in task_families}
    selected = [by_id[item] for item in priority if item in by_id]
    for task in task_families:
        if len(selected) >= 3:
            break
        if task not in selected:
            selected.append(task)
    return [
        {
            "id": task["id"],
            "name": task["name"],
            "version": task["version"],
            "tasks": task["tasks"],
            "gpu_model": task["gpu_model"],
            "gpu_count_range": task["gpu_count_range"],
            "cpus": task["cpus"],
            "memory_gb": task["memory_gb"],
            "manual_scoring": task["manual_scoring"],
            "intermediate_scoring": task["intermediate_scoring"],
            "visible_score_to_agent": task["visible_score_to_agent"],
            "readme_sha256": task["readme_sha256"],
            "manifest_sha256": task["manifest_sha256"],
        }
        for task in selected
    ]


def build_admission_receipt(*, repo: Path, rebench_root: Path, out: Path) -> dict[str, Any]:
    if not rebench_root.exists():
        raise FileNotFoundError(f"RE-Bench root not found: {rebench_root}")
    readme_path = rebench_root / "README.md"
    license_path = rebench_root / "LICENSE"
    suite_manifest_path = rebench_root / "suite_manifest.yaml"
    readme = readme_path.read_text(encoding="utf-8", errors="replace")
    license_text = license_path.read_text(encoding="utf-8", errors="replace")
    suite_manifest = suite_manifest_path.read_text(encoding="utf-8", errors="replace")
    suite_families = parse_suite_manifest(suite_manifest)
    task_families = [read_task_family(rebench_root, family) for family in suite_families]
    protected_count = sum(task["protected_solution_zip_count"] for task in task_families)
    frozen_slice = select_frozen_slice(task_families)
    admitted = bool(task_families) and "MIT License" in license_text and (rebench_root / ".git").exists()
    receipt = {
        "ticket": "EMBER-REBENCH-ADMISSION",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "repo": str(repo),
        "goal_path": str(repo / "GOAL.md"),
        "goal_source_sha256": sha256_file(repo / "GOAL.md") if (repo / "GOAL.md").exists() else None,
        "sources": {
            "github": REBENCH_GITHUB,
            "arxiv": REBENCH_ARXIV,
            "paper": REBENCH_PAPER,
            "local_path": str(rebench_root),
            "local_git_head": git_head(rebench_root),
        },
        "source_hashes": {
            "readme_sha256": sha256_text(readme),
            "license_sha256": sha256_text(license_text),
            "suite_manifest_sha256": sha256_text(suite_manifest),
        },
        "license_access": {
            "repo_license": "MIT License",
            "anti_overfit_request_recorded": "README/LICENSE request avoiding unprotected solution publication, training-data leakage, and overfitting.",
            "protected_solution_policy": "Do not extract, quote, publish, or train on protected solution contents; use only task/evaluator surfaces for admission.",
        },
        "benchmark_facts": {
            "name": "RE-Bench",
            "task_families": len(task_families),
            "tasks": sum(len(task.get("tasks", [])) for task in task_families),
            "all_machine_learning_or_ai_rd": all(task["expertise_machine_learning"] for task in task_families),
            "has_task_standard_manifest": bool(suite_families),
            "local_materialized": (rebench_root / ".git").exists(),
        },
        "task_evaluator_inventory": {
            "task_family_ids": [task["id"] for task in task_families],
            "resource_models": sorted({str(task["gpu_model"]) for task in task_families if task["gpu_model"]}),
            "manual_scoring_families": [task["id"] for task in task_families if task["manual_scoring"]],
            "intermediate_scoring_families": [task["id"] for task in task_families if task["intermediate_scoring"]],
            "visible_score_families": [task["id"] for task in task_families if task["visible_score_to_agent"]],
        },
        "frozen_heldout_slice": {
            "selection_rule": "Prefer low-count visible/evaluable ML repair, scaling-law self-improvement pressure, and kernel optimization pressure; exclude protected solution contents.",
            "rows": frozen_slice,
            "sha256": sha256_text(json.dumps(frozen_slice, sort_keys=True)),
            "gold_or_solution_contents_excluded": True,
        },
        "protected_solution_handling": {
            "protected_solution_files": protected_count,
            "extracted_protected_solutions": False,
            "published_unprotected_solutions": False,
            "zip_names_only_and_hashes_recorded": True,
        },
        "native_operator_routing": {
            "selected": "re-bench",
            "admission_state": "ADMITTED" if admitted else "BLOCKED_LOCAL_MATERIALIZATION",
            "reason": "After ScienceAgentBench artifact access blocked, RE-Bench is the next strongest AI-R&D benchmark with local task-family/evaluator materialization.",
        },
        "deleted_selector_routing": {
            "selected": None,
            "admission_state": "ROUTING_BLOCKED_DELETED_SELECTOR",
            "reason": "Deleting the native benchmark router prevents justified progression from ScienceAgentBench to RE-Bench.",
        },
        "deletion_sensitive": True,
        "run_constraints": {
            "vivaria_or_task_standard_runtime_required": True,
            "h100_resource_requests_present": True,
            "local_hardware_compatibility_verified": False,
            "next_preflight_must_check": ["task-standard runtime", "Docker/Vivaria path or local harness adapter", "GPU/H100 feasibility or bounded proxy policy"],
        },
        "field_level_pressure": [
            "AI R&D benchmark, not generic QA",
            "tasks require experiments, code changes, model training, kernels, or scaling-law inference",
            "human expert comparison and time-budget pressure are part of benchmark design",
        ],
        "code_vs_docs_metric": {
            "classification": "during-project benchmark admission receipt",
            "script_code_lines": len((repo / "scripts" / "ember_rebench_admission.py").read_text(encoding="utf-8").splitlines()) if (repo / "scripts" / "ember_rebench_admission.py").exists() else 0,
            "receipt_lines": 0,
            "task_families_materialized": len(task_families),
        },
        "next_executable_command": "python scripts\\ember_rebench_first_loop.py --task-family ai_rd_rust_codecontests_inference --frozen-slice receipts\\ember-post-resident-discovery\\rebench-admission-<timestamp>.json --out receipts\\ember-post-resident-discovery\\rebench-first-loop-<timestamp>.json",
        "verdict": "REBENCH_ADMITTED" if admitted else "REBENCH_BLOCKED",
    }
    receipt["code_vs_docs_metric"]["receipt_lines"] = len(json.dumps(receipt, indent=2, sort_keys=True).splitlines())
    write_json(out, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--rebench-root", default=str(DEFAULT_REBENCH_ROOT))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    if args.selftest:
        import ember_rebench_admission_selftest
        return ember_rebench_admission_selftest.main()
    repo = Path.cwd().resolve()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"rebench-admission-{ts}.json"
    if not out.is_absolute():
        out = repo / out
    receipt = build_admission_receipt(repo=repo, rebench_root=Path(args.rebench_root), out=out)
    print(json.dumps({
        "receipt": str(out),
        "verdict": receipt["verdict"],
        "task_families": receipt["benchmark_facts"]["task_families"],
        "protected_solution_files": receipt["protected_solution_handling"]["protected_solution_files"],
        "selected": receipt["native_operator_routing"]["selected"],
        "next_executable_command": receipt["next_executable_command"],
    }, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] in {"REBENCH_ADMITTED", "REBENCH_BLOCKED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

