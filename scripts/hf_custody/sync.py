#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""sync.py — receipted Hugging Face custody sync (issue #1308, Workstream A).

Reads an HF-custody inventory JSONL (one JSON object per line, as produced by
the Workstream A census — the operator-side census artifact this schema was
built against) and mirrors ONLY the rows whose
`disposition` is `UPLOAD_ALLOWED` to a Hugging Face Hub dataset repo.

HARD INVARIANTS (encoded here, not just documented):

  * Local files are authoritative and are NEVER modified by this tool.
    Nothing here writes, deletes, or renames a byte under an inventory row's
    `local_canonical_path`.
  * Mirror-only. This tool never downloads over local data and never
    deletes local data — there is no code path that pulls hub content back
    onto disk or removes a local path.
  * Rows with any disposition other than UPLOAD_ALLOWED (REQUIRES_OPERATOR_
    REVIEW, LOCAL_ONLY, EXCLUDED) are always SKIPPED, never uploaded, and
    each skip is recorded with its reason — this is how withheld items are
    preserved rather than silently dropped from the record.
  * Before any row is uploaded, its local per-file sha256 manifest is
    recomputed and compared against the row's own declared manifest hash
    (`content_hash`, when `hash_method` is `sha256_filelist_manifest` and
    `hash_status` is `complete`). A mismatch refuses that row's upload.
  * The whole run refuses to start (raises, uploads nothing) if any eligible
    (UPLOAD_ALLOWED) row is missing the sha/manifest fields needed to verify
    it (`content_hash`, `hash_method`, `hash_status`) — an inventory that
    cannot be verified is not a basis for any upload, eligible or not.
  * --dry-run is the default. A real upload requires --execute AND
    --dry-run is not passed (see build_arg_parser). In dry-run, zero
    huggingface_hub network calls are made.

Deletion of a mirrored HF path is never automated by this tool or any tool
in this package — see docs/hf-custody/SYNC.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi

HERE = Path(__file__).resolve().parent
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
SUPPORTED_HASH_METHOD = "sha256_filelist_manifest"
REQUIRED_ELIGIBLE_FIELDS = ("content_hash", "hash_method", "hash_status")


class InventoryRefusal(ValueError):
    """Raised when the whole run must refuse to start (fail-closed)."""


@dataclass
class SyncOutcome:
    """One row's outcome — either an upload receipt or a recorded skip."""

    row_id: int
    local_canonical_path: str
    disposition: str
    status: str  # "uploaded" | "dry_run" | "skipped" | "refused"
    reason: str | None = None
    files_count: int | None = None
    bytes: int | None = None
    manifest_sha256: str | None = None
    hf_repo: str | None = None
    hf_revision: str | None = None
    commit_message: str | None = None
    path_in_repo: str | None = None

    def to_receipt_dict(self, ts: str) -> dict[str, Any]:
        return {
            "ts": ts,
            "inventory_row_id": self.row_id,
            "local_path": self.local_canonical_path,
            "disposition": self.disposition,
            "status": self.status,
            "reason": self.reason,
            "files_count": self.files_count,
            "bytes": self.bytes,
            "manifest_sha256": self.manifest_sha256,
            "hf_repo": self.hf_repo,
            "hf_revision": self.hf_revision,
            "commit_message": self.commit_message,
            "path_in_repo": self.path_in_repo,
            "sha_convention": SHA_CONVENTION,
        }


def load_inventory(path: str | Path) -> list[tuple[int, dict[str, Any]]]:
    """Parse a JSONL inventory file. Returns [(1-based row_id, row_dict), ...].

    row_id is the 1-based line number — the same numbering the Workstream A
    census docs (inventory-summary.md) use when they say "row 7", "row 17",
    etc., so receipts stay cross-referenceable with that document.
    """
    rows: list[tuple[int, dict[str, Any]]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            rows.append((line_no, json.loads(line)))
    return rows


def select_eligible_rows(
    rows: list[tuple[int, dict[str, Any]]],
) -> tuple[list[tuple[int, dict[str, Any]]], list[SyncOutcome]]:
    """Split rows into (eligible UPLOAD_ALLOWED rows, skip outcomes for the rest)."""
    eligible: list[tuple[int, dict[str, Any]]] = []
    skips: list[SyncOutcome] = []
    for row_id, row in rows:
        disposition = row.get("disposition")
        if disposition == "UPLOAD_ALLOWED":
            eligible.append((row_id, row))
        else:
            skips.append(
                SyncOutcome(
                    row_id=row_id,
                    local_canonical_path=row.get("local_canonical_path", ""),
                    disposition=disposition or "UNKNOWN",
                    status="skipped",
                    reason=(
                        f"disposition={disposition!r} is not UPLOAD_ALLOWED "
                        f"({row.get('disposition_reason', 'no reason on row')})"
                    ),
                )
            )
    return eligible, skips


def validate_eligible_rows_verifiable(eligible: list[tuple[int, dict[str, Any]]]) -> None:
    """FAIL-CLOSED: refuse the whole run if any eligible row cannot be verified.

    An UPLOAD_ALLOWED row that is missing content_hash / hash_method /
    hash_status, or that declares a hash_method / hash_status this tool does
    not know how to verify against a live local per-file manifest, means the
    inventory cannot back up its own eligibility claim for that row. Rather
    than upload it unverified (or silently drop it), the whole run refuses
    to start — same posture as manifest_sha.py's fail-closed bin-dir guard.
    """
    problems: list[str] = []
    for row_id, row in eligible:
        missing = [k for k in REQUIRED_ELIGIBLE_FIELDS if not row.get(k)]
        if missing:
            problems.append(f"row {row_id}: missing field(s) {missing}")
            continue
        if row["hash_method"] != SUPPORTED_HASH_METHOD:
            problems.append(
                f"row {row_id}: hash_method={row['hash_method']!r} is not "
                f"verifiable by this tool (only {SUPPORTED_HASH_METHOD!r} "
                f"is supported for UPLOAD_ALLOWED rows)"
            )
        elif row["hash_status"] != "complete":
            problems.append(
                f"row {row_id}: hash_status={row['hash_status']!r} "
                f"(must be 'complete' for an UPLOAD_ALLOWED row to be "
                f"verified before upload)"
            )
    if problems:
        raise InventoryRefusal(
            "REFUSING TO RUN: " + str(len(problems)) + " eligible row(s) "
            "cannot be verified against the inventory:\n  "
            + "\n  ".join(problems)
        )


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_filelist_manifest(root: Path) -> dict[str, Any]:
    """Recompute a sha256_filelist_manifest-style manifest for `root`.

    Mirrors manifest_sha.py's convention: sort files by POSIX-style relative
    path, hash each file's bytes as-is, then combine into a single
    combined_sha256 over sorted "<relpath>\\t<sha256>\\t<size_bytes>\\n" lines.
    This is the same algorithm the census used to produce each UPLOAD_ALLOWED
    row's content_hash, so a live recompute is directly comparable to it.
    """
    files = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        files.append(
            {
                "name": rel,
                "sha256": _sha256_file(p),
                "size_bytes": p.stat().st_size,
            }
        )
    files.sort(key=lambda r: r["name"])
    combined = hashlib.sha256()
    for rec in files:
        combined.update(f"{rec['name']}\t{rec['sha256']}\t{rec['size_bytes']}\n".encode("utf-8"))
    return {
        "root": str(root),
        "files": files,
        "combined_sha256": combined.hexdigest(),
        "sha_convention": SHA_CONVENTION,
    }


def verify_local_manifest(row: dict[str, Any]) -> tuple[bool, dict[str, Any], str | None]:
    """Recompute the local manifest and compare it to row['content_hash'].

    Returns (ok, computed_manifest, reason_if_not_ok).
    Precondition: caller already ran validate_eligible_rows_verifiable, so
    hash_method/hash_status/content_hash are known present and supported.
    """
    root = Path(row["local_canonical_path"])
    if not root.is_dir():
        return False, {}, f"local_canonical_path does not exist or is not a directory: {root}"
    computed = compute_filelist_manifest(root)
    if computed["combined_sha256"] != row["content_hash"]:
        return (
            False,
            computed,
            "sha256_mismatch: local manifest "
            f"{computed['combined_sha256']} != inventory content_hash {row['content_hash']}",
        )
    return True, computed, None


def build_commit_message(row_id: int, row: dict[str, Any], manifest_sha256: str) -> str:
    return (
        f"hf-custody-sync: inventory row {row_id} "
        f"({row.get('source_identity', row.get('local_canonical_path', '?'))}) "
        f"manifest_sha256={manifest_sha256}"
    )


def sync_row(
    api: "HfApi | None",
    row_id: int,
    row: dict[str, Any],
    repo_id: str,
    execute: bool,
) -> SyncOutcome:
    """Verify then (maybe) upload a single eligible row. Never touches local bytes."""
    ok, computed, reason = verify_local_manifest(row)
    files_count = len(computed.get("files", [])) or None
    bytes_total = sum(f["size_bytes"] for f in computed.get("files", [])) or None
    if not ok:
        return SyncOutcome(
            row_id=row_id,
            local_canonical_path=row.get("local_canonical_path", ""),
            disposition=row.get("disposition", "UPLOAD_ALLOWED"),
            status="refused",
            reason=reason,
            files_count=files_count,
            bytes=bytes_total,
            manifest_sha256=computed.get("combined_sha256"),
        )

    manifest_sha256 = computed["combined_sha256"]
    commit_message = build_commit_message(row_id, row, manifest_sha256)
    path_in_repo = Path(row["local_canonical_path"]).name

    if not execute:
        return SyncOutcome(
            row_id=row_id,
            local_canonical_path=row["local_canonical_path"],
            disposition=row.get("disposition", "UPLOAD_ALLOWED"),
            status="dry_run",
            reason="--dry-run (default); no upload attempted",
            files_count=files_count,
            bytes=bytes_total,
            manifest_sha256=manifest_sha256,
            hf_repo=repo_id,
            hf_revision=None,
            commit_message=commit_message,
            path_in_repo=path_in_repo,
        )

    assert api is not None
    commit_info = api.upload_folder(
        repo_id=repo_id,
        repo_type="dataset",
        folder_path=row["local_canonical_path"],
        path_in_repo=path_in_repo,
        commit_message=commit_message,
    )
    hf_revision = getattr(commit_info, "oid", None) or getattr(commit_info, "commit_url", None)

    return SyncOutcome(
        row_id=row_id,
        local_canonical_path=row["local_canonical_path"],
        disposition=row.get("disposition", "UPLOAD_ALLOWED"),
        status="uploaded",
        reason=None,
        files_count=files_count,
        bytes=bytes_total,
        manifest_sha256=manifest_sha256,
        hf_repo=repo_id,
        hf_revision=hf_revision,
        commit_message=commit_message,
        path_in_repo=path_in_repo,
    )


def sync(
    inventory_path: str | Path,
    repo_id: str,
    execute: bool = False,
) -> list[SyncOutcome]:
    """Top-level orchestration. Fail-closed: raises InventoryRefusal before
    any upload if the inventory can't back up its UPLOAD_ALLOWED claims."""
    rows = load_inventory(inventory_path)
    eligible, skip_outcomes = select_eligible_rows(rows)
    validate_eligible_rows_verifiable(eligible)  # raises -> nothing uploaded

    api = HfApi() if execute else None
    outcomes: list[SyncOutcome] = list(skip_outcomes)
    for row_id, row in eligible:
        outcomes.append(sync_row(api, row_id, row, repo_id, execute))
    outcomes.sort(key=lambda o: o.row_id)
    return outcomes


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="hf-custody-sync (issue #1308)")
    ap.add_argument("--inventory", required=True, help="path to inventory JSONL")
    ap.add_argument("--repo-id", required=True, help="HF dataset repo id, e.g. wordingone/ember-custody")
    ap.add_argument(
        "--execute",
        action="store_true",
        help="perform real uploads (default is dry-run; this flag is required for any network call)",
    )
    ap.add_argument("--dry-run", action="store_true", help="explicit dry-run (this is also the default)")
    ap.add_argument("--receipts-path", default=None, help="append receipts JSONL here (default: stdout only)")
    return ap


def main(argv: list[str] | None = None) -> int:
    from . import receipts as receipts_mod  # local import: keep CLI-only dependency out of library import path

    args = build_arg_parser().parse_args(argv)
    execute = args.execute and not args.dry_run
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        outcomes = sync(args.inventory, args.repo_id, execute=execute)
    except InventoryRefusal as exc:
        print(f"[hf-custody-sync] {exc}", file=sys.stderr)
        return 1

    for outcome in outcomes:
        receipt = outcome.to_receipt_dict(ts)
        print(json.dumps(receipt), flush=True)
        if args.receipts_path:
            receipts_mod.append_receipt(args.receipts_path, receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
