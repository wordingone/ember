#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""regen_bloated_manifest.py -- one-time migration for the three lean_fetch.py
receipts (G-train-2, A-train-1, G-heldout-1) landed before commit 4075d25
("fix(corpus): stop lean_fetch.py's O(n^2) manifest.jsonl growth (#1753)").

Those receipts' manifest.jsonl rows each embed the full per-file breakdown
inline via human_provenance_basis (one copy per row, O(n^2) total size --
confirmed ~14.4GB for G-train-2's 9067-file manifest.jsonl vs ~116MB of
actual content). The fix moved that breakdown to a sibling
dest_root/_manifests/*.files.json, written once, with manifest.jsonl rows
referencing it via a short bounded notes string instead.

No re-fetch is needed or performed: dest_root/_manifests/*.json (the
receipt written by write_receipt(), NOT the *.files.json sibling the fix
introduces) already carries every file's path/sha256/declared_size_bytes
inline in its own (single-copy, not row-duplicated) notes field -- that is
ground truth. This script:

  1. Loads that single existing receipt JSON.
  2. Parses its old-shape notes to recover full_tree_file_count,
     partition_count, partition_index, partition_selected_count,
     budget_bytes, and the per-file list.
  3. Writes the sibling *.files.json the fixed fetch() would have written,
     via lean_fetch._write_file_manifest -- the actual fix code, not a
     reimplementation.
  4. Builds the same bounded notes string fetch() now builds, reusing the
     literal template in lean_fetch.fetch (kept as one constant here so any
     future change to that template has exactly one place to also update).
  5. Rebuilds a Receipt with every field unchanged except notes, and calls
     receipt.to_manifest_row() -- the actual fix code -- to produce new
     manifest.jsonl rows.
  6. Verifies the new rows are a rows-for-rows match against the old ones
     on every field except human_provenance_basis (same count, same
     sha256/bytes/license/fetched_ts/selection_rule/source_url multiset)
     before touching anything on disk.
  7. Renames the old manifest.jsonl to manifest.jsonl.bloated-pre-1753.bak
     (same filesystem, instant rename, zero extra disk) and writes the new
     rows to a fresh manifest.jsonl.

Usage:
    python regen_bloated_manifest.py DEST_ROOT [--dry-run]

DEST_ROOT is the corpus directory to regenerate (one of the domain slot
directories under the local corpus data root, e.g. its G-heldout-1 or
A-train-1 subdirectory).
--dry-run performs steps 1-6 and reports the verification result without
writing anything.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

# Direct execution appends the repository root so the package import resolves
# without publishing connector-local bare names or shadowing earlier imports.
_REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

import lean_fetch  # noqa: E402
from tools.corpus_connectors import receipt as rcpt  # noqa: E402

# Literal copy of the bounded-notes template lean_fetch.fetch() builds after
# commit 4075d25. Kept as one constant so this migration and any future
# reader can see at a glance it matches the fix, not a paraphrase of it.
NOTES_TEMPLATE = (
    "disjoint-partition GitHub tree fetch; {full_tree_file_count} files in full tree; "
    "partition {partition_index}/{partition_count} selected "
    "{partition_selected_count} files; {fetched_count} fetched; "
    "budget_bytes={budget_bytes}; "
    "file_manifest={file_manifest_relpath}"
)

_CANONICAL_URL_RE = re.compile(r"^https://github\.com/(?P<repo_id>.+)/tree/(?P<sha>[0-9a-f]+)$")


def _find_receipt_json(dest_root: Path) -> Path:
    manifests_dir = dest_root / "_manifests"
    candidates = sorted(p for p in manifests_dir.glob("*.json") if not p.name.endswith(".files.json"))
    if not candidates:
        raise SystemExit(f"no receipt *.json (non-.files.json) found under {manifests_dir}")
    if len(candidates) > 1:
        raise SystemExit(
            f"expected exactly one receipt json under {manifests_dir}, found {len(candidates)}: "
            f"{[p.name for p in candidates]} -- refusing to guess which is authoritative"
        )
    return candidates[0]


def _load_old_notes(notes_str: str) -> dict:
    try:
        return json.loads(notes_str)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"receipt notes is not the expected old-shape JSON blob: {exc}") from exc


def _repo_id_and_sha_from_canonical_url(canonical_url: str) -> tuple[str, str]:
    m = _CANONICAL_URL_RE.match(canonical_url)
    if not m:
        raise SystemExit(f"canonical_url does not match expected github tree URL shape: {canonical_url!r}")
    return m.group("repo_id"), m.group("sha")


def _old_manifest_rows(dest_root: Path) -> list[dict]:
    manifest_path = dest_root / "manifest.jsonl"
    rows = []
    with manifest_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _row_identity(row: dict) -> tuple:
    """Everything a manifest.jsonl row carries except the bloated/bounded
    notes field -- this is what must be byte-identical between old and new
    rows for the migration to be lossless."""
    return (row["source_url"], row["sha256"], row["bytes"], row["license"], row["fetched_ts"], row["selection_rule"])


def regenerate(dest_root: Path, dry_run: bool) -> None:
    receipt_json_path = _find_receipt_json(dest_root)
    print(f"[{dest_root.name}] receipt: {receipt_json_path}")

    with receipt_json_path.open("r", encoding="utf-8") as fh:
        old_receipt_dict = json.load(fh)

    old_notes = _load_old_notes(old_receipt_dict["notes"])
    fetched_notes = old_notes["files"]  # [{"path", "sha256", "declared_size_bytes"}, ...]
    full_tree_file_count = old_notes["full_tree_file_count"]
    partition_count = old_notes["partition_count"]
    partition_index = old_notes["partition_index"]
    partition_selected_count = old_notes["partition_selected_count"]
    budget_bytes = old_notes["budget_bytes"]
    files_fetched_old = old_notes["files_fetched"]

    top_level_files = old_receipt_dict["files"]  # [{"path", "bytes", "sha256"}, ...] -- FileEntry shape
    if len(top_level_files) != len(fetched_notes):
        raise SystemExit(
            f"[{dest_root.name}] top-level files ({len(top_level_files)}) != "
            f"notes.files ({len(fetched_notes)}) -- refusing, data mismatch inside the receipt itself"
        )
    if files_fetched_old != len(fetched_notes):
        raise SystemExit(
            f"[{dest_root.name}] notes.files_fetched ({files_fetched_old}) != len(notes.files) "
            f"({len(fetched_notes)}) -- refusing"
        )

    repo_id, sha = _repo_id_and_sha_from_canonical_url(old_receipt_dict["canonical_url"])
    expected_source_id = f"{repo_id}@{sha}#partition-{partition_index}-of-{partition_count}"
    if old_receipt_dict["source_id"] != expected_source_id:
        raise SystemExit(
            f"[{dest_root.name}] reconstructed source_id {expected_source_id!r} != "
            f"receipt's real source_id {old_receipt_dict['source_id']!r} -- refusing"
        )

    key = f"{rcpt.safe_key(repo_id)}-p{partition_index}-of-{partition_count}"

    old_rows = _old_manifest_rows(dest_root)
    if len(old_rows) != len(fetched_notes):
        raise SystemExit(
            f"[{dest_root.name}] old manifest.jsonl row count ({len(old_rows)}) != "
            f"receipt files_fetched ({len(fetched_notes)}) -- refusing"
        )

    print(
        f"[{dest_root.name}] repo_id={repo_id} sha={sha[:12]} partition={partition_index}/{partition_count} "
        f"files_fetched={files_fetched_old} old_rows={len(old_rows)}"
    )

    if dry_run:
        print(f"[{dest_root.name}] DRY RUN -- would write sibling .files.json + rewrite manifest.jsonl")
        file_manifest_relpath = f"_manifests/<ts>-{key}.files.json"
    else:
        file_manifest_path = lean_fetch._write_file_manifest(
            dest_root,
            key,
            full_tree_file_count,
            partition_count,
            partition_index,
            partition_selected_count,
            budget_bytes,
            fetched_notes,
        )
        file_manifest_relpath = file_manifest_path.relative_to(dest_root).as_posix()
        print(f"[{dest_root.name}] wrote sibling file manifest: {file_manifest_path}")

    new_notes = NOTES_TEMPLATE.format(
        full_tree_file_count=full_tree_file_count,
        partition_index=partition_index,
        partition_count=partition_count,
        partition_selected_count=partition_selected_count,
        fetched_count=files_fetched_old,
        budget_bytes=budget_bytes,
        file_manifest_relpath=file_manifest_relpath,
    )
    print(f"[{dest_root.name}] new notes ({len(new_notes)} chars): {new_notes}")

    new_receipt = rcpt.Receipt(
        source=old_receipt_dict["source"],
        source_id=old_receipt_dict["source_id"],
        canonical_url=old_receipt_dict["canonical_url"],
        license=old_receipt_dict["license"],
        license_evidence=old_receipt_dict["license_evidence"],
        revision=old_receipt_dict["revision"],
        files=[rcpt.FileEntry(path=f["path"], bytes=f["bytes"], sha256=f["sha256"]) for f in top_level_files],
        fetched_at=old_receipt_dict["fetched_at"],
        connector=rcpt.ConnectorInfo(**old_receipt_dict["connector"]),
        dest_root=old_receipt_dict["dest_root"],
        notes=new_notes,
    )
    new_rows = rcpt.to_manifest_row(new_receipt)

    if len(new_rows) != len(old_rows):
        raise SystemExit(f"[{dest_root.name}] new row count {len(new_rows)} != old row count {len(old_rows)} -- refusing")

    old_identities = sorted(_row_identity(r) for r in old_rows)
    new_identities = sorted(_row_identity(r) for r in new_rows)
    if old_identities != new_identities:
        raise SystemExit(
            f"[{dest_root.name}] row identities (source_url/sha256/bytes/license/fetched_ts/selection_rule) "
            f"differ between old and new -- refusing, would lose or corrupt data"
        )
    print(f"[{dest_root.name}] verified: {len(new_rows)} rows, identical identity set to old manifest.jsonl")

    if dry_run:
        print(f"[{dest_root.name}] DRY RUN -- not writing manifest.jsonl or renaming anything")
        return

    manifest_path = dest_root / "manifest.jsonl"
    backup_path = dest_root / "manifest.jsonl.bloated-pre-1753.bak"
    if backup_path.exists():
        raise SystemExit(f"[{dest_root.name}] backup path already exists, refusing to overwrite: {backup_path}")

    tmp_path = dest_root / "manifest.jsonl.regen.tmp"
    with tmp_path.open("w", encoding="utf-8") as fh:
        for row in new_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")

    manifest_path.rename(backup_path)
    tmp_path.rename(manifest_path)
    old_size = backup_path.stat().st_size
    new_size = manifest_path.stat().st_size
    print(
        f"[{dest_root.name}] DONE: manifest.jsonl {old_size} -> {new_size} bytes "
        f"(backup at {backup_path.name}); {len(new_rows)} rows preserved"
    )


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dest_root", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    regenerate(args.dest_root.resolve(), args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
