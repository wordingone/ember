#!/usr/bin/env python3
"""Run the equal-budget deterministic CLRS patch comparator.

The comparator is a predeclared simple learning-rate patch: upstream CLRS
floyd_warshall with learning_rate=0.003, same seeds and budget as the upstream
three-seed comparator. This is not an Ember run.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


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
    parser.add_argument("--learning-rate", type=float, default=0.003)
    args = parser.parse_args()

    governed = Path(__file__).with_name("run_c5_mlagentbench_clrs_governed_baseline.py")
    command = [
        sys.executable,
        str(governed),
        "--mlagentbench", str(args.mlagentbench),
        "--python", str(args.python),
        "--scratch", str(args.scratch),
        "--out", str(args.out),
        "--seeds", args.seeds,
        "--train-steps", str(args.train_steps),
        "--eval-every", str(args.eval_every),
        "--batch-size", str(args.batch_size),
        "--hidden-size", str(args.hidden_size),
        "--variant-id", "deterministic_lr3x_patch",
        "--variant-description", "equal-budget deterministic patch comparator: learning_rate=0.003 on unchanged MLAgentBench CLRS floyd_warshall task",
        f"--extra-train-flag=--learning_rate={args.learning_rate}",
        "--completion-limit", "This is an equal-budget deterministic CLRS patch comparator receipt for C5-0A. It is not an Ember loop result, not an Ember improvement claim, and not overall baseline completion.",
    ]
    if args.pretty:
        command.append("--pretty")
    return subprocess.run(command).returncode


if __name__ == "__main__":
    raise SystemExit(main())
