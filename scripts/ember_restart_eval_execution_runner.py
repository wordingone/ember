#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Run an evaluator command, then emit only a non-admissible evidence preflight."""
import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capability", required=True, choices=("text", "image", "audio", "reasoning", "tool"))
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--benchmark-id", required=True)
    parser.add_argument("--benchmark-version", required=True)
    parser.add_argument("--split-artifact", required=True, type=Path)
    parser.add_argument("--harness-artifact", required=True, type=Path)
    parser.add_argument("--protocol-artifact", required=True, type=Path)
    parser.add_argument("--raw-predictions", required=True, type=Path)
    parser.add_argument("--result-artifact", required=True, type=Path)
    parser.add_argument("--criterion-result", required=True, choices=("PASSED", "FAILED"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("evaluator command is required after --")
    if args.raw_predictions.exists() or args.result_artifact.exists():
        parser.error("evaluator outputs must not pre-exist")
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        parser.error(f"evaluator command failed with exit code {completed.returncode}: {completed.stderr.strip()}")
    if not args.raw_predictions.is_file() or not args.result_artifact.is_file():
        parser.error("evaluator command did not create predictions and score artifacts")
    preflight = Path(__file__).with_name("ember_restart_eval_execution_preflight.py")
    preflight_command = [sys.executable, str(preflight), "--capability", args.capability, "--checkpoint", str(args.checkpoint), "--benchmark-id", args.benchmark_id, "--benchmark-version", args.benchmark_version, "--split-artifact", str(args.split_artifact), "--harness-artifact", str(args.harness_artifact), "--protocol-artifact", str(args.protocol_artifact), "--raw-predictions", str(args.raw_predictions), "--result-artifact", str(args.result_artifact), "--criterion-result", args.criterion_result, "--output", str(args.output)]
    return subprocess.run(preflight_command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
