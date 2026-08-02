#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""pin.py — emit the fully-pinned hf:// reference for an hf-custody-sync receipt.

INVARIANT: training (or any other downstream consumer) is ONLY EVER allowed
to reference hf-custody-synced data via a fully pinned
``hf://datasets/<repo_id>@<revision>`` prefix. An unpinned/mutable prefix
(``hf://datasets/<repo_id>`` with no ``@<revision>``) is never an acceptable
reference to hand a consumer, because the mutable form can change under a
reader between two reads of the same nominal path — the whole point of the
sync receipt's hf_revision field is to kill that ambiguity at the source.

CLI:
    python pin.py --receipts path/to/receipts.jsonl [--row N]
        Print one pinned prefix per uploaded row (status == "uploaded"),
        optionally filtered to a single inventory_row_id.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


def pinned_prefix(receipt: dict[str, Any]) -> str:
    """Given one sync receipt row, return its fully-pinned hf:// prefix.

    Raises ValueError if the receipt has no hf_revision — this includes
    dry-run and skipped/refused receipts, none of which are ever pinnable:
    only a completed "uploaded" receipt carries a real revision sha.
    """
    repo = receipt.get("hf_repo")
    revision = receipt.get("hf_revision")
    if not repo:
        raise ValueError("pin.py: receipt has no hf_repo — nothing to pin")
    if not revision:
        raise ValueError(
            "pin.py: receipt has no hf_revision (status="
            f"{receipt.get('status')!r}) — only a completed 'uploaded' "
            "receipt is ever pinnable; dry-run/skip/refused receipts are not"
        )
    return f"hf://datasets/{repo}@{revision}"


def main(argv: list[str] | None = None) -> int:
    from . import receipts as receipts_mod

    ap = argparse.ArgumentParser(description="emit pinned hf:// prefixes from an hf-custody-sync receipts file")
    ap.add_argument("--receipts", required=True, help="path to the receipts JSONL")
    ap.add_argument("--row", type=int, default=None, help="filter to a single inventory_row_id")
    args = ap.parse_args(argv)

    rows = receipts_mod.read_receipts(Path(args.receipts))
    printed = 0
    for row in rows:
        if row.get("status") != "uploaded":
            continue
        if args.row is not None and row.get("inventory_row_id") != args.row:
            continue
        print(pinned_prefix(row))
        printed += 1
    if printed == 0:
        print("[pin] no uploaded receipts matched", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
