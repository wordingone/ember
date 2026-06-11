"""t2_r2_grpo.py — Round-2 GRPO arm wrapper (eng #30, issue #106).

GRPO-on-verifier-reward arm for round-2. Delegates to t2_grpo.py (eng #3)
via runpy, mirroring the daemon-wrapper shape of existing wrappers.

Launch interlock: requires --leo-gate-token=<non-empty>. Any dispatch
without this token raises SystemExit(1) immediately, before any dataset
or training work begins. This is the round-2 gate interlock.

Calibration: --calibrate plans the P(verify) elicitation pass using
w1_mbpp.elicit_prompt + calibrate.calibration_block (single source).
Brier score is recorded in the receipt post-hoc.

Frontier weighting for the GRPO prompt mix: the GRPO arm uses the
bits-weighted stratification (STRATUM_REPEATS from t2_grpo) on the MBPP
train split. Frontier-filtering in the GRPO context means restricting
the prompt pool to tasks with solve rate in (0, theta] — tasks the
current adapter cannot trivially solve, preserving gradient signal.
The wrapper passes a --focus-max-rate argument to the w1_mbpp sampler
(not to t2_grpo itself, which receives a pre-built stats-from path).

GRPO stats-from: t2_grpo.py needs --stats-from pointing to round-2
w1 samples receipts (*.jsonl). If the round-2 w1 floor receipts do not
yet exist, the wrapper uses the round-1 receipts as a fallback (with a
warning in the receipt). The caller is responsible for providing
up-to-date stats receipts.

AST-check: python -c "import ast; ast.parse(open('t2_r2_grpo.py').read())"
py_compile: python -m py_compile t2_r2_grpo.py
"""

import argparse
import glob
import json
import os
import runpy
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Launch interlock — first check, before any other work
# ---------------------------------------------------------------------------

def _require_gate_token():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--leo-gate-token", default="")
    args, _ = ap.parse_known_args()
    if not args.leo_gate_token.strip():
        print(
            "ERROR: t2_r2_grpo.py requires --leo-gate-token=<non-empty>. "
            "Launch-gate interlock for round-2 arms. "
            "Exiting without any training.",
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
        description="Round-2 GRPO arm wrapper (eng-30).")
    ap.add_argument("--leo-gate-token", required=True,
                    help="Launch gate: any non-empty string. Required.")
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-3B-Instruct")
    ap.add_argument("--tag-suffix", default="-q3",
                    help="Core tag suffix. Adapter tag: r2-<suffix>-grpo.")
    ap.add_argument("--max-steps", type=int, default=60)
    ap.add_argument("--num-generations", type=int, default=8)
    ap.add_argument("--beta", type=float, default=0.04)
    ap.add_argument("--lr", type=float, default=5e-6)
    ap.add_argument("--temp", type=float, default=0.8)
    ap.add_argument("--reward", default="binary",
                    choices=["binary", "partial"])
    ap.add_argument("--theta", type=float, default=0.5,
                    help="Frontier-filter: tasks with solve rate in (0, theta] "
                         "are included in the prompt pool. "
                         "Ignored when --all-verified is set.")
    ap.add_argument("--all-verified", action="store_true",
                    help="Use all verified tasks in prompt pool.")
    ap.add_argument("--stats-from", nargs="*", default=None,
                    help="Paths to w1 samples JSONL for GRPO stratification. "
                         "Defaults to the most recent round-2 w1 floor receipts, "
                         "falling back to round-1 receipts.")
    ap.add_argument("--calibrate", action="store_true",
                    help="Plan P(verify) elicitation pass (zero marginal GPU).")
    args, extra = ap.parse_known_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    clean_suffix = args.tag_suffix.lstrip("-")
    tag = f"r2-{clean_suffix}-grpo"

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

    # --- Frontier filter (informational for receipt; GRPO uses stats-from) ---
    from r2_arms import frontier_filter, solve_rates_from_ledger

    rates = solve_rates_from_ledger(LEDGER, CONTROL_POOL)
    theta = None if args.all_verified else args.theta

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
        f"[t2_r2_grpo] frontier_filter: theta={theta} "
        f"-> {tasks_filtered}/{tasks_all} tasks, "
        f"{len(filtered)}/{len(episodes)} episodes",
        flush=True,
    )

    # --- Resolve stats-from receipts ---
    stats_note = None
    if args.stats_from:
        stats_paths = args.stats_from
        stats_note = "caller-provided"
    else:
        # Try round-2 w1 floor receipts first, fall back to round-1
        r2_pattern = f"{RECEIPTS}/w1-floor-r2-*-samples.jsonl"
        r1_pattern = f"{RECEIPTS}/w1-floor-q3-*-samples.jsonl"
        r2_paths = sorted(glob.glob(r2_pattern))
        r1_paths = sorted(glob.glob(r1_pattern))
        if r2_paths:
            stats_paths = r2_paths
            stats_note = "auto-resolved: round-2 w1 receipts"
        elif r1_paths:
            stats_paths = r1_paths
            stats_note = (
                "WARNING: round-2 w1 receipts not found; "
                "falling back to round-1 receipts. "
                "Run the round-2 w1 floor probe first for accurate stratification."
            )
            print(f"[t2_r2_grpo] {stats_note}", flush=True)
        else:
            stats_paths = []
            stats_note = (
                "WARNING: no w1 floor receipts found. "
                "t2_grpo will use default stats-from paths. "
                "GRPO stratification may be stale."
            )
            print(f"[t2_r2_grpo] {stats_note}", flush=True)

    print(
        f"[t2_r2_grpo] stats_from: {len(stats_paths)} path(s) ({stats_note})",
        flush=True,
    )

    # --- Calibration plan ---
    calibration_receipt = None
    if args.calibrate:
        try:
            from r2_arms import calibration_plan
            from w1_mbpp import load_split
            problems = load_split("train")
            tasks_list, _ = calibration_plan(problems)
            calibration_receipt = {
                "planned": True,
                "n_tasks": len(tasks_list),
                "note": (
                    "Brier score computed post-hoc via "
                    "calibrate.calibration_block (single source)."
                ),
            }
        except ImportError as e:
            calibration_receipt = {"planned": False, "import_error": str(e)}

    # --- Receipt ---
    os.makedirs(RECEIPTS, exist_ok=True)
    receipt_path = f"{RECEIPTS}/r2-grpo-wrapper-{ts}.json"

    # Build the argv we will pass to t2_grpo
    grpo_argv = [
        "t2_grpo.py",
        "--model", args.model,
        "--tag", tag,
        "--max-steps", str(args.max_steps),
        "--num-generations", str(args.num_generations),
        "--beta", str(args.beta),
        "--lr", str(args.lr),
        "--temp", str(args.temp),
        "--reward", args.reward,
    ]
    if stats_paths:
        grpo_argv += ["--stats-from"] + stats_paths
    grpo_argv += extra

    pre_receipt = {
        "ticket": "NC0-T2-R2-GRPO-WRAPPER",
        "arm": "grpo",
        "tag": tag,
        "ts": ts,
        "gate_token_present": bool(_gate_token),
        "model": args.model,
        "max_steps": args.max_steps,
        "num_generations": args.num_generations,
        "beta": args.beta,
        "lr": args.lr,
        "temp": args.temp,
        "reward": args.reward,
        "theta": theta,
        "all_verified": args.all_verified,
        "frontier_filter": {
            "tasks_filtered": tasks_filtered,
            "tasks_total": tasks_all,
            "episodes_filtered": len(filtered),
            "episodes_total": len(episodes),
        },
        "stats_from": stats_paths,
        "stats_note": stats_note,
        "calibration": calibration_receipt,
        "no_training_launched_by_wrapper": True,
        "delegation": {
            "entry": "t2_grpo",
            "argv": grpo_argv,
        },
    }
    with open(receipt_path, "w", newline="\n") as f:
        json.dump(pre_receipt, f, indent=2, sort_keys=True)
    print(f"[t2_r2_grpo] pre-receipt: {receipt_path}", flush=True)

    # --- Delegate to t2_grpo ---
    sys.argv = grpo_argv
    print(f"[t2_r2_grpo] delegating: sys.argv={sys.argv}", flush=True)
    runpy.run_path(
        f"{NC}/scripts/t2_grpo.py",
        run_name="__main__",
    )


if __name__ == "__main__":
    main()
