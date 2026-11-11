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

Path scope under --staged (also the default under REPO_GUARD_SCOPE=staged):
the verdict for a file is a function of that file's bytes and its `text`
attribute only, so a commit can change the verdict only for the paths it
stages. Staged scope therefore checks exactly the staged paths
(`git diff --cached --diff-filter=ACMRT`), with their `text` attribute read
from the index (`git check-attr --cached`). The tree-wide form is unchanged and
is what CI (job `guard`, .github/workflows/repo-policy-gate.yml) and the
pre-push hook run: a violating file that is NOT staged is refused there, not by
the commit hook. Staged scope widens to the whole tree, with index bytes,
whenever the answer could depend on something a commit may change outside the
staged text files: a staged .gitattributes (it decides which paths are text), a
staged copy of this script (it decides the rule), or a staged set that git could
not list. Widening is announced and never narrows a check.
"""
from __future__ import annotations

import argparse
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
    """path -> index (stage 0) blob sha, via one `git ls-files -s -z` call for
    the whole tree -- avoids a subprocess per path. NUL-delimited bytes, so a
    path git would quote (non-ASCII, odd characters) still keys by its real
    name instead of silently missing its blob."""
    out = subprocess.run(
        ["git", "ls-files", "-s", "-z"], cwd=root, capture_output=True, check=True,
    )
    shas: dict[str, str] = {}
    for record in out.stdout.split(b"\0"):
        meta, _, path = record.partition(b"\t")
        parts = meta.split()
        if len(parts) < 2 or not path:
            continue
        shas[path.decode("utf-8")] = parts[1].decode("ascii")
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


def find_crlf_files(root: Path, rel_paths: Iterable[str], *, staged: bool | None = None) -> list[str]:
    use_index = _STAGED if staged is None else staged
    filtered = [rel for rel in rel_paths if not any(part in SKIP_DIRS for part in Path(rel).parts)]
    offenders: list[str] = []
    if use_index:
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


def _text_attribute_names(root: Path, names: list[bytes], *, cached: bool) -> list[str] | None:
    """Of `names` (byte paths), those git attributes `text` (anything but `unset`).
    `cached` reads .gitattributes from the index instead of the working tree.
    Returns None when git answered for fewer paths than it was asked about
    (discovery broke; the caller must not read that as a pass)."""
    if not names:
        return []
    stdin_data = b"\0".join(names) + b"\0"
    command = ["git", "check-attr"] + (["--cached"] if cached else []) + ["--stdin", "-z", "text"]
    proc = subprocess.run(command, cwd=root, input=stdin_data, check=True, capture_output=True)
    fields = proc.stdout.split(b"\0")
    if fields and fields[-1] == b"":
        fields = fields[:-1]
    result: list[str] = []
    seen = 0
    for i in range(0, len(fields) - 2, 3):
        name_b, _attr_b, value_b = fields[i], fields[i + 1], fields[i + 2]
        seen += 1
        if value_b == b"unset":
            continue
        result.append(name_b.decode("utf-8"))
    return result if seen == len(names) else None


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


def _discovery_broken() -> int:
    print(
        "FAIL [line-endings] discovered ZERO tracked text files, which cannot "
        "be true for this repository. The discovery chain (git ls-files -> git "
        "check-attr) is broken, not the tree. Do not read this as a pass."
    )
    return 1


def _report(offenders: list[str], ok_message: str) -> int:
    if offenders:
        print("FAIL [line-endings] CRLF found in tracked text files:")
        for item in offenders[:50]:
            print(f"  {item}")
        if len(offenders) > 50:
            print(f"  ... {len(offenders) - 50} more")
        print("Normalize these files to LF. .gitattributes should prevent recurrence.")
        return 1
    print(ok_message)
    return 0


def check_staged_paths(root: Path, changed: list[str]) -> int:
    """Staged scope: only the staged paths, index bytes, index attributes."""
    if not changed:
        print("ok   [line-endings] staged scope: no staged paths (tree-wide form runs in CI and pre-push)")
        return 0
    text = _text_attribute_names(root, [n.encode("utf-8") for n in changed], cached=True)
    if text is None:
        print(
            "FAIL [line-endings] git check-attr answered for fewer staged paths than were "
            "asked. The discovery chain is broken, not the staged files. Do not read this as a pass."
        )
        return 1
    offenders = find_crlf_files(root, text, staged=True)
    return _report(
        offenders,
        f"ok   [line-endings] staged scope: {len(text)} of {len(changed)} staged paths are text, "
        "all LF-only (tree-wide form runs in CI and pre-push)",
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
        print(f"note [line-endings] staged scope widened to the whole tree: {reason}")
    paths = tracked_text_paths(root)
    if not paths:
        return _discovery_broken()
    offenders = find_crlf_files(root, paths, staged=args.staged)
    return _report(offenders, "ok   [line-endings] tracked text files are LF-only")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
