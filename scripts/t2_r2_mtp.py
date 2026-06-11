"""t2_r2_mtp.py — Round-2 MTP-aux SFT arm wrapper (eng #30, issue #106).

MTP-aux SFT arm for round-2. Delegates to t2_mtp.py (eng #4) via import.

Launch interlock: requires --leo-gate-token=<non-empty>. Any dispatch
without this token raises SystemExit(1) before any dataset or training work.

MTP note (eng #140, Kai r2 audit + gate rework): the original
install-at-r1-path delegation was broken — t2_mtp regenerated
wcode-r1.jsonl from the full ledger before building, so the wrapper's
filtered view never reached training (live evidence:
r2-mtp-wrapper-20260611T033826Z vs t2-r2-q3-mtp-20260611T034305Z).
The first fix had the wrapper build its OWN view (ledger -> theta ->
mbpp filter), which skipped ext_clean — a row-level confound vs the
sft arm's view (gate finding on PR #143). Final shape (option b of the
gate comment): this wrapper consumes the SAME view file the sft arm
wrote — ledger/views/wcode-r2-sft.jsonl — sha-pinned, so dataset
identity with the sft arm holds by-construction and can never drift.
t2_mtp re-asserts the pin at build time and cross-checks rows +
n_examples against the certified sft receipt (fail-closed), so BOTH
receipts carry identity claim:true with a checkable basis.
The wrapper writes no view and applies no filter; theta/ext-clean
were applied by the sft arm at view-write time. Dispatch order:
the sft arm (t2_r2w) must run first; this wrapper fails closed if
the sft view or its certified receipt is absent. wcode-r1.jsonl is
never touched.

Calibration (zero marginal GPU, single source = calibrate.py + w1_mbpp).

AST-check: python -c "import ast; ast.parse(open('t2_r2_mtp.py').read())"
py_compile: python -m py_compile t2_r2_mtp.py
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
    ap.add_argument("--theta", type=float, default=None,
                    help="REFUSED if set: the dataset is the sft arm's "
                         "pinned view; theta was applied by t2_r2w at "
                         "view-write time and is not configurable here.")
    ap.add_argument("--all-verified", action="store_true",
                    help="REFUSED if set: same reason as --theta.")
    ap.add_argument("--license-allow", default=None,
                    help="Passed through to t2_mtp's build. MUST match the "
                         "value the sft arm ran with — the dispatcher gives "
                         "both arms the same flags; recorded in the receipt.")
    ap.add_argument("--calibrate", action="store_true",
                    help="Plan calibration elicitation pass (zero marginal GPU).")
    args, extra = ap.parse_known_args()

    # Fail-closed: silently accepting a filter knob the pinned view cannot
    # honor would make the receipt fictional (the exact failure class this
    # rework removes). Refuse instead.
    if args.theta is not None or args.all_verified:
        print(
            "ERROR: t2_r2_mtp.py no longer applies a frontier filter — the "
            "dataset is pinned to the sft arm's view "
            "(ledger/views/wcode-r2-sft.jsonl), where theta/ext-clean were "
            "already applied at view-write time. Drop --theta/--all-verified; "
            "to change the pool, re-run the sft arm with new flags first.",
            flush=True,
        )
        sys.exit(1)

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

    VIEWS = f"{NC}/ledger/views"
    RECEIPTS = f"{NC}/receipts"

    # --- Consume the sft arm's view, sha-pinned (eng #140 gate rework) ---
    # The wrapper writes NO view and applies NO filter. Dataset identity
    # with the sft arm is by-construction: same file, same bytes.
    sft_view = os.path.join(VIEWS, "wcode-r2-sft.jsonl")
    if not os.path.exists(sft_view):
        print(
            f"ERROR: sft view not found: {sft_view}. The sft arm (t2_r2w) "
            "writes this view and must run first — dispatch order is "
            "sft -> mtp. Refusing to build a substitute view: that is "
            "exactly the dataset-identity drift this wrapper exists to "
            "prevent.",
            flush=True,
        )
        sys.exit(1)
    view_rows = 0
    with open(sft_view, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                view_rows += 1
    if view_rows == 0:
        print(f"ERROR: sft view is empty: {sft_view}. Re-run the sft arm.",
              flush=True)
        sys.exit(1)
    import hashlib
    h = hashlib.sha256()
    with open(sft_view, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    sft_view_sha256 = h.hexdigest()
    print(
        f"[t2_r2_mtp] consuming sft view: {sft_view} "
        f"({view_rows} rows, sha256={sft_view_sha256[:12]}...)",
        flush=True,
    )

    # --- Resolve the certified sft receipt (identity anchor) ---
    # t2_mtp cross-checks rows + n_examples against it and asserts the
    # build-time view hash equals our pin above. Skip dry-run and
    # empty-dataset receipts: only a trained sft run certifies the numbers.
    sft_receipt_path = None
    for cand in sorted(glob.glob(f"{RECEIPTS}/t2-r2w-sft-*.json"),
                       reverse=True):
        try:
            with open(cand, encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not rec.get("dry_run") and rec.get("training"):
            sft_receipt_path = cand
            break
    if sft_receipt_path is None:
        print(
            f"ERROR: no certified sft receipt found "
            f"({RECEIPTS}/t2-r2w-sft-*.json with dry_run=false and a "
            "training block). The sft arm must complete first — its "
            "receipt anchors the identity assert. Refusing.",
            flush=True,
        )
        sys.exit(1)
    print(f"[t2_r2_mtp] identity anchor: {sft_receipt_path}", flush=True)

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

    # eng #140 delegation argv: the sft arm's view, sha-pinned above,
    # the certified sft receipt as identity anchor, receipt linkage,
    # and the sft-mirror build flags. t2_mtp asserts all anchors
    # fail-closed before training and claims identity TRUE.
    delegate_argv = [
        "t2_mtp.py",
        "--model", args.model,
        "--tag", tag,
        "--k-aux", str(args.k_aux),
        "--lam", str(args.lam),
        "--view-path", sft_view,
        "--sft-receipt", sft_receipt_path,
        "--expected-view-sha256", sft_view_sha256,
        "--round", "2",
        "--wrapper-receipt", receipt_path,
        "--gate-token-present",
    ]
    if args.license_allow:
        delegate_argv += ["--license-allow", args.license_allow]
    delegate_argv += extra

    pre_receipt = {
        "ticket": "NC0-T2-R2-MTP-WRAPPER",
        "arm": "mtp",
        "tag": tag,
        "ts": ts,
        "gate_token_present": bool(_gate_token),
        "model": args.model,
        "k_aux": args.k_aux,
        "lam": args.lam,
        "license_allow": args.license_allow,
        "dataset_identity": {
            "claim": True,
            "arm": "r2-q3-sft (t2_r2w sft arm)",
            "basis": ("by-construction: this arm trains on the SAME view "
                      "file the sft arm wrote (no copy, no rebuild), "
                      "sha-pinned here; t2_mtp re-hashes it at build time "
                      "and asserts equality with this pin, cross-checks "
                      "rows + n_examples against the certified sft "
                      "receipt, and mirrors the sft build shape (flat cap "
                      "+ license_allow) — all fail-closed before "
                      "training. theta + ext_clean were applied by the "
                      "sft arm at view-write time."),
            "view_path": sft_view,
            "view_rows": view_rows,
            "view_sha256": sft_view_sha256,
            "sft_receipt": sft_receipt_path,
        },
        "sha_convention": ("sha256 over on-disk raw bytes "
                           "(binary read, no line-ending normalization)"),
        "calibration": calibration_receipt,
        "no_training_launched_by_wrapper": True,
        "view_plumb_note": (
            "eng #140 (gate rework, option b): the wrapper builds no view "
            "and applies no filter — it consumes wcode-r2-sft.jsonl, "
            "fail-closed if absent. The first fix's self-built view "
            "skipped ext_clean (row-level confound vs the sft arm); the "
            "original delegation was overwritten by t2_mtp's ledger "
            "regeneration and never reached training. wcode-r1.jsonl is "
            "never touched by this wrapper."
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
