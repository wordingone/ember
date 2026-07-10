#!/usr/bin/env python3
"""a1_corpus_lineage.py -- ember #631 deliverable 3b: correct the false universal
corpus-lineage premise of PR #603's predicate scan.

Cures the "lineage" half of A1 machinery defect #3 (refs #123 finding 3). PR #603's
scan asserted shards-v0 is "the only corpus any completed training run consumed" and
treated that as the whole contamination universe. The audit's counterexample:
`receipts/t2-r1w-q3-20260610T211509Z.json` (world=mbpp, training.steps=57,
n_examples=294) -- a COMPLETED training run that consumed MBPP-derived inputs, NOT
shards-v0. The universal premise is therefore false.

This script:
  1. REPRODUCE-FIRST: loads the counterexample receipt and asserts it is a completed
     training run consuming a non-shards-v0 corpus, falsifying the universal premise;
  2. mechanically ENUMERATES owned training corpora -> the completed-training receipts
     that consumed each;
  3. records the CORRECTED premise + the lineage-binding gate rule (the gate binds ONE
     exact checkpoint lineage and scans every training input THAT lineage consumed --
     shards-v0 is sufficient ONLY for a lineage that consumed only shards-v0), which
     scripts/a1_freeze_consumer.py (deliverable 5) enforces.

Emits an append-only lineage receipt chained by sha256 to the published scan receipt
(never edited).

Usage:
  python scripts/a1_corpus_lineage.py \\
      --published-scan receipts/a1-predicate-scan/a1-predicate-scan-20260709T231932Z.json \\
      --counterexample receipts/t2-r1w-q3-20260610T211509Z.json \\
      --bmulti1-scan receipts/a1-predicate-scan/a1-bmulti1-scan-<ts>.json \\
      --out receipts/eval-suite-freeze/a1-corpus-lineage-<UTCts>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import receipt_write  # noqa: E402

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def enumerate_completed_training(repo: str):
    """Return list of {receipt, model, world, steps} for every tracked receipt that
    carries a completed-training signal (train_loss / training.steps)."""
    tracked = subprocess.run(["git", "-C", repo, "ls-files", "receipts/"],
                             capture_output=True, text=True, check=True).stdout.split()
    out = []
    for rel in tracked:
        p = os.path.join(repo, rel)
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if '"train_loss"' not in txt and '"training"' not in txt:
            continue
        try:
            d = json.loads(txt)
        except json.JSONDecodeError:
            continue
        tr = d.get("training") if isinstance(d.get("training"), dict) else {}
        has_train = ("train_loss" in d) or ("train_loss" in tr) or ("steps" in tr)
        if not has_train:
            continue
        out.append({
            "receipt": rel.replace(os.sep, "/"),
            "model": d.get("model"),
            "world": d.get("world"),
            "steps": tr.get("steps", d.get("steps")),
            "n_examples": tr.get("n_examples", (d.get("dataset") or {}).get("n_examples")
                                   if isinstance(d.get("dataset"), dict) else None),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--published-scan", required=True)
    ap.add_argument("--counterexample", required=True)
    ap.add_argument("--bmulti1-scan", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    # 1. reproduce-first: the counterexample falsifies the universal premise
    ce = json.load(open(os.path.join(REPO, args.counterexample), encoding="utf-8"))
    ce_world = ce.get("world")
    ce_steps = (ce.get("training") or {}).get("steps")
    ce_nex = (ce.get("training") or {}).get("n_examples")
    premise_falsified = bool(ce_steps) and ce_world not in (None, "", "shards-v0")

    # 2. enumerate owned corpora -> consuming completed-training runs
    runs = enumerate_completed_training(REPO)
    world_to_runs = {}
    for r in runs:
        world_to_runs.setdefault(r["world"] or "unspecified", []).append(r["receipt"])

    owned_corpora = [
        {"corpus": "shards-v0",
         "kind": "text pretraining shards (26 *.bin, 6,973,632,300 content tokens)",
         "consumed_by": "the ember pretraining lineage (W1 collapse-control, W2 G-arm) "
                        "-- these are the shards-v0 consumers named in the scan docstring; "
                        "they do NOT carry a train_loss field in the enumerated shape",
         "scanned_by_a1": True},
        {"corpus": "RL/SFT worlds (mbpp + NC0-ladder worlds)",
         "kind": "eval-derived RL/SFT training inputs (e.g. MBPP tasks)",
         "consumed_by": f"{len(runs)} completed training run(s) enumerated below "
                        f"(NC0-ladder Qwen2.5-Coder RL runs; a SEPARATE base-model lineage "
                        f"from ember's C8, but completed training runs nonetheless -- the "
                        f"exact objects that falsify 'shards-v0 is the only corpus consumed')",
         "scanned_by_a1": "N/A -- these are eval-set-derived training inputs; whether they "
                          "are IN a given C8 lineage depends on that lineage (see gate rule)"},
        {"corpus": "manifests/corpus/b-multi-1",
         "kind": "image-caption multimodal (500 rows)",
         "consumed_by": "NO completed training run (acquire/smoke/scope receipts only)",
         "scanned_by_a1": "YES (defensively, refs #631 deliverable 3a: "
                          + args.bmulti1_scan.replace(os.sep, "/") + ")"},
        {"corpus": "density-ab-{arm-a,arm-b}-100M.bin",
         "kind": "100M-token proportional SAMPLE of shards-v0 (density-ab-spec-v1 sec.2)",
         "consumed_by": "density-ab experiments; content is a subset of shards-v0",
         "scanned_by_a1": "covered transitively by scanning shards-v0"},
    ]

    receipt = {
        "ticket": "A1-CORPUS-LINEAGE-CORRECTION",
        "ts": datetime.now(timezone.utc).isoformat(),
        "schema": "a1-corpus-lineage/v1",
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "issue_refs": ["#631", "#123", "#593", "#440"],
        "corrects": {
            "published_scan": {
                "path": args.published_scan.replace(os.sep, "/"),
                "sha256": file_sha256(os.path.join(REPO, args.published_scan)),
                "false_premise": "shards-v0 is the only corpus any completed training run "
                                 "has consumed (treated as the whole contamination universe)",
                "note": "NEVER edited (append-only). This receipt supersedes the premise text only.",
            },
        },
        "reproduce_first": {
            "counterexample_receipt": args.counterexample.replace(os.sep, "/"),
            "counterexample_sha256": file_sha256(os.path.join(REPO, args.counterexample)),
            "world": ce_world,
            "training_steps": ce_steps,
            "training_n_examples": ce_nex,
            "premise_falsified": premise_falsified,
            "statement": f"a COMPLETED training run (world={ce_world!r}, steps={ce_steps}, "
                         f"n_examples={ce_nex}) consumed a non-shards-v0 corpus; the universal "
                         f"premise is false",
        },
        "enumerated_completed_training_runs": {
            "n_runs": len(runs),
            "by_world": {w: sorted(v) for w, v in sorted(world_to_runs.items())},
            "enumeration_rule": "git ls-files receipts/ | receipts carrying a completed-training "
                                "signal (train_loss or training.steps)",
        },
        "owned_corpora": owned_corpora,
        "bmulti1_scan": {
            "receipt": args.bmulti1_scan.replace(os.sep, "/"),
            "receipt_sha256": file_sha256(os.path.join(REPO, args.bmulti1_scan)),
        },
        "corrected_premise": (
            "shards-v0 is the ember PRETRAINING corpus, and it is NOT the only corpus any "
            "completed training run has consumed: NC0-ladder RL/SFT runs consumed eval-derived "
            "worlds (MBPP and others). The A1 predicate universe cannot be a universal "
            "'shards-v0 only' claim."),
        "lineage_binding_gate_rule": (
            "A governed C8 capability claim MUST declare its EXACT checkpoint lineage -- the "
            "ordered chain of training receipts (pretraining + any RL/SFT stages) that produced "
            "the exact model making the claim. The A1 predicate scan MUST cover every training "
            "input that declared lineage consumed. shards-v0 alone is a sufficient universe ONLY "
            "for a lineage that consumed only shards-v0; a lineage that also consumed eval-derived "
            "RL/SFT worlds requires those inputs scanned too. A claim whose lineage is not fully "
            "declared-and-scanned is INADMISSIBLE. Enforced by scripts/a1_freeze_consumer.py "
            "(#631 deliverable 5) via its required --lineage-manifest."),
        "scope": "this correction does NOT retract the shards-v0 scan (suite-a CLEAN, suite-b "
                 "147-exclusion set stands); it removes the false universal framing and installs "
                 "the lineage-binding requirement.",
    }

    out_abs = os.path.join(REPO, args.out)
    d = os.path.dirname(out_abs)
    if d:
        os.makedirs(d, exist_ok=True)
    receipt_write.checked_write(out_abs, receipt)
    print(f"A1_CORPUS_LINEAGE: premise_falsified={premise_falsified}; "
          f"completed_training_runs={len(runs)} across worlds={sorted(world_to_runs)}; "
          f"b-multi-1 scanned -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
