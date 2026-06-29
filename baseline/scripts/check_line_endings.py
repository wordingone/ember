#!/usr/bin/env python3
"""Report CRLF/LF line-ending state for a baseline tree."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".json",
    ".jsonl",
    ".py",
    ".ps1",
    ".sh",
    ".toml",
    ".yaml",
    ".yml",
}


def classify(path: Path) -> str:
    data = path.read_bytes()
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    cr = data.count(b"\r") - crlf
    if cr:
        return "MIXED-OR-CR"
    if crlf and lf:
        return "MIXED"
    if crlf:
        return "CRLF"
    if lf:
        return "LF"
    return "NO_EOL"


def iter_text(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            yield path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=["report", "fail-mixed"], default="fail-mixed")
    args = parser.parse_args()

    rows = [{"path": str(path.relative_to(args.root)), "line_ending": classify(path)} for path in iter_text(args.root)]
    print(json.dumps({"root": str(args.root), "files": rows}, indent=2, sort_keys=True))

    if args.mode == "fail-mixed" and any(row["line_ending"].startswith("MIXED") for row in rows):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
