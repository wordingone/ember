"""w4_control_delta_repair.py — eng-41 (#151): checked repair receipt for
w4 G1 receipts produced before the control-pairs fix (mail 14529).

Pre-fix w4_eval guarded the control comparison behind a literal
'trained' arm name, so a five-arm r2 record (base/sft/mtp/grpo/control)
receipt carries every <arm>_minus_base_ci95 but NO control deltas —
partial/pre-gate under STATE's decision rule. This tool post-processes
the run's OWN samples JSONL into a checked repair receipt carrying the
missing <arm>_minus_control_ci95 legs (bootstrap + exact block), so the
finished run can gate without a GPU rerun (Kai 14529 option a; rerun is
option b — gate-holder's call).

Validity is PROVEN, not assumed: bootstrap_ci/paired_delta_ci are
seeded (seed=7, deterministic), so the tool recomputes the base deltas
and per-arm pass rates from the samples and asserts EXACT equality with
the original receipt before emitting anything — if the repair pipeline
cannot reproduce the original computation bit-for-bit, it refuses.

Task order is recovered from the samples file itself: rows are written
arm-major in task order (k consecutive samples per task), so first-seen
tid order within the first arm IS the original eval order. Pairing rule
is imported from w4_eval.control_pairs — single source, never copied.

CPU-only; no model load; no GPU. Windows-safe via the declared
`resource` shim (w4_eval's import chain reaches t1_probe's POSIX
rlimits; the sandbox is not exercised here).

Usage:
  python w4_control_delta_repair.py --samples <w4-...-samples.jsonl> \
      --receipt <w4-eval-...json> [--out-dir DIR (default: receipt's dir)]

Sentinel: W4_CONTROL_DELTA_REPAIR_DONE <path>.
"""
import argparse
import hashlib
import json
import os
import sys
import types
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Windows test-shim (declared): w4_eval -> t1_probe imports POSIX
# `resource` at module level for sandbox rlimits; nothing here executes
# sandboxed code. Shimming ONLY makes the import succeed on nt.
if os.name == "nt":
    sys.modules.setdefault("resource", types.ModuleType("resource"))

from w4_eval import control_pairs, parse_arms, task_pass_vector  # noqa: E402
from t4_eval import paired_delta_ci  # noqa: E402
from receipt_write import checked_write  # noqa: E402
try:
    from stats_exact import build_exact_block as _build_exact_block  # noqa: E402
except ImportError:
    _build_exact_block = None

SHA_CONVENTION = ("sha256 over on-disk raw bytes "
                  "(binary read, no line-ending normalization)")


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_samples(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        raise SystemExit(f"repair: samples file is empty: {path}")
    return rows


def recover_order(rows, first_arm):
    """First-seen tid order within the first arm = original eval order
    (w4_eval writes arm-major, k consecutive samples per task)."""
    order, seen = [], set()
    for r in rows:
        if r["arm"] != first_arm:
            continue
        if r["tid"] not in seen:
            seen.add(r["tid"])
            order.append(r["tid"])
    if not order:
        raise SystemExit(f"repair: no rows for first arm {first_arm!r}")
    return order


def repair(samples_path, receipt_path, out_dir=None):
    with open(receipt_path, encoding="utf-8") as f:
        original = json.load(f)
    arm_names = [n for n, _ in parse_arms(original["args"]["arm"])]
    if "control" not in arm_names:
        raise SystemExit("repair: original run has no control arm — "
                         "nothing to repair")
    missing = [f"{n}_minus_control_ci95" for n in arm_names
               if n not in ("base", "control")]
    already = [k for k in missing if k in original.get("deltas", {})]
    if already:
        raise SystemExit(
            f"repair: original receipt already carries {already} — "
            "post-fix receipt, repair unnecessary. Refusing.")

    rows = load_samples(samples_path)
    by_arm = {}
    for r in rows:
        by_arm.setdefault(r["arm"], []).append(r)
    if set(by_arm) != set(arm_names):
        raise SystemExit(
            f"repair: samples arms {sorted(by_arm)} != receipt arms "
            f"{sorted(arm_names)}. Refusing.")

    order = recover_order(rows, arm_names[0])
    if len(order) != original["n_tasks"]:
        raise SystemExit(
            f"repair: recovered task order has {len(order)} tasks, "
            f"receipt says {original['n_tasks']}. Refusing.")
    arm_vec = {n: task_pass_vector(by_arm[n], order) for n in arm_names}

    # --- Validity cross-check: reproduce the original computation ---
    # (seeded bootstrap => exact equality or the pipeline is wrong)
    crosscheck = {"base_deltas_compared": 0, "pass_any_compared": 0}
    for name in arm_names:
        got = round(100 * sum(arm_vec[name]) / len(arm_vec[name]), 2)
        want = original["arms"][name]["pass_any_pct"]
        if got != want:
            raise SystemExit(
                f"repair: pass_any_pct mismatch for {name}: recomputed "
                f"{got} vs receipt {want}. Order recovery or samples are "
                "wrong. Refusing.")
        crosscheck["pass_any_compared"] += 1
    if "base" in arm_vec:
        for name in arm_names:
            if name == "base":
                continue
            key = f"{name}_minus_base_ci95"
            got = paired_delta_ci(arm_vec[name], arm_vec["base"])
            want = original["deltas"].get(key)
            if got != want:
                raise SystemExit(
                    f"repair: {key} mismatch: recomputed {got} vs receipt "
                    f"{want}. Seeded CI must reproduce exactly. Refusing.")
            crosscheck["base_deltas_compared"] += 1

    # --- The missing legs ---
    pairs = control_pairs(arm_vec)
    deltas = {key: paired_delta_ci(a, b) for key, (a, b) in pairs.items()}
    exact = None
    if _build_exact_block is not None:
        succ_by_arm = {n: sum(arm_vec[n]) for n in arm_names}
        exact = _build_exact_block(succ_by_arm, pairs, len(order))

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = out_dir or os.path.dirname(os.path.abspath(receipt_path))
    receipt = {
        "ticket": "W4-CONTROL-DELTA-REPAIR",
        "ts": ts,
        "issue": "wordingone/ember#151",
        "repairs_receipt": os.path.basename(receipt_path),
        "repairs_receipt_sha256": file_sha256(receipt_path),
        "samples_file": os.path.basename(samples_path),
        "samples_sha256": file_sha256(samples_path),
        "sha_convention": SHA_CONVENTION,
        "original_ts": original["ts"],
        "original_tag": original["args"].get("tag", ""),
        "n_tasks": len(order),
        "arms": arm_names,
        "crosscheck": {
            **crosscheck,
            "method": ("recomputed per-arm pass_any_pct and every "
                       "<arm>_minus_base_ci95 from the samples; exact "
                       "equality with the original receipt asserted "
                       "fail-closed before emitting (CIs are seeded/"
                       "deterministic)"),
        },
        "deltas": deltas,
        "exact_control": exact,
        "method": ("task order = first-seen tid order of the first arm "
                   "(arm-major write order); pairing rule = "
                   "w4_eval.control_pairs (single source); pre-fix "
                   "receipt lacked control legs per eng #151"),
        "no_gpu": True,
    }
    out_path = os.path.join(
        out_dir, f"w4-control-delta-repair-{original['ts']}-{ts}.json")
    checked_write(out_path, receipt)
    print(json.dumps({"deltas": deltas,
                      "crosscheck": receipt["crosscheck"]}, indent=2))
    print(f"W4_CONTROL_DELTA_REPAIR_DONE {out_path}", flush=True)
    return out_path, receipt


def main():
    ap = argparse.ArgumentParser(description="eng-41 w4 control-delta repair")
    ap.add_argument("--samples", required=True)
    ap.add_argument("--receipt", required=True)
    ap.add_argument("--out-dir", default=None,
                    help="default: the original receipt's directory")
    args = ap.parse_args()
    repair(args.samples, args.receipt, args.out_dir)


if __name__ == "__main__":
    main()
