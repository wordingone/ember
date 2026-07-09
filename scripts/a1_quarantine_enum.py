#!/usr/bin/env python3
"""a1_quarantine_enum.py -- ember issue #593 deliverable 2: pre-freeze
quarantine enumeration.

Enumerates EVERY existing receipt citing suite-(a)/(b) and classifies each
`pre_freeze: true` (development-only, quarantined from claims). Machine-
readable, serializer-emitted (receipt_write.checked_write), one row per
receipt: path-relative id, ts, why-quarantined.

Enumeration source (named, mechanical, reproducible):
  - the git-TRACKED files under receipts/ at the PR base
    (`git ls-files receipts/`), i.e. every receipt in the repository's
    published evidence tree;
  - markers searched (derived from the pin receipts, never hardcoded):
      (i)  suite (a): the w2-heldout decontam receipt's batch_sha256;
      (ii) suite (b): each pinned dataset's test_split_sha256 from
           receipts/eval-suite-freeze/eval-suite-freeze-v1.json;
      (iii) the literal strings "eval-suite-v1" / "eval_suite_v1"
           (suite-(b)-citing receipts that reference the suite by name
           rather than by hash).
  - a file cites a suite iff its raw text contains any marker.

Classification rule (mechanical, disclosed):
  - `cites_scores`: the receipt text contains an eval-score field name
    ("eval_loss", "final_eval_loss", "target_eval_loss", '"score"') --
    receipts that carry NUMBERS against a suite;
  - `pin_or_infrastructure`: marker present but no score field -- pin
    receipts, decontam receipts, sha cross-references.
  Both classes are quarantined (`pre_freeze: true`): NO pre-freeze receipt
  may be cited by a capability claim, score-carrying or not; the class
  label only explains WHY each is in the list.

Usage:
  python scripts/a1_quarantine_enum.py \\
      --heldout-receipt receipts/ember-c-scale/w2-heldout-decontam-20260708T121128Z.json \\
      --freeze-receipt receipts/eval-suite-freeze/eval-suite-freeze-v1.json \\
      --out receipts/eval-suite-freeze/a1-prefreeze-quarantine-<UTCts>.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import receipt_write  # noqa: E402

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"

# '"eval_loss' (no closing quote) deliberately matches every suffixed variant
# too: eval_loss_bf16 / eval_loss_fp32 / eval_loss_pre_checkpoint / ... --
# the fp32-reeval receipts carry scores ONLY under suffixed names.
SCORE_FIELD_MARKERS = ['"eval_loss', '"final_eval_loss"', '"target_eval_loss"', '"score"']
NAME_MARKERS = ["eval-suite-v1", "eval_suite_v1"]


def git_tracked_receipts(repo: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", repo, "ls-files", "receipts/"],
        capture_output=True, text=True, check=True)
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--heldout-receipt", required=True)
    ap.add_argument("--freeze-receipt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--freeze-ts", default=None,
                     help="the A1 declaration freeze_ts (ISO); rows are pre_freeze "
                          "iff their citation predates the declaration -- every "
                          "enumerated row is, since the declaration lands in this PR")
    args = ap.parse_args()

    heldout = json.load(open(os.path.join(REPO, args.heldout_receipt), encoding="utf-8"))
    freeze = json.load(open(os.path.join(REPO, args.freeze_receipt), encoding="utf-8"))

    suite_a_sha = heldout["batch_sha256"]
    suite_b_shas = {ds["name"]: ds["test_split_sha256"]
                    for ds in freeze["datasets"]
                    if ds.get("test_split_sha256") and ds["test_split_sha256"] != "PIN-PENDING"}

    hash_markers = {"suite_a_batch_sha256": suite_a_sha}
    for name, sha in suite_b_shas.items():
        hash_markers[f"suite_b:{name}"] = sha

    tracked = git_tracked_receipts(REPO)
    self_rel = os.path.relpath(os.path.join(REPO, args.out), REPO).replace(os.sep, "/")

    rows = []
    n_unreadable = 0
    for rel in tracked:
        if rel == self_rel:
            continue
        p = os.path.join(REPO, rel)
        try:
            text = open(p, "r", encoding="utf-8", errors="replace").read()
        except OSError:
            n_unreadable += 1
            continue

        found = [label for label, sha in hash_markers.items() if sha in text]
        found += [f"name:{m}" for m in NAME_MARKERS if m in text]
        if not found:
            continue

        try:
            ts = json.loads(text).get("ts")
        except (json.JSONDecodeError, AttributeError):
            ts = None

        cites_scores = any(m in text for m in SCORE_FIELD_MARKERS)
        rows.append({
            "id": rel.replace(os.sep, "/"),
            "ts": ts,
            "pre_freeze": True,
            "cites_scores": cites_scores,
            "class": "score-carrying" if cites_scores else "pin_or_infrastructure",
            "markers_found": found,
            "why_quarantined": (
                "cites suite-(a)/(b) content and predates the A1 freeze "
                "declaration (this PR): development-only, quarantined from "
                "capability claims" if cites_scores else
                "references suite-(a)/(b) pins pre-declaration: infrastructure/"
                "pin receipt, quarantined from capability claims (carries no "
                "eval-score fields)"),
        })

    receipt = {
        "ticket": "A1-PREFREEZE-QUARANTINE",
        "ts": datetime.now(timezone.utc).isoformat(),
        "schema": "a1-prefreeze-quarantine/v1",
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "issue_refs": ["#593", "#123", "#591"],
        "enumeration_source": {
            "file_set": "git ls-files receipts/ (every tracked receipt at the PR base)",
            "n_files_enumerated": len(tracked),
            "n_files_unreadable": n_unreadable,
            "hash_markers": hash_markers,
            "name_markers": NAME_MARKERS,
            "score_field_markers": SCORE_FIELD_MARKERS,
            "rule": "a receipt cites a suite iff its raw text contains any marker; "
                    "every citing receipt is pre_freeze (the declaration lands in "
                    "this PR, after all of them)",
        },
        "freeze_ts_ref": args.freeze_ts,
        "n_quarantined": len(rows),
        "n_score_carrying": sum(1 for r in rows if r["cites_scores"]),
        "n_pin_or_infrastructure": sum(1 for r in rows if not r["cites_scores"]),
        "rows": rows,
    }

    out_abs = os.path.join(REPO, args.out)
    d = os.path.dirname(out_abs)
    if d:
        os.makedirs(d, exist_ok=True)
    receipt_write.checked_write(out_abs, receipt)
    print(f"A1_QUARANTINE: {len(rows)} receipts quarantined "
          f"({receipt['n_score_carrying']} score-carrying, "
          f"{receipt['n_pin_or_infrastructure']} pin/infrastructure) "
          f"from {len(tracked)} enumerated -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
