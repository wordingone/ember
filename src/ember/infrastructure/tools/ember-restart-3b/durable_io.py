# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Small-file replacement durability shared by checkpoint writer and custody ledger."""

from __future__ import annotations

import ctypes
import os
import uuid
from pathlib import Path


def fsync_parent_directory(parent: Path) -> None:
    """Durably flush a POSIX directory entry update; Windows write-through owns this boundary."""
    if os.name == "nt":
        return
    descriptor = os.open(str(parent), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_replace_durable(source: Path, target: Path) -> None:
    """Replace a fully-fsynced small file and persist parent-directory metadata."""
    if os.name == "nt":
        movefile_replace_existing = 0x00000001
        movefile_write_through = 0x00000008
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if not kernel32.MoveFileExW(str(source), str(target), movefile_replace_existing | movefile_write_through):
            raise ctypes.WinError(ctypes.get_last_error())
        return
    os.replace(source, target)
    fsync_parent_directory(target.parent)
def atomic_create_durable(target: Path, payload: bytes) -> None:
    """Create one new small file without replacement and durably publish its directory entry."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        if os.name == "nt":
            movefile_write_through = 0x00000008
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            if not kernel32.MoveFileExW(str(temporary), str(target), movefile_write_through):
                error = ctypes.get_last_error()
                if error in {80, 183}:
                    raise FileExistsError(target)
                raise ctypes.WinError(error)
        else:
            os.link(temporary, target)
            fsync_parent_directory(target.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass