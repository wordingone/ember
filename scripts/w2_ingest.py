"""w2_ingest.py — W-code ledger ingest: w1 sample rows -> ledger episodes.

Wires research/teacher-system-2026-06-10.md S1 + the W-code world into the
existing round machinery. Reads w1-floor *-samples.jsonl rows
({"task": "mbpp:<id>", "verified", "error", "src", "prompt", "sampler"}),
converts them to t2_round ledger records (same key scheme `task:sha(src)`,
same append_jsonl dedup), and appends:
  verified rows           -> ledger/episodes.jsonl
  failed rows WITH src    -> ledger/control_pool.jsonl  (G2 control material)
  rows without src        -> skipped (extraction failures carry no program)

Records carry "prompt" inline so build_dataset renders the EXACT user text the
sampler saw (mbpp:* keys are not in ARC_TRAIN — without an inline prompt they
would be silently skipped), and "sampler" for per-teacher G3 leave-set-out.

Receipt: receipts/w2-ingest-<ts>.json. Pure conversion logic is import-light
(stdlib + the stdlib-only ledger_license/fp6_provenance siblings) so it
unit-tests anywhere; t2_round (-> t1_probe -> torch) is imported inside
main() only.
"""

import argparse
import glob as globlib
import hashlib
import json
import os
from datetime import datetime, timezone

from ledger_license import census as license_census, stamp  # eng #70

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"


def sha(s):
    # Identical to t2_round.sha (sha1 hex, 16 chars) — duplicated only to keep
    # this module importable without the t1_probe/torch chain for unit tests.
    return hashlib.sha1(s.encode()).hexdigest()[:16]


def samples_to_records(rows, round_n, ts="", receipt=""):
    """w1 sample rows -> (verified_records, failed_records). Pure.

    Emits ledger schema v3 (docs/ledger-schema-v3.md): explicit verified/ts/
    origin/receipt on every record — origin absorbs the w1 sampler identity
    (one provenance field; sampler kept as passthrough for leave-set-out
    tooling). "solved" mirrors "verified" for W-code: the MBPP harness'
    asserts ARE the task's full test, there is no separate held-back pair.
    """
    verified, failed = [], []
    for row in rows:
        src = row.get("src")
        if not src:
            continue
        rec = {"key": f"{row['task']}:{sha(src)}",
               "task": row["task"], "src": src,
               "verified": bool(row.get("verified")),
               "ts": ts, "receipt": receipt,
               "origin": row.get("sampler") or "w1-floor",
               "round": round_n, "solved": bool(row.get("verified"))}
        for field in ("prompt", "sampler"):
            if row.get(field):
                rec[field] = row[field]
        stamp(rec)  # eng #70: license_class/license_basis at ingest
        (verified if row.get("verified") else failed).append(rec)
    return verified, failed


def load_rows(patterns):
    rows, files = [], []
    for pat in patterns:
        for path in sorted(globlib.glob(pat)):
            files.append(os.path.basename(path))
            with open(path) as f:
                rows.extend(json.loads(line) for line in f if line.strip())
    return rows, files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", nargs="+", required=True,
                    help="w1 *-samples.jsonl path(s) or glob(s)")
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true",
                    help="report counts; write nothing")
    args, _unknown = ap.parse_known_args()  # daemon appends args; ignore them

    rows, files = load_rows(args.samples)
    if not rows:
        raise SystemExit(f"w2_ingest: no rows matched {args.samples}")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    verified, failed = samples_to_records(
        rows, args.round, ts=ts, receipt=f"w2-ingest-{ts}.json")

    # Frontier annotation (eng #5): per-task solve-rate posterior pooled
    # over ALL loaded sample rows -> phat/bits/stratum on every record.
    # The ledger keeps every verified episode; the easy-mass discount is
    # applied at DATASET build via frontier.caps_from_records.
    from frontier import annotate_records, outcome_stats, report_block
    stats = outcome_stats(rows)
    annotate_records(verified, stats)
    annotate_records(failed, stats)

    receipt = {"ticket": "W2-INGEST",
               "ts": ts,
               "args": vars(args), "files": files, "rows_read": len(rows),
               "verified_records": len(verified),
               "control_records": len(failed),
               "samplers": sorted({r.get("sampler", "?") for r in
                                   verified + failed}),
               "by_license": license_census(verified + failed),  # eng #70
               "frontier": report_block(verified),
               "dry_run": args.dry_run}
    if not args.dry_run:
        from t2_round import CONTROL_POOL, LEDGER, append_jsonl
        receipt["episodes_added"] = append_jsonl(LEDGER, verified)
        receipt["control_added"] = append_jsonl(CONTROL_POOL, failed)

    os.makedirs(RECEIPTS, exist_ok=True)
    out = f"{RECEIPTS}/w2-ingest-{receipt['ts']}.json"
    with open(out, "w") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print("W2_INGEST_DONE")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, f"{NC}/scripts")
    main()
