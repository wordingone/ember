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
BOM. Genuine binary artifacts must be pinned `-text` in .gitattributes
(excluded, same as the LF check).

Scope under --staged (also the default under REPO_GUARD_SCOPE=staged, what
.githooks/pre-commit runs with): the verdict for a file is a function of that
file's bytes and its `text` attribute only, so a commit can change the verdict
only for the paths it stages. Staged scope therefore checks exactly the staged
paths (`git diff --cached --diff-filter=ACMRT`), reading the bytes that will be
committed from the git INDEX (one `git cat-file --batch`) and the `text`
attribute from the index (`git check-attr --cached`) -- not the working tree, so
"stage a bad blob, restore a clean working copy" is refused and the inverse is
not wrongly refused. The tree-wide form (no flag, no REPO_GUARD_SCOPE) is
unchanged and is what CI (job `guard`, .github/workflows/repo-policy-gate.yml)
and the pre-push hook run: a violating file that is NOT staged is refused
there, not by the commit hook. Staged scope widens to the whole tree (index
bytes) whenever the answer could depend on something a commit may change
outside the staged text files: a staged .gitattributes (it decides which paths
are text), a staged copy of this script (it decides the rule), or a staged set
git could not list. Widening is announced and never narrows the check.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable

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

# Mirrors repo-guard.sh's own "${REPO_GUARD_SCOPE:-}" = "staged" test.
_STAGED = os.environ.get("REPO_GUARD_SCOPE", "") == "staged"


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


def offense_for(data: bytes) -> str | None:
    """Why `data` is not acceptable tracked text, or None if it is."""
    if not data:
        return None
    bom = detect_bom(data)
    if bom is not None:
        return bom
    try:
        data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        return f"invalid UTF-8 at byte {exc.start}: {exc.reason}"
    return None


def find_encoding_offenders(paths: Iterable[Path], root: Path) -> list[tuple[str, str]]:
    offenders: list[tuple[str, str]] = []
    for path in paths:
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        reason = offense_for(path.read_bytes())
        if reason is not None:
            offenders.append((path.relative_to(root).as_posix(), reason))
    return offenders


def _index_blobs(root: Path, rel_paths: list[str]) -> dict[str, bytes]:
    """path -> bytes as staged in the index, one `git ls-files -s -z` plus one
    `git cat-file --batch` for the whole set (no process per file). A path with
    no stage-0 blob (a gitlink, an unmerged path) is absent from the result."""
    if not rel_paths:
        return {}
    listing = subprocess.run(
        ["git", "ls-files", "-s", "-z"], cwd=root, capture_output=True, check=True,
    )
    shas: dict[str, str] = {}
    for record in listing.stdout.split(b"\0"):
        meta, _, name = record.partition(b"\t")
        parts = meta.split()
        if len(parts) >= 3 and parts[2] == b"0" and name:
            shas[name.decode("utf-8")] = parts[1].decode("ascii")
    wanted = [rel for rel in rel_paths if rel in shas]
    if not wanted:
        return {}
    stdin_data = ("\n".join(shas[rel] for rel in wanted) + "\n").encode("utf-8")
    proc = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=root, input=stdin_data, capture_output=True, check=True,
    )
    out = proc.stdout
    result: dict[str, bytes] = {}
    pos = 0
    for rel in wanted:
        nl = out.find(b"\n", pos)
        if nl == -1:
            break
        header = out[pos:nl].decode("utf-8", errors="replace").split()
        if len(header) == 3:
            size = int(header[2])
            start = nl + 1
            result[rel] = out[start:start + size]
            pos = start + size + 1  # skip the object's trailing newline
        else:
            pos = nl + 1  # "<sha> missing": one line, no body
    return result


def find_encoding_offenders_staged(rel_paths: Iterable[str], root: Path) -> list[tuple[str, str]]:
    """Same verdicts as find_encoding_offenders, on the bytes the index holds."""
    wanted = [rel for rel in rel_paths if not any(part in SKIP_DIRS for part in Path(rel).parts)]
    blobs = _index_blobs(root, wanted)
    offenders: list[tuple[str, str]] = []
    for rel in wanted:
        data = blobs.get(rel)
        if data is None:
            continue
        reason = offense_for(data)
        if reason is not None:
            offenders.append((Path(rel).as_posix(), reason))
    return offenders


def staged_changed_paths(root: Path) -> list[str] | None:
    """Paths the index adds, copies, modifies, renames (new name) or retypes against
    HEAD, or None when git cannot say (the caller then checks the whole tree)."""
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--no-renames", "--diff-filter=ACMRT", "-z"],
        cwd=root, capture_output=True,
    )
    if proc.returncode != 0:
        return None
    try:
        return [n.decode("utf-8") for n in proc.stdout.split(b"\0") if n]
    except UnicodeDecodeError:
        return None


def scope_widening_reason(changed: list[str]) -> str | None:
    """Why staged scope must not be narrowed to `changed`, or None if it may be. The
    verdict for an unstaged file moves only if the text attributes or this rule move."""
    own = Path(__file__).name
    for rel in changed:
        base = rel.rsplit("/", 1)[-1].lower()
        if base == ".gitattributes":
            return f"{rel} is staged (it decides which paths are text)"
        if base == own.lower():
            return f"{rel} is staged (it decides the rule)"
    return None


def staged_text_paths(root: Path, changed: list[str]) -> list[str] | None:
    """Of the staged paths, those git attributes `text` per the INDEX's .gitattributes.
    None when git answered for fewer paths than it was asked about."""
    if not changed:
        return []
    proc = subprocess.run(
        ["git", "check-attr", "--cached", "--stdin", "-z", "text"],
        cwd=root,
        input=b"\0".join(n.encode("utf-8") for n in changed) + b"\0",
        check=True,
        capture_output=True,
    )
    fields = proc.stdout.split(b"\0")
    if fields and fields[-1] == b"":
        fields = fields[:-1]
    result: list[str] = []
    seen = 0
    for i in range(0, len(fields) - 2, 3):
        seen += 1
        if fields[i + 2] == b"unset":
            continue
        result.append(fields[i].decode("utf-8"))
    return result if seen == len(changed) else None


def _report(offenders: list[tuple[str, str]], ok_message: str) -> int:
    if offenders:
        print("FAIL [encoding] tracked text files are not valid UTF-8:")
        for name, reason in offenders[:50]:
            print(f"  {name}: {reason}")
        if len(offenders) > 50:
            print(f"  ... {len(offenders) - 50} more")
        print(
            "Tracked text files must be UTF-8 with no UTF-16/UTF-32 BOM. "
            "Re-encode the file, or if it is genuinely binary mark it -text "
            "in .gitattributes."
        )
        return 1
    print(ok_message)
    return 0


def check_staged_paths(root: Path, changed: list[str]) -> int:
    """Staged scope: only the staged paths, index bytes, index attributes."""
    if not changed:
        print("ok   [encoding] staged scope: no staged paths (tree-wide form runs in CI and pre-push)")
        return 0
    text = staged_text_paths(root, changed)
    if text is None:
        print(
            "FAIL [encoding] git check-attr answered for fewer staged paths than were asked. "
            "The discovery chain is broken, not the staged files. Do not read this as a pass."
        )
        return 1
    return _report(
        find_encoding_offenders_staged(text, root),
        f"ok   [encoding] staged scope: {len(text)} of {len(changed)} staged paths are text, "
        "all valid UTF-8, no UTF-16/32 BOM (tree-wide form runs in CI and pre-push)",
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=None)
    parser.add_argument("--staged", action="store_true", default=_STAGED)
    args = parser.parse_args(argv[1:])
    root = Path(args.root).resolve() if args.root else Path.cwd().resolve()
    if args.staged:
        changed = staged_changed_paths(root)
        reason = "git could not list the staged paths" if changed is None else scope_widening_reason(changed)
        if changed is not None and reason is None:
            return check_staged_paths(root, changed)
        print(f"note [encoding] staged scope widened to the whole tree: {reason}")
    paths = tracked_text_paths(root)
    # ZERO-HIT IS A FAILURE, NOT A PASS. This check's entire output when it finds
    # nothing is "ok", and it finds nothing both when the tree is clean and when
    # discovery broke -- two opposite states, one indistinguishable message. That
    # is not hypothetical here: the \r\n stdin bug repaired above made this exact
    # helper return [] on every Windows run, so the check reported ok while
    # examining no files at all, for as long as it existed. A guard whose silent
    # failure mode looks identical to success is the failure mode this whole
    # issue is about, so refuse the empty set rather than bless it.
    if not paths:
        print(
            "FAIL [encoding] discovered ZERO tracked text files, which cannot be "
            "true for this repository. The discovery chain (git ls-files -> git "
            "check-attr) is broken, not the tree. Do not read this as a pass."
        )
        return 1
    if args.staged:
        offenders = find_encoding_offenders_staged(
            [p.relative_to(root).as_posix() for p in paths], root
        )
    else:
        offenders = find_encoding_offenders(paths, root)
    return _report(offenders, "ok   [encoding] tracked text files are valid UTF-8, no UTF-16/32 BOM")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
