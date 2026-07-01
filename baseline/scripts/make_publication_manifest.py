#!/usr/bin/env python3
"""Emit a non-self-referential publication manifest for baseline/."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

EXCLUDED = {
    "completion-lock.json",
    "receipts/acceptance-readiness-redteam-2026-06-29.json",
    "receipts/completion-verifier-fail-repaired-goal-2026-06-29.json",
    "receipts/publication-manifest-2026-06-29.json",
    "receipts/publication-surface-validation-2026-06-29.json",
    "receipts/remote-proof-2026-06-29.json",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build(root: Path) -> dict[str, Any]:
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        if rel in EXCLUDED:
            continue
        files.append({"path": rel, "sha256": sha256(path), "size_bytes": path.stat().st_size})
    manifest_input = "\n".join(f"{row['sha256']}  {row['path']}" for row in files)
    return {
        "root": "baseline",
        "hash_policy": "sha256 over substantive baseline files excluding self-referential lock/proof receipts",
        "excluded_paths": sorted(EXCLUDED),
        "manifest_hash": hashlib.sha256(manifest_input.encode("utf-8")).hexdigest(),
        "file_count": len(files),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    result = build(args.root.resolve())
    text = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
