#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""remint_hashes.py — one-time re-mint of an hf-custody inventory's
UPLOAD_ALLOWED content_hash values from a size-only census construction to
sync.py's content-based one (issue #1308, 2026-08-02).

BACKGROUND: a live --dry-run of src/ember/data/hf_custody/sync.py against the real
Workstream A inventory refused ALL 8 UPLOAD_ALLOWED rows with sha256_mismatch.
The census's "sha256_filelist_manifest" turned out to hash only relative
paths and file SIZES (sync.compute_sizeonly_manifest) — never file content.
That is a structural check, not an integrity check: two directories with the
same file names and sizes but different bytes would hash identically under
it, so it can't be trusted to catch a same-size tamper before publication.
sync.compute_filelist_manifest (content-based, hashes actual file bytes) is
the correct upload-integrity gate. This script re-mints each eligible row's
content_hash to the content-based value, ONLY after empirically confirming
row-by-row that the OLD value really was produced by the size-only
construction (i.e. that nothing on disk drifted since the census — a row
whose size-only recompute does NOT match its existing content_hash is left
completely untouched and reported, not guessed at).

What this script does to each UPLOAD_ALLOWED row, in order:
  1. Recompute compute_sizeonly_manifest(local_canonical_path).
  2. If that does NOT equal the row's current content_hash: STOP for this
     row. Leave every field on the row byte-for-byte unchanged. Record the
     mismatch in the remint receipt so a human looks at it — this means the
     row's disk contents (or the file-list itself) changed since the census
     ran, which is a fresh eligibility question, not something this script
     resolves.
  3. Otherwise: the census claim is confirmed for this row. Preserve the old
     value under a NEW field `content_hash_sizeonly_census` (never
     discarded — see the operator ruling this script implements: "census
     values preserved, not trusted for integrity"). Compute
     compute_filelist_manifest(local_canonical_path)["combined_sha256"] and
     write it as the new `content_hash`. Set `hash_method` to
     sync.SUPPORTED_HASH_METHOD (the content-based construction's name).
     Add a `hash_remint` note explaining what happened and when.

Non-eligible rows (anything whose disposition isn't UPLOAD_ALLOWED) are
never read or modified — this script only ever touches the fields listed
above, only on rows this repo's own eligibility gate would upload.

Default is a DRY PREVIEW: the inventory file on disk is not touched unless
--write is passed. A remint receipt JSON (one row per eligible row, every
outcome — reminted or left-untouched-on-mismatch) is always printed to
stdout, and written to disk when --receipt-path is given (or --write
implies a default receipt path next to the inventory file, timestamped).

CLI:
    python -m ember.data.hf_custody.remint_hashes --inventory PATH [--write]
                                                [--receipt-path PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import sync

REMINT_NOTE = (
    "2026-08-02: census hash was size-only (content-blind); re-minted "
    "content-based from disk; byte integrity anchored by ingestion-receipt "
    "per-file sha256 where available (rows 13, 17 verified)."
)


def remint_rows(
    rows: list[tuple[int, dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (updated_row_dicts_in_original_order, per-eligible-row results).

    Non-eligible rows pass through completely unchanged (same dict, same
    identity even). Eligible rows are reminted only if their size-only
    recompute confirms the census's claimed content_hash; otherwise the row
    passes through unchanged too, and the result records the mismatch.
    """
    updated: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    for row_id, row in rows:
        if row.get("disposition") != "UPLOAD_ALLOWED":
            updated.append(row)
            continue

        root = Path(row["local_canonical_path"])
        old_hash = row.get("content_hash")
        sizeonly = sync.compute_sizeonly_manifest(root)
        sizeonly_match = sizeonly == old_hash

        result: dict[str, Any] = {
            "row_id": row_id,
            "local_canonical_path": row["local_canonical_path"],
            "census_content_hash": old_hash,
            "sizeonly_recompute": sizeonly,
            "sizeonly_match": sizeonly_match,
        }

        if not sizeonly_match:
            result["action"] = "SKIPPED_NO_SIZEONLY_MATCH"
            result["note"] = (
                "size-only recompute does NOT match the existing "
                "content_hash — row left completely unchanged; disk may "
                "have drifted since the census, needs a fresh eligibility "
                "look before this row can be reminted"
            )
            results.append(result)
            updated.append(row)
            continue

        new_manifest = sync.compute_filelist_manifest(root)
        new_hash = new_manifest["combined_sha256"]

        new_row = dict(row)
        new_row["content_hash_sizeonly_census"] = old_hash
        new_row["content_hash"] = new_hash
        new_row["hash_method"] = sync.SUPPORTED_HASH_METHOD
        new_row["hash_remint"] = REMINT_NOTE

        result["action"] = "REMINTED"
        result["new_content_hash"] = new_hash
        result["new_hash_method"] = sync.SUPPORTED_HASH_METHOD
        results.append(result)
        updated.append(new_row)

    return updated, results


def write_inventory(path: Path, row_dicts: list[dict[str, Any]]) -> None:
    """Rewrite the JSONL file, one compact JSON object per line, LF only."""
    lines = [json.dumps(r, ensure_ascii=False) + "\n" for r in row_dicts]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)


def build_receipt(inventory_path: Path, results: list[dict[str, Any]], ts: str) -> dict[str, Any]:
    reminted = [r for r in results if r["action"] == "REMINTED"]
    skipped = [r for r in results if r["action"] == "SKIPPED_NO_SIZEONLY_MATCH"]
    return {
        "ts": ts,
        "ticket": "HF-CUSTODY-SYNC-1308-REMINT",
        "inventory_path": str(inventory_path),
        "sizeonly_construction": "sync.compute_sizeonly_manifest (census-reproducing, structure-only)",
        "content_construction": "sync.compute_filelist_manifest (content-based, the new authority)",
        "rows_processed": len(results),
        "rows_reminted": len(reminted),
        "rows_skipped_no_match": len(skipped),
        "results": results,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="remint hf-custody inventory content_hash values (issue #1308)")
    ap.add_argument("--inventory", required=True, help="path to the inventory JSONL to remint")
    ap.add_argument("--write", action="store_true", help="actually rewrite the inventory file (default: dry preview only)")
    ap.add_argument(
        "--receipt-path",
        default=None,
        help="where to write the remint receipt JSON (default: alongside the inventory, timestamped)",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    inventory_path = Path(args.inventory)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    rows = sync.load_inventory(inventory_path)
    updated, results = remint_rows(rows)

    receipt = build_receipt(inventory_path, results, ts)
    print(json.dumps(receipt, indent=2))

    receipt_path = Path(args.receipt_path) if args.receipt_path else (
        inventory_path.parent / f"remint-receipt-{ts}.json"
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with open(receipt_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
        f.write("\n")
    print(f"[remint] receipt written: {receipt_path}", file=sys.stderr)

    skipped = [r for r in results if r["action"] == "SKIPPED_NO_SIZEONLY_MATCH"]
    if skipped:
        print(
            f"[remint] {len(skipped)} row(s) left UN-REMINTED (size-only mismatch): "
            + ", ".join(str(r["row_id"]) for r in skipped),
            file=sys.stderr,
        )

    if not args.write:
        print("[remint] DRY PREVIEW ONLY — pass --write to rewrite the inventory file", file=sys.stderr)
        return 0

    write_inventory(inventory_path, updated)
    print(f"[remint] inventory rewritten: {inventory_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
