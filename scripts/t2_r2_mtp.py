"""t2_r2_mtp.py — Round-2 MTP-aux SFT arm wrapper (eng #30, issue #106).

MTP-aux SFT arm for round-2. Delegates to t2_mtp.py (eng #4) via import.

Launch interlock: requires --leo-gate-token=<non-empty>. Any dispatch
without this token raises SystemExit(1) before any dataset or training work.

MTP note (eng #140, Kai r2 audit): the original install-at-r1-path
delegation was broken — t2_mtp regenerated wcode-r1.jsonl from the full
ledger before building, so the wrapper's filtered view never reached
training (live evidence: r2-mtp-wrapper-20260611T033826Z vs
t2-r2-q3-mtp-20260611T034305Z). t2_mtp now accepts --view-path; this
wrapper writes the filtered view to wcode-r2.jsonl and passes it
explicitly. wcode-r1.jsonl is never touched.

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

    # --- Write the frontier-filtered round-2 view (eng #140) ---
    # Passed to t2_mtp via --view-path; wcode-r1.jsonl is never touched.
    os.makedirs(VIEWS, exist_ok=True)
    view_r2 = os.path.join(VIEWS, "wcode-r2.jsonl")
    # Filter: only mbpp:* tasks (W-code world)
    wcode_eps = [e for e in filtered
                 if str(e.get("task", "")).startswith("mbpp:")]
    with open(view_r2, "w", newline="\n") as f:
        for ep in wcode_eps:
            f.write(json.dumps(ep) + "\n")
    import hashlib
    h = hashlib.sha256()
    with open(view_r2, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    view_r2_sha256 = h.hexdigest()
    print(
        f"[t2_r2_mtp] wrote round-2 view: {view_r2} "
        f"({len(wcode_eps)} wcode episodes, sha256={view_r2_sha256[:12]}...)",
        flush=True,
    )

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

    # eng #140 delegation argv: explicit view path + receipt linkage.
    delegate_argv = [
        "t2_mtp.py",
        "--model", args.model,
        "--tag", tag,
        "--k-aux", str(args.k_aux),
        "--lam", str(args.lam),
        "--view-path", view_r2,
        "--round", "2",
        "--wrapper-receipt", receipt_path,
        "--gate-token-present",
    ] + extra

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
        "view_r2_rows": len(wcode_eps),
        "view_r2_sha256": view_r2_sha256,
        "sha_convention": ("sha256 over on-disk raw bytes "
                           "(binary read, no line-ending normalization)"),
        "calibration": calibration_receipt,
        "no_training_launched_by_wrapper": True,
        "view_plumb_note": (
            "eng #140: t2_mtp consumes --view-path explicitly; the prior "
            "install-at-wcode-r1.jsonl delegation was overwritten by "
            "t2_mtp's ledger regeneration and never reached training. "
            "wcode-r1.jsonl is no longer touched by this wrapper."
        ),
        "delegation": {
            "entry": "t2_mtp",
            "argv": delegate_argv,
        },
    }
    with open(receipt_path, "w", newline="\n") as f:
        json.dump(pre_receipt, f, indent=2, sort_keys=True)
    print(f"[t2_r2_mtp] pre-receipt: {receipt_path}", flush=True)

    # --- Delegate to t2_mtp ---
    sys.argv = delegate_argv
    print(f"[t2_r2_mtp] delegating: sys.argv={sys.argv}", flush=True)
    runpy.run_path(
        f"{NC}/scripts/t2_mtp.py",
        run_name="__main__",
    )


if __name__ == "__main__":
    main()
