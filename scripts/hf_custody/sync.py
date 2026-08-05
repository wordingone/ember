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
  * TWO-PHASE, WHOLE-RUN VERIFICATION (PR #1311 review, M1). Every eligible
    (UPLOAD_ALLOWED) row's local per-file sha256 manifest is recomputed and
    compared against the row's declared `content_hash` BEFORE the first
    `create_commit` call of the run. Verification is never interleaved with
    uploads: if ANY eligible row mismatches, is missing its directory,
    contains a refused symlink, or collides on `path_in_repo` with another
    row, the WHOLE RUN refuses (raises InventoryRefusal) and zero rows are
    uploaded — not just the offending row. See verify_all_eligible_rows().
  * Per-row receipts are emitted immediately as each outcome is produced
    (PR #1311 review, M2) via the optional `on_outcome` callback threaded
    through sync(). An exception raised mid-upload-loop (e.g. a network
    failure on row k+1) still leaves receipts for rows 1..k on disk before
    it propagates — no partial upload is ever left unreceipted.
  * A revision is only ever recorded as a real, resolvable commit sha (PR
    #1311 review, M3): `hf_revision` is ALWAYS either `None` or a 40-hex
    sha matching `receipts.REVISION_RE`. There is no commit_url fallback —
    a missing/invalid `oid` on the returned CommitInfo is a hard error for
    that row (caught, receipted as status="error", then re-raised).
  * --dry-run is the default. A real upload requires --execute AND
    --dry-run is not passed (see build_arg_parser). In dry-run, zero
    huggingface_hub network calls are made.
  * Upload fileset is a SUBSET of the verified fileset (PR #1311 review,
    M4b/m3): dotfiles, `.git*` paths, and the `.cache/huggingface` family
    huggingface_hub itself always excludes are excluded from the commit
    operations built for the row (`_build_commit_operations`) via
    `UPLOAD_IGNORE_PATTERNS` (issue #1313 rework: this now explicitly
    unions in `HF_UPLOAD_FOLDER_DEFAULT_IGNORE_PATTERNS`, matching what
    `upload_folder` always applied on top of any caller-supplied
    `ignore_patterns` — `create_commit` has no such implicit behavior, so
    the union must be supplied here), but verification still
    hashes them — the verification set stays census-identical, only the
    published bytes are narrower. A refused symlink anywhere in the walk
    aborts verification (and therefore the whole run) rather than being
    silently skipped or silently uploaded.
  * Row-scoped publication conditions (PR #1311 review, M4a; folded into a
    single commit per issue #1313/N1). If a row carries an optional
    `publish_note` field, its text is uploaded as a `README.md` alongside
    the row's data (generated in-memory — this does NOT write anything to
    the local directory) and the row's receipt records `readme_uploaded:
    true`. The README is included as one more operation in the SAME
    `create_commit` call as the row's data files (not a second, trailing
    `upload_file` commit) — a README failure now fails the whole row's
    commit instead of leaving previously-committed data published without
    its label, and the pinned `hf_revision` for the row always points at a
    commit that contains the README whenever `readme_uploaded` is true, so
    there is no separate "README commit revision" to track (issue #1313/N4
    — moot once N1 is fixed: one commit, one revision, covering both).

Deletion of a mirrored HF path is never automated by this tool or any tool
in this package — see docs/custody/hf-sync.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from huggingface_hub import CommitOperationAdd, HfApi
from huggingface_hub.utils import filter_repo_objects

from . import receipts as receipts_mod

HERE = Path(__file__).resolve().parent
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"

# The content-based construction (compute_filelist_manifest) — the only
# hash_method this tool trusts as an upload-integrity gate. NOTE (2026-08-02):
# the Workstream A census's own original "sha256_filelist_manifest" label
# turned out to name a size-only, content-blind construction (see
# compute_sizeonly_manifest) — a same-name collision with what this tool
# needs, not the same algorithm. inventory-v1.jsonl's UPLOAD_ALLOWED rows
# were re-minted (remint_hashes.py) to carry THIS value under hash_method,
# with the old size-only hash preserved separately under
# content_hash_sizeonly_census. Deliberately renamed here (not left as
# "sha256_filelist_manifest") so the two constructions can never be
# silently confused again.
SUPPORTED_HASH_METHOD = "sha256_content_manifest"
REQUIRED_ELIGIBLE_FIELDS = ("content_hash", "hash_method", "hash_status")

# huggingface_hub's own HfApi.upload_folder ALWAYS appends this exact pattern
# family to whatever ignore_patterns the caller passes (source:
# huggingface_hub.hf_api.DEFAULT_IGNORE_PATTERNS as of the huggingface_hub
# version this tool is pinned against) — it is not something a caller can
# opt out of. Inlined here as a named constant, rather than imported,
# because `huggingface_hub.hf_api.DEFAULT_IGNORE_PATTERNS` is an internal
# module attribute (no leading underscore on the name, but not part of the
# package's public `__init__` surface either) that could move or change
# without notice across hub versions; a wrong/missing value here would
# silently under-filter, so it is pinned by
# test_hf_default_ignore_patterns_is_subset_of_installed_library, which
# fails loudly if a newer installed hub version widens its own denylist
# beyond what's listed here (issue #1313, N1-rework: the create_commit
# path below builds its own operations list and therefore does NOT get
# upload_folder's implicit append for free — it must be unioned in
# explicitly, see UPLOAD_IGNORE_PATTERNS).
HF_UPLOAD_FOLDER_DEFAULT_IGNORE_PATTERNS = [
    ".git", ".git/*", "*/.git", "**/.git/**",
    ".cache/huggingface", ".cache/huggingface/*", "*/.cache/huggingface", "**/.cache/huggingface/**",
]

# Excludes dotfiles/dotdirs, .git* paths, AND (via the union above) the
# `.cache/huggingface` family huggingface_hub always excludes on its own,
# from the UPLOADED fileset only. Verification (compute_filelist_manifest)
# is NOT filtered by this — it stays census-identical (M4b). The exact
# glob-matching semantics against these patterns are huggingface_hub's own
# (`huggingface_hub.utils.filter_repo_objects`) and are exercised by
# test_create_commit_operations_exclude_dotfiles_and_git and
# test_create_commit_operations_exclude_hf_cache_dir.
UPLOAD_IGNORE_PATTERNS = [
    "**/.*", ".*", "**/.git", "**/.git/**", ".git", ".git/**",
] + HF_UPLOAD_FOLDER_DEFAULT_IGNORE_PATTERNS


class InventoryRefusal(ValueError):
    """Raised when the whole run must refuse to start (fail-closed)."""


@dataclass
class SyncOutcome:
    """One row's outcome — an upload/dry-run receipt, a skip, or an error."""

    row_id: int | None
    local_canonical_path: str | None
    disposition: str | None
    status: str  # "uploaded" | "dry_run" | "skipped" | "error"
    reason: str | None = None
    files_count: int | None = None
    bytes: int | None = None
    manifest_sha256: str | None = None
    hf_repo: str | None = None
    hf_revision: str | None = None
    commit_message: str | None = None
    path_in_repo: str | None = None
    readme_uploaded: bool = False

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
            "readme_uploaded": self.readme_uploaded,
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
    """Recompute a per-file sha256 manifest for `root` (recursive, all files).

    This is a CONTENT-based manifest: sort by relative POSIX path, hash each
    file's actual bytes as-is, combine into a single combined_sha256 over
    sorted "<relpath>\\t<sha256>\\t<size_bytes>\\n" lines. This is a distinct
    construction from scripts/manifest_sha.py (which is flat, *.bin-only,
    and keyed by bare filename) and, as of 2026-08-02, is ALSO confirmed
    distinct from the Workstream A census's own "sha256_filelist_manifest"
    label: the census construction never reads file content at all — see
    compute_sizeonly_manifest below. This function's whole purpose is to be
    the content-based upload-integrity gate the size-only census construction
    cannot be (same-size tampering is invisible to a size-only hash; it is
    not invisible here). inventory-v1.jsonl's UPLOAD_ALLOWED rows were
    re-minted on 2026-08-02 to use THIS function's output as content_hash —
    see remint_hashes.py and each row's hash_remint note.

    Refuses (raises ValueError) on any symlink encountered in the walk —
    this tool will never hash-then-publish a symlink's target transparently.

    This intentionally does NOT exclude dotfiles/.git* — the verification
    set stays census-identical. Excluding withheld paths from the UPLOADED
    fileset (not the verified one) is upload_verified_row's job via
    UPLOAD_IGNORE_PATTERNS.
    """
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise ValueError(f"symlink refused in verification walk: {p}")
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


def compute_sizeonly_manifest(root: Path) -> str:
    """Reproduce the Workstream A census's ORIGINAL "sha256_filelist_manifest"
    construction, exactly, for historical verification only.

    STRUCTURE-ONLY CHECK — NOT AN INTEGRITY CHECK. This hashes relative
    paths and file SIZES; it never reads a single byte of file content. Two
    directories with the same file names and sizes but completely different
    content produce the SAME hash under this function. This is why the
    census's content_hash values could not be reproduced by any
    content-based construction (compute_filelist_manifest above) — they
    were never content-based to begin with — and why this function exists
    only to (a) empirically confirm that historical fact per-row
    (remint_hashes.py does this before touching anything) and (b) document
    the construction precisely enough that nobody has to reverse-engineer
    it again. It is NEVER used as the tool's actual upload-integrity gate;
    compute_filelist_manifest is the only function sync_row/verify_all_
    eligible_rows use for that.

    Exact construction (confirmed empirically against rows 13 and 17's
    known-good ingestion-receipt hashes, then against all 8 UPLOAD_ALLOWED
    rows, 2026-08-02): os.walk(root, followlinks=False) — dotfiles/dotdirs
    INCLUDED, no exclusions of any kind; for each file, the POSIX-style
    relative path (forward slashes, computed the same way regardless of
    host OS); collected as (relpath, size_bytes) pairs; sorted by relpath
    using plain Python ordinal string comparison (the default `sort`); a
    single hashlib.sha256() object is then updated, per file in that sorted
    order, with `relpath.encode("utf-8") + b"\\x00" + str(size_bytes).encode
    ("utf-8") + b"\\n"` — i.e. NUL-separated path/size, LF-terminated,
    streamed straight into one incremental digest (equivalent to, but more
    memory-efficient than, hashing the full joined string in one call).
    """
    files: list[tuple[str, int]] = []
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for fn in filenames:
            p = Path(dirpath) / fn
            rel = p.relative_to(root).as_posix()
            files.append((rel, p.stat().st_size))
    files.sort(key=lambda r: r[0])
    h = hashlib.sha256()
    for rel, size in files:
        h.update(rel.encode("utf-8") + b"\x00" + str(size).encode("utf-8") + b"\n")
    return h.hexdigest()


@dataclass
class VerifiedRow:
    """One eligible row that has already passed whole-run verification."""

    row_id: int
    row: dict[str, Any]
    manifest: dict[str, Any]
    path_in_repo: str


def _find_path_in_repo_collisions(
    candidates: list[tuple[int, str]],
) -> dict[str, list[int]]:
    by_path: dict[str, list[int]] = {}
    for row_id, path_in_repo in candidates:
        by_path.setdefault(path_in_repo, []).append(row_id)
    return {p: ids for p, ids in by_path.items() if len(ids) > 1}


def verify_all_eligible_rows(
    eligible: list[tuple[int, dict[str, Any]]],
) -> list[VerifiedRow]:
    """PHASE 1 (M1 fix): verify EVERY eligible row before ANY upload happens.

    Recomputes each row's local manifest, compares it to the row's declared
    content_hash, and checks for path_in_repo basename collisions across the
    whole eligible set. If ANY row fails ANY of these checks, the whole run
    refuses (raises InventoryRefusal) and the caller must not attempt a
    single create_commit call — verification and upload are never
    interleaved. Precondition: validate_eligible_rows_verifiable already
    passed, so content_hash/hash_method/hash_status are known present and
    supported for every row here.
    """
    verified: list[VerifiedRow] = []
    problems: list[str] = []
    path_candidates: list[tuple[int, str]] = []

    for row_id, row in eligible:
        root = Path(row["local_canonical_path"])
        if not root.is_dir():
            problems.append(f"row {row_id}: local_canonical_path is not a directory: {root}")
            continue
        try:
            manifest = compute_filelist_manifest(root)
        except ValueError as exc:
            problems.append(f"row {row_id}: {exc}")
            continue
        if manifest["combined_sha256"] != row["content_hash"]:
            problems.append(
                f"row {row_id}: sha256_mismatch: local manifest "
                f"{manifest['combined_sha256']} != inventory content_hash {row['content_hash']}"
            )
            continue
        path_in_repo = Path(row["local_canonical_path"]).name
        path_candidates.append((row_id, path_in_repo))
        verified.append(
            VerifiedRow(row_id=row_id, row=row, manifest=manifest, path_in_repo=path_in_repo)
        )

    collisions = _find_path_in_repo_collisions(path_candidates)
    if collisions:
        for path_in_repo, row_ids in collisions.items():
            problems.append(
                f"path_in_repo collision {path_in_repo!r}: rows {row_ids} would "
                "silently overwrite each other in the hub repo"
            )

    if problems:
        raise InventoryRefusal(
            "REFUSING TO RUN: verification failed for "
            + str(len(problems)) + " eligible row(s)/check(s) before any "
            "upload was attempted:\n  " + "\n  ".join(problems)
        )
    return verified


def build_commit_message(row_id: int, row: dict[str, Any], manifest_sha256: str) -> str:
    return (
        f"hf-custody-sync: inventory row {row_id} "
        f"({row.get('source_identity', row.get('local_canonical_path', '?'))}) "
        f"manifest_sha256={manifest_sha256}"
    )


def _readme_content(row: dict[str, Any]) -> str:
    note = row["publish_note"]
    return note if note.endswith("\n") else note + "\n"


def _build_commit_operations(
    row: dict[str, Any],
    manifest: dict[str, Any],
    path_in_repo: str,
) -> list[CommitOperationAdd]:
    """Build the ONE commit's worth of operations for a verified row (N1 fix).

    Data files are the verified manifest's fileset (census-identical) minus
    UPLOAD_IGNORE_PATTERNS — the UNION of this repo's own dotfile/.git
    exclusions and `HF_UPLOAD_FOLDER_DEFAULT_IGNORE_PATTERNS` (the
    `.git`+`.cache/huggingface` family `upload_folder` always applies on
    top of whatever `ignore_patterns` a caller passes; `create_commit`
    itself has no such implicit behavior, so this function must supply the
    union explicitly to match what the old `upload_folder` call actually
    excluded — not just the repo's own patterns in isolation), computed
    here with huggingface_hub's own `filter_repo_objects` so the matching
    semantics are identical. If the row carries a `publish_note`, its
    README.md is APPENDED to this same operations list — never issued as a
    separate, trailing commit — so a single `create_commit` call either
    lands data and README together or fails the row's commit atomically.
    """
    root = Path(row["local_canonical_path"])
    included = filter_repo_objects(
        manifest["files"],
        ignore_patterns=UPLOAD_IGNORE_PATTERNS,
        key=lambda f: f["name"],
    )
    operations = [
        CommitOperationAdd(
            path_in_repo=f"{path_in_repo}/{f['name']}",
            path_or_fileobj=str(root / f["name"]),
        )
        for f in included
    ]
    if row.get("publish_note"):
        operations.append(
            CommitOperationAdd(
                path_in_repo=f"{path_in_repo}/README.md",
                path_or_fileobj=_readme_content(row).encode("utf-8"),
            )
        )
    return operations


def upload_verified_row(
    api: "HfApi | None",
    verified: VerifiedRow,
    repo_id: str,
    execute: bool,
) -> SyncOutcome:
    """PHASE 2: upload (or dry-run) a row that has already passed verification.

    Never re-touches local bytes for reading purposes beyond what the
    per-row `create_commit` call's `CommitOperationAdd` operations read.
    Raises on any upload failure (network error, or a returned commit with
    no valid sha) — the caller (sync()) is responsible for receipting the
    failure and propagating it; this function never swallows an upload
    error into a quiet "refused" outcome. One `create_commit` call per row
    (N1): data files and, when present, the row's README.md land in the
    SAME commit — never a second, trailing commit.
    """
    row_id, row, manifest, path_in_repo = (
        verified.row_id,
        verified.row,
        verified.manifest,
        verified.path_in_repo,
    )
    files_count = len(manifest["files"]) or None
    bytes_total = sum(f["size_bytes"] for f in manifest["files"]) or None
    manifest_sha256 = manifest["combined_sha256"]
    commit_message = build_commit_message(row_id, row, manifest_sha256)
    has_publish_note = bool(row.get("publish_note"))

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
            readme_uploaded=False,
        )

    assert api is not None
    operations = _build_commit_operations(row, manifest, path_in_repo)
    commit_info = api.create_commit(
        repo_id=repo_id,
        repo_type="dataset",
        operations=operations,
        commit_message=commit_message,
    )
    oid = getattr(commit_info, "oid", None)
    if not oid or not receipts_mod.REVISION_RE.fullmatch(oid):
        # M3: no commit_url fallback. A missing/invalid oid is a hard error —
        # never record an unpinned/non-sha reference as a revision.
        raise RuntimeError(
            f"hf-custody-sync: create_commit returned no valid commit sha for "
            f"row {row_id} (oid={oid!r}) — refusing to record an unpinned "
            "revision"
        )

    # N1: README landed in the SAME commit as the data (or not at all — no
    # partial state). N4: that commit's oid (already captured above as the
    # row's hf_revision) IS the README's revision whenever readme_uploaded
    # is true — there is no second commit to separately record.
    readme_uploaded = has_publish_note

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
        hf_revision=oid,
        commit_message=commit_message,
        path_in_repo=path_in_repo,
        readme_uploaded=readme_uploaded,
    )


def _error_outcome(verified: VerifiedRow, repo_id: str, exc: Exception) -> SyncOutcome:
    manifest = verified.manifest
    return SyncOutcome(
        row_id=verified.row_id,
        local_canonical_path=verified.row.get("local_canonical_path"),
        disposition=verified.row.get("disposition", "UPLOAD_ALLOWED"),
        status="error",
        reason=str(exc),
        files_count=len(manifest["files"]) or None,
        bytes=sum(f["size_bytes"] for f in manifest["files"]) or None,
        manifest_sha256=manifest["combined_sha256"],
        hf_repo=repo_id,
        hf_revision=None,
        commit_message=build_commit_message(verified.row_id, verified.row, manifest["combined_sha256"]),
        path_in_repo=verified.path_in_repo,
        readme_uploaded=False,
    )


def sync(
    inventory_path: str | Path,
    repo_id: str,
    execute: bool = False,
    on_outcome: Callable[[SyncOutcome], None] | None = None,
) -> list[SyncOutcome]:
    """Top-level orchestration.

    Fail-closed (M1): loads + selects + validates + verifies EVERY eligible
    row before any upload; a single bad row raises InventoryRefusal with
    zero create_commit calls made.

    Per-outcome receipting (M2): if `on_outcome` is given, it is called
    immediately after each outcome is produced — skips first, then each
    verified row's dry-run/upload/error outcome, in that order, as it
    happens. If an upload raises mid-loop, that row's "error" outcome is
    still passed to `on_outcome` before the exception is re-raised, so
    receipts for every row processed so far (including the failing one)
    are never lost.
    """
    rows = load_inventory(inventory_path)
    eligible, skip_outcomes = select_eligible_rows(rows)
    validate_eligible_rows_verifiable(eligible)  # raises -> nothing uploaded
    verified = verify_all_eligible_rows(eligible)  # raises -> nothing uploaded (M1)

    api = HfApi() if execute else None
    outcomes: list[SyncOutcome] = []

    for outcome in skip_outcomes:
        outcomes.append(outcome)
        if on_outcome is not None:
            on_outcome(outcome)

    for v in verified:
        try:
            outcome = upload_verified_row(api, v, repo_id, execute)
        except Exception as exc:  # noqa: BLE001 — deliberately broad: any upload failure is receipted then re-raised
            error_outcome = _error_outcome(v, repo_id, exc)
            outcomes.append(error_outcome)
            if on_outcome is not None:
                on_outcome(error_outcome)
            raise
        outcomes.append(outcome)
        if on_outcome is not None:
            on_outcome(outcome)

    outcomes.sort(key=lambda o: (o.row_id is None, o.row_id))
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
    args = build_arg_parser().parse_args(argv)
    execute = args.execute and not args.dry_run
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def on_outcome(outcome: SyncOutcome) -> None:
        receipt = outcome.to_receipt_dict(ts)
        print(json.dumps(receipt), flush=True)
        if args.receipts_path:
            receipts_mod.append_receipt(args.receipts_path, receipt)

    try:
        sync(args.inventory, args.repo_id, execute=execute, on_outcome=on_outcome)
    except InventoryRefusal as exc:
        print(f"[hf-custody-sync] {exc}", file=sys.stderr)
        if args.receipts_path:
            receipts_mod.append_receipt(
                args.receipts_path,
                {
                    "ts": ts,
                    "inventory_row_id": None,
                    "local_path": None,
                    "disposition": None,
                    "status": "run_refused",
                    "reason": str(exc),
                    "files_count": None,
                    "bytes": None,
                    "manifest_sha256": None,
                    "hf_repo": args.repo_id,
                    "hf_revision": None,
                    "commit_message": None,
                    "path_in_repo": None,
                    "readme_uploaded": False,
                    "sha_convention": SHA_CONVENTION,
                },
            )
        return 1
    except Exception as exc:  # noqa: BLE001 — mid-run failure already receipted row-by-row via on_outcome
        print(f"[hf-custody-sync] aborted mid-run: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
