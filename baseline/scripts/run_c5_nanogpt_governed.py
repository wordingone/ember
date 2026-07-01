#!/usr/bin/env python3
"""Run a governed bounded C5-0B nanoGPT_lite trial.

This is not a smoke harness: it preserves the upstream model shape and two-seed
run structure, records every budget edit, and marks the receipt as governed.
The bounded profile exists to produce a valid local PASS/FAIL/INVALID-RUN trial
receipt before any long full-budget run is justified.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

PATCHES = {
    "eval_interval = 250 if dataset == \"shakespeare_char\" else 1000": "eval_interval = 10 if dataset == \"shakespeare_char\" else 10",
    "log_interval = 10 if dataset == \"shakespeare_char\" else 100": "log_interval = 5 if dataset == \"shakespeare_char\" else 5",
    "eval_iters = 200": "eval_iters = 10",
    "max_iters = 5000 if dataset == \"shakespeare_char\" else 100000": "max_iters = 20 if dataset == \"shakespeare_char\" else 20",
    "warmup_iters = 100 if dataset == \"shakespeare_char\" else 200": "warmup_iters = 5 if dataset == \"shakespeare_char\" else 5",
    "compile = True  # do not torch compile the model on macbooks": "compile = False  # governed bounded run disables compile overhead",
    "num_samples = 10  # number of samples to draw": "num_samples = 2  # governed bounded inference samples",
    "max_new_tokens = 500  # number of tokens generated in each sample": "max_new_tokens = 64  # governed bounded generation budget",
}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def patch_experiment(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    applied = []
    for old, new in PATCHES.items():
        if old not in text:
            applied.append({"old": old, "new": new, "status": "missing"})
            continue
        text = text.replace(old, new, 1)
        applied.append({"old": old, "new": new, "status": "applied"})
    path.write_text(text, encoding="utf-8", newline="\n")
    return applied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--work-template", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--run-label", default="governed_bounded_run_0")
    parser.add_argument("--candidate-kind", default="external_baseline_control")
    args = parser.parse_args()

    t0 = time.time()
    receipt = {
        "task_id": "C5-0B-AI-Scientist-nanoGPT-lite",
        "job": args.run_label,
        "governed_run": True,
        "candidate_kind": args.candidate_kind,
        "verdict": "INVALID-RUN",
        "timeout_seconds": args.timeout_seconds,
        "budget": {
            "profile": "bounded_non_smoke",
            "max_iters": 20,
            "eval_iters": 10,
            "num_seeds_shakespeare_char": 2,
            "model_shape_preserved": True,
            "batch_size_preserved": True,
            "block_size_preserved": True,
        },
    }
    try:
        repo = args.repo.resolve()
        source = repo / "templates" / "nanoGPT_lite"
        work = args.work_template.resolve()
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(source, work)

        expected_data = work.parent.parent / "data" / "shakespeare_char"
        source_data = repo / "data" / "shakespeare_char"
        if not expected_data.exists():
            expected_data.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_data, expected_data)

        patches = patch_experiment(work / "experiment.py")
        missing_patches = [p for p in patches if p["status"] != "applied"]
        out_dir = work / "run_0"
        cmd = [sys.executable, "experiment.py", "--out_dir", "run_0"]
        proc = subprocess.run(cmd, cwd=work, text=True, capture_output=True, timeout=args.timeout_seconds)
        final_info = out_dir / "final_info.json"
        parsed = json.loads(final_info.read_text(encoding="utf-8")) if final_info.exists() else None
        per_seed = [out_dir / f"final_info_shakespeare_char_{i}.json" for i in range(2)]
        ok = proc.returncode == 0 and final_info.exists() and all(p.exists() for p in per_seed) and not missing_patches
        receipt.update(
            {
                "verdict": "PASS" if ok else "INVALID-RUN",
                "elapsed_seconds": time.time() - t0,
                "command": cmd,
                "cwd": str(work),
                "returncode": proc.returncode,
                "patches": patches,
                "outputs": {
                    "final_info_json": str(final_info),
                    "final_info_json_exists": final_info.exists(),
                    "per_seed_json": [str(p) for p in per_seed],
                    "per_seed_json_exists": [p.exists() for p in per_seed],
                },
                "parsed_final_info": parsed,
                "stdout_tail": proc.stdout[-8000:],
                "stderr_tail": proc.stderr[-8000:],
            }
        )
    except Exception as exc:
        receipt.update(
            {
                "verdict": "INVALID-RUN",
                "elapsed_seconds": time.time() - t0,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback_tail": traceback.format_exc()[-8000:],
            }
        )
    write_json(args.receipt, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())