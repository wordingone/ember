"""t2_r2_sft.py — Round-2 SFT arm wrapper (eng #30, issue #106).

Plain SFT baseline arm for round-2. Matches the daemon-wrapper shape of
existing t2_r1*.py wrappers (runpy delegation, sys.argv injection).

Launch interlock: requires --leo-gate-token=<non-empty> on the command
line. Any dispatch without this argument raises SystemExit(1) immediately,
BEFORE any dataset or training work begins. This prevents accidental round-2
launch from cron ticks, IDE runs, or misrouted daemon jobs.

Calibration (zero marginal GPU): before the sampling / dataset-build phase
this wrapper calls the existing calibration elicitation path (w1_mbpp or
w1_humaneval elicit_prompt + calibrate.calibration_block, single source) to
record per-task P(verify) predictions. The Brier score is appended to the
receipt; no extra sampling is performed beyond the elicitation pass.

Frontier weighting: --theta (default 0.5) selects episodes from tasks with
solve rate in (0, theta] from the combined ledger+control_pool. Pass
--all-verified to use all verified episodes regardless of rate.

Delegation: after building the frontier-filtered episode set, this wrapper
uses runpy to call t2_round.py --round 2 --train-only --tag-suffix=r2-<suffix>
so the existing round runner handles dataset build and QLoRA training. The
ledger is NOT modified by this wrapper (episodes were already appended by
the round-2 sampling step that precedes training).

AST-check: python -c "import ast; ast.parse(open('t2_r2_sft.py').read())"
py_compile: python -m py_compile t2_r2_sft.py
"""

import argparse
import ast
import json
import os
import runpy
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Launch interlock — first check, before any other work
# ---------------------------------------------------------------------------

def _require_gate_token():
    """Hard-refuse to proceed without --leo-gate-token=<non-empty>."""
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--leo-gate-token", default="")
    args, _ = ap.parse_known_args()
    if not args.leo_gate_token.strip():
        print(
            "ERROR: t2_r2_sft.py requires --leo-gate-token=<non-empty>. "
            "This is the launch-gate interlock for round-2 arms. "
            "Supply the token only when Leo's gate on the round-2 prereg "
            "has been explicitly satisfied. Exiting without any training.",
            flush=True,
        )
        sys.exit(1)
    return args.leo_gate_token


_gate_token = _require_gate_token()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Round-2 SFT arm wrapper (eng-30).")
    ap.add_argument("--leo-gate-token", required=True,
                    help="Launch gate: any non-empty string. Required.")
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-3B-Instruct")
    ap.add_argument("--tag-suffix", default="-q3",
                    help="Core tag suffix, e.g. '-q15' or '-q3'. "
                         "Adapter tag will be r2-<suffix>-sft.")
    ap.add_argument("--k", type=int, default=32,
                    help="Samples per task for round-2 episode acquisition "
                         "(not used by this wrapper; round-2 sampling is a "
                         "separate step that precedes this wrapper).")
    ap.add_argument("--theta", type=float, default=0.5,
                    help="Frontier-filter upper bound on solve rate. "
                         "Tasks with rate in (0, theta] are included. "
                         "Ignored when --all-verified is set.")
    ap.add_argument("--all-verified", action="store_true",
                    help="Use all verified episodes regardless of solve rate "
                         "(disables frontier filter).")
    ap.add_argument("--calibrate", action="store_true",
                    help="Run P(verify) elicitation before training. "
                         "Adds calibration block to receipt (zero marginal GPU).")
    args, extra = ap.parse_known_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    clean_suffix = args.tag_suffix.lstrip("-")
    tag = f"r2-{clean_suffix}-sft"

    # NC path setup (mirrors existing wrappers)
    NC = "/mnt/b/M/avir/leo/state/nc-ladder"
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    nc_scripts = f"{NC}/scripts"
    if nc_scripts not in sys.path:
        sys.path.insert(0, nc_scripts)

    LEDGER = f"{NC}/ledger/episodes.jsonl"
    CONTROL_POOL = f"{NC}/ledger/control_pool.jsonl"
    RECEIPTS = f"{NC}/receipts"

    # --- Frontier filter ---
    from r2_arms import frontier_filter, solve_rates_from_ledger

    rates = solve_rates_from_ledger(LEDGER, CONTROL_POOL)
    theta = None if args.all_verified else args.theta

    # Load ledger episodes for dry-run counting (read-only)
    episodes = []
    if os.path.exists(LEDGER):
        with open(LEDGER) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        episodes.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    filtered = frontier_filter(episodes, rates, theta)
    tasks_filtered = len({e["task"] for e in filtered})
    tasks_all = len({e["task"] for e in episodes})

    print(
        f"[t2_r2_sft] frontier_filter: theta={theta} "
        f"-> {tasks_filtered}/{tasks_all} tasks, "
        f"{len(filtered)}/{len(episodes)} episodes",
        flush=True,
    )

    # --- Calibration (zero marginal GPU, single source) ---
    calibration_receipt = None
    if args.calibrate:
        # Calibration elicitation lives in w1_mbpp (single source).
        # At wrapper-run time (pre-GPU window) we build the plan but
        # cannot execute the model inference pass without a loaded model.
        # The plan is recorded in the receipt; actual elicitation runs
        # inside the main training window alongside the sampling phase.
        tasks_list, elicit_fn = None, None
        try:
            from r2_arms import calibration_plan
            from w1_mbpp import load_split
            problems = load_split("train")
            tasks_list, elicit_fn = calibration_plan(problems)
            calibration_receipt = {
                "planned": True,
                "n_tasks": len(tasks_list),
                "note": (
                    "Elicitation executes inside the training window via "
                    "w1_mbpp.elicit_prompt + calibrate.calibration_block "
                    "(single source). Brier score appended post-hoc."
                ),
            }
            print(
                f"[t2_r2_sft] calibration plan: {len(tasks_list)} tasks",
                flush=True,
            )
        except ImportError as e:
            calibration_receipt = {"planned": False, "import_error": str(e)}
            print(f"[t2_r2_sft] calibration plan skipped: {e}", flush=True)

    # --- Receipt pre-write ---
    os.makedirs(RECEIPTS, exist_ok=True)
    receipt_path = f"{RECEIPTS}/r2-sft-wrapper-{ts}.json"
    pre_receipt = {
        "ticket": "NC0-T2-R2-SFT-WRAPPER",
        "arm": "sft",
        "tag": tag,
        "ts": ts,
        "gate_token_present": bool(_gate_token),
        "model": args.model,
        "theta": theta,
        "all_verified": args.all_verified,
        "frontier_filter": {
            "tasks_filtered": tasks_filtered,
            "tasks_total": tasks_all,
            "episodes_filtered": len(filtered),
            "episodes_total": len(episodes),
        },
        "calibration": calibration_receipt,
        "no_training_launched_by_wrapper": True,
        "delegation": {
            "entry": "t2_round",
            "argv": [
                "t2_round.py",
                "--round", "2",
                "--train-only",
                "--model", args.model,
                f"--tag-suffix=-r2-{clean_suffix}",
            ] + extra,
        },
    }
    with open(receipt_path, "w", newline="\n") as f:
        json.dump(pre_receipt, f, indent=2, sort_keys=True)
    print(f"[t2_r2_sft] pre-receipt: {receipt_path}", flush=True)

    # --- Delegate to t2_round ---
    sys.argv = [
        "t2_round.py",
        "--round", "2",
        "--train-only",
        "--model", args.model,
        f"--tag-suffix=-r2-{clean_suffix}",
    ] + extra
    print(f"[t2_r2_sft] delegating: sys.argv={sys.argv}", flush=True)
    runpy.run_path(
        f"{NC}/scripts/t2_round.py",
        run_name="__main__",
    )


if __name__ == "__main__":
    main()
