#!/usr/bin/env python3
"""Run a three-seed MLAgentBench CLRS upstream-baseline comparator receipt.

This is stronger than the one-step smoke because it records multiple governed
upstream-baseline seeds and aggregate score statistics. It is still not an
Ember improvement claim: no Ember loop or equal-budget patch comparator runs
here.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from run_c5_mlagentbench_clrs_smoke import apply_compat_patch, git_head, module_versions, parse_log, sha256

EXPECTED_COMMIT = "5d71205cc20a8e95d43aa7cb7120e89ca3323e31"


def run_seed(args: argparse.Namespace, source_copy: Path, seed: int) -> dict[str, Any]:
    clrs_root = source_copy / "MLAgentBench" / "benchmarks" / "CLRS"
    train_py = clrs_root / "env" / "train.py"
    run_root = args.scratch.resolve() / f"seed-{seed}"
    run_root.mkdir(parents=True, exist_ok=True)
    command = [
        str(args.python.resolve()),
        str(train_py),
        "--algorithms=floyd_warshall",
        "--train_lengths=4",
        f"--seed={seed}",
        f"--batch_size={args.batch_size}",
        f"--train_steps={args.train_steps}",
        f"--eval_every={args.eval_every}",
        f"--test_every={args.train_steps}",
        f"--log_every={args.eval_every}",
        f"--hidden_size={args.hidden_size}",
        "--nb_msg_passing_steps=1",
        *args.extra_train_flag,
        f"--checkpoint_path={run_root / 'checkpoints'}",
        f"--dataset_path={run_root / 'CLRS30'}",
    ]
    env = __import__("os").environ.copy()
    env["PYTHONPATH"] = str(clrs_root / "env")
    env["TF_CPP_MIN_LOG_LEVEL"] = "3"
    started = datetime.now(timezone.utc)
    proc = subprocess.run(command, text=True, capture_output=True, cwd=str(clrs_root / "env"), env=env)
    ended = datetime.now(timezone.utc)
    combined = (proc.stdout or "") + (proc.stderr or "")
    (run_root / "train.log").write_text(combined, encoding="utf-8", newline="\n")
    parsed = parse_log(combined)
    ckpt = run_root / "checkpoints"
    checkpoint_files = []
    if ckpt.exists():
        for path in sorted(p for p in ckpt.rglob("*") if p.is_file()):
            checkpoint_files.append({
                "name": path.relative_to(ckpt).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            })
    test_scores = [row["score"] for row in parsed.get("test_events", [])]
    val_scores = [row["score"] for row in parsed.get("val_events", [])]
    pass_conditions = {
        "returncode_zero": proc.returncode == 0,
        "done_seen": parsed.get("done_seen") is True,
        "checkpoint_seen": parsed.get("checkpoint_seen") is True,
        "restore_seen": parsed.get("restore_seen") is True,
        "has_test_score": bool(test_scores),
        "has_checkpoint_files": len(checkpoint_files) >= 3,
    }
    return {
        "seed": seed,
        "duration_seconds": round((ended - started).total_seconds(), 3),
        "pass_conditions": pass_conditions,
        "passed": all(pass_conditions.values()),
        "test_score": test_scores[-1] if test_scores else None,
        "best_val_score_observed": max(val_scores) if val_scores else None,
        "parsed_log": parsed,
        "checkpoint_files": checkpoint_files,
        "stdout_stderr_tail": combined[-3000:],
    }


def summarize(seed_runs: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [r["test_score"] for r in seed_runs if isinstance(r.get("test_score"), (int, float))]
    if not scores:
        return {"seed_count": len(seed_runs), "valid_score_count": 0}
    return {
        "seed_count": len(seed_runs),
        "valid_score_count": len(scores),
        "mean_test_score": statistics.fmean(scores),
        "min_test_score": min(scores),
        "max_test_score": max(scores),
        "stdev_test_score": statistics.stdev(scores) if len(scores) > 1 else 0.0,
        "scores": scores,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mlagentbench", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--seeds", default="42,43,44")
    parser.add_argument("--train-steps", type=int, default=3)
    parser.add_argument("--eval-every", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--hidden-size", type=int, default=16)
    parser.add_argument("--variant-id", default="upstream_baseline")
    parser.add_argument("--variant-description", default="unchanged upstream MLAgentBench CLRS baseline with declared Windows/NumPy compatibility patch")
    parser.add_argument("--extra-train-flag", action="append", default=[])
    parser.add_argument("--completion-limit", default="This is a governed three-seed upstream-baseline comparator receipt for C5-0A. It is not an Ember loop result, not an equal-budget deterministic patch comparator, not a C5 improvement claim, and not overall baseline completion.")
    args = parser.parse_args()

    seeds = [int(x.strip()) for x in args.seeds.split(",") if x.strip()]
    if len(seeds) < 3:
        raise SystemExit("at least three seeds are required")
    source = args.mlagentbench.resolve()
    scratch = args.scratch.resolve()
    source_copy = scratch / "MLAgentBench-compat-copy"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)
    shutil.copytree(source, source_copy)
    clrs_root = source_copy / "MLAgentBench" / "benchmarks" / "CLRS"
    patches = apply_compat_patch([clrs_root / "env" / "train.py", clrs_root / "scripts" / "eval.py"])

    started = datetime.now(timezone.utc)
    seed_runs = [run_seed(args, source_copy, seed) for seed in seeds]
    ended = datetime.now(timezone.utc)
    summary = summarize(seed_runs)
    pass_conditions = {
        "source_commit_pinned": git_head(source) == EXPECTED_COMMIT,
        "three_or_more_seeds": len(seeds) >= 3,
        "all_seed_runs_passed": all(run.get("passed") for run in seed_runs),
        "all_seed_scores_numeric": summary.get("valid_score_count") == len(seeds),
    }
    verdict = "C5_MLAGENTBENCH_CLRS_GOVERNED_BASELINE_PASS" if all(pass_conditions.values()) else "C5_MLAGENTBENCH_CLRS_GOVERNED_BASELINE_FAIL"
    receipt = {
        "created_at_utc": ended.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "duration_seconds": round((ended - started).total_seconds(), 3),
        "verdict": verdict,
        "failure_count": 0 if verdict.endswith("PASS") else 1,
        "pass_conditions": pass_conditions,
        "source": {
            "id": "mlagentbench",
            "selected_task": "CLRS/floyd_warshall",
            "source_commit": git_head(source),
            "expected_commit": EXPECTED_COMMIT,
            "upstream_train_sha256": sha256(source / "MLAgentBench" / "benchmarks" / "CLRS" / "env" / "train.py"),
            "upstream_eval_sha256": sha256(source / "MLAgentBench" / "benchmarks" / "CLRS" / "scripts" / "eval.py"),
        },
        "compatibility_patch": patches,
        "environment": {
            "runner_python_label": "isolated CLRS venv supplied by --python; local absolute path intentionally omitted",
            "module_versions": module_versions(args.python.resolve()),
        },
        "run_config": {
            "algorithm": "floyd_warshall",
            "train_lengths": [4],
            "seeds": seeds,
            "batch_size": args.batch_size,
            "train_steps": args.train_steps,
            "eval_every": args.eval_every,
            "hidden_size": args.hidden_size,
            "nb_msg_passing_steps": 1,
            "variant_id": args.variant_id,
            "comparator": args.variant_description,
            "extra_train_flags": args.extra_train_flag,
        },
        "aggregate": summary,
        "seed_runs": seed_runs,
        "local_path_policy": "Receipt omits absolute local paths. Reproduce by cloning MLAgentBench at the pinned commit, creating the isolated CLRS env, and running this script with local --mlagentbench/--python/--scratch paths.",
        "completion_limit": args.completion_limit,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(receipt, indent=2 if args.pretty else None, sort_keys=True)
    args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if verdict.endswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
