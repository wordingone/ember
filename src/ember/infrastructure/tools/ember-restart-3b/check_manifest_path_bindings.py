#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail when a repository data manifest has a stale or hash-drifted path binding."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterator


PATH_MIGRATIONS = {
    "tokenizer/tokenizer.json": "domains/model/tokenizer/tokenizer.json",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bindings(value: object, pointer: str = "$") -> Iterator[tuple[str, str, str]]:
    if isinstance(value, dict):
        path = value.get("path")
        digest = value.get("sha256")
        if isinstance(path, str) and isinstance(digest, str):
            yield pointer, path, digest
        for key, child in value.items():
            yield from bindings(child, f"{pointer}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from bindings(child, f"{pointer}[{index}]")


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    manifest_root = root / "data" / "ember-restart-3b"
    for manifest in sorted(manifest_root.glob("*.json")):
        try:
            value = json.loads(manifest.read_bytes())
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"{manifest.relative_to(root).as_posix()}: invalid JSON: {error}")
            continue
        for pointer, relative, expected in bindings(value):
            if Path(relative).is_absolute() or "\\" in relative or ".." in Path(relative).parts:
                errors.append(
                    f"{manifest.relative_to(root).as_posix()}:{pointer}: noncanonical path {relative!r}"
                )
                continue
            candidates = [root / relative, manifest.parent / relative]
            migrated = PATH_MIGRATIONS.get(relative)
            if migrated is not None:
                candidates.append(root / migrated)
            existing = next((candidate for candidate in candidates if candidate.is_file()), None)
            if existing is None:
                errors.append(
                    f"{manifest.relative_to(root).as_posix()}:{pointer}: missing binding {relative}"
                )
                continue
            if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
                errors.append(
                    f"{manifest.relative_to(root).as_posix()}:{pointer}: invalid sha256 for {relative}"
                )
                continue
            actual = sha256(existing)
            if actual != expected:
                errors.append(
                    f"{manifest.relative_to(root).as_posix()}:{pointer}: sha256 mismatch for "
                    f"{relative}: expected={expected} actual={actual}"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = validate(args.root.resolve())
    if errors:
        print("MANIFEST_PATH_BINDINGS_REFUSED")
        for error in errors:
            print(error)
        return 1
    print("MANIFEST_PATH_BINDINGS_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
