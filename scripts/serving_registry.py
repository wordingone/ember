#!/usr/bin/env python3
"""serving_registry.py — single-source-of-truth registry for all running model servers (#516).

Contract: state/serving-registry.json (ABSOLUTE runtime location: the state/ dir inside the ember repo).
Format: JSONL with one row per registered server.
Row schema: {port, model_path, pid, launched_by, ts, device}

Callers: serve_cbase_openai.py (on startup/shutdown), ember-cli body (before spawn decision),
watchdog (drift detection), and board probes (identity verification).

Operations:
  - register(port, model_path, pid, launched_by, device, registry_path=None)
    Append a row; return the full row dict.
  - deregister(port=None, pid=None, registry_path=None)
    Remove rows matching the filter (by port or by pid); return count removed.
  - read(registry_path=None) -> list[dict]
    Read all rows from the registry; return empty list if file doesn't exist.
  - find_for_model(model_path, registry_path=None) -> dict|None
    Find a registered row for the given model_path; return first match or None.

Serialization: JSON.dumps (serializer-written); atomic replace-on-write.
Tolerant reader: missing file = empty registry.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Try to infer REPO_ROOT; fallback to None for tests that pass explicit paths.
try:
    _SCRIPT_PATH = Path(__file__).resolve()
    _REPO_ROOT = _SCRIPT_PATH.parent.parent
    REGISTRY_PATH_DEFAULT = _REPO_ROOT / "state" / "serving-registry.json"
except Exception:
    REGISTRY_PATH_DEFAULT = None


def _now_iso() -> str:
    """Return current UTC time in ISO8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def register(
    port: int,
    model_path: str,
    pid: int,
    launched_by: str,
    device: str = "cuda",
    registry_path: Optional[str | Path] = None,
) -> dict[str, Any]:
    """Register a new server in the registry.

    Args:
        port: serving port (e.g., 8082 or 8083)
        model_path: absolute path to the model checkpoint
        pid: process ID of the server
        launched_by: identifier of the launcher (e.g., "watchdog", "serve_cbase_openai", "ember-cli-body")
        device: "cuda" or "cpu"
        registry_path: path to registry file (default: REGISTRY_PATH_DEFAULT)

    Returns:
        dict with the registered row including ts.
    """
    registry_path = Path(registry_path or REGISTRY_PATH_DEFAULT)

    row = {
        "port": port,
        "model_path": str(model_path),
        "pid": pid,
        "launched_by": launched_by,
        "ts": _now_iso(),
        "device": device,
    }

    # Read existing rows
    rows = read(registry_path=registry_path)

    # Append new row
    rows.append(row)

    # Atomic replace-on-write
    _write_atomic(rows, registry_path)

    return row


def deregister(
    port: Optional[int] = None,
    pid: Optional[int] = None,
    registry_path: Optional[str | Path] = None,
) -> int:
    """Deregister server(s) from the registry.

    Args:
        port: remove by port (mutually exclusive with pid)
        pid: remove by pid (mutually exclusive with port)
        registry_path: path to registry file

    Returns:
        Number of rows removed.
    """
    if port is None and pid is None:
        raise ValueError("Must specify either port or pid")
    if port is not None and pid is not None:
        raise ValueError("Cannot specify both port and pid")

    registry_path = Path(registry_path or REGISTRY_PATH_DEFAULT)

    rows = read(registry_path=registry_path)
    original_count = len(rows)

    if port is not None:
        rows = [r for r in rows if r.get("port") != port]
    else:
        rows = [r for r in rows if r.get("pid") != pid]

    removed_count = original_count - len(rows)

    # Write back
    _write_atomic(rows, registry_path)

    return removed_count


def read(registry_path: Optional[str | Path] = None) -> list[dict[str, Any]]:
    """Read all rows from the registry.

    Args:
        registry_path: path to registry file (default: REGISTRY_PATH_DEFAULT)

    Returns:
        List of row dicts; empty list if file doesn't exist.
    """
    registry_path = Path(registry_path or REGISTRY_PATH_DEFAULT)

    if not registry_path.exists():
        return []

    rows = []
    try:
        content = registry_path.read_text(encoding="utf-8")
        for line in content.strip().split("\n"):
            if line.strip():
                rows.append(json.loads(line))
    except Exception as e:
        # Tolerant reader: log but don't crash
        print(f"WARNING: Failed to read registry {registry_path}: {e}", file=sys.stderr)

    return rows


def find_for_model(
    model_path: str,
    registry_path: Optional[str | Path] = None,
) -> Optional[dict[str, Any]]:
    """Find a registered server for the given model_path.

    Args:
        model_path: model path to search for
        registry_path: path to registry file

    Returns:
        First matching row dict, or None if not found.
    """
    rows = read(registry_path=registry_path)
    for row in rows:
        if row.get("model_path") == str(model_path):
            return row
    return None


def _write_atomic(rows: list[dict[str, Any]], registry_path: Path) -> None:
    """Write rows to registry with atomic replace-on-write.

    Atomicity: write to temp file first, then rename.
    """
    registry_path = Path(registry_path)

    # Ensure parent directory exists
    registry_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file
    temp_path = registry_path.with_suffix(".tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

        # Atomic rename
        temp_path.replace(registry_path)
    except Exception as e:
        # Clean up temp file on error
        if temp_path.exists():
            temp_path.unlink()
        raise RuntimeError(f"Failed to write registry {registry_path}: {e}") from e


# Self-test (run via: python serving_registry.py selftest)
def _selftest():
    """Quick self-test of the registry operations."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        test_registry = Path(tmpdir) / "test-registry.json"

        # Test register
        row1 = register(8082, "/path/to/model27b", 1234, "watchdog", "cuda", test_registry)
        assert row1["port"] == 8082
        assert row1["pid"] == 1234

        # Test read
        rows = read(test_registry)
        assert len(rows) == 1

        # Test register second
        row2 = register(8083, "/path/to/model2.2b", 5678, "serve_cbase_openai", "cuda", test_registry)
        rows = read(test_registry)
        assert len(rows) == 2

        # Test find_for_model
        found = find_for_model("/path/to/model27b", test_registry)
        assert found is not None
        assert found["pid"] == 1234

        # Test deregister by port
        removed = deregister(port=8082, registry_path=test_registry)
        assert removed == 1
        rows = read(test_registry)
        assert len(rows) == 1

        # Test deregister by pid
        removed = deregister(pid=5678, registry_path=test_registry)
        assert removed == 1
        rows = read(test_registry)
        assert len(rows) == 0

        print("All self-tests passed!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        _selftest()
    else:
        print(__doc__)
