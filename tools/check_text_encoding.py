#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reject tracked text files that are not valid UTF-8, or that carry a
UTF-16/UTF-32 BOM (issue #247).

git's `-I`/`text=auto` binary heuristics treat NUL-heavy content as binary
and silently exclude it from every text-based repo-guard scan (`names`,
`paths`, `path-frags` all run via `git grep -I`). A UTF-16-encoded tracked
file is almost entirely NUL bytes (every ASCII char null-padded), so it
never engages those scans at all -- it isn't defeated, it's invisible. A
single-byte non-UTF-8 sequence (e.g. a stray cp1252 em-dash) is a related
but distinct gap: too few NUL bytes to trip git's binary heuristic, but
still not valid UTF-8, and still capable of hiding a scan-defeating byte
sequence (and, independently, of being a SyntaxError at import time for a
tracked .py file -- PEP 263 requires a valid encoding to even parse).

This check closes both gaps directly: every tracked file git attributes
call `text` (the same population `check_line_endings.py` already enforces
LF on) must strict-decode as UTF-8, and must not start with a UTF-16/UTF-32
BOM. Genuine binary artifacts are either pinned `-text` in .gitattributes
(excluded, same as the LF check) or excluded here by extension.
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

# Longer/more-specific signatures first: a UTF-32LE BOM (FF FE 00 00) starts
# with the exact bytes of a UTF-16LE BOM (FF FE), so checking UTF-16 first
# would misclassify every UTF-32LE file as UTF-16LE.
BOM_SIGNATURES = [
    (b"\xff\xfe\x00\x00", "UTF-32LE BOM"),
    (b"\x00\x00\xfe\xff", "UTF-32BE BOM"),
    (b"\xff\xfe", "UTF-16LE BOM"),
    (b"\xfe\xff", "UTF-16BE BOM"),
]


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
    # (issue #247 fix review). Binary I/O with an explicit "\n" join sidesteps
    # the translation entirely; see the matching fix in check_line_endings.py.
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


def detect_bom(data: bytes) -> str | None:
    for sig, label in BOM_SIGNATURES:
        if data.startswith(sig):
            return label
    return None


def find_encoding_offenders(paths: Iterable[Path], root: Path) -> list[tuple[str, str]]:
    offenders: list[tuple[str, str]] = []
    for path in paths:
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in BINARY_EXTS:
            continue
        if not path.is_file():
            continue
        data = path.read_bytes()
        if not data:
            continue
        bom = detect_bom(data)
        if bom is not None:
            offenders.append((path.relative_to(root).as_posix(), bom))
            continue
        try:
            data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            offenders.append((
                path.relative_to(root).as_posix(),
                f"invalid UTF-8 at byte {exc.start}: {exc.reason}",
            ))
    return offenders


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path.cwd().resolve()
    offenders = find_encoding_offenders(tracked_text_paths(root), root)
    if offenders:
        print("FAIL [encoding] tracked text files are not valid UTF-8:")
        for name, reason in offenders[:50]:
            print(f"  {name}: {reason}")
        if len(offenders) > 50:
            print(f"  ... {len(offenders) - 50} more")
        print(
            "Tracked text files must be UTF-8 with no UTF-16/UTF-32 BOM. "
            "Re-encode the file, or if it is genuinely binary mark it -text "
            "in .gitattributes (and add its extension to BINARY_EXTS here)."
        )
        return 1
    print("ok   [encoding] tracked text files are valid UTF-8, no UTF-16/32 BOM")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
