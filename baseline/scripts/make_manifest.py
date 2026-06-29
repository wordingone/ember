#!/usr/bin/env python3
"""Emit a deterministic manifest for a baseline tree."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SKIP_PARTS = {".git", "__pycache__"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    files = []
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            files.append({"path": rel, "sha256": sha256(path), "size_bytes": path.stat().st_size})
    tree_hash = hashlib.sha256("\n".join(f"{row['sha256']}  {row['path']}" for row in files).encode("utf-8")).hexdigest()
    print(json.dumps({"root": str(root), "tree_hash": tree_hash, "files": files}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())