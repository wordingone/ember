#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bounded, read-only custody census for the repository ``scratch/`` surface.

The census never moves or deletes bytes.  It records only relative paths and
content digests, and the guard reopens the same root before accepting a
receipt.  Large or ambiguous trees fail closed before a manifest is written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SCHEMA_VERSION = "ember-scratch-custody-v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_REPARSE_POINT = 0x0400
_MANIFEST_KEYS = {
    "schema_version",
    "label",
    "target",
    "source_commit",
    "source_status_sha256",
    "policy",
    "entries",
    "top_level",
    "summary",
    "manifest_sha256",
}
_ENTRY_KEYS = {"path", "kind", "bytes", "sha256", "tracked"}
_TOP_LEVEL_KEYS = {"path", "files", "bytes", "sha256"}
_POLICY_KEYS = {"max_bytes", "max_files", "read_only", "reparse_refused"}


class CensusError(ValueError):
    """Raised for an untrusted, changed, or over-budget census input."""


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = os.lstat(path).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & _REPARSE_POINT)


def _safe_relative(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise CensusError("path escapes census root") from exc
    text = PurePosixPath(*relative.parts).as_posix()
    if not text or text.startswith("/") or "\\" in text:
        raise CensusError("ambiguous census path")
    if any(part in {"", ".", ".."} for part in PurePosixPath(text).parts):
        raise CensusError("ambiguous census path")
    return text


def _walk_files(target: Path, max_bytes: int, max_files: int) -> list[tuple[str, int, str]]:
    if _is_reparse(target):
        raise CensusError("symlink or reparse point in census root")
    if not target.is_dir():
        raise CensusError("census target is not a directory")
    files: list[tuple[str, int, str]] = []
    total = 0
    stack = [target]
    while stack:
        current = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name, reverse=True)
        except OSError as exc:
            raise CensusError("census root cannot be read") from exc
        for child in children:
            if _is_reparse(child):
                raise CensusError(f"symlink or reparse point: {child.name}")
            if child.is_dir():
                stack.append(child)
                continue
            if not child.is_file():
                raise CensusError("unsupported filesystem entry in census root")
            try:
                size = child.stat().st_size
            except OSError as exc:
                raise CensusError("census file cannot be stat'ed") from exc
            total += size
            if total > max_bytes:
                raise CensusError("byte budget exceeded before manifest")
            if len(files) >= max_files:
                raise CensusError("file-count budget exceeded before manifest")
            digest = hashlib.sha256()
            try:
                with child.open("rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
            except OSError as exc:
                raise CensusError("census file cannot be read") from exc
            files.append((_safe_relative(child, target), size, digest.hexdigest()))
    return sorted(files)


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _source_binding(root: Path) -> tuple[str, str, set[str]]:
    commit = _git(root, "rev-parse", "HEAD") or "UNBOUND"
    status = _git(root, "status", "--porcelain", "--untracked-files=all") or ""
    tracked_text = _git(root, "ls-files", "--", "scratch") or ""
    tracked = {line.replace("\\", "/") for line in tracked_text.splitlines() if line}
    return commit, _sha256(status.encode("utf-8")), tracked


def _top_level(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        first = entry["path"].split("/", 1)[0]
        grouped.setdefault(first, []).append(entry)
    result = []
    for path, rows in sorted(grouped.items()):
        payload = [{key: row[key] for key in ("path", "bytes", "sha256")} for row in rows]
        result.append(
            {
                "path": path,
                "files": len(rows),
                "bytes": sum(row["bytes"] for row in rows),
                "sha256": _sha256(_canonical_json(payload)),
            }
        )
    return result


def build_manifest(
    root: Path,
    *,
    label: str,
    target: str = "scratch",
    max_bytes: int,
    max_files: int = 100_000,
) -> dict[str, Any]:
    if not isinstance(label, str) or not label or "/" in label or "\\" in label:
        raise CensusError("label must be a single nonempty name")
    if type(max_bytes) is not int or max_bytes < 0:
        raise CensusError("max_bytes must be a nonnegative integer")
    if type(max_files) is not int or max_files <= 0:
        raise CensusError("max_files must be a positive integer")
    root = Path(root)
    if _is_reparse(root) or not root.is_dir():
        raise CensusError("census root is not a real directory")
    target_path = root / target
    if target != "scratch" or Path(target).name != target or target in {"", ".", ".."}:
        raise CensusError("target must be the repository scratch directory")
    rows = _walk_files(target_path, max_bytes, max_files)
    source_commit, status_sha, tracked = _source_binding(root)
    entries = [
        {
            "path": path,
            "kind": "file",
            "bytes": size,
            "sha256": digest,
            "tracked": f"scratch/{path}" in tracked,
        }
        for path, size, digest in rows
    ]
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "label": label,
        "target": target,
        "source_commit": source_commit,
        "source_status_sha256": status_sha,
        "policy": {
            "max_bytes": max_bytes,
            "max_files": max_files,
            "read_only": True,
            "reparse_refused": True,
        },
        "entries": entries,
        "top_level": _top_level(entries),
        "summary": {"files": len(entries), "bytes": sum(row["bytes"] for row in entries)},
        "manifest_sha256": "",
    }
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    return manifest


def manifest_sha256(manifest: dict[str, Any]) -> str:
    candidate = dict(manifest)
    candidate.pop("manifest_sha256", None)
    return _sha256(_canonical_json(candidate))


def _validate_shape(manifest: Any) -> None:
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise CensusError("manifest schema is not closed")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise CensusError("manifest schema version mismatch")
    if not isinstance(manifest["label"], str) or not manifest["label"]:
        raise CensusError("manifest label is invalid")
    if manifest["target"] != "scratch":
        raise CensusError("manifest target is invalid")
    if not isinstance(manifest["source_commit"], str):
        raise CensusError("source commit is invalid")
    if not isinstance(manifest["policy"], dict) or set(manifest["policy"]) != _POLICY_KEYS:
        raise CensusError("manifest policy schema is not closed")
    policy = manifest["policy"]
    if type(policy["max_bytes"]) is not int or policy["max_bytes"] < 0:
        raise CensusError("manifest max_bytes is invalid")
    if type(policy["max_files"]) is not int or policy["max_files"] <= 0:
        raise CensusError("manifest max_files is invalid")
    if policy["read_only"] is not True or policy["reparse_refused"] is not True:
        raise CensusError("manifest policy is not fail-closed")
    if not _HEX64.fullmatch(manifest["source_status_sha256"]):
        raise CensusError("source status digest is invalid")
    if not isinstance(manifest["entries"], list) or not isinstance(manifest["top_level"], list):
        raise CensusError("manifest inventory is invalid")
    seen_paths: set[str] = set()
    for entry in manifest["entries"]:
        if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
            raise CensusError("manifest entry schema is not closed")
        if (
            not isinstance(entry["path"], str)
            or "\\" in entry["path"]
            or Path(entry["path"]).is_absolute()
            or any(part in {"", ".", ".."} for part in PurePosixPath(entry["path"]).parts)
            or entry["path"] in seen_paths
        ):
            raise CensusError("manifest entry path is invalid")
        seen_paths.add(entry["path"])
        if type(entry["bytes"]) is not int or entry["bytes"] < 0:
            raise CensusError("manifest entry bytes are invalid")
        if not isinstance(entry["tracked"], bool) or not _HEX64.fullmatch(entry["sha256"]):
            raise CensusError("manifest entry digest is invalid")
    for row in manifest["top_level"]:
        if not isinstance(row, dict) or set(row) != _TOP_LEVEL_KEYS:
            raise CensusError("manifest top-level schema is not closed")
    if not isinstance(manifest["summary"], dict) or set(manifest["summary"]) != {"files", "bytes"}:
        raise CensusError("manifest summary schema is not closed")
    if type(manifest["summary"]["files"]) is not int or type(manifest["summary"]["bytes"]) is not int:
        raise CensusError("manifest summary is invalid")
    if not _HEX64.fullmatch(manifest["manifest_sha256"]):
        raise CensusError("manifest digest is invalid")
    if manifest["manifest_sha256"] != manifest_sha256(manifest):
        raise CensusError("manifest hash mismatch")


def validate_manifest(root: Path, manifest: dict[str, Any], *, require_git: bool = False) -> dict[str, Any]:
    _validate_shape(manifest)
    root = Path(root)
    current = build_manifest(
        root,
        label=manifest["label"],
        target=manifest["target"],
        max_bytes=manifest["policy"]["max_bytes"],
        max_files=manifest["policy"]["max_files"],
    )
    if require_git and not _HEX40.fullmatch(current["source_commit"]):
        raise CensusError("guard requires a Git source commit")
    expected_entries = {row["path"]: row for row in current["entries"]}
    for row in manifest["entries"]:
        actual = expected_entries.get(row["path"])
        if actual is None or actual["bytes"] != row["bytes"] or actual["sha256"] != row["sha256"]:
            raise CensusError("entry bytes or digest mismatch")
    if current != manifest:
        raise CensusError("manifest drift")
    return manifest


def write_manifest(root: Path, output: Path, *, label: str, target: str = "scratch", max_bytes: int, max_files: int = 100_000) -> Path:
    output = Path(output)
    if output.exists():
        raise CensusError("manifest destination already exists")
    manifest = build_manifest(root, label=label, target=target, max_bytes=max_bytes, max_files=max_files)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_bytes(_canonical_json(manifest))
    os.replace(temporary, output)
    return output


def _cli(argv: Iterable[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    census = subparsers.add_parser("census")
    census.add_argument("--root", required=True, type=Path)
    census.add_argument("--output", required=True, type=Path)
    census.add_argument("--label", required=True)
    census.add_argument("--max-bytes", required=True, type=int)
    census.add_argument("--max-files", type=int, default=100_000)
    guard = subparsers.add_parser("guard")
    guard.add_argument("--root", required=True, type=Path)
    guard.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args(list(argv))
    try:
        if args.command == "census":
            write_manifest(args.root, args.output, label=args.label, max_bytes=args.max_bytes, max_files=args.max_files)
            print("CENSUS_WRITTEN")
        else:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            validate_manifest(args.root, manifest, require_git=True)
            print("CENSUS_GUARD_PASS")
        return 0
    except (CensusError, OSError, json.JSONDecodeError) as exc:
        print(f"CENSUS_REFUSED: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_cli(os.sys.argv[1:]))
