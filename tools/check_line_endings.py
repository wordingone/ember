#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reject CRLF in tracked text files.

Git attributes should normalize text to LF, but this guard catches Windows
checkout or tooling drift before it reaches public history. Paths explicitly
marked -text are byte-pinned artifacts and are skipped.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Iterable

BINARY_EXTS = {
    ".bin", ".dat", ".gguf", ".gz", ".jpg", ".jpeg", ".npy", ".npz",
    ".onnx", ".png", ".pt", ".safetensors", ".zip",
}

SKIP_DIRS = {
    ".git",
    "node_modules",
}


def is_probably_binary(data: bytes, path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTS:
        return True
    return b"\0" in data[:8192]


def find_crlf_files(paths: Iterable[Path], root: Path) -> list[str]:
    offenders: list[str] = []
    for path in paths:
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        data = path.read_bytes()
        if is_probably_binary(data, path):
            continue
        if b"\r\n" in data:
            offenders.append(path.relative_to(root).as_posix())
    return offenders


def tracked_text_paths(root: Path) -> list[Path]:
    out = subprocess.check_output(["git", "ls-files"], cwd=root, text=True)
    names = [line for line in out.splitlines() if line]
    if not names:
        return []
    # Binary mode (text=False) end to end: subprocess's text=True universal-
    # newline translation rewrites every "\n" in `input` to os.linesep before
    # the child ever sees it. On Windows that turns each pathname's stdin
    # line into "<name>\r\n" -- git-check-attr then reads a filename with a
    # trailing \r, cannot match it to any real tracked path, and the whole
    # tracked-text population comes back empty regardless of file content
    # (issue #247 fix review: this made this check a silent no-op on every
    # Windows-local run, whatever line endings the tracked files actually
    # had). Binary I/O with an explicit "\n" join sidesteps the translation.
    stdin_bytes = ("\n".join(names) + "\n").encode("utf-8")
    proc = subprocess.run(
        ["git", "check-attr", "--stdin", "text"],
        cwd=root,
        input=stdin_bytes,
        check=True,
        capture_output=True,
    )
    result: list[Path] = []
    for line in proc.stdout.decode("utf-8", errors="replace").split("\n"):
        line = line.rstrip("\r")
        if not line:
            continue
        parts = line.rsplit(": ", 2)
        if len(parts) != 3:
            continue
        name, _attr, value = parts
        if value == "unset":
            continue
        result.append(root / name)
    return result


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path.cwd().resolve()
    offenders = find_crlf_files(tracked_text_paths(root), root)
    if offenders:
        print("FAIL [line-endings] CRLF found in tracked text files:")
        for item in offenders[:50]:
            print(f"  {item}")
        if len(offenders) > 50:
            print(f"  ... {len(offenders) - 50} more")
        print("Normalize these files to LF. .gitattributes should prevent recurrence.")
        return 1
    print("ok   [line-endings] tracked text files are LF-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))