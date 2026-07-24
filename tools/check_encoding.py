#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reject tracked text files that fail a strict UTF-8 decode (gh issue #247).

repo-guard's `[names]` (and `[paths]`/`[path-frags]`) scans run via
`git grep -I`, which SKIPS any file git's own heuristic classifies as
binary. A tracked file encoded as UTF-16LE-with-BOM sails through every one
of those scans clean regardless of its actual text content: each character
is null-padded, so the hashed/plaintext denylist strings never match the
byte stream, even though the same content re-encoded as UTF-8 (zero textual
change) immediately trips the `[names]` gate. Confirmed live: a founder-name
-derived codename sat in `scripts/ember_totality/ember_totality_spec.py`
for its entire life on master (landed via #234) undetected, and a
byte-faithful UTF-8 transcode of that exact file (#246) caught it instantly.

Scope extension (same issue, second finding): the blind spot is not
BOM-specific. Nine tracked probe files (`test_c0.py` .. `test_c14.py`,
`test_surface2.py`) crash at import with
`SyntaxError: Non-UTF-8 code starting with '\\x97' ... but no encoding
declared` -- a single-byte non-UTF-8 sequence (cp1252-shaped), not a
UTF-16/32 BOM. The fix here is general: reject ANY tracked text file that
fails a strict UTF-8 decode, not just BOM-carrying files specifically.

Reuses this repo's existing text-file discovery convention
(tools/check_line_endings.py's `git check-attr --stdin text` + binary-ext/
NUL-byte fallback) so "text file" means the same thing to every repo-guard
check -- no separate, driftable definition of what counts as text.
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


def is_probably_binary(path: Path) -> bool:
    """Extension-only, deliberately WITHOUT check_line_endings.py's sibling
    NUL-byte sniff: a NUL byte in the first 8KiB is exactly what a UTF-16
    (or UTF-32) encoded ASCII text file looks like -- every other byte of a
    plain-ASCII UTF-16LE stream IS 0x00. Reusing that heuristic here would
    silently exclude the precise blind-spot file class issue #247 exists to
    catch. Genuinely opaque binary artifacts (checkpoints, images, corpora)
    are excluded by extension here, and by the .gitattributes `-text` pins
    tracked_text_paths() already honors (receipts/**, tokenizer/**, etc.)."""
    return path.suffix.lower() in BINARY_EXTS


def tracked_text_paths(root: Path) -> list[Path]:
    out = subprocess.check_output(["git", "ls-files"], cwd=root, text=True)
    names = [line for line in out.splitlines() if line]
    if not names:
        return []
    # Byte-mode stdin, not text=True: on Windows, subprocess's text-mode
    # stdin pipe applies universal-newline translation on WRITE, turning
    # every "\n" in `input` into "\r\n". git check-attr then treats that
    # trailing \r as part of the filename ("scripts/note2.py\r"), fails to
    # match the real tracked path, and silently omits it from the result --
    # the exact file this check exists to catch would otherwise vanish
    # before ever being opened. Byte-mode input with an explicit b"\n"
    # terminator sidesteps the translation entirely; output is decoded by
    # hand afterward.
    proc = subprocess.run(
        ["git", "check-attr", "--stdin", "text"],
        cwd=root,
        input=("\n".join(names) + "\n").encode("utf-8"),
        check=True,
        capture_output=True,
    )
    stdout = proc.stdout.decode("utf-8", errors="replace")
    result: list[Path] = []
    for line in stdout.splitlines():
        parts = line.rsplit(": ", 2)
        if len(parts) != 3:
            continue
        name, _attr, value = parts
        if value == "unset":
            continue
        result.append(root / name)
    return result


def _decode_error_context(data: bytes, err: "UnicodeDecodeError") -> str:
    """One-line human-readable pointer: byte offset, the offending byte(s)
    in hex, and which text line they fall on (by counting b'\\n' up to the
    error's start -- cheap, exact, no full-file text decode required since
    the whole point is that a full decode is what just failed)."""
    line_no = data.count(b"\n", 0, err.start) + 1
    bad = data[err.start:err.end] or data[err.start:err.start + 1]
    return f"byte offset {err.start} (line {line_no}), bytes {bad.hex()}: {err.reason}"


def find_non_utf8_files(paths: Iterable[Path], root: Path) -> list[str]:
    offenders: list[str] = []
    for path in paths:
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if is_probably_binary(path):
            continue
        data = path.read_bytes()
        try:
            data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as err:
            rel = path.relative_to(root).as_posix()
            offenders.append(f"{rel} -- {_decode_error_context(data, err)}")
    return offenders


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path.cwd().resolve()
    offenders = find_non_utf8_files(tracked_text_paths(root), root)
    if offenders:
        print("FAIL [encoding] tracked text files fail a strict UTF-8 decode:")
        for item in offenders[:50]:
            print(f"  {item}")
        if len(offenders) > 50:
            print(f"  ... {len(offenders) - 50} more")
        print("A non-UTF-8 tracked text file is a blind spot for every git-grep-based "
              "repo-guard scan ([names]/[paths]/[path-frags] all use `git grep -I`, "
              "which silently skips files git classifies as binary). Re-encode as "
              "UTF-8 (no textual content change) or mark the path -text in "
              ".gitattributes if it is genuinely a byte-pinned non-text artifact.")
        return 1
    print("ok   [encoding] tracked text files are strict-UTF-8 decodable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
