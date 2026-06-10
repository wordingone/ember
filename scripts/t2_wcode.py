"""t2_wcode.py — W-code round-1 plain-SFT arm (contract row 9, arm A).

Trains the 3B core on its OWN verified W-code episodes (on-policy: every
ledger mbpp:* record was sampled by the core itself in w1 — the t5 harm
receipt killed off-policy expert imitation, this arm is the honest
replacement). World-filtered: the ARC seed episodes (DSL surface form,
t5-proven coding damage −4..−28pp) are EXCLUDED; whether worlds mix in one
adapter is a later-round design question (replay-mix arm, round-2 AC).

Pipeline: ledger/episodes.jsonl --filter mbpp:*--> ledger/views/wcode-r1.jsonl
(derived view, regenerated every run) -> bits-weighted dataset (frontier dict
caps, eng #5: easy 2 / mid 4 / frontier 8) -> t2_round.train_lora (same
proven QLoRA recipe + governor) -> adapters/r1w-q3[-control].

--control: matched-budget arm from control_pool mbpp:* fails (G2), counts
mirrored per-task against the arm-A dataset.

Receipt: receipts/t2-r1w-q3[-control]-<ts>.json with the no-silent-caps
frontier block. G1 eval surface after both arms: w1_mbpp --split validation
(43 heldout tasks) base vs adapter vs control; t5 harm gate on the adapter.
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"
VIEWS = f"{NC}/ledger/views"


def write_view(src_path, view_path, prefix="mbpp:"):
    """Filter a ledger file to one world -> derived view file. Returns recs."""
    recs = []
    with open(src_path) as f:
        for line in f:
            r = json.loads(line)
            if r["task"].startswith(prefix):
                recs.append(r)
    os.makedirs(os.path.dirname(view_path), exist_ok=True)
    with open(view_path, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-3B-Instruct")
    ap.add_argument("--control", action="store_true")
    ap.add_argument("--tag", default="r1w-q3")
    args, _unknown = ap.parse_known_args()  # daemon appends args; ignore them

    import sys
    sys.path.insert(0, f"{NC}/scripts")
    from frontier import caps_from_records, report_block
    from t2_round import CONTROL_POOL, LEDGER, ADAPTERS, build_dataset, \
        train_lora

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tag = args.tag + ("-control" if args.control else "")

    arm_recs = write_view(LEDGER, f"{VIEWS}/wcode-r1.jsonl")
    if not arm_recs:
        raise SystemExit("t2_wcode: no mbpp:* records in ledger — ingest first")
    caps = caps_from_records(arm_recs)

    if args.control:
        _, verified_counts = build_dataset(f"{VIEWS}/wcode-r1.jsonl", cap=caps)
        ctrl_recs = write_view(CONTROL_POOL, f"{VIEWS}/wcode-r1-control.jsonl")
        examples, counts = build_dataset(f"{VIEWS}/wcode-r1-control.jsonl",
                                         match_counts=verified_counts)
    else:
        examples, counts = build_dataset(f"{VIEWS}/wcode-r1.jsonl", cap=caps)

    receipt = {"ticket": "NC0-T2-WCODE", "ts": ts, "control": args.control,
               "model": args.model, "world": "mbpp", "round": 1,
               "ledger_records_world": len(arm_recs),
               "frontier": report_block(arm_recs),
               "dataset": {"n_examples": len(examples),
                           "n_tasks": len(counts)},
               "excluded": "ARC seed episodes (off-policy DSL, t5 harm "
                           "receipt 20260610T203520Z)"}
    if not examples:
        receipt["verdict"] = "EMPTY-DATASET (gate before training)"
    else:
        t0 = time.time()
        receipt["training"] = train_lora(args.model, examples,
                                         f"{ADAPTERS}/{tag}")
        receipt["training"]["secs"] = round(time.time() - t0, 1)
        receipt["adapter"] = f"{ADAPTERS}/{tag}"

    os.makedirs(RECEIPTS, exist_ok=True)
    with open(f"{RECEIPTS}/t2-{tag}-{ts}.json", "w") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps({k: v for k, v in receipt.items() if k != "frontier"},
                     indent=2, default=str))
    print("T2_WCODE_DONE")


if __name__ == "__main__":
    main()
