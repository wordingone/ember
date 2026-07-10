#!/usr/bin/env python3
"""receipt_errata_scan.py -- mechanical generator for docs/receipt-errata.jsonl
(gh issue #612, FROZEN SPEC).

C-INV is RED after the #608 hardening: post-genesis receipts that lack a
correct invariant_sha256 stamp are genuine violations, and retro-stamping
landed receipt bytes is banned (refs #482, append-only). Issue #612 specifies
an append-only errata annex instead: this scanner enumerates every historical
(pre-hardening-cutoff) unstamped/mismatched post-genesis receipt using THE
SAME scan logic test_c_invariant.check_stamped_receipts runs, and emits one
JSONL row per receipt -- no hand-typed paths, no hand-typed counts.

Hard cutoff (issue #612 point 3): errata coverage is CLOSED to receipts
created after the #608 hardening merge, 2026-07-10T00:08:35Z (sha 411d35e5).
A post-genesis violation whose own `ts` is AFTER the cutoff is NOT emitted as
an errata row here -- it stays a genuine, uncovered violation that
test_c_invariant.py's amended check_stamped_receipts must still RED on.

Row schema (issue #612 point 1, verbatim):
  {"receipt_path", "defect": "missing-invariant-stamp" | "stamp-mismatch",
   "discovered_ts", "discovery_source": "refs #608 hardening scan",
   "disposition": "historical-pre-hardening", "note"}

discovered_ts is pinned to the #608 hardening merge timestamp itself (the
scan that surfaced these violations ran as part of that hardening pass) --
every row shares the same discovered_ts, which by construction predates or
equals the cutoff that governs coverage eligibility.

Run: python receipt_errata_scan.py [--out docs/receipt-errata.jsonl]
Deterministic: sorted receipts/ walk, fixed field order, no wall-clock read
anywhere in classification (discovered_ts is the frozen hardening constant,
not datetime.now()).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import test_c_invariant as c_inv  # noqa: E402  (reuse root/constants/scan logic)

ROOT = c_inv.ROOT
RECEIPTS = c_inv.RECEIPTS
INVARIANT_SHA256 = c_inv.INVARIANT_SHA256
GENESIS_TS = c_inv.GENESIS_TS

# Issue #612 point 3, frozen constant: the #608 hardening merge commit's own
# committer-date timestamp (sha 411d35e5, "fix: probe-harden C-GROW/C-INV
# vocabulary gaps + totality ts self-stamp (#608)"). Duplicated here (not
# imported) so this generator -- like the probe it feeds -- stays
# self-contained; test_c_invariant.py carries the same literal constant for
# its own cutoff enforcement.
HARDENING_CUTOFF_TS = "2026-07-10T00:08:35Z"

DISCOVERY_SOURCE = "refs #608 hardening scan"
DISPOSITION = "historical-pre-hardening"


def scan_violations():
    """Re-run test_c_invariant's exact post-genesis stamp scan, returning
    every violation (missing or mismatched stamp) as
    (rel_path, defect, receipt_ts, receipt_epoch)."""
    genesis_epoch = c_inv._parse_receipt_ts(GENESIS_TS)
    violations = []
    for path in sorted(RECEIPTS.rglob("*.json")):
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as fh:
                d = json.load(fh)
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        ts = d.get("ts")
        receipt_epoch = c_inv._parse_receipt_ts(ts)
        if receipt_epoch is None or receipt_epoch < genesis_epoch:
            continue
        stamp_val = d.get("invariant_sha256")
        if stamp_val == INVARIANT_SHA256:
            continue  # correctly stamped -- not a violation
        defect = "missing-invariant-stamp" if stamp_val is None else "stamp-mismatch"
        violations.append((path.relative_to(ROOT).as_posix(), defect, ts, receipt_epoch))
    return violations


def build_rows(violations, cutoff_epoch):
    """Partition scanned violations by the hard cutoff. Only pre-cutoff
    (historical) violations become errata rows; post-cutoff violations are
    returned separately as genuine, uncovered failures."""
    errata_rows = []
    post_cutoff_uncovered = []
    for rel_path, defect, ts, receipt_epoch in violations:
        if receipt_epoch > cutoff_epoch:
            post_cutoff_uncovered.append((rel_path, defect, ts))
            continue
        errata_rows.append({
            "receipt_path": rel_path,
            "defect": defect,
            "discovered_ts": HARDENING_CUTOFF_TS,
            "discovery_source": DISCOVERY_SOURCE,
            "disposition": DISPOSITION,
            "note": (
                f"pre-hardening receipt (ts={ts!r}) predates the #608 stamp-"
                "enforcement merge (sha 411d35e5, 2026-07-10T00:08:35Z); "
                "invariant_sha256 stamping was not yet required when this "
                "receipt was written. Not retro-stamped or retro-edited "
                "(refs #482, receipts are append-only) -- this row is the "
                "disclosed historical annex covering it instead."
            ),
        })
    return errata_rows, post_cutoff_uncovered


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "docs" / "receipt-errata.jsonl"))
    args = ap.parse_args()

    cutoff_epoch = c_inv._parse_receipt_ts(HARDENING_CUTOFF_TS)
    violations = scan_violations()
    errata_rows, post_cutoff_uncovered = build_rows(violations, cutoff_epoch)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for row in errata_rows:
            fh.write(json.dumps(row, sort_keys=True))
            fh.write("\n")

    print(f"scanned {len(violations)} total violations under receipts/")
    print(f"errata rows written (pre-cutoff, historical): {len(errata_rows)} -> {out_path}")
    print(f"post-cutoff uncovered (genuine, must be stamped): {len(post_cutoff_uncovered)}")
    for rel_path, defect, ts in post_cutoff_uncovered:
        print(f"  UNCOVERED post-cutoff: {rel_path} (defect={defect}, ts={ts!r})")


if __name__ == "__main__":
    main()
