#!/usr/bin/env python3
"""Static-check the selected C5 zero-spend task subset."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def require(path: Path, label: str, issues: list[dict]) -> bool:
    if not path.exists():
        issues.append({"label": label, "path": str(path), "issue": "missing"})
        return False
    return True


def line_contains(path: Path, pattern: str) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")
    return re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE) is not None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mlagentbench", type=Path, required=True)
    parser.add_argument("--ai-scientist", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    issues: list[dict] = []
    rows: list[dict] = []

    ml = args.mlagentbench.resolve()
    clrs = ml / "MLAgentBench" / "benchmarks" / "CLRS"
    clrs_files = {
        "research_problem": clrs / "scripts" / "research_problem.txt",
        "eval": clrs / "scripts" / "eval.py",
        "train": clrs / "env" / "train.py",
        "processors": clrs / "env" / "processors.py",
        "baseline_model_description": clrs / "env" / "baseline_model_description.txt",
        "data_description": clrs / "env" / "data_description.txt",
    }
    clrs_ok = all(require(path, f"clrs:{name}", issues) for name, path in clrs_files.items())
    clrs_checks = {
        "mentions_floyd_warshall": line_contains(clrs_files["research_problem"], r"floyd_warshall") if clrs_files["research_problem"].exists() else False,
        "requires_baseline_model_loadable": line_contains(clrs_files["research_problem"], r"BaselineModel") if clrs_files["research_problem"].exists() else False,
        "eval_has_get_score": line_contains(clrs_files["eval"], r"def\s+get_score") if clrs_files["eval"].exists() else False,
        "train_saves_best_checkpoint": line_contains(clrs_files["train"], r"best\.pkl|checkpoint") if clrs_files["train"].exists() else False,
        "processors_has_triplet_hook": line_contains(clrs_files["processors"], r"get_triplet_msgs") if clrs_files["processors"].exists() else False,
    }
    rows.append({
        "task_id": "C5-0A-MLAgentBench-CLRS",
        "root": str(clrs),
        "static_ok": clrs_ok and all(clrs_checks.values()),
        "checks": clrs_checks,
        "files": {name: {"path": str(path), "sha256": sha256(path)} for name, path in clrs_files.items() if path.exists()},
    })

    ai = args.ai_scientist.resolve()
    ng = ai / "templates" / "nanoGPT_lite"
    ai_files = {
        "experiment": ng / "experiment.py",
        "plot": ng / "plot.py",
        "prompt": ng / "prompt.json",
        "ideas": ng / "ideas.json",
        "seed_ideas": ng / "seed_ideas.json",
        "writeup": ng / "WRITEUP.md",
        "prepare_shakespeare": ai / "data" / "shakespeare_char" / "prepare.py",
    }
    ai_ok = all(require(path, f"ai_scientist:{name}", issues) for name, path in ai_files.items())
    ai_checks = {
        "experiment_has_train": line_contains(ai_files["experiment"], r"def\s+train") if ai_files["experiment"].exists() else False,
        "experiment_uses_shakespeare": line_contains(ai_files["experiment"], r"shakespeare_char") if ai_files["experiment"].exists() else False,
        "experiment_has_run0": line_contains(ai_files["experiment"], r"run_0") if ai_files["experiment"].exists() else False,
        "experiment_writes_json": line_contains(ai_files["experiment"], r"json") if ai_files["experiment"].exists() else False,
        "prepare_fetches_tiny_shakespeare": line_contains(ai_files["prepare_shakespeare"], r"tinyshakespeare|char-rnn") if ai_files["prepare_shakespeare"].exists() else False,
    }
    rows.append({
        "task_id": "C5-0B-AI-Scientist-nanoGPT-lite",
        "root": str(ng),
        "static_ok": ai_ok and all(ai_checks.values()),
        "checks": ai_checks,
        "files": {name: {"path": str(path), "sha256": sha256(path)} for name, path in ai_files.items() if path.exists()},
    })

    verdict = "PASS" if not issues and all(row["static_ok"] for row in rows) else "INVALID-RUN"
    result = {"verdict": verdict, "issues": issues, "tasks": rows}
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())