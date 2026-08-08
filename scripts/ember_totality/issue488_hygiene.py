# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed, reviewable repository-hygiene inventory for issue #488.

The scanner is read-only.  Applying a reviewed manifest is an explicit,
content-addressed operation and never touches ``.git`` or untracked bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import argparse
import datetime as _dt
import sys
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
GOAL_ID = "EMBER-02"
WORKSTREAM_ID = "EMBER-02A"
NEXT_EXECUTED_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
_HEX64 = set("0123456789abcdef")


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
                "references": refs[:20],
                "action": "PROTECTED_EVIDENCE" if protected else "DELETE_CANDIDATE",
                "superseded_by": canonical,
                "reason": "byte-identical duplicate with no tracked reference" if not protected else "referenced tracked evidence",
            })
    return candidates


def build_reference_manifest(repo_root: str | os.PathLike[str]) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    tracked = _tracked_paths(root)
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
        "working_set": compute_working_set(str(root)),
        "inventory": inventory,
        "candidates": candidates,
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


def apply_safe_cleanup(
    repo_root: str | os.PathLike[str],
    manifest: dict[str, Any],
    paths: list[str],
    receipt_path: str | os.PathLike[str],
) -> dict[str, Any]:
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ValueError("unsupported hygiene manifest")
    rows = {row.get("path"): row for row in manifest.get("candidates", [])}
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate cleanup path")
    root = Path(repo_root).resolve()
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
        working_set_after = compute_working_set(str(root))
        receipt = {
            "ticket": "EMBER-488-HYGIENE",
            "ts": _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
            "schema_version": CLEANUP_SCHEMA,
            "goal_id": GOAL_ID,
            "workstream_id": WORKSTREAM_ID,
            "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
            "artifact_class": "hygiene_evidence",
            "manifest_sha256": manifest.get("manifest_sha256"),
            "before": before,
            "after": after,
            "working_set_before": working_set_before,
            "working_set_after_cleanup": working_set_after,
            "deleted": deleted,
            "rollback": {"files": deleted, "action": "restore exact bytes from the recorded hashes"},
            "non_regression": {"git_metadata_mutated": False, "private_or_untracked_bytes_deleted": False},
        }
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Issue #488 closed hygiene inventory")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan = subparsers.add_parser("scan")
    scan.add_argument("repo_root", type=Path)
    scan.add_argument("manifest", type=Path)
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
    else:
        payload = json.loads(args.manifest.read_text(encoding="utf-8"))
        apply_safe_cleanup(args.repo_root, payload, args.paths, args.receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
