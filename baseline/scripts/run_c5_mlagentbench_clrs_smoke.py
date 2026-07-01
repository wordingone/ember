#!/usr/bin/env python3
"""Run the MLAgentBench CLRS tiny upstream-baseline smoke in an isolated env.

This is a comparator executability smoke, not an Ember improvement claim. It
copies the pinned MLAgentBench tree to a scratch directory, applies a narrow
Windows/NumPy PRNG bound compatibility patch, runs one tiny CLRS training job,
parses upstream train.py log output, and writes a public-safe receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_MODULES = ["absl", "attrs", "chex", "clrs", "haiku", "jax", "jaxlib", "numpy", "optax", "tensorflow"]
PRNG_OLD = "rng.randint(2**32)"
PRNG_NEW = "int(rng.randint(0, 2**31 - 1))"
KEY_OLD = "jax.random.PRNGKey(rng.randint(2**32))"
KEY_NEW = "jax.random.PRNGKey(int(rng.randint(0, 2**31 - 1)))"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head(repo: Path) -> str | None:
    proc = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True, capture_output=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def module_versions(python: Path) -> dict[str, Any]:
    code = """
import importlib, importlib.util, json
mods = __import__('os').environ['EMBER_CLRS_MODULES'].split(',')
out = {}
for name in mods:
    present = importlib.util.find_spec(name) is not None
    version = None
    if present:
        mod = importlib.import_module(name)
        version = getattr(mod, '__version__', None)
    out[name] = {'present': present, 'version': version}
print(json.dumps(out, sort_keys=True))
""".strip()
    env = os.environ.copy()
    env["EMBER_CLRS_MODULES"] = ",".join(REQUIRED_MODULES)
    proc = subprocess.run([str(python), "-c", code], text=True, capture_output=True, env=env)
    if proc.returncode != 0:
        return {"import_probe_failed": {"returncode": proc.returncode, "stderr_tail": proc.stderr[-2000:]}}
    return json.loads(proc.stdout)


def apply_compat_patch(files: list[Path]) -> list[dict[str, Any]]:
    patches: list[dict[str, Any]] = []
    for path in files:
        before = path.read_text(encoding="utf-8")
        after = before.replace(KEY_OLD, KEY_NEW).replace(PRNG_OLD, PRNG_NEW)
        replacements = before.count(KEY_OLD) + before.count(PRNG_OLD)
        path.write_text(after, encoding="utf-8", newline="\n")
        patches.append({
            "file": path.name,
            "old_sha256": hashlib.sha256(before.encode("utf-8")).hexdigest(),
            "new_sha256": hashlib.sha256(after.encode("utf-8")).hexdigest(),
            "replacement_count": replacements,
            "patch_scope": "Windows/NumPy PRNG upper-bound compatibility only; no model, data, score, or optimizer logic changed.",
        })
    return patches


def parse_log(text: str) -> dict[str, Any]:
    val = re.findall(r"\(val\) algo ([^ ]+) step (\d+): \{[^}]*'score': ([0-9.eE+-]+)[^}]*\}", text)
    test = re.findall(r"\(test\) algo ([^ ]+) : \{[^}]*'score': ([0-9.eE+-]+)[^}]*\}", text)
    loss = re.findall(r"Algo ([^ ]+) step (\d+) current loss ([0-9.eE+-]+), current_train_items (\d+)", text)
    return {
        "loss_events": [
            {"algorithm": a, "step": int(s), "loss": float(l), "current_train_items": int(n)} for a, s, l, n in loss
        ],
        "val_events": [
            {"algorithm": a, "step": int(s), "score": float(score)} for a, s, score in val
        ],
        "test_events": [
            {"algorithm": a, "score": float(score)} for a, score in test
        ],
        "done_seen": "Done!" in text,
        "checkpoint_seen": "Checkpointing best model" in text,
        "restore_seen": "Restoring best model" in text,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mlagentbench", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--train-steps", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--hidden-size", type=int, default=16)
    args = parser.parse_args()

    source = args.mlagentbench.resolve()
    scratch = args.scratch.resolve()
    run_root = scratch / "run"
    source_copy = scratch / "MLAgentBench-compat-copy"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)
    shutil.copytree(source, source_copy)

    clrs_root = source_copy / "MLAgentBench" / "benchmarks" / "CLRS"
    train_py = clrs_root / "env" / "train.py"
    eval_py = clrs_root / "scripts" / "eval.py"
    patches = apply_compat_patch([train_py, eval_py])
    run_root.mkdir(parents=True)

    command = [
        str(args.python.resolve()),
        str(train_py),
        "--algorithms=floyd_warshall",
        "--train_lengths=4",
        f"--batch_size={args.batch_size}",
        f"--train_steps={args.train_steps}",
        "--eval_every=1",
        "--test_every=1",
        "--log_every=1",
        f"--hidden_size={args.hidden_size}",
        "--nb_msg_passing_steps=1",
        f"--checkpoint_path={run_root / 'checkpoints'}",
        f"--dataset_path={run_root / 'CLRS30'}",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(clrs_root / "env")
    env["TF_CPP_MIN_LOG_LEVEL"] = "3"
    started = datetime.now(timezone.utc)
    proc = subprocess.run(command, text=True, capture_output=True, cwd=str(clrs_root / "env"), env=env)
    ended = datetime.now(timezone.utc)
    combined = (proc.stdout or "") + (proc.stderr or "")
    log_path = scratch / "train-smoke.log"
    log_path.write_text(combined, encoding="utf-8", newline="\n")
    parsed = parse_log(combined)

    checkpoint_files = []
    ckpt = run_root / "checkpoints"
    if ckpt.exists():
        for path in sorted(p for p in ckpt.rglob("*") if p.is_file()):
            checkpoint_files.append({
                "name": path.relative_to(ckpt).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            })

    pass_conditions = {
        "returncode_zero": proc.returncode == 0,
        "done_seen": parsed["done_seen"],
        "checkpoint_seen": parsed["checkpoint_seen"],
        "restore_seen": parsed["restore_seen"],
        "has_test_score": len(parsed["test_events"]) >= 1,
        "has_checkpoint_files": len(checkpoint_files) >= 3,
    }
    verdict = "C5_MLAGENTBENCH_CLRS_SMOKE_PASS" if all(pass_conditions.values()) else "C5_MLAGENTBENCH_CLRS_SMOKE_FAIL"

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
            "expected_commit": "5d71205cc20a8e95d43aa7cb7120e89ca3323e31",
            "upstream_train_sha256": sha256(source / "MLAgentBench" / "benchmarks" / "CLRS" / "env" / "train.py"),
            "upstream_eval_sha256": sha256(source / "MLAgentBench" / "benchmarks" / "CLRS" / "scripts" / "eval.py"),
        },
        "compatibility_patch": patches,
        "environment": {
            "python_version": sys.version,
            "runner_python_label": "isolated CLRS venv supplied by --python; local absolute path intentionally omitted",
            "module_versions": module_versions(args.python.resolve()),
        },
        "run_config": {
            "algorithm": "floyd_warshall",
            "train_lengths": [4],
            "batch_size": args.batch_size,
            "train_steps": args.train_steps,
            "eval_every": 1,
            "test_every": 1,
            "hidden_size": args.hidden_size,
            "nb_msg_passing_steps": 1,
        },
        "parsed_log": parsed,
        "checkpoint_files": checkpoint_files,
        "stdout_stderr_tail": combined[-4000:],
        "local_path_policy": "Receipt omits absolute local paths. Reproduce by cloning MLAgentBench at the pinned commit, creating the isolated CLRS env, and running this script with local --mlagentbench/--python/--scratch paths.",
        "completion_limit": "This proves the selected MLAgentBench CLRS upstream baseline can execute a tiny scored smoke after a declared compatibility patch. It is not an Ember improvement, not a three-seed governed C5 trial, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(receipt, indent=2 if args.pretty else None, sort_keys=True)
    args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if verdict.endswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
