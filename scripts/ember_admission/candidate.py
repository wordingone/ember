# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Private staging, no-replace publication, and quarantine for candidates."""

from __future__ import annotations

import ctypes
import os
import stat
import secrets
from pathlib import Path
from typing import Mapping

from source_snapshot import SourceSnapshot

FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _is_reparse_point(path: Path) -> bool:
    info = path.stat(follow_symlinks=False)
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(
        attributes & FILE_ATTRIBUTE_REPARSE_POINT
    )


def _validated_output_root(output_root: Path) -> Path:
    absolute = output_root.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if not current.exists():
            break
        if _is_reparse_point(current):
            raise ValueError("output.reparse")
        if not current.is_dir():
            raise ValueError("output.type")
    absolute.mkdir(parents=True, exist_ok=True)
    if _is_reparse_point(absolute) or not absolute.is_dir():
        raise ValueError("output.reparse")
    return absolute.resolve(strict=True)



def _write_snapshot(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def stage_candidate(
    output_root: Path,
    candidate_id: str,
    snapshots: Mapping[str, SourceSnapshot],
) -> tuple[Path, dict[str, Path], Path]:
    root = _validated_output_root(output_root)
    destination = root / candidate_id
    if destination.exists():
        raise ValueError("candidate.exists")
    staging = root / f".{candidate_id}.staging-{secrets.token_hex(8)}"
    staging.mkdir()
    try:
        staged_paths: dict[str, Path] = {}
        for role, snapshot in snapshots.items():
            target = staging / Path(snapshot.relative_path)
            _write_snapshot(target, snapshot.content)
            staged_paths[role] = target
    except Exception:
        if staging.exists():
            for child in sorted(staging.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            staging.rmdir()
        raise


    return staging, staged_paths, destination


def publish_staged_candidate(
    staging: Path,
    destination: Path,
    snapshots: Mapping[str, SourceSnapshot],
) -> tuple[Path, dict[str, Path]]:
    if not staging.is_dir():
        raise ValueError("candidate.staging")
    if destination.exists():
        raise ValueError("candidate.exists")
    if os.name == "nt":
        movefile_write_through = 0x00000008
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if not kernel32.MoveFileExW(
            str(staging),
            str(destination),
            movefile_write_through,
        ):
            error = ctypes.get_last_error()
            if error in {80, 183}:
                raise ValueError("candidate.exists")
            raise ValueError("candidate.publish") from ctypes.WinError(error)
    else:
        try:
            staging.rename(destination)
            directory = os.open(str(destination.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError as exc:
            raise ValueError("candidate.publish") from exc
    published_paths = {
        role: destination / Path(snapshot.relative_path)
        for role, snapshot in snapshots.items()
    }
    return destination, published_paths


def quarantine_candidate(candidate: Path) -> None:
    if not candidate.exists():
        return
    quarantine = candidate.parent / ".quarantine"
    quarantine.mkdir(exist_ok=True)
    destination = quarantine / f"{candidate.name}-{secrets.token_hex(8)}"
    candidate.rename(destination)
