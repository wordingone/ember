#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""RE-Bench first-loop preflight for Ember's external heldout path."""
from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

DEFAULT_TASK_FAMILY = "ai_rd_rust_codecontests_inference"
REQUIRED_ENV = "AI_RD_RUST_CODECONTESTS_INFERENCE_OPENAI_API_KEY"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"


def sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def windows_memory_gb() -> float | None:
    if os.name != "nt":
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
            pages = os.sysconf("SC_PHYS_PAGES")
            return round(page_size * pages / (1024**3), 2)
        except Exception:  # noqa: BLE001
            return None

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)) == 0:
        return None
    return round(stat.ullTotalPhys / (1024**3), 2)


def parse_requirements(task_dir: Path) -> dict[str, Any]:
    manifest = (task_dir / "manifest.yaml").read_text(encoding="utf-8", errors="replace")
    return {
        "required_cpus": int(_first_match(r"cpus:\s*(\d+)", manifest) or 0),
        "required_memory_gb": int(_first_match(r"memory_gb:\s*(\d+)", manifest) or 0),
        "visible_score_to_agent": "visible_to_agent: true" in manifest,
        "score_on_usage_limits": "score_on_usage_limits: true" in manifest,
        "manifest_sha256": sha256_text(manifest),
    }


def module_is_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False

def evaluate_preflight(
    *,
    task_dir: Path,
    env: dict[str, str] | None = None,
    module_available: Callable[[str], bool] | None = None,
    which: Callable[[str], str | None] | None = None,
    cpu_count: Callable[[], int | None] | None = None,
    memory_gb: Callable[[], float | None] | None = None,
) -> dict[str, Any]:
    env = env if env is not None else os.environ
    module_available = module_available or module_is_available
    which = which or shutil.which
    cpu_count = cpu_count or os.cpu_count
    memory_gb = memory_gb or windows_memory_gb
    requirements = parse_requirements(task_dir)
    cpus = cpu_count() or 0
    memory = memory_gb()
    task_standard = module_available("metr.task_protected_scoring")
    tools = {name: which(name) for name in ["rustc", "cargo", "docker", "git"]}
    blocked_reasons: list[str] = []
    if not task_standard:
        blocked_reasons.append("task_standard_runtime_missing")
    if not env.get(REQUIRED_ENV):
        blocked_reasons.append("task_openai_key_missing")
    if not tools.get("rustc") or not tools.get("cargo"):
        blocked_reasons.append("rust_toolchain_missing")
    if not tools.get("docker"):
        blocked_reasons.append("docker_missing")
    if cpus < requirements["required_cpus"] or memory is None or memory < requirements["required_memory_gb"]:
        blocked_reasons.append("resource_envelope_insufficient")
    return {
        "requirements": requirements,
        "available": {
            "logical_cpus": cpus,
            "memory_gb": memory,
            "tools": tools,
            "task_standard_runtime": task_standard,
            "task_openai_key_present": bool(env.get(REQUIRED_ENV)),
        },
        "blocked_reasons": blocked_reasons,
    }


def build_receipt(*, repo: Path, task_family: str, task_dir: Path, out: Path, preflight: dict[str, Any]) -> dict[str, Any]:
    readme = (task_dir / "README.md").read_text(encoding="utf-8", errors="replace")
    build_steps = (task_dir / "build_steps.json").read_text(encoding="utf-8", errors="replace")
    protected_zips = sorted(task_dir.glob("*.zip"))
    blocked = preflight["blocked_reasons"]
    verdict = "REBENCH_FIRST_LOOP_BLOCKED" if blocked else "REBENCH_FIRST_LOOP_PREFLIGHT_PASS"
    receipt = {
        "ticket": "EMBER-REBENCH-FIRST-LOOP",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "repo": str(repo),
        "goal_path": str(repo / "docs/authority/GOAL.md"),
        "goal_source_sha256": sha256_file(repo / "docs/authority/GOAL.md") if (repo / "docs/authority/GOAL.md").exists() else None,
        "task_family": task_family,
        "task_dir": str(task_dir),
        "source_hashes": {
            "readme_sha256": sha256_text(readme),
            "manifest_sha256": preflight["requirements"]["manifest_sha256"],
            "build_steps_sha256": sha256_text(build_steps),
        },
        "frozen_public_inputs": {
            "task_family": task_family,
            "readme_sha256": sha256_text(readme),
            "build_steps_sha256": sha256_text(build_steps),
            "heldout_test_file_not_read": True,
            "protected_solution_contents_excluded": True,
        },
        "protected_solution_handling": {
            "protected_solution_files": len(protected_zips),
            "protected_solution_zip_names": [path.name for path in protected_zips],
            "extracted_protected_solutions": False,
            "quoted_or_published_solution_contents": False,
        },
        "preflight": preflight,
        "blocked_reasons": blocked,
        "equal_budget_status": "not_run_preflight_blocked" if blocked else "ready_to_enforce_in_first_loop",
        "abc_deleted_status": "not_run_preflight_blocked" if blocked else "preflight_only_no_scores_yet",
        "native_operator_routing": {
            "selected": task_family,
            "admission_state": "BLOCKED_RUNTIME_PREFLIGHT" if blocked else "PREFLIGHT_READY",
            "reason": "CPU-only RE-Bench family is the first executable field-level target after ScienceAgentBench artifact access blocked.",
        },
        "deleted_selector_routing": {
            "selected": None,
            "admission_state": "ROUTING_BLOCKED_DELETED_SELECTOR",
            "reason": "Deleting the native loop selector prevents choosing the CPU-only RE-Bench task family.",
        },
        "deletion_sensitive": True,
        "next_benchmark_if_unfixable": {
            "selected": "paperbench",
            "next_executable_command": "python scripts\\ember_paperbench_admission.py --out receipts\\ember-post-resident-discovery\\paperbench-admission-<timestamp>.json",
        },
        "next_executable_command": (
            "Install/enable the missing RE-Bench runtime pieces named in blocked_reasons, then rerun this command."
            if blocked
            else "Run matched A/B/C/deleted RE-Bench attempts under the admitted task-standard runtime."
        ),
        "code_vs_docs_metric": {
            "classification": "during-project RE-Bench first-loop preflight receipt",
            "script_code_lines": len((repo / "scripts" / "ember_rebench_first_loop.py").read_text(encoding="utf-8").splitlines()) if (repo / "scripts" / "ember_rebench_first_loop.py").exists() else 0,
            "receipt_lines": 0,
        },
        "verdict": verdict,
    }
    receipt["code_vs_docs_metric"]["receipt_lines"] = len(json.dumps(receipt, indent=2, sort_keys=True).splitlines())
    write_json(out, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--task-family", default=DEFAULT_TASK_FAMILY)
    parser.add_argument("--rebench-root", default=None)
    parser.add_argument("--frozen-slice", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    if args.selftest:
        import ember_rebench_first_loop_selftest
        return ember_rebench_first_loop_selftest.main()
    if not args.rebench_root:
        parser.error(
            "--rebench-root is required unless --selftest is used (no baked-in "
            "default; original path was scrubbed for public export, see issue #261)"
        )
    repo = Path.cwd().resolve()
    task_dir = Path(args.rebench_root) / args.task_family
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else Path("receipts/ember-post-resident-discovery") / f"rebench-first-loop-{ts}.json"
    if not out.is_absolute():
        out = repo / out
    preflight = evaluate_preflight(task_dir=task_dir)
    receipt = build_receipt(repo=repo, task_family=args.task_family, task_dir=task_dir, out=out, preflight=preflight)
    print(json.dumps({
        "receipt": str(out),
        "verdict": receipt["verdict"],
        "blocked_reasons": receipt["blocked_reasons"],
        "selected": receipt["native_operator_routing"]["selected"],
        "next_executable_command": receipt["next_executable_command"],
    }, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] in {"REBENCH_FIRST_LOOP_BLOCKED", "REBENCH_FIRST_LOOP_PREFLIGHT_PASS"} else 2


if __name__ == "__main__":
    raise SystemExit(main())