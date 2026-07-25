#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reject CRLF in tracked text files.

Git attributes should normalize text to LF, but this guard catches Windows
checkout or tooling drift before it reaches public history. Paths explicitly
marked -text are byte-pinned artifacts and are skipped.

Byte source depends on REPO_GUARD_SCOPE, mirroring the sibling legacy-name
policy checker under tools/ and tools/repo-guard.sh's own scope handling:
under REPO_GUARD_SCOPE=staged (what .githooks/pre-commit actually runs
with), every file's content comes from the git INDEX -- the exact bytes
about to be committed, not the working tree. Reading working-tree bytes
unconditionally was a real gap: stage a CRLF file, restore the working tree
to an LF-only version, and a working-tree read would report clean while the
commit that lands still carries CRLF (or the inverse: stage a clean fix,
leave a stale CRLF working-tree copy behind, and the check would wrongly
fail). The tracked-path LIST itself (`git ls-files`) is already
index-derived either way, so only the per-file content read needed the
scope branch.

Staged-scope reads are BATCHED via one `git cat-file --batch` process fed
every needed blob sha at once (`git ls-files -s` supplies the shas), not one
`git show :path` subprocess per file -- a per-file subprocess is correct but
was measured too slow across a repo of this size (one process spawn per
tracked file). Non-staged scope is unchanged: plain filesystem reads.
"""
from __future__ import annotations

import os
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

# Mirrors repo-guard.sh's own "${REPO_GUARD_SCOPE:-}" = "staged" test.
_STAGED = os.environ.get("REPO_GUARD_SCOPE", "") == "staged"


def _staged_blob_shas(root: Path) -> dict[str, str]:
    """path -> index (stage 0) blob sha, via one `git ls-files -s` call for
    the whole tree -- avoids a subprocess per path."""
    out = subprocess.run(
        ["git", "ls-files", "-s"], cwd=root, capture_output=True, text=True, check=True,
    )
    shas: dict[str, str] = {}
    for line in out.stdout.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) < 2 or not path:
            continue
        shas[path] = parts[1]
    return shas


def _batch_read_blobs(root: Path, path_to_sha: dict[str, str]) -> dict[str, bytes]:
    """path -> blob bytes, via one `git cat-file --batch` process for every
    requested sha at once instead of one subprocess per file. Protocol per
    requested object: "<sha> <type> <size>\\n<content>\\n", or
    "<sha> missing\\n" if the object cannot be resolved (skipped)."""
    if not path_to_sha:
        return {}
    paths = list(path_to_sha.keys())
    stdin_data = ("\n".join(path_to_sha[p] for p in paths) + "\n").encode("utf-8")
    proc = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=root, input=stdin_data, capture_output=True,
    )
    out = proc.stdout
    result: dict[str, bytes] = {}
    pos = 0
    for p in paths:
        nl = out.find(b"\n", pos)
        if nl == -1:
            break
        header = out[pos:nl].decode("utf-8", errors="replace").split()
        if len(header) == 3:
            _sha, _type, size_s = header
            size = int(size_s)
            start = nl + 1
            result[p] = out[start:start + size]
            pos = start + size + 1  # skip the object's trailing newline
        else:
            # "<sha> missing" (or any other unexpected shape) -- one line, no body.
            pos = nl + 1
    return result


def is_probably_binary(data: bytes, rel: str) -> bool:
    if Path(rel).suffix.lower() in BINARY_EXTS:
        return True
    return b"\0" in data[:8192]


def find_crlf_files(root: Path, rel_paths: Iterable[str]) -> list[str]:
    filtered = [rel for rel in rel_paths if not any(part in SKIP_DIRS for part in Path(rel).parts)]
    offenders: list[str] = []
    if _STAGED:
        shas = _staged_blob_shas(root)
        blobs = _batch_read_blobs(root, {rel: shas[rel] for rel in filtered if rel in shas})
        for rel in filtered:
            data = blobs.get(rel)
            if data is None:
                continue
            if is_probably_binary(data, rel):
                continue
            if b"\r\n" in data:
                offenders.append(rel)
        return offenders
    for rel in filtered:
        try:
            data = (root / rel).read_bytes()
        except OSError:
            continue
        if is_probably_binary(data, rel):
            continue
        if b"\r\n" in data:
            offenders.append(rel)
    return offenders


def tracked_text_paths(root: Path) -> list[str]:
    # -z (NUL-delimited) on BOTH calls, entirely in bytes -- Python's text=True
    # subprocess mode translates outgoing '\n' to '\r\n' when writing input= on
    # Windows, which corrupted the path fed to check-attr (git then saw a
    # trailing \r as part of the path and quoted it: `"name\r": text: ...`,
    # silently breaking every downstream lookup keyed by the clean name). NUL
    # separators have no such translation and sidestep the issue entirely.
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    names = [n for n in out.stdout.split(b"\0") if n]
    if not names:
        return []
    stdin_data = b"\0".join(names) + b"\0"
    proc = subprocess.run(
        ["git", "check-attr", "--stdin", "-z", "text"],
        cwd=root,
        input=stdin_data,
        check=True,
        capture_output=True,
    )
    fields = proc.stdout.split(b"\0")
    if fields and fields[-1] == b"":
        fields = fields[:-1]
    result: list[str] = []
    for i in range(0, len(fields) - 2, 3):
        name_b, _attr_b, value_b = fields[i], fields[i + 1], fields[i + 2]
        if value_b == b"unset":
            continue
        result.append(name_b.decode("utf-8"))
    return result


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path.cwd().resolve()
    offenders = find_crlf_files(root, tracked_text_paths(root))
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