# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""receipts.py — append-only JSONL receipts for hf-custody-sync (issue #1308).

One JSON object per line, one line per sync outcome (upload, dry-run, skip,
or refusal). Append-only: this module never rewrites or truncates an
existing receipts file, and never deletes a row — including for rows that
were SKIPPED because their disposition withheld them (REQUIRES_OPERATOR_
REVIEW / LOCAL_ONLY / EXCLUDED). The skip rows ARE the withheld-items
preservation record; losing them would be indistinguishable from silently
dropping the item.

Receipt row shape (see sync.SyncOutcome.to_receipt_dict):
    {
      "ts": ISO8601-compact UTC timestamp shared by the whole sync run,
      "inventory_row_id": 1-based line number in the inventory JSONL,
      "local_path": row's local_canonical_path,
      "disposition": the row's disposition as read from the inventory,
      "status": "uploaded" | "dry_run" | "skipped" | "refused",
      "reason": human-readable reason (always set for skipped/refused/dry_run,
                None for a completed "uploaded" row),
      "files_count": int or null,
      "bytes": int or null,
      "manifest_sha256": recomputed local combined_sha256, or null,
      "hf_repo": target repo id, or null for a skip,
      "hf_revision": the created commit sha (the pin), null unless status
                     == "uploaded",
      "commit_message": the commit message used/would-be-used,
      "path_in_repo": destination path inside the dataset repo,
      "sha_convention": "bytes on disk as-is (binary read, no line-ending
                          normalization)",
    }
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def append_receipt(path: str | Path, record: dict[str, Any]) -> None:
    """Append one JSON line to `path`, creating parent dirs if needed.

    Uses a single write() of one already-newline-terminated line plus an
    fsync, so a receipt row is never observed partially written. This does
    NOT do the atomic-replace dance receipt_write.checked_write() does
    (that's for single-object canonical files); an append-only log's unit
    of atomicity is the line, not the whole file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=False) + "\n"
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def read_receipts(path: str | Path) -> list[dict[str, Any]]:
    """Read all receipt rows from an append-only JSONL file. Skips blank lines."""
    rows: list[dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        return rows
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
