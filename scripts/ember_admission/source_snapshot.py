# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Read-once, hash-bound source snapshots for admission candidate production."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


FILE_ATTRIBUTE_REPARSE_POINT = 0x400


@dataclass(frozen=True)
class SourceSnapshot:
    role: str
    relative_path: str
    sha256: str
    content: bytes
    source_device: int | None = None
    source_inode: int | None = None
    source_size: int | None = None
    source_mtime_ns: int | None = None
    source_ctime_ns: int | None = None


def _is_reparse_point(path: Path) -> bool:
    info = path.stat(follow_symlinks=False)
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)


def _open_regular_source(workspace: Path, relative_path: str) -> Path:
    current = workspace
    for part in relative_path.split("/"):
        current = current / part
        try:
            info = current.stat(follow_symlinks=False)
        except OSError as exc:
            raise ValueError("source.missing") from exc
        if stat.S_ISLNK(info.st_mode) or _is_reparse_point(current):
            raise ValueError("source.reparse")
    try:
        resolved = current.resolve(strict=True)
    except OSError as exc:
        raise ValueError("source.missing") from exc
    if os.path.commonpath((str(workspace), str(resolved))) != str(workspace):
        raise ValueError("source.escape")
    if not resolved.is_file():
        raise ValueError("source.type")
    return resolved


def snapshot_sources(
    workspace_path: Path,
    descriptor: Mapping[str, Any],
) -> dict[str, SourceSnapshot]:
    try:
        workspace = workspace_path.resolve(strict=True)
    except OSError as exc:
        raise ValueError("workspace.missing") from exc
    if not workspace.is_dir() or _is_reparse_point(workspace):
        raise ValueError("workspace.type")
    used_file_identities: set[tuple[int, int]] = set()
    snapshots: dict[str, SourceSnapshot] = {}
    used_paths: set[str] = set()
    for row in descriptor["roles"]:
        role = row["role"]
        relative_path = row["path"]
        source = _open_regular_source(workspace, relative_path)
        path_identity = os.path.normcase(str(source))
        source_info = source.stat(follow_symlinks=False)
        file_identity = (source_info.st_dev, source_info.st_ino)
        if (
            path_identity in used_paths
            or file_identity in used_file_identities
        ):
            raise ValueError("source.alias")
        before_read = source.stat(follow_symlinks=False)
        content = source.read_bytes()
        after_read = source.stat(follow_symlinks=False)
        if (
            before_read.st_dev != after_read.st_dev
            or before_read.st_ino != after_read.st_ino
            or before_read.st_size != after_read.st_size
            or before_read.st_mtime_ns != after_read.st_mtime_ns
            or before_read.st_ctime_ns != after_read.st_ctime_ns
            or before_read.st_size != len(content)
        ):
            raise ValueError("source.drift")
        digest = hashlib.sha256(content).hexdigest()
        used_file_identities.add(file_identity)
        if digest != row["sha256"]:
            raise ValueError("source.hash")
        used_paths.add(path_identity)
        snapshots[role] = SourceSnapshot(
            role=role,
            relative_path=relative_path,
            sha256=digest,
            content=content,
            source_device=before_read.st_dev,
            source_inode=before_read.st_ino,
            source_size=before_read.st_size,
            source_mtime_ns=before_read.st_mtime_ns,
            source_ctime_ns=before_read.st_ctime_ns,
        )
    return snapshots


def _matches_snapshot(
    path: Path,
    snapshot: SourceSnapshot,
    *,
    require_source_identity: bool = False,
) -> bool:
    try:
        before_read = path.stat(follow_symlinks=False)
        content = path.read_bytes()
        after_read = path.stat(follow_symlinks=False)
    except OSError:
        return False
    if (
        before_read.st_dev != after_read.st_dev
        or before_read.st_ino != after_read.st_ino
        or before_read.st_size != after_read.st_size
        or before_read.st_mtime_ns != after_read.st_mtime_ns
        or before_read.st_ctime_ns != after_read.st_ctime_ns
    ):
        return False
    if require_source_identity and snapshot.source_device is not None:
        if (
            before_read.st_dev != snapshot.source_device
            or before_read.st_ino != snapshot.source_inode
            or before_read.st_size != snapshot.source_size
            or before_read.st_mtime_ns != snapshot.source_mtime_ns
            or before_read.st_ctime_ns != snapshot.source_ctime_ns
        ):
            return False


    return (
        hashlib.sha256(content).hexdigest() == snapshot.sha256
        and content == snapshot.content
    )

def verify_source_snapshots(
    workspace_path: Path,
    snapshots: Mapping[str, SourceSnapshot],
) -> bool:
    try:
        workspace = workspace_path.resolve(strict=True)
    except OSError:
        return False
    for snapshot in snapshots.values():
        try:
            source = _open_regular_source(workspace, snapshot.relative_path)
        except ValueError:
            return False
        if not _matches_snapshot(source, snapshot, require_source_identity=True):
            return False
    return True


def verify_published_snapshots(
    published_paths: Mapping[str, Path],
    snapshots: Mapping[str, SourceSnapshot],
) -> bool:
    return set(published_paths) == set(snapshots) and all(
        _matches_snapshot(published_paths[role], snapshot)
        for role, snapshot in snapshots.items()
    )


def resolve_workspace_descriptor(
    workspace_path: Path,
    descriptor_path: Path,
) -> Path:
    try:
        workspace = workspace_path.resolve(strict=True)
        descriptor = descriptor_path.resolve(strict=True)
        relative = descriptor.relative_to(workspace)
    except (OSError, ValueError) as exc:
        raise ValueError("descriptor.location") from exc
    if (
        not workspace.is_dir()
        or _is_reparse_point(workspace)
        or not relative.parts
    ):
        raise ValueError("descriptor.location")
    return _open_regular_source(workspace, relative.as_posix())


def snapshot_descriptor(
    workspace_path: Path,
    descriptor_path: Path,
) -> SourceSnapshot:
    try:
        workspace = workspace_path.resolve(strict=True)
        descriptor = descriptor_path.resolve(strict=True)
        relative = descriptor.relative_to(workspace).as_posix()
        before_read = descriptor.stat(follow_symlinks=False)
        content = descriptor.read_bytes()
        after_read = descriptor.stat(follow_symlinks=False)
    except (OSError, ValueError) as exc:
        raise ValueError("descriptor.location") from exc
    if (
        not descriptor.is_file()
        or before_read.st_dev != after_read.st_dev
        or before_read.st_ino != after_read.st_ino
        or before_read.st_size != after_read.st_size
        or before_read.st_mtime_ns != after_read.st_mtime_ns
        or before_read.st_ctime_ns != after_read.st_ctime_ns
        or before_read.st_size != len(content)
    ):
        raise ValueError("descriptor.drift")
    return SourceSnapshot(
        role="input_descriptor",
        relative_path=relative,
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        source_device=before_read.st_dev,
        source_inode=before_read.st_ino,
        source_size=before_read.st_size,
        source_mtime_ns=before_read.st_mtime_ns,
        source_ctime_ns=before_read.st_ctime_ns,
    )


def verify_descriptor_snapshot(
    workspace_path: Path,
    snapshot: SourceSnapshot,
) -> bool:
    if snapshot.role != "input_descriptor":
        return False
    try:
        workspace = workspace_path.resolve(strict=True)
        descriptor = _open_regular_source(workspace, snapshot.relative_path)
    except (OSError, ValueError):
        return False
    return _matches_snapshot(
        descriptor,
        snapshot,
        require_source_identity=True,
    )
