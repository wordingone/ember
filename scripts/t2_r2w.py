"""t2_r2w.py — Round-2 W-code sft + control arms, CORRECTED data path.

DEVIATION RECORD (prereg §1.2, recorded per audit-§6): the #112 wrapper
t2_r2_sft computed the theta frontier filter for its receipt but then
delegated to `t2_round --round 2 --train-only`, which builds from the FULL
mixed ledger (ARC + W) with flat caps — the filtered set never reached
training. That is not the registered arm ("frontier-weighted theta=0.5"
on the W-code world). This runner implements the registered semantics,
reusing the proven round-1 pieces (t2_wcode.write_view, frontier.ext_clean,
t2_round.build_dataset/train_lora) and the r2_arms single-source rates:

  sft:     ledger --mbpp:*--> view --ext_clean--> --theta-filter (0,0.5]-->
           build_dataset (flat MAX_PER_TASK cap) --> train_lora
           -> adapters/r2-q3-sft
  control: control_pool --mbpp:*--> view, counts MIRRORED per-task against
           the sft arm's dataset (recomputed deterministically from the
           same ledger state) -> adapters/r2-q3-control

mtp/grpo arms are NOT here: t2_r2_mtp -> t2_mtp regenerates the W view
itself (bits-caps = the r1 default-recipe winner, correct as built);
t2_r2_grpo samples on-policy with verifier reward.

Launch interlock: --leo-gate-token required (same shape as the #112
wrappers). --dry-run builds everything and writes a receipt but stops
before train_lora (CPU-safe preflight).

AST: python -c "import ast; ast.parse(open('scripts/t2_r2w.py').read())"
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from receipt_write import checked_write  # noqa: E402 (eng #107)

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
if os.name == "nt":
    NC = "B:/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"
VIEWS = f"{NC}/ledger/views"
LEDGER = f"{NC}/ledger/episodes.jsonl"
CONTROL_POOL = f"{NC}/ledger/control_pool.jsonl"
ADAPTERS = f"{NC}/adapters"

THETA = 0.5  # prereg §1.2 frozen

SHA_CONVENTION = ("sha256 over on-disk raw bytes "
                  "(binary read, no line-ending normalization)")


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _view_entry(path, rows):
    """Receipt entry for a view file ALREADY written to disk — the sha
    is taken from the on-disk bytes post-write, so a downstream
    consumer's --expected-view-sha256 can be pinned straight from the
    certified receipt (eng #150)."""
    return {"path": path, "rows": rows, "sha256": file_sha256(path)}


def _require_gate_token():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--leo-gate-token", default="")
    args, _ = ap.parse_known_args()
    if not args.leo_gate_token.strip():
        print(
            "ERROR: t2_r2w.py requires --leo-gate-token=<non-empty> "
            "(round-2 launch interlock). Exiting without any work.",
            flush=True,
        )
        sys.exit(1)
    return args.leo_gate_token


_gate_token = _require_gate_token()


def build_sft_examples(allow=None):
    """Regenerate W-code views from the CURRENT ledger, ext-clean, apply
    the frozen theta filter, build the dataset. Returns
    (examples, counts, info_block, views). Deterministic from ledger
    state — the control arm recomputes this to mirror counts. `views`
    maps each view filename written here to its post-write
    path/rows/sha256 entry (eng #150)."""
    from frontier import ext_clean, load_ext_flags
    from r2_arms import frontier_filter, solve_rates_from_ledger
    from t2_round import build_dataset
    from t2_wcode import write_view

    arm_recs = write_view(LEDGER, f"{VIEWS}/wcode-r2.jsonl")
    views = {"wcode-r2.jsonl":
             _view_entry(f"{VIEWS}/wcode-r2.jsonl", len(arm_recs))}
    arm_recs = ext_clean(arm_recs,
                         load_ext_flags([f"{RECEIPTS}/v-ext-flags-*.jsonl"]))

    rates = solve_rates_from_ledger(LEDGER, CONTROL_POOL)
    filtered = frontier_filter(arm_recs, rates, THETA)

    view_path = f"{VIEWS}/wcode-r2-sft.jsonl"
    with open(view_path, "w", encoding="utf-8", newline="\n") as vf:
        for r in filtered:
            vf.write(json.dumps(r) + "\n")
    views["wcode-r2-sft.jsonl"] = _view_entry(view_path, len(filtered))

    examples, counts = build_dataset(view_path, license_allow=allow)
    info = {
        "theta": THETA,
        "view_rows_wcode": len(arm_recs),
        "view_rows_after_theta": len(filtered),
        "tasks_wcode": len({r["task"] for r in arm_recs}),
        "tasks_after_theta": len({r["task"] for r in filtered}),
        "dataset_examples": len(examples),
        "dataset_tasks": len(counts),
        "rates_source": "r2_arms.solve_rates_from_ledger(ledger+control_pool)",
    }
    return examples, counts, info, views


def main():
    ap = argparse.ArgumentParser(description="Round-2 W-code sft/control arms "
                                             "(corrected data path).")
    ap.add_argument("--leo-gate-token", required=True)
    ap.add_argument("--arm", choices=("sft", "control"), required=True)
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-3B-Instruct")
    ap.add_argument("--tag-suffix", default="-q3")
    ap.add_argument("--license-allow", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="build dataset + receipt, no training (CPU preflight)")
    args, _unknown = ap.parse_known_args()  # daemon appends args; ignore

    sys.path.insert(0, f"{NC}/scripts")
    from ledger_license import parse_allow
    from t2_round import build_dataset, train_lora
    from t2_wcode import write_view
    from t1_probe import pacing_snapshot

    allow = parse_allow(args.license_allow) if args.license_allow else None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    clean = args.tag_suffix.lstrip("-")
    tag = f"r2-{clean}-{args.arm}"

    sft_examples, sft_counts, info, views = build_sft_examples(allow)

    if args.arm == "sft":
        examples, counts = sft_examples, sft_counts
    else:
        ctrl_recs = write_view(CONTROL_POOL, f"{VIEWS}/wcode-r2-control.jsonl")
        views["wcode-r2-control.jsonl"] = _view_entry(
            f"{VIEWS}/wcode-r2-control.jsonl", len(ctrl_recs))
        examples, counts = build_dataset(f"{VIEWS}/wcode-r2-control.jsonl",
                                         match_counts=sft_counts,
                                         license_allow=allow)
        info["control_view_rows"] = len(ctrl_recs)
        info["control_examples"] = len(examples)
        info["mirrors"] = "sft per-task counts (recomputed, same ledger state)"

    receipt = {
        "ticket": "NC0-T2-R2W",
        "arm": args.arm,
        "tag": tag,
        "ts": ts,
        "round": 2,
        "model": args.model,
        "gate_token_present": bool(_gate_token),
        "deviation": ("prereg-§1.2 data-path correction: #112 t2_r2_sft "
                      "delegated to full-ledger flat-cap build; this runner "
                      "trains the registered W-code theta-filtered set"),
        "frontier_filter": info,
        "views_written": views,
        "sha_convention": SHA_CONVENTION,
        "dry_run": args.dry_run,
    }

    if not examples:
        receipt["verdict"] = "EMPTY-DATASET (gate before training)"
    elif not args.dry_run:
        t0 = time.time()
        receipt["training"] = train_lora(args.model, examples,
                                         f"{ADAPTERS}/{tag}")
        receipt["training"]["secs"] = round(time.time() - t0, 1)
        receipt["adapter"] = f"{ADAPTERS}/{tag}"

    receipt["pacing"] = pacing_snapshot()  # fp-14 convention, at write time
    os.makedirs(RECEIPTS, exist_ok=True)
    out = f"{RECEIPTS}/t2-r2w-{args.arm}-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps({k: receipt[k] for k in
                      ("arm", "tag", "frontier_filter", "dry_run")}, indent=2))
    print(f"T2_R2W_DONE {out}")


if __name__ == "__main__":
    main()
