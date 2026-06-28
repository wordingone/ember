#!/usr/bin/env python3
"""PaperBench admission probe for Ember's post-RE-Bench path."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"

DEFAULT_FRONTIER_ROOT = Path(r"<local-path>")
PAPERBENCH_GITHUB = "https://github.com/openai/frontier-evals/tree/main/project/paperbench"
PAPERBENCH_ARXIV = "https://arxiv.org/abs/2504.01848"
EXPECTED_PAPER_COUNT = 20
REQUIRED_PAPER_FILES = ("addendum.md", "paper.md", "paper.pdf")


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
    except Exception:  # noqa: BLE001
        return None


def path_status(root: Path) -> dict[str, bool]:
    pb = root / "project" / "paperbench"
    return {
        "frontier_root_exists": root.exists(),
        "root_readme": (root / "README.md").exists(),
        "root_license": (root / "LICENSE.md").exists(),
        "root_pyproject": (root / "pyproject.toml").exists(),
        "paperbench_readme": (pb / "README.md").exists(),
        "paperbench_data_dir": (pb / "data").is_dir(),
        "paperbench_papers_dir": (pb / "data" / "papers").is_dir(),
        "paperbench_judge_eval_dir": (pb / "data" / "judge_eval").is_dir(),
    }


def collect_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for label, path in {
        "root_readme_sha256": root / "README.md",
        "root_license_sha256": root / "LICENSE.md",
        "paperbench_readme_sha256": root / "project" / "paperbench" / "README.md",
        "root_pyproject_sha256": root / "pyproject.toml",
    }.items():
        if path.exists() and path.is_file():
            hashes[label] = sha256_file(path)
    return hashes




def is_lfs_pointer(path: Path) -> bool:
    try:
        if path.stat().st_size > 2048:
            return False
        return path.read_bytes().startswith(b"version https://git-lfs.github.com/spec/v1")
    except OSError:
        return False


def paperbench_data_hydration_metrics(root: Path) -> dict[str, Any]:
    pb_data = root / "project" / "paperbench" / "data"
    papers_root = pb_data / "papers"
    paper_dirs = sorted([p for p in papers_root.iterdir() if p.is_dir()]) if papers_root.is_dir() else []
    files = sorted([p for p in pb_data.rglob("*") if p.is_file()]) if pb_data.is_dir() else []
    pointer_files = [p for p in files if is_lfs_pointer(p)]
    missing_required: dict[str, list[str]] = {}
    for paper_dir in paper_dirs:
        missing = [name for name in REQUIRED_PAPER_FILES if not (paper_dir / name).is_file()]
        if missing:
            missing_required[paper_dir.name] = missing
    return {
        "expected_paper_count": EXPECTED_PAPER_COUNT,
        "paper_dir_count": len(paper_dirs),
        "paper_dirs": [p.name for p in paper_dirs],
        "required_files_per_paper": list(REQUIRED_PAPER_FILES),
        "papers_missing_required_files": missing_required,
        "file_count": len(files),
        "total_bytes": sum(p.stat().st_size for p in files),
        "lfs_pointer_file_count": len(pointer_files),
        "lfs_pointer_file_samples": [str(p.relative_to(root)) for p in pointer_files[:20]],
        "hydration_ready": (
            len(paper_dirs) >= EXPECTED_PAPER_COUNT
            and not missing_required
            and not pointer_files
        ),
    }

def build_admission_receipt(*, repo: Path, frontier_root: Path, out: Path) -> dict[str, Any]:
    status = path_status(frontier_root)
    hydration = paperbench_data_hydration_metrics(frontier_root)
    pb = frontier_root / "project" / "paperbench"
    readme = (pb / "README.md").read_text(encoding="utf-8", errors="replace") if status["paperbench_readme"] else ""
    blocked_reasons: list[str] = []
    if not all([status["root_pyproject"], status["paperbench_readme"], status["paperbench_data_dir"]]):
        blocked_reasons.append("paperbench_project_incomplete")
    if not status["paperbench_papers_dir"]:
        blocked_reasons.append("paperbench_data_lfs_not_hydrated")
    if hydration["paper_dir_count"] < EXPECTED_PAPER_COUNT:
        blocked_reasons.append("paperbench_data_partial")
    if hydration["papers_missing_required_files"]:
        blocked_reasons.append("paperbench_required_files_missing")
    if hydration["lfs_pointer_file_count"]:
        blocked_reasons.append("paperbench_data_lfs_pointer_files")
    if "uv sync" not in readme:
        blocked_reasons.append("paperbench_runtime_instructions_missing")
    if "Git-LFS" in readme or "git lfs fetch" in readme:
        data_policy = "README requires manual Git-LFS hydration for project/paperbench/data and separately notes JudgeEval tarballs that cannot be redistributed automatically."
    else:
        data_policy = "PaperBench data hydration policy not confirmed from local README."
    admitted = not blocked_reasons
    receipt = {
        "ticket": "EMBER-PAPERBENCH-ADMISSION",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "repo": str(repo),
        "goal_path": str(repo / "GOAL.md"),
        "goal_source_sha256": sha256_file(repo / "GOAL.md") if (repo / "GOAL.md").exists() else None,
        "sources": {
            "github": PAPERBENCH_GITHUB,
            "arxiv": PAPERBENCH_ARXIV,
            "local_frontier_root": str(frontier_root),
            "local_git_head": git_head(frontier_root),
        },
        "source_hashes": collect_hashes(frontier_root),
        "license_access": {
            "frontier_evals_license": "MIT license per local LICENSE.md" if status["root_license"] else "license file missing locally",
            "data_hydration_policy": data_policy,
        },
        "benchmark_facts": {
            "name": "PaperBench",
            "paperbench_readme_present": status["paperbench_readme"],
            "paper_claim": "20 ICML 2024 Spotlight/Oral paper replications and 8316 gradable tasks per paper/README sources",
            "stages": ["agent rollout", "reproduction", "grading"],
            "requires_uv": "uv sync" in readme,
            "requires_docker": "Docker" in readme,
            "requires_api_keys": "API key" in readme or "OPENAI_API_KEY" in readme,
            "requires_gpu_for_full_run": "GPU" in readme,
        },
        "local_materialization": status,
        "data_hydration_metrics": hydration,
        "blocked_reasons": blocked_reasons,
        "native_operator_routing": {
            "selected": "paperbench",
            "admission_state": "ADMITTED" if admitted else "BLOCKED_LOCAL_MATERIALIZATION",
            "reason": "PaperBench is the next field-level benchmark after ScienceAgentBench artifact access and RE-Bench first-loop preflight both blocked by receipt.",
        },
        "deleted_selector_routing": {
            "selected": None,
            "admission_state": "ROUTING_BLOCKED_DELETED_SELECTOR",
            "reason": "Deleting the native benchmark router prevents justified transition from RE-Bench block to PaperBench.",
        },
        "deletion_sensitive": True,
        "protected_data_boundaries": {
            "data_lfs_hydrated": status["paperbench_data_dir"] and status["paperbench_papers_dir"] and hydration["hydration_ready"],
            "judge_eval_tarballs_redistributed": False,
            "private_or_large_data_not_embedded_in_receipt": True,
        },
        "frozen_heldout_slice": {
            "status": "not_frozen_materialization_blocked" if blocked_reasons else "ready_to_freeze_from_local_data",
            "gold_or_rubric_private_contents_excluded": True,
        },
        "next_benchmark_if_blocked": {
            "selected": "broader-d3-multifamily",
            "next_executable_command": "python scripts\\ember_d3_broader_multifamily_admission.py --out receipts\\ember-post-resident-discovery\\d3-broader-multifamily-admission-<timestamp>.json",
        },
        "next_executable_command": (
            "Hydrate PaperBench Git-LFS data and missing project files, then rerun admission."
            if blocked_reasons else
            "Run first PaperBench A/B/C/deleted loop using the admitted local PaperBench project."
        ),
        "code_vs_docs_metric": {
            "classification": "during-project PaperBench admission receipt",
            "script_code_lines": len((repo / "scripts" / "ember_paperbench_admission.py").read_text(encoding="utf-8").splitlines()) if (repo / "scripts" / "ember_paperbench_admission.py").exists() else 0,
            "receipt_lines": 0,
        },
        "verdict": "PAPERBENCH_ADMITTED" if admitted else "PAPERBENCH_BLOCKED",
    }
    receipt["code_vs_docs_metric"]["receipt_lines"] = len(json.dumps(receipt, indent=2, sort_keys=True).splitlines())
    write_json(out, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--frontier-root", default=str(DEFAULT_FRONTIER_ROOT))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    if args.selftest:
        import ember_paperbench_admission_selftest
        return ember_paperbench_admission_selftest.main()
    repo = Path.cwd().resolve()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else Path("receipts/ember-post-resident-discovery") / f"paperbench-admission-{ts}.json"
    if not out.is_absolute():
        out = repo / out
    receipt = build_admission_receipt(repo=repo, frontier_root=Path(args.frontier_root), out=out)
    print(json.dumps({
        "receipt": str(out),
        "verdict": receipt["verdict"],
        "blocked_reasons": receipt["blocked_reasons"],
        "selected": receipt["native_operator_routing"]["selected"],
        "next_executable_command": receipt["next_executable_command"],
    }, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] in {"PAPERBENCH_ADMITTED", "PAPERBENCH_BLOCKED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())