#!/usr/bin/env python3
"""Run a governed deterministic C5-0B nanoGPT_lite patch comparator."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

BUDGET_PATCHES = {
    "eval_interval = 250 if dataset == \"shakespeare_char\" else 1000": "eval_interval = 10 if dataset == \"shakespeare_char\" else 10",
    "log_interval = 10 if dataset == \"shakespeare_char\" else 100": "log_interval = 5 if dataset == \"shakespeare_char\" else 5",
    "eval_iters = 200": "eval_iters = 10",
    "max_iters = 5000 if dataset == \"shakespeare_char\" else 100000": "max_iters = 20 if dataset == \"shakespeare_char\" else 20",
    "warmup_iters = 100 if dataset == \"shakespeare_char\" else 200": "warmup_iters = 5 if dataset == \"shakespeare_char\" else 5",
    "compile = True  # do not torch compile the model on macbooks": "compile = False  # governed bounded run disables compile overhead",
    "num_samples = 10  # number of samples to draw": "num_samples = 2  # governed bounded inference samples",
    "max_new_tokens = 500  # number of tokens generated in each sample": "max_new_tokens = 64  # governed bounded generation budget",
}

DETERMINISTIC_PATCHES = {
    "learning_rate = 1e-3 if dataset == \"shakespeare_char\" else 5e-4": "learning_rate = 8e-4 if dataset == \"shakespeare_char\" else 5e-4",
    "dropout = 0.2  # for pretraining 0 is good, for finetuning try 0.1+": "dropout = 0.1  # deterministic comparator patch: lower dropout under same budget",
}

LOCAL_MARKERS = ["C:" + "/" + "tmp", "C:" + "\\" + "tmp", "B:" + "/" + "M", "B:" + "\\" + "M", "C:" + "/" + "Users" + "/" + "Admin", "C:" + "\\" + "Users" + "\\" + "Admin"]


def sanitize_text(text: str) -> str:
    out = text.replace("\\", "/")
    for marker in LOCAL_MARKERS:
        out = out.replace(marker.replace("\\", "/"), "<LOCAL_PATH>")
        out = out.replace(marker, "<LOCAL_PATH>")
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def patch_experiment(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    applied = []
    for patch_group, patches in (("budget", BUDGET_PATCHES), ("deterministic_comparator", DETERMINISTIC_PATCHES)):
        for old, new in patches.items():
            if old not in text:
                applied.append({"group": patch_group, "old": old, "new": new, "status": "missing"})
                continue
            text = text.replace(old, new, 1)
            applied.append({"group": patch_group, "old": old, "new": new, "status": "applied"})
    path.write_text(text, encoding="utf-8", newline="\n")
    return applied


def scrub_paths(obj: Any, work: Path) -> Any:
    if isinstance(obj, str):
        text = obj.replace(str(work), "<WORKDIR>").replace(str(work).replace("\\", "/"), "<WORKDIR>")
        return sanitize_text(text)
    if isinstance(obj, list):
        return [scrub_paths(item, work) for item in obj]
    if isinstance(obj, dict):
        return {key: scrub_paths(value, work) for key, value in obj.items()}
    return obj


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--work-template", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args()

    t0 = time.time()
    work = args.work_template.resolve()
    receipt: dict[str, Any] = {
        "task_id": "C5-0B-AI-Scientist-nanoGPT-lite",
        "job": "governed_bounded_deterministic_patch_comparator",
        "candidate_kind": "deterministic_patch_comparator",
        "governed_run": True,
        "verdict": "INVALID-RUN",
        "timeout_seconds": args.timeout_seconds,
        "local_path_policy": "Checked-in receipt redacts machine-local paths; work-template and source repo are inputs only.",
        "budget": {
            "profile": "bounded_non_smoke_equal_budget",
            "max_iters": 20,
            "eval_iters": 10,
            "num_seeds_shakespeare_char": 2,
            "model_shape_preserved": True,
            "batch_size_preserved": True,
            "block_size_preserved": True,
        },
        "deterministic_patch": {
            "learning_rate_shakespeare_char": "1e-3 -> 8e-4",
            "dropout": "0.2 -> 0.1",
            "rationale": "Simple non-agent deterministic hyperparameter comparator under identical bounded budget.",
        },
    }
    try:
        repo = args.repo.resolve()
        source = repo / "templates" / "nanoGPT_lite"
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
                "elapsed_seconds": round(time.time() - t0, 6),
                "command": ["python", "experiment.py", "--out_dir", "run_0"],
                "cwd": "<WORKDIR>",
                "returncode": proc.returncode,
                "patches": patches,
                "outputs": {
                    "final_info_json": "<WORKDIR>/run_0/final_info.json",
                    "final_info_json_exists": final_info.exists(),
                    "per_seed_json": [f"<WORKDIR>/run_0/final_info_shakespeare_char_{i}.json" for i in range(2)],
                    "per_seed_json_exists": [p.exists() for p in per_seed],
                    "final_info_json_sha256": sha256_file(final_info) if final_info.exists() else None,
                },
                "parsed_final_info": parsed,
                "stdout_tail": sanitize_text(proc.stdout[-8000:]),
                "stderr_tail": sanitize_text(proc.stderr[-8000:]),
                "completion_limit": "This is a deterministic same-budget comparator run only. It is not an Ember improvement and not overall baseline completion.",
            }
        )
        receipt = scrub_paths(receipt, work)
    except Exception as exc:
        receipt.update(
            {
                "verdict": "INVALID-RUN",
                "elapsed_seconds": round(time.time() - t0, 6),
                "error_type": type(exc).__name__,
                "error": sanitize_text(str(exc)),
                "traceback_tail": sanitize_text(traceback.format_exc()[-8000:]),
            }
        )
    write_json(args.receipt, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
