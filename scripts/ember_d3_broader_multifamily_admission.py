#!/usr/bin/env python3
"""Admit a broader fresh D3-Gym multi-family slice for Ember's next loop."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_STATE_ROOT = Path(r"<local-path>")
SOLVED_TASK_IDS = {"task_9", "task_10", "task_11", "task_12"}
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
D3_HF = "https://huggingface.co/datasets/osunlp/D3-Gym"
D3_GITHUB = "https://github.com/osunlp/D3-Gym"
D3_ARXIV = "https://arxiv.org/abs/2506.04592"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def task_id(row: dict[str, Any]) -> str | None:
    return row.get("task_id") or row.get("id") or row.get("task")


def field(row: dict[str, Any], *names: str) -> Any:
    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    for name in names:
        if row.get(name) is not None:
            return row.get(name)
        if meta.get(name) is not None:
            return meta.get(name)
    return None


def load_rows(path: Path) -> list[dict[str, Any]]:
    data = read_json(path)
    if isinstance(data, dict):
        rows = data.get("rows") or data.get("tasks") or data.get("data") or []
    elif isinstance(data, list):
        rows = data
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def normalize_row(row: dict[str, Any], source_path: Path) -> dict[str, Any]:
    tid = task_id(row)
    normalized = {
        "task_id": tid,
        "discipline": field(row, "discipline", "domain", "category"),
        "original_repo": field(row, "original_repo", "repo", "github_repo", "github"),
        "docker_image": field(row, "docker_image", "image"),
        "evaluator_kind": field(row, "evaluator_kind", "evaluator", "eval_type") or "docker_run_and_eval",
        "source_row_idx": field(row, "source_row_idx", "row_idx", "index"),
        "source_path": str(source_path),
        "row_sha256": sha256_text(json.dumps(row, sort_keys=True, ensure_ascii=False)),
    }
    return normalized


def candidate_files(state_root: Path) -> list[Path]:
    return sorted(state_root.glob("D3-Gym*/d3-gym-tasks-frozen*.json"))


def collect_candidates(state_root: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for path in candidate_files(state_root):
        for row in load_rows(path):
            normalized = normalize_row(row, path)
            if normalized["task_id"]:
                candidates.append(normalized)
    return candidates


def task_number(row: dict[str, Any]) -> int:
    text = str(row.get("task_id") or "")
    if text.startswith("task_"):
        try:
            return int(text.split("_")[-1])
        except ValueError:
            return -1
    return -1


def latest_surface_rows(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_source: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        by_source.setdefault(str(row.get("source_path") or ""), []).append(row)
    best_rows: list[dict[str, Any]] = []
    best_max = -1
    for rows in by_source.values():
        surface_max = max((task_number(row) for row in rows), default=-1)
        if surface_max > best_max:
            best_max = surface_max
            best_rows = rows
    return best_rows


def select_multifamily_slice(candidates: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    latest = latest_surface_rows(candidates)
    fresh = [row for row in latest if row["task_id"] not in SOLVED_TASK_IDS]
    by_repo: dict[str, list[dict[str, Any]]] = {}
    for row in fresh:
        repo = str(row.get("original_repo") or "")
        if not repo:
            continue
        by_repo.setdefault(repo, []).append(row)
    selected: list[dict[str, Any]] = []
    for repo in sorted(by_repo):
        rows = sorted(by_repo[repo], key=task_number)
        if rows:
            selected.append(rows[0])
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        selected_ids = {row["task_id"] for row in selected}
        for row in sorted(fresh, key=task_number):
            if row["task_id"] not in selected_ids:
                selected.append(row)
                selected_ids.add(row["task_id"])
            if len(selected) >= limit:
                break
    return sorted(selected, key=task_number)


def find_admission_receipts(state_root: Path) -> list[Path]:
    return sorted(state_root.glob("D3-Gym*/d3-gym-admission*.json"))


def build_admission_receipt(*, repo: Path, state_root: Path, out: Path) -> dict[str, Any]:
    candidates = collect_candidates(state_root)
    selected = select_multifamily_slice(candidates)
    repos = sorted({str(row["original_repo"]) for row in selected if row.get("original_repo")})
    disciplines = sorted({str(row["discipline"]) for row in selected if row.get("discipline")})
    evaluators = sorted({str(row["evaluator_kind"]) for row in selected if row.get("evaluator_kind")})
    source_paths = sorted({row["source_path"] for row in selected})
    source_hashes = {path: sha256_file(Path(path)) for path in source_paths if Path(path).exists()}
    admission_paths = find_admission_receipts(state_root)
    admission_hashes = {str(path): sha256_file(path) for path in admission_paths if path.exists()}

    blocked_reasons: list[str] = []
    if not candidates:
        blocked_reasons.append("d3_frozen_rows_missing")
    if len(selected) < 4:
        blocked_reasons.append("insufficient_fresh_task_count")
    if len(repos) < 2:
        blocked_reasons.append("insufficient_family_diversity")
    if any(row["task_id"] in SOLVED_TASK_IDS for row in selected):
        blocked_reasons.append("solved_task_reused")
    if not evaluators:
        blocked_reasons.append("evaluator_inventory_missing")

    admitted = not blocked_reasons
    task_args = " ".join(f"--task-id {row['task_id']}" for row in selected) if selected else "--task-id <blocked>"
    next_command = (
        "python scripts\\ember_d3_broader_multifamily_loop.py "
        "--admission receipts\\ember-post-resident-discovery\\d3-broader-multifamily-admission-<timestamp>.json "
        f"{task_args} --timeout-seconds 180 --execute"
    )
    receipt = {
        "ticket": "EMBER-D3-BROADER-MULTIFAMILY-ADMISSION",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "repo": str(repo),
        "goal_path": str(repo / "GOAL.md"),
        "goal_source_sha256": sha256_file(repo / "GOAL.md") if (repo / "GOAL.md").exists() else None,
        "sources": {
            "hf_dataset": D3_HF,
            "github": D3_GITHUB,
            "arxiv": D3_ARXIV,
            "local_state_root": str(state_root),
            "admission_receipts": [str(path) for path in admission_paths],
        },
        "source_hashes": {
            "selected_frozen_row_files": source_hashes,
            "local_admission_receipts": admission_hashes,
        },
        "license_access": {
            "basis": "public D3-Gym dataset rows already materialized locally plus local admission receipt license/access basis",
            "no_private_gold_or_solution_contents_embedded": True,
            "task_rows_refrozen_from_public_materialization": True,
        },
        "benchmark_facts": {
            "name": "D3-Gym",
            "candidate_count": len(candidates),
            "solved_task_ids_excluded": sorted(SOLVED_TASK_IDS),
            "selected_task_count": len(selected),
            "family_diversity": {
                "original_repo_count": len(repos),
                "original_repos": repos,
                "qualifies_as_multifamily": len(repos) >= 2,
            },
            "domain_diversity": {
                "discipline_count": len(disciplines),
                "disciplines": disciplines,
                "honest_limitation": "single_discipline_chemistry" if disciplines == ["Chemistry"] else None,
            },
            "fresh_relative_to_solved_d3_task9_12": not any(row["task_id"] in SOLVED_TASK_IDS for row in selected),
        },
        "frozen_heldout_slice": {
            "selection_rule": "Native selector chooses fresh unsolved D3 rows, one per source repo first, to maximize family diversity before adding same-family rows.",
            "rows": selected,
            "sha256": sha256_text(json.dumps(selected, sort_keys=True)),
            "gold_or_solution_contents_excluded": True,
        },
        "task_evaluator_inventory": {
            "evaluator_kinds": evaluators,
            "docker_images": [row["docker_image"] for row in selected if row.get("docker_image")],
            "requires_docker": "docker_run_and_eval" in evaluators,
        },
        "native_operator_routing": {
            "selected": "d3-broader-multifamily" if admitted else None,
            "admission_state": "ADMITTED" if admitted else "BLOCKED",
            "reason": "ScienceAgentBench artifact access, RE-Bench first-loop feasibility, and PaperBench materialization are receipt-blocked; this D3 slice is the next local external heldout route only if it is fresh and multi-family.",
        },
        "deleted_selector_routing": {
            "selected": None,
            "admission_state": "ROUTING_BLOCKED_DELETED_SELECTOR",
            "reason": "Deleting the native selector leaves source inspection intact but removes the justified family-diverse task route; no static priority fallback is allowed.",
        },
        "deletion_sensitive": True,
        "blocked_reasons": blocked_reasons,
        "next_executable_command": next_command if admitted else "Reopen external benchmark discovery; broader D3 admission blocked by " + ", ".join(blocked_reasons),
        "next_benchmark_if_blocked": {
            "selected": "external-benchmark-discovery",
            "next_executable_command": "python scripts\\ember_external_benchmark_discovery.py --exclude scienceagentbench,re-bench,paperbench,d3-gym --out receipts\\ember-post-resident-discovery\\external-benchmark-discovery-<timestamp>.json",
        },
        "code_vs_docs_metric": {
            "classification": "during-project broader-D3 admission receipt",
            "script_code_lines": len((repo / "scripts" / "ember_d3_broader_multifamily_admission.py").read_text(encoding="utf-8").splitlines()) if (repo / "scripts" / "ember_d3_broader_multifamily_admission.py").exists() else 0,
            "receipt_lines": 0,
        },
        "verdict": "D3_BROADER_MULTIFAMILY_ADMITTED" if admitted else "D3_BROADER_MULTIFAMILY_BLOCKED",
    }
    receipt["code_vs_docs_metric"]["receipt_lines"] = len(json.dumps(receipt, indent=2, sort_keys=True).splitlines())
    write_json(out, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--state-root", default=str(DEFAULT_STATE_ROOT))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    if args.selftest:
        import ember_d3_broader_multifamily_admission_selftest

        return ember_d3_broader_multifamily_admission_selftest.main()
    repo = Path.cwd().resolve()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else Path("receipts/ember-post-resident-discovery") / f"d3-broader-multifamily-admission-{ts}.json"
    if not out.is_absolute():
        out = repo / out
    receipt = build_admission_receipt(repo=repo, state_root=Path(args.state_root), out=out)
    print(json.dumps({
        "receipt": str(out),
        "verdict": receipt["verdict"],
        "blocked_reasons": receipt["blocked_reasons"],
        "selected": receipt["native_operator_routing"]["selected"],
        "selected_task_ids": [row["task_id"] for row in receipt["frozen_heldout_slice"]["rows"]],
        "next_executable_command": receipt["next_executable_command"],
    }, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] in {"D3_BROADER_MULTIFAMILY_ADMITTED", "D3_BROADER_MULTIFAMILY_BLOCKED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
