#!/usr/bin/env python3
"""Run a bounded C5-0B nanoGPT_lite smoke in a copied template tree."""

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
    "batch_size = 64 if dataset == \"shakespeare_char\" else 32": "batch_size = 4 if dataset == \"shakespeare_char\" else 4",
    "block_size = 256  # context of up to 256 previous characters": "block_size = 64  # smoke-reduced context",
    "eval_interval = 250 if dataset == \"shakespeare_char\" else 1000": "eval_interval = 1 if dataset == \"shakespeare_char\" else 1",
    "log_interval = 10 if dataset == \"shakespeare_char\" else 100": "log_interval = 1 if dataset == \"shakespeare_char\" else 1",
    "eval_iters = 200": "eval_iters = 2",
    "n_layer = 6  # baby GPT model :)": "n_layer = 2  # smoke-reduced model",
    "n_head = 6": "n_head = 2",
    "n_embd = 384": "n_embd = 128",
    "max_iters = 5000 if dataset == \"shakespeare_char\" else 100000": "max_iters = 3 if dataset == \"shakespeare_char\" else 3",
    "warmup_iters = 100 if dataset == \"shakespeare_char\" else 200": "warmup_iters = 1 if dataset == \"shakespeare_char\" else 1",
    "compile = True  # do not torch compile the model on macbooks": "compile = False  # smoke disables compile overhead",
    "num_samples = 10  # number of samples to draw": "num_samples = 1  # smoke sample count",
    "max_new_tokens = 500  # number of tokens generated in each sample": "max_new_tokens = 16  # smoke generation budget",
    '"shakespeare_char": 2,': '"shakespeare_char": 1,',
}


def write_receipt(path: Path, receipt: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


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
    parser.add_argument("--timeout-seconds", type=int, default=240)
    args = parser.parse_args()

    t0 = time.time()
    receipt = {
        "task_id": "C5-0B-AI-Scientist-nanoGPT-lite",
        "job": "smoke_reduced_run_0",
        "verdict": "INVALID-RUN",
        "timeout_seconds": args.timeout_seconds,
    }
    try:
        repo = args.repo.resolve()
        source = repo / "templates" / "nanoGPT_lite"
        work = args.work_template.resolve()
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(source, work)

        # If the smoke copy is outside the AI Scientist repo, reproduce enough layout for ../../data.
        expected_data = work.parent.parent / "data" / "shakespeare_char"
        source_data = repo / "data" / "shakespeare_char"
        if not expected_data.exists():
            expected_data.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_data, expected_data)

        applied = patch_experiment(work / "experiment.py")
        out_dir = work / "run_0"
        cmd = [sys.executable, "experiment.py", "--out_dir", "run_0"]
        proc = subprocess.run(cmd, cwd=work, text=True, capture_output=True, timeout=args.timeout_seconds)
        elapsed = time.time() - t0
        final_info = out_dir / "final_info.json"
        per_seed = out_dir / "final_info_shakespeare_char_0.json"
        parsed = json.loads(final_info.read_text(encoding="utf-8")) if final_info.exists() else None
        verdict = "PASS" if proc.returncode == 0 and final_info.exists() and per_seed.exists() else "INVALID-RUN"
        receipt.update(
            {
                "verdict": verdict,
                "command": cmd,
                "cwd": str(work),
                "elapsed_seconds": elapsed,
                "returncode": proc.returncode,
                "patches": applied,
                "outputs": {
                    "final_info_json": str(final_info),
                    "final_info_json_exists": final_info.exists(),
                    "per_seed_json": str(per_seed),
                    "per_seed_json_exists": per_seed.exists(),
                },
                "parsed_final_info": parsed,
                "stdout_tail": proc.stdout[-4000:],
                "stderr_tail": proc.stderr[-4000:],
            }
        )
    except Exception as exc:
        receipt.update(
            {
                "verdict": "INVALID-RUN",
                "elapsed_seconds": time.time() - t0,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback_tail": traceback.format_exc()[-4000:],
            }
        )
    write_receipt(args.receipt, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())