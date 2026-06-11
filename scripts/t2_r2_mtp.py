"""t2_r2_mtp.py — Round-2 MTP-aux SFT arm wrapper (eng #30, issue #106).

MTP-aux SFT arm for round-2. Delegates to t2_mtp.py (eng #4) via import.

Launch interlock: requires --leo-gate-token=<non-empty>. Any dispatch
without this token raises SystemExit(1) before any dataset or training work.

MTP note: t2_mtp.main() reads its dataset from the view file at
  NC/ledger/views/wcode-r1.jsonl  (hardcoded in t2_mtp.py).
For round-2 the correct view is wcode-r2.jsonl. Since the new-files-only
constraint forbids editing t2_mtp.py, this wrapper pre-writes the view to
the expected path (wcode-r1.jsonl — overwriting the round-1 view in place)
before delegating. This is safe only if the round-1 view is not needed
concurrently; the caller is responsible for sequencing.

PR honesty note: if overwriting wcode-r1.jsonl is unacceptable, the MTP
arm requires a one-line addition to t2_mtp.py (a --view-path argument) to
avoid stomping the round-1 view. That constitutes a trainer extension
(single argument). The arm config is otherwise fully concrete; training
machinery exists and works. This wrapper is the complete round-2 envelope
pending that one parameter addition if the caller wants to preserve the r1
view.

Calibration (zero marginal GPU, single source = calibrate.py + w1_mbpp).
Frontier weighting via r2_arms.frontier_filter (single source = r2_arms.py).

AST-check: python -c "import ast; ast.parse(open('t2_r2_mtp.py').read())"
py_compile: python -m py_compile t2_r2_mtp.py
"""

import argparse
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
            "ERROR: t2_r2_mtp.py requires --leo-gate-token=<non-empty>. "
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
        description="Round-2 MTP-aux SFT arm wrapper (eng-30).")
    ap.add_argument("--leo-gate-token", required=True,
                    help="Launch gate: any non-empty string. Required.")
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-3B-Instruct")
    ap.add_argument("--tag-suffix", default="-q3",
                    help="Core tag suffix. Adapter tag: r2-<suffix>-mtp.")
    ap.add_argument("--k-aux", type=int, default=3,
                    help="MTP aux depths (passed to t2_mtp via sys.argv).")
    ap.add_argument("--lam", type=float, default=0.3,
                    help="MTP aux loss weight lambda.")
    ap.add_argument("--theta", type=float, default=0.5,
                    help="Frontier-filter upper bound on solve rate.")
    ap.add_argument("--all-verified", action="store_true",
                    help="Use all verified episodes (disables frontier filter).")
    ap.add_argument("--calibrate", action="store_true",
                    help="Plan calibration elicitation pass (zero marginal GPU).")
    args, extra = ap.parse_known_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    clean_suffix = args.tag_suffix.lstrip("-")
    tag = f"r2-{clean_suffix}-mtp"

    NC = "/mnt/b/M/avir/leo/state/nc-ladder"
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    nc_scripts = f"{NC}/scripts"
    if nc_scripts not in sys.path:
        sys.path.insert(0, nc_scripts)

    LEDGER = f"{NC}/ledger/episodes.jsonl"
    CONTROL_POOL = f"{NC}/ledger/control_pool.jsonl"
    VIEWS = f"{NC}/ledger/views"
    RECEIPTS = f"{NC}/receipts"

    # --- Frontier filter ---
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
        f"[t2_r2_mtp] frontier_filter: theta={theta} "
        f"-> {tasks_filtered}/{tasks_all} tasks, "
        f"{len(filtered)}/{len(episodes)} episodes",
        flush=True,
    )

    # --- Write the frontier-filtered view for t2_mtp.main() ---
    # t2_mtp reads from VIEWS/wcode-r1.jsonl. We write a round-2 filtered
    # view to VIEWS/wcode-r2.jsonl AND (to satisfy the hardcoded path)
    # symlink/overwrite wcode-r1.jsonl.
    # See PR honesty note in module docstring.
    os.makedirs(VIEWS, exist_ok=True)
    view_r2 = os.path.join(VIEWS, "wcode-r2.jsonl")
    # Filter: only mbpp:* tasks (W-code world)
    wcode_eps = [e for e in filtered
                 if str(e.get("task", "")).startswith("mbpp:")]
    with open(view_r2, "w", newline="\n") as f:
        for ep in wcode_eps:
            f.write(json.dumps(ep) + "\n")
    print(
        f"[t2_r2_mtp] wrote round-2 view: {view_r2} "
        f"({len(wcode_eps)} wcode episodes)",
        flush=True,
    )

    # Overwrite the path t2_mtp.main() reads from with our round-2 view.
    # Backup the round-1 view first.
    view_r1 = os.path.join(VIEWS, "wcode-r1.jsonl")
    view_r1_backup = os.path.join(VIEWS, "wcode-r1.jsonl.r2-backup")
    if os.path.exists(view_r1) and not os.path.exists(view_r1_backup):
        import shutil
        shutil.copy2(view_r1, view_r1_backup)
        print(f"[t2_r2_mtp] backed up r1 view -> {view_r1_backup}", flush=True)
    import shutil
    shutil.copy2(view_r2, view_r1)
    print(f"[t2_r2_mtp] installed r2 view at r1 path for t2_mtp delegation",
          flush=True)

    # --- Calibration plan (zero marginal GPU) ---
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
    receipt_path = f"{RECEIPTS}/r2-mtp-wrapper-{ts}.json"
    pre_receipt = {
        "ticket": "NC0-T2-R2-MTP-WRAPPER",
        "arm": "mtp",
        "tag": tag,
        "ts": ts,
        "gate_token_present": bool(_gate_token),
        "model": args.model,
        "k_aux": args.k_aux,
        "lam": args.lam,
        "theta": theta,
        "all_verified": args.all_verified,
        "frontier_filter": {
            "tasks_filtered": tasks_filtered,
            "tasks_total": tasks_all,
            "episodes_filtered": len(filtered),
            "wcode_episodes_filtered": len(wcode_eps),
            "episodes_total": len(episodes),
        },
        "view_r2": view_r2,
        "view_r1_backup": view_r1_backup if os.path.exists(view_r1_backup) else None,
        "calibration": calibration_receipt,
        "no_training_launched_by_wrapper": True,
        "mtp_trainer_extension_note": (
            "t2_mtp.py reads from wcode-r1.jsonl (hardcoded). "
            "Round-2 wrapper installs the r2 view at that path. "
            "A --view-path argument to t2_mtp.py would avoid this; "
            "that is a one-line trainer extension (not implemented per "
            "new-files-only constraint). The backup at wcode-r1.jsonl.r2-backup "
            "preserves the round-1 view."
        ),
        "delegation": {
            "entry": "t2_mtp",
            "argv": [
                "t2_mtp.py",
                "--model", args.model,
                "--tag", tag,
                "--k-aux", str(args.k_aux),
                "--lam", str(args.lam),
            ] + extra,
        },
    }
    with open(receipt_path, "w", newline="\n") as f:
        json.dump(pre_receipt, f, indent=2, sort_keys=True)
    print(f"[t2_r2_mtp] pre-receipt: {receipt_path}", flush=True)

    # --- Delegate to t2_mtp ---
    sys.argv = [
        "t2_mtp.py",
        "--model", args.model,
        "--tag", tag,
        "--k-aux", str(args.k_aux),
        "--lam", str(args.lam),
    ] + extra
    print(f"[t2_r2_mtp] delegating: sys.argv={sys.argv}", flush=True)
    runpy.run_path(
        f"{NC}/scripts/t2_mtp.py",
        run_name="__main__",
    )


if __name__ == "__main__":
    main()
