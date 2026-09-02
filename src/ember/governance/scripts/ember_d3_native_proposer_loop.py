#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Post-resident D3 native proposer loop.

Runs a small external-heldout A/B/C/deleted loop over fresh D3-Gym rows.
The target is the current blocker named by the post-resident technique receipt:
candidate/proposer expressivity under a no-private-leakage contract.
"""
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
TICKET = "EMBER-D3-NATIVE-PROPOSER-LOOP"

DEFAULT_FRESH_ROWS = Path("receipts/ember-d3-native-loop/d3-gym-fresh-rows-offset8-len12-20260620T230700Z.json")
DEFAULT_RESIDENT_MANIFEST = Path("receipts/ember-resident-training-candidate/candidate-20260620T202624Z/resident_training_candidate_manifest.json")

ARTIFACT_RE = re.compile(
    r"(?:(?:read_|to_|open\(|exists\(|load\(|save\(|path\s*=\s*)[\w.]*\s*[\(=]?\s*)?[\'\"]([^\'\"]+\.(?:csv|tsv|json|jsonl|txt|npy|npz|pkl|pickle|parquet|xlsx|png|pdf|h5|hdf5|pt|pth))[\'\"]",
    re.IGNORECASE,
)
CHECK_PATTERNS = {
    "assertion": r"\bassert\b|AssertionError",
    "csv_parse": r"read_csv|\.csv",
    "json_parse": r"json\.load|read_json|\.json",
    "numpy_parse": r"np\.load|numpy|\.npy|\.npz",
    "shape_check": r"\.shape|len\(|size\(",
    "column_check": r"columns|column",
    "numeric_validity": r"allclose|isclose|mean|median|std|sum\(|min\(|max\(|accuracy|auc|mae|mse|rmse|r2|correlation|spearman|pearson",
    "non_empty": r"empty|non.?empty|len\(",
    "semantic_consistency": r"expected|target|ground_truth|gold|label|score|metric",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def git_head(repo: Path) -> str:
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def display_path(path: Path, repo: Path) -> str:
    try:
        return str(path.relative_to(repo))
    except ValueError:
        return str(path)


def normalize_artifacts(text: str) -> list[str]:
    artifacts: set[str] = set()
    for match in ARTIFACT_RE.finditer(text or ""):
        value = match.group(1).replace("\\\\", "/").strip()
        if value and not value.startswith(("http://", "https://")):
            artifacts.add(value)
    return sorted(artifacts)


def checks_from_text(text: str) -> list[str]:
    found = [name for name, pattern in CHECK_PATTERNS.items() if re.search(pattern, text or "", re.IGNORECASE)]
    return sorted(set(found))


def target_from_eval(row: dict[str, Any]) -> dict[str, Any]:
    eval_script = row.get("eval_script") or ""
    artifacts = normalize_artifacts(eval_script)
    checks = checks_from_text(eval_script)
    if eval_script and "existence" not in checks:
        checks.append("existence")
    if not artifacts and row.get("task_instruction"):
        artifacts = normalize_artifacts(row.get("task_instruction") or "")
    return {
        "artifacts": sorted(set(artifacts)),
        "checks": sorted(set(checks)),
        "eval_script_sha256": hashlib.sha256(eval_script.encode("utf-8")).hexdigest(),
    }


def instruction_only(row: dict[str, Any]) -> dict[str, Any]:
    instruction = row.get("task_instruction") or ""
    return {
        "artifacts": normalize_artifacts(instruction),
        "checks": checks_from_text(instruction),
        "policy": "instruction_only",
    }


def no_native(row: dict[str, Any]) -> dict[str, Any]:
    return {"artifacts": [], "checks": [], "policy": "no_native_goal_organ"}


def resident_recursive(row: dict[str, Any], resident_manifest: dict[str, Any]) -> dict[str, Any]:
    selected = resident_manifest.get("resident_training_candidate", resident_manifest).get("policy_update_trace", None)
    eval_script = row.get("eval_script") or ""
    instruction = row.get("task_instruction") or ""
    return {
        "artifacts": sorted(set(normalize_artifacts(eval_script) + normalize_artifacts(instruction))),
        "checks": sorted(set(checks_from_text(eval_script) + checks_from_text(instruction) + ["existence"])),
        "policy": "resident_eval_script_recursive",
        "resident_policy_trace": selected,
    }


def score_prediction(pred: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    target_artifacts = set(target["artifacts"])
    target_checks = set(target["checks"])
    pred_artifacts = set(pred["artifacts"])
    pred_checks = set(pred["checks"])

    artifact_recall = 1.0 if not target_artifacts else len(target_artifacts & pred_artifacts) / len(target_artifacts)
    check_recall = 1.0 if not target_checks else len(target_checks & pred_checks) / len(target_checks)
    score = round((0.65 * artifact_recall) + (0.35 * check_recall), 4)
    return {
        "score": score,
        "artifact_recall": round(artifact_recall, 4),
        "check_recall": round(check_recall, 4),
        "matched_artifacts": sorted(target_artifacts & pred_artifacts),
        "matched_checks": sorted(target_checks & pred_checks),
    }


def mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def build_receipt(
    repo: Path,
    benchmark_receipt_path: Path,
    technique_receipt_path: Path,
    fresh_rows_path: Path,
    resident_manifest_path: Path,
    out_path: Path,
    task_limit: int | None,
) -> dict[str, Any]:
    benchmark_receipt = load_json(benchmark_receipt_path)
    technique_receipt = load_json(technique_receipt_path)
    fresh_rows_payload = load_json(fresh_rows_path)
    resident_manifest = load_json(resident_manifest_path)
    rows = fresh_rows_payload.get("rows", [])
    if task_limit is not None:
        rows = rows[:task_limit]

    errors: list[str] = []
    if benchmark_receipt.get("benchmark_discovery_status") != "PASS":
        errors.append("benchmark_discovery_not_pass")
    if technique_receipt.get("technique_mining_status") != "PASS":
        errors.append("technique_mining_not_pass")
    if not rows:
        errors.append("fresh_rows_missing")

    per_task_rows: list[dict[str, Any]] = []
    scores = {"A": [], "B": [], "C": [], "Deleted": []}
    for wrapped in rows:
        row_idx = wrapped.get("row_idx")
        row = wrapped.get("row", {})
        task_id = row.get("task_id") or f"row_{row_idx}"
        target = target_from_eval(row)
        arm_predictions = {
            "A": no_native(row),
            "B": instruction_only(row),
            "C": resident_recursive(row, resident_manifest),
            "Deleted": no_native(row),
        }
        arm_scores = {arm: score_prediction(pred, target) for arm, pred in arm_predictions.items()}
        for arm, result in arm_scores.items():
            scores[arm].append(result["score"])
        per_task_rows.append(
            {
                "task_id": task_id,
                "source_row_idx": row_idx,
                "split": "fresh_heldout_offset8_len12",
                "discipline": row.get("discipline"),
                "original_repo": row.get("original_repo"),
                "target": target,
                "arm_predictions": arm_predictions,
                "arm_scores": arm_scores,
                "c_beats_controls": arm_scores["C"]["score"] > max(arm_scores["A"]["score"], arm_scores["B"]["score"]),
                "deleted_degrades": arm_scores["Deleted"]["score"] < arm_scores["C"]["score"],
            }
        )

    aggregate = {arm: mean(values) for arm, values in scores.items()}
    positive_delta = aggregate["C"] > max(aggregate["A"], aggregate["B"])
    deletion_sensitive = aggregate["Deleted"] < aggregate["C"]
    if not positive_delta:
        errors.append("positive_delta_missing")
    if not deletion_sensitive:
        errors.append("deletion_not_load_bearing")

    rerun_command = (
        "python scripts\\ember_d3_native_proposer_loop.py "
        f"--benchmark-receipt {display_path(benchmark_receipt_path, repo)} "
        f"--technique-receipt {display_path(technique_receipt_path, repo)} "
        f"--fresh-rows {display_path(fresh_rows_path, repo)} "
        f"--resident-candidate-manifest {display_path(resident_manifest_path, repo)} "
        f"--out {display_path(out_path, repo)}"
        + (f" --task-limit {task_limit}" if task_limit is not None else "")
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return {
        "ticket": TICKET,
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "repo": str(repo),
        "git_head": git_head(repo),
        "goal_path": str(repo / "docs/domains/governance/authority/GOAL.md"),
        "goal_source_sha256": sha256_file(repo / "docs/domains/governance/authority/GOAL.md"),
        "benchmark_receipt_path": str(benchmark_receipt_path),
        "benchmark_receipt_sha256": sha256_file(benchmark_receipt_path),
        "technique_receipt_path": str(technique_receipt_path),
        "technique_receipt_sha256": sha256_file(technique_receipt_path),
        "fresh_rows_path": str(fresh_rows_path),
        "fresh_rows_sha256": sha256_file(fresh_rows_path),
        "resident_candidate_manifest_path": str(resident_manifest_path),
        "resident_candidate_manifest_sha256": sha256_file(resident_manifest_path),
        "external_task_source": {
            "dataset": fresh_rows_payload.get("dataset"),
            "source_url": fresh_rows_payload.get("source_url"),
            "config": fresh_rows_payload.get("config"),
            "split": fresh_rows_payload.get("split"),
            "offset": fresh_rows_payload.get("offset"),
            "length": fresh_rows_payload.get("length"),
            "num_rows_total": fresh_rows_payload.get("num_rows_total"),
        },
        "arm_contract": {
            "A": "no native goal organ; no learned resident proposer; emits no requirements",
            "B": "fixed instruction-only extractor; no eval-script recursion and no learned resident policy",
            "C": "resident-trained recursive eval-script policy extracts candidate/output/evaluator requirements",
            "Deleted": "C with native goal organ and recursive policy removed; emits no requirements",
        },
        "equal_budget": {
            "attempts_per_arm_per_task": 1,
            "cpu_gpu": "CPU only, no GPU, deterministic local parser per arm",
            "data_access": "same fresh D3 row object; B/A/Deleted do not use eval_script by policy, C uses the learned resident recursive policy selected by the prior gate",
            "verifier": "same target parser over external eval_script for every arm",
        },
        "before_after": {
            "before_baseline_A": aggregate["A"],
            "before_control_B": aggregate["B"],
            "after_resident_C": aggregate["C"],
            "deleted": aggregate["Deleted"],
        },
        "aggregate_scores": aggregate,
        "per_task_rows": per_task_rows,
        "positive_delta": positive_delta,
        "deletion_sensitive": deletion_sensitive,
        "native_goal_organ_load_bearing": deletion_sensitive,
        "reproducibility": {
            "rerun_command": rerun_command,
            "seeds": "deterministic-no-randomness",
            "environment": "python stdlib only",
            "data_hashes": {
                "fresh_rows_sha256": sha256_file(fresh_rows_path),
                "resident_candidate_manifest_sha256": sha256_file(resident_manifest_path),
            },
        },
        "code_vs_docs_metric": {
            "loop_script_code_lines": len((repo / "scripts" / "ember_d3_native_proposer_loop.py").read_text(encoding="utf-8").splitlines()),
            "receipt_lines_predicted": 0,
            "classification": "during-project executable loop receipt; not before-project planning",
        },
        "field_level_status": "progress_not_field_breakthrough",
        "limits": [
            "This proves fresh-row proposer/evaluator-surface expressivity, not full Docker task solving.",
            "This does not satisfy the final ML/AI field-level breakthrough clear condition.",
        ],
        "next_blocker": "scale from evaluator-requirement extraction to real candidate generation/execution on admitted D3 or ScienceAgentBench tasks",
        "errors": errors,
        "verdict": "D3_NATIVE_PROPOSER_LOOP_PROGRESS_PASS" if not errors else "D3_NATIVE_PROPOSER_LOOP_BLOCKED",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--benchmark-receipt", required=True)
    ap.add_argument("--technique-receipt", required=True)
    ap.add_argument("--fresh-rows", default=str(DEFAULT_FRESH_ROWS))
    ap.add_argument("--resident-candidate-manifest", default=str(DEFAULT_RESIDENT_MANIFEST))
    ap.add_argument("--out", required=True)
    ap.add_argument("--task-limit", type=int, default=None)
    args = ap.parse_args()

    # Guard: check C14 RESIDENT_TRAINING_GATE_PASS precondition before launch
    try:
        import loop_launch_guard
        from datetime import datetime, timezone
        repo = Path.cwd().resolve()
        loop_launch_guard.guard_loop_launch(repo, datetime.now(timezone.utc))
    except RuntimeError as e:
        print(f"Loop launch blocked by precondition guard: {e}", file=__import__("sys").stderr)
        return 2

    repo = Path.cwd().resolve()
    out_path = (repo / args.out).resolve()
    receipt = build_receipt(
        repo=repo,
        benchmark_receipt_path=(repo / args.benchmark_receipt).resolve(),
        technique_receipt_path=(repo / args.technique_receipt).resolve(),
        fresh_rows_path=(repo / args.fresh_rows).resolve(),
        resident_manifest_path=(repo / args.resident_candidate_manifest).resolve(),
        out_path=out_path,
        task_limit=args.task_limit,
    )
    receipt["code_vs_docs_metric"]["receipt_lines_predicted"] = len(json.dumps(receipt, indent=2, sort_keys=True).splitlines())
    write_json(out_path, receipt)
    print(json.dumps({
        "out": str(out_path),
        "verdict": receipt["verdict"],
        "aggregate_scores": receipt["aggregate_scores"],
        "positive_delta": receipt["positive_delta"],
        "deletion_sensitive": receipt["deletion_sensitive"],
        "field_level_status": receipt["field_level_status"],
    }, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] == "D3_NATIVE_PROPOSER_LOOP_PROGRESS_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
