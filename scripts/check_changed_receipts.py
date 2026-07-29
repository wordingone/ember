#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail closed on changed receipt JSON paths supplied on stdin."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path, PurePosixPath

import receipt_check


NON_RECEIPT_PATHS = frozenset({"receipts/train_config.json"})


def _candidate(root: Path, raw: str) -> Path | None:
    relative = raw.replace("\\", "/")
    if not relative:
        return None
    posix = PurePosixPath(relative)
    if (
        posix.is_absolute()
        or ".." in posix.parts
        or len(posix.parts) < 2
        or posix.parts[0] != "receipts"
        or posix.suffix.lower() != ".json"
        or relative in NON_RECEIPT_PATHS
    ):
        return None
    path = root.joinpath(*posix.parts)
    if not path.is_file():
        return None
    return path


def check_paths(root: Path, paths: list[str]) -> int:
    checked = 0
    failed = 0
    for raw in paths:
        path = _candidate(root, raw)
        if path is None:
            continue
        checked += 1
        if receipt_check.run_file(str(path)) != 0:
            failed += 1
    if failed:
        print(f"CHANGED_RECEIPTS_FAIL checked={checked} failed={failed}")
        return 1
    print(f"CHANGED_RECEIPTS_PASS count={checked}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="validate changed receipts listed as repository-relative paths"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--null",
        action="store_true",
        help="read NUL-delimited paths, as emitted by git diff -z",
    )
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        print(f"CHANGED_RECEIPTS_FAIL invalid UTF-8 path input: {exc}")
        return 1
    paths = raw.split("\0") if args.null else raw.splitlines()
    return check_paths(args.root.resolve(), paths)


if __name__ == "__main__":
    raise SystemExit(main())
