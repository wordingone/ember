# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed, reviewable repository-hygiene inventory for issue #488.

The scanner is read-only.  Applying a reviewed manifest is an explicit,
content-addressed operation and never touches ``.git`` or untracked bytes.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import argparse
import datetime as _dt
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Iterable

# Make direct ``python scripts/ember_totality/issue488_hygiene.py`` execution
# resolve only this repository's package, without ambient PYTHONPATH.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ember_totality.ember_totality_spec import compute_working_set


MANIFEST_SCHEMA = "ember-issue-488-reference-manifest-v1"
CLEANUP_SCHEMA = "ember-issue-488-cleanup-receipt-v1"
POLICY_SCHEMA = "ember-issue-488-hygiene-policy-v1"
GOAL_ID = "EMBER-02"
WORKSTREAM_ID = "EMBER-02A"
NEXT_EXECUTED_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
CANONICAL_CARRIER = "GOVERNANCE.md"
ABSORBED_248_COMMENT = "https://github.com/wordingone/ember/issues/488#issuecomment-5101881455"
_HEX64 = set("0123456789abcdef")
_RECEIPT_FIELDS = {
    "ticket", "ts", "sha_convention", "schema_version", "goal_id",
    "workstream_id", "next_executed_outcome", "artifact_class", "policy",
    "cleanup_scope", "manifest_sha256", "before", "after",
    "working_set_before", "working_set_after_cleanup", "deleted", "rollback",
    "non_regression", "receipt_sha256",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


def _tracked_paths(root: Path) -> list[str]:
    try:
        output = _git(root, "ls-files", "-z")
    except (OSError, subprocess.CalledProcessError):
        return []
    return [item for item in output.split("\x00") if item]


def _relative_files(root: Path, prefix: str) -> list[str]:
    directory = root / prefix
    if not directory.is_dir():
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and ".git" not in path.parts
    )


def _inventory_bucket(root: Path, paths: Iterable[str]) -> dict[str, Any]:
    rows = []
    for relative in sorted(paths):
        path = root / Path(relative)
        if not path.is_file():
            continue
        rows.append({"path": relative, "bytes": path.stat().st_size, "sha256": _sha256_file(path)})
    return {
        "count": len(rows),
        "bytes": sum(row["bytes"] for row in rows),
        "sha256": _sha256_bytes(_canonical(rows)),
    }


def _tracked_references(root: Path, tracked: list[str], candidates: Iterable[str]) -> dict[str, list[str]]:
    references: dict[str, list[str]] = {relative: [] for relative in candidates}
    candidate_names = {relative: (relative, Path(relative).name) for relative in candidates}
    for source in tracked:
        source_path = root / Path(source)
        try:
            text = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for candidate, (full_name, basename) in candidate_names.items():
            if candidate == source:
                continue
            if full_name in text or basename in text:
                references[candidate].append(source)
    return references


def _duplicate_candidates(root: Path, tracked: list[str], references: dict[str, list[str]]) -> list[dict[str, Any]]:
    groups: dict[tuple[int, str], list[str]] = {}
    for relative in tracked:
        if not (relative.startswith("docs/") or relative.startswith("scripts/") or relative.startswith("receipts/")):
            continue
        path = root / Path(relative)
        if not path.is_file():
            continue
        key = (path.stat().st_size, _sha256_file(path))
        groups.setdefault(key, []).append(relative)
    candidates: list[dict[str, Any]] = []
    for (_size, digest), paths in sorted(groups.items()):
        if len(paths) < 2:
            continue
        canonical = sorted(paths)[0]
        for relative in sorted(paths)[1:]:
            path = root / Path(relative)
            refs = sorted(references.get(relative, []))
            protected = bool(refs)
            candidates.append({
                "path": relative,
                "kind": "tracked_duplicate",
                "bytes": path.stat().st_size,
                "sha256": digest,
                "reference_count": len(refs),
                "references": refs,
                "action": "PROTECTED_EVIDENCE" if protected else "DELETE_CANDIDATE",
                "superseded_by": canonical,
                "reason": "byte-identical duplicate with no tracked reference" if not protected else "referenced tracked evidence",
            })
    return candidates


def _working_set_from_tree(root: Path, tracked: list[str]) -> dict[str, Any]:
    """Compatibility wrapper around the canonical working-set producer."""
    return compute_working_set(root, tracked_override=tracked, include_open_issues=False)


def _policy_contract() -> dict[str, Any]:
    """Return the closed, path-free policy carried by every #488 manifest."""
    return {
        "schema_version": POLICY_SCHEMA,
        "canonical_carrier": CANONICAL_CARRIER,
        "first_bounded_cleanup_pass": True,
        "remaining_cadence_transferred": True,
        "transfer_basis": ABSORBED_248_COMMENT,
        "doc_supersession": "declare_supersedes_or_invalidates_and_delete_superseded_in_superseding_pr",
        "receipt_retention": "protect_claimed_or_cited; annex_uncited_older_than_30d_quarterly; working_readable",
        "script_taxonomy": "propose_unreferenced_deletion_with_scan_and_atomic_consumer_updates",
        "issue_cadence": "silent_over_14d_pointer_park_or_operator_kill_only",
        "trend_wince": "working_set_growth_without_battery_movement_is_named_wince",
        "carrier_discipline": "extend_existing_carrier_before_opening_issue",
        "eng_sync_tally": "classify_protected_annex_or_duplicate_before_move",
        "receipt_atomicity": "claims_index_board_receipt_check_and_consumers_move_atomically",
        "ledger_archive": "receipts/ledger_append_only_with_v1_archived_reconstruction",
        "dispatch_equivalence": "equivalence_tests_and_reviewed_manifest_before_stub_removal",
    }


def _receipt_content_hash(receipt: dict[str, Any]) -> str:
    body = dict(receipt)
    body.pop("receipt_sha256", None)
    return _sha256_bytes(_canonical(body))


def _validate_receipt_projection(
    receipt: dict[str, Any],
    manifest: dict[str, Any],
    *,
    expected_before: dict[str, int],
    expected_after: dict[str, int],
    expected_working_set_before: dict[str, Any],
    expected_working_set_after: dict[str, Any],
) -> None:
    """Authenticate every receipt authority field against the historical tree."""
    if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_FIELDS:
        raise ValueError("cleanup receipt fields malformed")
    if receipt["schema_version"] != CLEANUP_SCHEMA:
        raise ValueError("cleanup receipt schema mismatch")
    if receipt["ticket"] != "EMBER-488-HYGIENE" or receipt["goal_id"] != GOAL_ID:
        raise ValueError("cleanup receipt identity mismatch")
    if receipt["workstream_id"] != WORKSTREAM_ID or receipt["next_executed_outcome"] != NEXT_EXECUTED_OUTCOME:
        raise ValueError("cleanup receipt workstream mismatch")
    if receipt["artifact_class"] != "hygiene_evidence":
        raise ValueError("cleanup receipt artifact class mismatch")
    if receipt["sha_convention"] != "sha256 over on-disk raw bytes (binary read, no line-ending normalization)":
        raise ValueError("cleanup receipt hash convention mismatch")
    if receipt["policy"] != _policy_contract() or receipt["policy"] != manifest.get("policy"):
        raise ValueError("cleanup receipt policy mismatch")
    expected_scope = {
        "kind": "first_bounded_cleanup_pass",
        "canonical_carrier": CANONICAL_CARRIER,
        "remaining_cadence_transferred": True,
        "transfer_basis": ABSORBED_248_COMMENT,
    }
    if receipt["cleanup_scope"] != expected_scope:
        raise ValueError("cleanup receipt scope mismatch")
    if not _is_sha256(receipt["manifest_sha256"]) or receipt["manifest_sha256"] != manifest.get("manifest_sha256"):
        raise ValueError("cleanup receipt manifest binding mismatch")
    if not _is_sha256(receipt["receipt_sha256"]):
        raise ValueError("cleanup receipt content hash malformed")
    if _receipt_content_hash(receipt) != receipt["receipt_sha256"]:
        raise ValueError("cleanup receipt content hash mismatch")
    for name, expected in (("before", expected_before), ("after", expected_after)):
        value = receipt[name]
        if not isinstance(value, dict) or set(value) != {"files", "bytes"}:
            raise ValueError(f"cleanup receipt {name} snapshot malformed")
        if type(value["files"]) is not int or value["files"] < 0 or type(value["bytes"]) is not int or value["bytes"] < 0:
            raise ValueError(f"cleanup receipt {name} snapshot values malformed")
        if value != expected:
            raise ValueError(f"cleanup receipt {name} snapshot mismatch")
    if receipt["working_set_before"] != expected_working_set_before:
        raise ValueError("cleanup receipt working-set-before mismatch")
    if receipt["working_set_after_cleanup"] != expected_working_set_after:
        raise ValueError("cleanup receipt working-set-after mismatch")
    deleted = receipt["deleted"]
    if not isinstance(deleted, list) or len({row.get("path") for row in deleted if isinstance(row, dict)}) != len(deleted):
        raise ValueError("cleanup receipt deletion projection malformed")
    for row in deleted:
        if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
            raise ValueError("cleanup receipt deletion row malformed")
        if not isinstance(row["path"], str) or type(row["bytes"]) is not int or row["bytes"] < 0 or not _is_sha256(row["sha256"]):
            raise ValueError("cleanup receipt deletion values malformed")
    if receipt["rollback"] != {
        "files": deleted,
        "action": "restore exact bytes from the recorded hashes",
    }:
        raise ValueError("cleanup receipt rollback binding mismatch")
    if receipt["non_regression"] != {
        "git_metadata_mutated": False,
        "private_or_untracked_bytes_deleted": False,
    }:
        raise ValueError("cleanup receipt non-regression binding mismatch")


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX64


def _exact_child(root: Path, relative: str) -> Path:
    """Resolve one relative path without symlink, reparse, or case aliases."""
    _validate_relative_path(relative)
    if relative.replace("\\", "/") != relative:
        raise ValueError("path separator alias")
    cursor = root
    for part in Path(relative).parts:
        children = [child for child in cursor.iterdir() if child.name.casefold() == part.casefold()]
        if len(children) != 1 or children[0].name != part:
            raise ValueError("path case or reparse alias")
        cursor = children[0]
        attributes = getattr(os.lstat(cursor), "st_file_attributes", 0)
        if cursor.is_symlink() or attributes & 0x400:
            raise ValueError("symlink or reparse cleanup path")
    return cursor


def _validate_manifest(
    root: Path,
    manifest: dict[str, Any],
    *,
    historical: bool = False,
    tracked_override: list[str] | None = None,
) -> None:
    """Validate a producer-shaped manifest before any cleanup mutation."""
    expected_keys = {
        "schema_version", "source_commit", "source_clean", "policy",
        "working_set", "inventory", "candidates", "selected_cleanup", "completed_cleanup", "manifest_sha256",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        raise ValueError("closed hygiene manifest fields required")
    if manifest["schema_version"] != MANIFEST_SCHEMA:
        raise ValueError("unsupported hygiene manifest")
    if not isinstance(manifest["source_commit"], str) or len(manifest["source_commit"]) != 40 or set(manifest["source_commit"]) - set("0123456789abcdef"):
        raise ValueError("manifest source commit malformed")
    if type(manifest["source_clean"]) is not bool:
        raise ValueError("manifest source_clean malformed")
    if historical:
        if manifest["source_clean"] is not True:
            raise ValueError("historical manifest source was not clean")
    else:
        try:
            live_head = _git(root, "rev-parse", "HEAD")
            live_status = _git(root, "status", "--porcelain")
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ValueError("manifest requires live Git authority") from exc
        if live_head != manifest["source_commit"]:
            raise ValueError("manifest source commit drift")
        if live_status or manifest["source_clean"] is not True:
            raise ValueError("manifest source tree is not clean")
    if manifest["policy"] != _policy_contract():
        raise ValueError("hygiene policy contract drift")
    if not _is_sha256(manifest["manifest_sha256"]):
        raise ValueError("manifest hash malformed")
    body = dict(manifest)
    recorded_hash = body.pop("manifest_sha256")
    if _sha256_bytes(_canonical(body)) != recorded_hash:
        raise ValueError("manifest hash mismatch")
    if not isinstance(manifest["working_set"], dict) or not isinstance(manifest["inventory"], dict):
        raise ValueError("manifest working-set or inventory malformed")
    inventory = manifest["inventory"]
    if set(inventory) != {"docs", "scripts", "tracked_receipts", "untracked_receipts", "git_packs"}:
        raise ValueError("manifest inventory fields malformed")
    for bucket in inventory.values():
        if not isinstance(bucket, dict) or set(bucket) != {"count", "bytes", "sha256"}:
            raise ValueError("manifest inventory bucket malformed")
        if type(bucket["count"]) is not int or bucket["count"] < 0 or type(bucket["bytes"]) is not int or bucket["bytes"] < 0 or not _is_sha256(bucket["sha256"]):
            raise ValueError("manifest inventory values malformed")
    candidates = manifest["candidates"]
    if not isinstance(candidates, list):
        raise ValueError("manifest candidates malformed")
    seen: set[str] = set()
    for row in candidates:
        fields = {"path", "kind", "bytes", "sha256", "reference_count", "references", "action", "superseded_by", "reason"}
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError("manifest candidate fields malformed")
        relative = row["path"]
        if not isinstance(relative, str) or relative in seen:
            raise ValueError("manifest candidate path duplicated")
        seen.add(relative)
        if type(row["bytes"]) is not int or row["bytes"] < 0 or not _is_sha256(row["sha256"]):
            raise ValueError("manifest candidate bytes/hash malformed")
        if row["kind"] != "tracked_duplicate" or row["action"] not in {"PROTECTED_EVIDENCE", "ANNEX_CANDIDATE", "DELETE_CANDIDATE"}:
            raise ValueError("manifest candidate kind/action malformed")
        if type(row["reference_count"]) is not int or row["reference_count"] < 0 or not isinstance(row["references"], list) or any(not isinstance(item, str) for item in row["references"]):
            raise ValueError("manifest candidate references malformed")
        if row["reference_count"] != len(row["references"]):
            raise ValueError("manifest candidate reference count mismatch")
        target = _exact_child(root, relative)
        if target.stat().st_size != row["bytes"] or _sha256_file(target) != row["sha256"]:
            raise ValueError("manifest candidate bytes drift")
        if row["action"] == "DELETE_CANDIDATE":
            if row["reference_count"] != 0 or row["references"] or not isinstance(row["superseded_by"], str):
                raise ValueError("delete candidate is referenced or lacks canonical")
            canonical = _exact_child(root, row["superseded_by"])
            if canonical.stat().st_size != row["bytes"] or _sha256_file(canonical) != row["sha256"]:
                raise ValueError("delete candidate canonical mismatch")
        elif row["action"] == "PROTECTED_EVIDENCE" and row["reference_count"] == 0:
            raise ValueError("protected candidate lacks reference evidence")
    selected = manifest["selected_cleanup"]
    if not isinstance(selected, list):
        raise ValueError("selected cleanup projection malformed")
    candidate_by_path = {row["path"]: row for row in candidates}
    selected_paths: set[str] = set()
    for row in selected:
        if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256", "superseded_by"}:
            raise ValueError("selected cleanup row malformed")
        relative = row["path"]
        if not isinstance(relative, str) or relative in selected_paths:
            raise ValueError("selected cleanup path duplicated")
        selected_paths.add(relative)
        candidate = candidate_by_path.get(relative)
        if candidate is None or candidate["action"] != "DELETE_CANDIDATE":
            raise ValueError("selected cleanup path is not a deletion candidate")
        if row["bytes"] != candidate["bytes"] or row["sha256"] != candidate["sha256"] or row["superseded_by"] != candidate["superseded_by"]:
            raise ValueError("selected cleanup candidate binding mismatch")
        if not _is_sha256(row["sha256"]):
            raise ValueError("selected cleanup hash malformed")
        canonical = _exact_child(root, row["superseded_by"])
        if canonical.stat().st_size != row["bytes"] or _sha256_file(canonical) != row["sha256"]:
            raise ValueError("selected cleanup canonical mismatch")
    completed = manifest["completed_cleanup"]
    if not isinstance(completed, list):
        raise ValueError("completed cleanup projection malformed")
    for row in completed:
        if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256", "superseded_by", "receipt_path"}:
            raise ValueError("completed cleanup row malformed")
        if row["path"] in seen or not isinstance(row["path"], str) or not _is_sha256(row["sha256"]):
            raise ValueError("completed cleanup path/hash malformed")
        seen.add(row["path"])
        if type(row["bytes"]) is not int or row["bytes"] < 0 or not isinstance(row["superseded_by"], str) or not isinstance(row["receipt_path"], str):
            raise ValueError("completed cleanup values malformed")
        canonical = _exact_child(root, row["superseded_by"])
        if canonical.stat().st_size != row["bytes"] or _sha256_file(canonical) != row["sha256"]:
            raise ValueError("completed cleanup rollback mismatch")

    tracked = tracked_override if tracked_override is not None else _tracked_paths(root)
    if tracked:
        expected = build_reference_manifest(
            root,
            tracked_override=tracked,
            source_commit_override=manifest["source_commit"] if historical else None,
            source_clean_override=True if historical else None,
            include_open_issues=not historical,
        )
        for field in ("working_set", "inventory", "candidates"):
            if manifest[field] != expected[field]:
                raise ValueError(f"manifest {field} projection drift")


def build_reference_manifest(
    repo_root: str | os.PathLike[str],
    *,
    tracked_override: list[str] | None = None,
    source_commit_override: str | None = None,
    source_clean_override: bool | None = None,
    working_set_override: dict[str, Any] | None = None,
    include_open_issues: bool = False,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    tracked = tracked_override if tracked_override is not None else _tracked_paths(root)
    if source_commit_override is not None:
        source_commit = source_commit_override
        source_clean = True if source_clean_override is None else source_clean_override
    else:
        try:
            source_commit = _git(root, "rev-parse", "HEAD")
            source_clean = not bool(_git(root, "status", "--porcelain"))
        except (OSError, subprocess.CalledProcessError):
            source_commit = "0" * 40
            source_clean = False

    tracked_receipts = [p for p in tracked if p.startswith("receipts/")]
    untracked_receipts = []
    receipts_root = root / "receipts"
    if receipts_root.is_dir():
        tracked_set = set(tracked)
        untracked_receipts = [
            path.relative_to(root).as_posix()
            for path in receipts_root.rglob("*")
            if path.is_file() and path.relative_to(root).as_posix() not in tracked_set
        ]
    pack_paths = []
    pack_root = root / ".git" / "objects" / "pack"
    if pack_root.is_dir():
        pack_paths = [path for path in pack_root.iterdir() if path.is_file()]

    inventory = {
        "docs": _inventory_bucket(root, [p for p in tracked if p.startswith("docs/")]),
        "scripts": _inventory_bucket(root, [p for p in tracked if p.startswith("scripts/")]),
        "tracked_receipts": _inventory_bucket(root, tracked_receipts),
        "untracked_receipts": _inventory_bucket(root, untracked_receipts),
        "git_packs": {
            "count": len(pack_paths),
            "bytes": sum(path.stat().st_size for path in pack_paths),
            "sha256": _sha256_bytes(_canonical([
                {"bytes": path.stat().st_size, "sha256": _sha256_file(path)}
                for path in sorted(pack_paths)
            ])),
        },
    }
    preliminary_references = {relative: [] for relative in tracked}
    preliminary_candidates = _duplicate_candidates(root, tracked, preliminary_references)
    references = _tracked_references(root, tracked, [row["path"] for row in preliminary_candidates])
    candidates = _duplicate_candidates(root, tracked, references)
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA,
        "source_commit": source_commit,
        "source_clean": source_clean,
        "policy": _policy_contract(),
        "working_set": working_set_override if working_set_override is not None else compute_working_set(
            root,
            tracked_override=tracked,
            include_open_issues=include_open_issues,
        ),
        "inventory": inventory,
        "candidates": candidates,
        "selected_cleanup": [],
        "completed_cleanup": [],
    }
    manifest["manifest_sha256"] = _sha256_bytes(_canonical(manifest))
    return manifest


def _snapshot(root: Path) -> dict[str, int]:
    count = 0
    total_bytes = 0
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        count += 1
        total_bytes += path.stat().st_size
    return {"files": count, "bytes": total_bytes}


def _validate_relative_path(relative: str) -> None:
    path = Path(relative)
    if not relative or path.is_absolute() or relative.replace("\\", "/").startswith("../") or ".." in path.parts:
        raise ValueError("unsafe cleanup path")
    if ".git" in path.parts:
        raise ValueError(".git mutation is forbidden")


def _extract_validated_git_archive(archive: bytes, destination: Path) -> None:
    """Materialize a Git archive only after rejecting traversal and links."""
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        members = bundle.getmembers()
        for member in members:
            name = member.name.replace("\\", "/")
            pure = Path(name)
            if not name or pure.is_absolute() or ".." in pure.parts or "\\" in member.name:
                raise ValueError("historical archive path traversal")
            if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                raise ValueError("historical archive member type is unsafe")
        for member in members:
            target = destination / Path(member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise ValueError("historical archive file is unreadable")
            with target.open("wb") as output:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    output.write(chunk)


def _git_archive(root: Path, source_commit: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), "archive", "--format=tar", source_commit],
        check=True,
        capture_output=True,
    )
    return result.stdout


def apply_safe_cleanup(
    repo_root: str | os.PathLike[str],
    manifest: dict[str, Any],
    paths: list[str],
    receipt_path: str | os.PathLike[str],
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    _validate_manifest(root, manifest)
    policy = manifest["policy"]
    rows = {row.get("path"): row for row in manifest.get("candidates", [])}
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate cleanup path")
    destination = Path(receipt_path)
    if destination.exists():
        raise ValueError("refusing to overwrite cleanup receipt")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A reviewed cleanup may only begin from the exact clean tree that was
    # scanned.  Tiny unit fixtures without their own .git directory are
    # intentionally treated as isolated non-repository custody roots.
    try:
        git_root = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    except (OSError, subprocess.CalledProcessError):
        git_root = None
    if git_root == root:
        if manifest.get("source_clean") is not True:
            raise ValueError("cleanup requires a clean scanned source tree")
        if _git(root, "rev-parse", "HEAD") != manifest.get("source_commit"):
            raise ValueError("cleanup source commit drift")
        if _git(root, "status", "--porcelain"):
            raise ValueError("cleanup source tree is dirty")
        tracked = set(_tracked_paths(root))
    else:
        tracked = set()
    selected = []
    for relative in paths:
        _validate_relative_path(relative)
        row = rows.get(relative)
        if not row or row.get("action") != "DELETE_CANDIDATE":
            raise ValueError("path is not an approved deletion candidate")
        if tracked and relative not in tracked:
            raise ValueError("cleanup path is not tracked")
        path = root / Path(relative)
        if not path.is_file() or path.stat().st_size != row.get("bytes") or _sha256_file(path) != row.get("sha256"):
            raise ValueError("candidate bytes changed")
        selected.append((relative, row, path))

    backups = [(path, path.read_bytes()) for _relative, _row, path in selected]
    before = _snapshot(root)
    working_set_before = manifest.get("working_set")
    deleted = []
    temporary_receipt = destination.with_name(destination.name + ".tmp")
    try:
        for relative, row, path in selected:
            path.unlink()
            deleted.append({"path": relative, "bytes": row["bytes"], "sha256": row["sha256"]})
        after = _snapshot(root)
        working_set_after = _working_set_from_tree(root, sorted(tracked))
        receipt = {
            "ticket": "EMBER-488-HYGIENE",
            "ts": _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
            "schema_version": CLEANUP_SCHEMA,
            "goal_id": GOAL_ID,
            "workstream_id": WORKSTREAM_ID,
            "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
            "artifact_class": "hygiene_evidence",
            "policy": policy,
            "cleanup_scope": {
                "kind": "first_bounded_cleanup_pass",
                "canonical_carrier": CANONICAL_CARRIER,
                "remaining_cadence_transferred": True,
                "transfer_basis": ABSORBED_248_COMMENT,
            },
            "manifest_sha256": manifest.get("manifest_sha256"),
            "before": before,
            "after": after,
            "working_set_before": working_set_before,
            "working_set_after_cleanup": working_set_after,
            "deleted": deleted,
            "rollback": {"files": deleted, "action": "restore exact bytes from the recorded hashes"},
            "non_regression": {"git_metadata_mutated": False, "private_or_untracked_bytes_deleted": False},
        }
        receipt["receipt_sha256"] = _receipt_content_hash(receipt)
        temporary_receipt.write_bytes(_canonical(receipt) + b"\n")
        os.replace(temporary_receipt, destination)
        return receipt
    except Exception:
        for path, content in backups:
            path.write_bytes(content)
        if temporary_receipt.exists():
            temporary_receipt.unlink()
        raise


def write_manifest(repo_root: str | os.PathLike[str], destination: str | os.PathLike[str]) -> dict[str, Any]:
    """Write one canonical manifest without overwriting an existing artifact."""
    path = Path(destination)
    if path.exists():
        raise ValueError("refusing to overwrite reference manifest")
    manifest = build_reference_manifest(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(manifest) + b"\n")
    return manifest


def validate_post_cleanup(
    repo_root: str | os.PathLike[str],
    manifest_path: str | os.PathLike[str],
    receipt_path: str | os.PathLike[str],
) -> None:
    """Reopen the pre-cleanup Git tree and verify the later deletion receipt."""
    root = Path(repo_root).resolve()
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("cleanup manifest or receipt is unreadable") from exc
    source_commit = manifest.get("source_commit")
    if not isinstance(source_commit, str) or len(source_commit) != 40:
        raise ValueError("historical source commit malformed")
    try:
        _git(root, "cat-file", "-e", f"{source_commit}^{{commit}}")
        _git(root, "merge-base", "--is-ancestor", source_commit, "HEAD")
        if _git(root, "status", "--porcelain"):
            raise ValueError("post-cleanup source tree is dirty")
        tracked = [item for item in _git(root, "ls-tree", "-r", "--name-only", source_commit).splitlines() if item]
        archive = _git_archive(root, source_commit)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("historical source commit is not an ancestor of this Git tree") from exc
    with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP") or os.environ.get("TMP")) as directory:
        historical_root = Path(directory)
        _extract_validated_git_archive(archive, historical_root)
        _validate_manifest(historical_root, manifest, historical=True, tracked_override=tracked)
        expected_before = _snapshot(historical_root)
        expected_working_set_before = compute_working_set(
            historical_root,
            tracked_override=tracked,
            include_open_issues=False,
        )
        deleted = receipt.get("deleted") if isinstance(receipt, dict) else None
        if not isinstance(deleted, list):
            raise ValueError("cleanup receipt deletion projection malformed")
        candidates = {
            row["path"]: row
            for row in manifest.get("candidates", [])
            if isinstance(row, dict) and row.get("action") == "DELETE_CANDIDATE"
        }
        selected = manifest.get("selected_cleanup")
        if not isinstance(selected, list):
            raise ValueError("manifest selected cleanup projection malformed")
        selected_by_path = {row["path"]: row for row in selected if isinstance(row, dict)}
        deleted_paths = {row.get("path") for row in deleted if isinstance(row, dict)}
        if set(selected_by_path) != deleted_paths:
            raise ValueError("cleanup receipt selected deletion mismatch")
        completed = manifest.get("completed_cleanup")
        if not isinstance(completed, list):
            raise ValueError("manifest completed cleanup projection malformed")
        if completed:
            completed_paths = {row.get("path") for row in completed if isinstance(row, dict)}
            if completed_paths != deleted_paths:
                raise ValueError("cleanup receipt completed deletion mismatch")
        for row in deleted:
            if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
                raise ValueError("cleanup receipt deletion row malformed")
            candidate = candidates.get(row["path"])
            selected_row = selected_by_path.get(row["path"])
            if candidate is None or selected_row is None:
                raise ValueError("cleanup receipt selected candidate mismatch")
            if row["bytes"] != candidate["bytes"] or row["sha256"] != candidate["sha256"]:
                raise ValueError("cleanup receipt selected candidate mismatch")
            if row["bytes"] != selected_row["bytes"] or row["sha256"] != selected_row["sha256"]:
                raise ValueError("cleanup receipt selected candidate binding mismatch")
            historical_path = _exact_child(historical_root, row["path"])
            if historical_path.stat().st_size != row["bytes"] or _sha256_file(historical_path) != row["sha256"]:
                raise ValueError("cleanup receipt historical candidate bytes drift")
            historical_path.unlink()
        expected_after = _snapshot(historical_root)
        deleted_paths = {row["path"] for row in deleted}
        expected_working_set_after = compute_working_set(
            historical_root,
            tracked_override=[path for path in tracked if path not in deleted_paths],
            include_open_issues=False,
        )
        _validate_receipt_projection(
            receipt,
            manifest,
            expected_before=expected_before,
            expected_after=expected_after,
            expected_working_set_before=expected_working_set_before,
            expected_working_set_after=expected_working_set_after,
        )
    diff_lines = _git(root, "diff", "--name-status", source_commit, "HEAD").splitlines()
    deleted_from_git = {
        line.split("\t", 1)[1]
        for line in diff_lines
        if line.startswith("D\t") and "\t" in line
    }
    if deleted_from_git != {row["path"] for row in receipt["deleted"]}:
        raise ValueError("tracked deletion set is not receipt-selected")
    for row in deleted:
        candidate = candidates[row["path"]]
        deleted_path = root / Path(row["path"])
        if deleted_path.exists() or deleted_path.is_symlink():
            raise ValueError("selected cleanup path still exists")
        canonical = _exact_child(root, candidate["superseded_by"])
        if canonical.stat().st_size != row["bytes"] or _sha256_file(canonical) != row["sha256"]:
            raise ValueError("selected cleanup canonical bytes drift")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Issue #488 closed hygiene inventory")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan = subparsers.add_parser("scan")
    scan.add_argument("repo_root", type=Path)
    scan.add_argument("manifest", type=Path)
    validate = subparsers.add_parser("validate")
    validate.add_argument("repo_root", type=Path)
    validate.add_argument("manifest", type=Path)
    validate.add_argument("receipt", type=Path)
    apply = subparsers.add_parser("apply")
    apply.add_argument("repo_root", type=Path)
    apply.add_argument("manifest", type=Path)
    apply.add_argument("receipt", type=Path)
    apply.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)
    if args.command == "scan":
        if args.manifest.exists():
            raise SystemExit("refusing to overwrite reference manifest")
        write_manifest(args.repo_root, args.manifest)
    elif args.command == "validate":
        validate_post_cleanup(args.repo_root, args.manifest, args.receipt)
    else:
        payload = json.loads(args.manifest.read_text(encoding="utf-8"))
        apply_safe_cleanup(args.repo_root, payload, args.paths, args.receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
