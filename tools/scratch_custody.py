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
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SCHEMA_VERSION = "ember-scratch-custody-v1"
DISPOSITION_TICKET = "ISSUE-1450-SCRATCH-DISPOSITION"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
AUTHORITY = {
    "goal_id": "EMBER-02",
    "workstream_id": "EMBER-02A",
    "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_REPARSE_POINT = 0x0400
_MANIFEST_KEYS = {
    "schema_version",
    "authority",
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
_DISPOSITION_KEYS = {
    "schema_version", "ticket", "ts", "sha_convention", "invariant_sha256", "authority",
    "source_manifest_sha256", "source", "entries", "summary", "disposition_sha256",
}
_DISPOSITION_SOURCE_KEYS = {"commit", "status_sha256", "files", "bytes"}
_DISPOSITION_ENTRY_KEYS = {
    "path", "files", "bytes", "tree_sha256", "producer", "issue_or_run",
    "references", "identical_copy", "disposition",
}
_ANNOTATION_KEYS = {"producer", "issue_or_run", "references", "identical_copy"}


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
    top_level = _git(root, "rev-parse", "--show-toplevel")
    commit = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain", "--untracked-files=all")
    tracked_text = _git(root, "ls-files", "--", "scratch")
    if top_level is None or commit is None or status is None or tracked_text is None:
        raise CensusError("Git source binding cannot be read")
    if Path(top_level).resolve(strict=True) != root.resolve(strict=True):
        raise CensusError("census root must be the Git repository root")
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
        "authority": dict(AUTHORITY),
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


def _validate_authority(value: Any) -> None:
    if not isinstance(value, dict) or value != AUTHORITY:
        raise CensusError("authority binding mismatch")


def _validate_shape(manifest: Any) -> None:
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise CensusError("manifest schema is not closed")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise CensusError("manifest schema version mismatch")
    _validate_authority(manifest["authority"])
    if not isinstance(manifest["label"], str) or not manifest["label"]:
        raise CensusError("manifest label is invalid")
    if manifest["target"] != "scratch":
        raise CensusError("manifest target is invalid")
    if not isinstance(manifest["source_commit"], str) or not _HEX40.fullmatch(
        manifest["source_commit"]
    ):
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
        if entry["kind"] != "file":
            raise CensusError("manifest entry kind is invalid")
        if type(entry["bytes"]) is not int or entry["bytes"] < 0:
            raise CensusError("manifest entry bytes are invalid")
        if not isinstance(entry["tracked"], bool) or not _HEX64.fullmatch(entry["sha256"]):
            raise CensusError("manifest entry digest is invalid")
    if [entry["path"] for entry in manifest["entries"]] != sorted(seen_paths):
        raise CensusError("manifest entry order is not canonical")
    seen_top_level: set[str] = set()
    for row in manifest["top_level"]:
        if not isinstance(row, dict) or set(row) != _TOP_LEVEL_KEYS:
            raise CensusError("manifest top-level schema is not closed")
        if (
            not isinstance(row["path"], str)
            or not row["path"]
            or "/" in row["path"]
            or "\\" in row["path"]
            or row["path"] in {".", ".."}
            or row["path"] in seen_top_level
        ):
            raise CensusError("manifest top-level path is invalid")
        seen_top_level.add(row["path"])
        if type(row["files"]) is not int or row["files"] <= 0:
            raise CensusError("manifest top-level file count is invalid")
        if type(row["bytes"]) is not int or row["bytes"] < 0:
            raise CensusError("manifest top-level byte count is invalid")
        if not _HEX64.fullmatch(row["sha256"]):
            raise CensusError("manifest top-level digest is invalid")
    if not isinstance(manifest["summary"], dict) or set(manifest["summary"]) != {"files", "bytes"}:
        raise CensusError("manifest summary schema is not closed")
    if type(manifest["summary"]["files"]) is not int or type(manifest["summary"]["bytes"]) is not int:
        raise CensusError("manifest summary is invalid")
    if manifest["top_level"] != _top_level(manifest["entries"]):
        raise CensusError("manifest top-level projection mismatch")
    expected_summary = {
        "files": len(manifest["entries"]),
        "bytes": sum(entry["bytes"] for entry in manifest["entries"]),
    }
    if manifest["summary"] != expected_summary:
        raise CensusError("manifest summary projection mismatch")
    if not _HEX64.fullmatch(manifest["manifest_sha256"]):
        raise CensusError("manifest digest is invalid")
    if manifest["manifest_sha256"] != manifest_sha256(manifest):
        raise CensusError("manifest hash mismatch")


def disposition_sha256(disposition: dict[str, Any]) -> str:
    candidate = dict(disposition)
    candidate.pop("disposition_sha256", None)
    return _sha256(_canonical_json(candidate))


def _is_path_free_text(value: str) -> bool:
    slash_parts = value.split("/")
    return (
        "\\" not in value
        and "\n" not in value
        and "\r" not in value
        and not value.startswith("/")
        and not value.lower().startswith("file:")
        and re.match(r"(?i)^[a-z]:", value) is None
        and not any(part in {".", ".."} for part in slash_parts)
    )


def _validate_annotation(annotation: Any, *, require_canonical: bool = False) -> None:
    if not isinstance(annotation, dict) or set(annotation) != _ANNOTATION_KEYS:
        raise CensusError("annotation schema is not closed")
    if (
        not isinstance(annotation["producer"], str)
        or not annotation["producer"]
        or not isinstance(annotation["issue_or_run"], str)
        or not annotation["issue_or_run"]
    ):
        raise CensusError("annotation identity is invalid")
    references = annotation["references"]
    if not isinstance(references, list) or not all(
        isinstance(reference, str) and reference for reference in references
    ):
        raise CensusError("annotation references are invalid")
    if require_canonical and references != sorted(set(references)):
        raise CensusError("annotation references are not canonical")
    annotation_text = [annotation["producer"], annotation["issue_or_run"], *references]
    if not all(_is_path_free_text(value) for value in annotation_text):
        raise CensusError("annotation text is not path-free")
    if annotation["identical_copy"] not in {
        "PROVEN_DIFFERENT", "NOT_FOUND", "UNRESOLVED",
    }:
        raise CensusError("annotation copy disposition is invalid")


def build_disposition(
    manifest: dict[str, Any], annotations: dict[str, dict[str, Any]], *, ts: str | None = None,
) -> dict[str, Any]:
    _validate_shape(manifest)
    if not isinstance(annotations, dict):
        raise CensusError("annotations must be an object")
    top_level = {row["path"]: row for row in manifest["top_level"]}
    foreign = sorted(set(annotations) - set(top_level))
    if foreign:
        raise CensusError("annotation path is outside the census")
    entries = []
    for path, census_row in sorted(top_level.items()):
        annotation = annotations.get(
            path,
            {
                "producer": "UNKNOWN",
                "issue_or_run": "UNKNOWN",
                "references": [],
                "identical_copy": "UNRESOLVED",
            },
        )
        _validate_annotation(annotation)
        annotation = dict(annotation)
        annotation["references"] = sorted(set(annotation["references"]))
        entries.append(
            {
                "path": path,
                "files": census_row["files"],
                "bytes": census_row["bytes"],
                "tree_sha256": census_row["sha256"],
                "producer": annotation["producer"],
                "issue_or_run": annotation["issue_or_run"],
                "references": annotation["references"],
                "identical_copy": annotation["identical_copy"],
                "disposition": "KEEP_UNRESOLVED",
            }
        )
    disposition: dict[str, Any] = {
        "schema_version": "ember-scratch-disposition-v1",
        "ticket": DISPOSITION_TICKET,
        "ts": ts or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sha_convention": SHA_CONVENTION,
        "invariant_sha256": INVARIANT_SHA256,
        "authority": dict(AUTHORITY),
        "source_manifest_sha256": manifest["manifest_sha256"],
        "source": {
            "commit": manifest["source_commit"],
            "status_sha256": manifest["source_status_sha256"],
            "files": manifest["summary"]["files"],
            "bytes": manifest["summary"]["bytes"],
        },
        "entries": entries,
        "summary": {
            "entries": len(entries),
            "keep_unresolved": len(entries),
            "move_ready": 0,
        },
        "disposition_sha256": "",
    }
    disposition["disposition_sha256"] = disposition_sha256(disposition)
    return disposition


def validate_disposition(
    manifest: dict[str, Any], disposition: dict[str, Any],
) -> dict[str, Any]:
    _validate_shape(manifest)
    if not isinstance(disposition, dict) or set(disposition) != _DISPOSITION_KEYS:
        raise CensusError("disposition schema is not closed")
    if disposition["schema_version"] != "ember-scratch-disposition-v1":
        raise CensusError("disposition schema version mismatch")
    if disposition["ticket"] != DISPOSITION_TICKET:
        raise CensusError("disposition ticket mismatch")
    if disposition["sha_convention"] != SHA_CONVENTION:
        raise CensusError("disposition sha convention mismatch")
    if disposition["invariant_sha256"] != INVARIANT_SHA256:
        raise CensusError("disposition invariant mismatch")
    try:
        parsed_ts = datetime.fromisoformat(disposition["ts"].replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise CensusError("disposition timestamp is invalid") from exc
    if parsed_ts.tzinfo is None:
        raise CensusError("disposition timestamp is invalid")
    _validate_authority(disposition["authority"])
    if disposition["source_manifest_sha256"] != manifest["manifest_sha256"]:
        raise CensusError("disposition source manifest mismatch")
    expected_source = {
        "commit": manifest["source_commit"],
        "status_sha256": manifest["source_status_sha256"],
        "files": manifest["summary"]["files"],
        "bytes": manifest["summary"]["bytes"],
    }
    if (
        not isinstance(disposition["source"], dict)
        or set(disposition["source"]) != _DISPOSITION_SOURCE_KEYS
        or disposition["source"] != expected_source
    ):
        raise CensusError("disposition source binding mismatch")
    if disposition["disposition_sha256"] != disposition_sha256(disposition):
        raise CensusError("disposition hash mismatch")
    entries = disposition["entries"]
    if not isinstance(entries, list):
        raise CensusError("disposition entries are invalid")
    census_rows = {row["path"]: row for row in manifest["top_level"]}
    seen: set[str] = set()
    entry_order: list[str] = []
    for row in entries:
        if not isinstance(row, dict) or set(row) != _DISPOSITION_ENTRY_KEYS:
            raise CensusError("disposition entry schema is not closed")
        path = row["path"]
        if not isinstance(path, str) or path in seen or path not in census_rows:
            raise CensusError("disposition entry path is invalid")
        seen.add(path)
        entry_order.append(path)
        census_row = census_rows[path]
        if (
            row["files"] != census_row["files"]
            or row["bytes"] != census_row["bytes"]
            or row["tree_sha256"] != census_row["sha256"]
        ):
            raise CensusError("disposition census binding mismatch")
        _validate_annotation(
            {key: row[key] for key in _ANNOTATION_KEYS},
            require_canonical=True,
        )
        if row["disposition"] != "KEEP_UNRESOLVED":
            raise CensusError("disposition grants unsupported move authority")
    if seen != set(census_rows):
        raise CensusError("disposition is not set-equal to census")
    if entry_order != sorted(entry_order):
        raise CensusError("disposition entry order is not canonical")
    expected_summary = {
        "entries": len(entries),
        "keep_unresolved": len(entries),
        "move_ready": 0,
    }
    if disposition["summary"] != expected_summary:
        raise CensusError("disposition summary mismatch")
    return disposition


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
    manifest = build_manifest(root, label=label, target=target, max_bytes=max_bytes, max_files=max_files)
    return _write_new_document(Path(output), _canonical_json(manifest), "manifest")


def _write_new_document(output: Path, payload: bytes, kind: str) -> Path:
    if output.exists():
        raise CensusError(f"{kind} destination already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise CensusError(f"{kind} temporary already exists") from exc
    try:
        os.link(temporary, output)
    except FileExistsError as exc:
        temporary.unlink()
        raise CensusError(f"{kind} destination already exists") from exc
    except OSError:
        temporary.unlink()
        raise
    temporary.unlink()
    return output


def write_disposition(
    manifest: dict[str, Any], annotations: dict[str, dict[str, Any]], output: Path,
) -> Path:
    disposition = build_disposition(manifest, annotations)
    return _write_new_document(Path(output), _canonical_json(disposition), "disposition")


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
    disposition = subparsers.add_parser("disposition")
    disposition.add_argument("--manifest", required=True, type=Path)
    disposition.add_argument("--annotations", required=True, type=Path)
    disposition.add_argument("--output", required=True, type=Path)
    disposition_guard = subparsers.add_parser("disposition-guard")
    disposition_guard.add_argument("--manifest", required=True, type=Path)
    disposition_guard.add_argument("--disposition", required=True, type=Path)
    args = parser.parse_args(list(argv))
    try:
        if args.command == "census":
            write_manifest(args.root, args.output, label=args.label, max_bytes=args.max_bytes, max_files=args.max_files)
            print("CENSUS_WRITTEN")
        elif args.command == "guard":
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            validate_manifest(args.root, manifest, require_git=True)
            print("CENSUS_GUARD_PASS")
        elif args.command == "disposition":
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            annotations = json.loads(args.annotations.read_text(encoding="utf-8"))
            write_disposition(manifest, annotations, args.output)
            print("DISPOSITION_WRITTEN")
        else:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            disposition_doc = json.loads(args.disposition.read_text(encoding="utf-8"))
            validate_disposition(manifest, disposition_doc)
            print("DISPOSITION_GUARD_PASS")
        return 0
    except (CensusError, OSError, json.JSONDecodeError) as exc:
        print(f"CENSUS_REFUSED: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_cli(os.sys.argv[1:]))
