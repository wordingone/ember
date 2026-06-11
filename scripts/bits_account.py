"""bits_account.py — three-estimator banked-bits receipt (#30).

Compares, on the current mbpp ledger view (post-cap kept set throughout):
  1. naive      — report_block on all verified records (252.2-class number)
  2. ext-clean  — report_block after dropping measured-wrong keys (eng #21)
  3. corrected  — fpr_corrected_bits: exact where measured (flagged -> 0,
                  covered-clean -> full), FPR-discounted on episodes MBPP+
                  cannot measure (uncovered tasks), stratum Wilson CI
                  propagated -> (lo, point, hi) band.

Inputs are receipts: v-ext flags jsonl (wrong-only) + the v-extended
receipt's uncovered task list and per-stratum (wrong, n) counts. Strata
absent from the FPR receipt fall back to the OVERALL rate (stated on the
receipt). Pure stdlib (+ frontier, power). Receipt: receipts/bits-account-<ts>.json.
"""
import glob as globlib
import json
import os
from datetime import datetime, timezone

from frontier import (ext_clean, fpr_corrected_bits, load_ext_flags,
                      report_block)
from power import wilson

NC = "B:/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"


def main():
    recs = []
    with open(f"{NC}/ledger/episodes.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["task"].startswith("mbpp:"):
                recs.append(r)

    flags = load_ext_flags([f"{RECEIPTS}/v-ext-flags-*.jsonl"])
    vext_path = sorted(globlib.glob(f"{RECEIPTS}/v-extended-*.json"))[-1]
    vext = json.load(open(vext_path, encoding="utf-8"))
    uncovered = {f"mbpp:{t}" for t in vext["uncovered_tasks"]}

    overall = vext["fpr"]["overall"]
    fpr_ci, fallback = {}, []
    strata = {r["stratum"] for r in recs}
    for st in strata:
        blk = vext["fpr"].get(st)
        if blk is None or not blk["n"]:
            blk, note = overall, st
            fallback.append(st)
        lo, hi = wilson(blk["ext_wrong"], blk["n"])
        fpr_ci[st] = (round(lo, 4), round(blk["ext_wrong"] / blk["n"], 4),
                      round(hi, 4))

    naive = report_block(recs)
    clean = report_block(ext_clean(recs, flags))
    corrected = fpr_corrected_bits(recs, flags, uncovered, fpr_ci)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "BITS-ACCOUNT", "ts": ts,
        "ledger_mbpp_records": len(recs),
        "flags_wrong_only": len(flags),
        "fpr_source": os.path.basename(vext_path),
        "uncovered_tasks": sorted(uncovered),
        "fpr_ci_by_stratum": fpr_ci,
        "fpr_fallback_to_overall": fallback,
        "estimators": {
            "naive_total": naive["total_bits_banked"],
            "ext_clean_total": clean["total_bits_banked"],
            "fpr_corrected": corrected,
        },
        "reading": "corrected.point is the working B numerator; the "
                   "[lo,hi] band carries MBPP+ non-coverage uncertainty "
                   "only (covered episodes are measured, not estimated)",
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    out = f"{RECEIPTS}/bits-account-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"BITS_ACCOUNT_DONE {out}")


if __name__ == "__main__":
    main()
