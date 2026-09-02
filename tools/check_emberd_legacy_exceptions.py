#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""check_emberd_legacy_exceptions.py — content-addressed exemption mode for
tools/repo-guard.sh's emberd-legacy-name check.

Purpose (state/specs/ember-lab-absorption-contract-2026-07-25.md, Part 4):
the emberd -> ember-lab rename is complete everywhere except two historical
records that must keep their exact original bytes forever (a receipt whose
own digest fields would change meaning if edited; a cached census of two
still-open GitHub issue titles). Exempting those files by PATH ALONE, the
way src/ember/infrastructure/tools/repo-guard-names-exclude.cfg already exempts other paths for the
plaintext/hashed NAMES check, is a hole: anyone can create or rename a file
into an exempted prefix. This script exempts by (path, sha256) PAIR instead
-- an edit to an excepted file changes its digest and un-exempts it
automatically, and nothing can satisfy an exemption it wasn't enumerated
for. This is a separate, narrower check; the existing NAMES check and its
path-prefix exclude file are untouched.

Reads:
  - the exceptions file at EXCEPTIONS_PATH, ALWAYS
    "tools/emberd-legacy-exceptions.json" -- hardcoded, never taken from an
    environment variable. An earlier revision read this path from
    EMBERD_EXCEPTIONS_PATH, which let anything invoking this script (an
    inherited shell env, a stray export) point it at an attacker-controlled
    policy file instead of the committed one; the fail-closed validation this
    script performs is worthless if it can be pointed at bytes the subject
    under test chose. See state/failure-classes/ (byte-provenance class).
  - the newline-separated list of tracked paths already found (by the caller,
    via `git grep -nIiE '\bemberd\b'`) to contain the legacy name, passed via
    the EMBERD_PATHS environment variable

Byte source (both the exceptions file itself AND every matched path's
content digest) depends on REPO_GUARD_SCOPE, mirroring the caller's own
scope handling in repo-guard.sh:
  - REPO_GUARD_SCOPE=staged (what the real pre-commit hook runs with, via
    `env REPO_GUARD_SCOPE=staged bash tools/repo-guard.sh` in
    .githooks/pre-commit): every byte comes from the git INDEX (`git show
    :path`) -- the exact bytes about to be committed. Reading working-tree
    bytes here instead was the earlier bug: stage divergent content, then
    restore the working tree to the enumerated original, and a working-tree
    read reports the ORIGINAL (excepted) digest while the commit that
    actually lands carries the STAGED (unexcepted) bytes -- a green guard on
    a commit whose real content was never adjudicated.
  - any other scope (including unset, the default local/CI run): working-
    tree bytes via the filesystem, exactly as before -- unchanged.

FAIL CLOSED, always, on any of: exceptions file missing, empty, unparseable
JSON, wrong/missing schema field, malformed entry, a matched path with no
enumerated exception, or a matched path whose current content digest does not
equal its enumerated digest. Absence of a working exceptions file is never
read as permission -- the branch this script gets wrong if it is only
exercised with a good file present.

Exit 0: the committed exceptions policy is present, valid, and schema-
conformant, AND every matched path (if any) is covered by an exact
(path, sha256) pair.
Exit 1: the policy is invalid/missing/malformed, OR a matched path is not
covered, for a reason printed to stdout (parseable, human-legible).

Policy validity is unconditional; only match adjudication is conditional.
The committed policy is always parsed and schema-validated on every
invocation -- including a zero-hit run, where repo-guard.sh still calls this
script (with EMBERD_PATHS empty) so a missing/corrupt policy cannot ride
along silently on a tree with nothing to adjudicate. Asked with zero paths,
this script validates the policy and then exits 0 trivially (nothing to
adjudicate) ONLY if that validation passed.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

# Hardcoded, never overridable by environment -- see the docstring above.
EXCEPTIONS_PATH = "tools/emberd-legacy-exceptions.json"
SCHEMA = "emberd-legacy-exceptions-v1"

# Mirrors repo-guard.sh's own "${REPO_GUARD_SCOPE:-}" = "staged" test.
_STAGED = os.environ.get("REPO_GUARD_SCOPE", "") == "staged"


def _read_bytes(path: str) -> bytes | None:
    """Bytes for `path` from the byte source this scope is bound to: the git
    INDEX (stage 0 blob) under staged scope, the filesystem otherwise. Never
    silently falls back from one source to the other -- a path absent from
    the bound source is None, full stop, regardless of what the other source
    holds."""
    if _STAGED:
        proc = subprocess.run(
            ["git", "show", f":{path}"], capture_output=True,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def sha256_of(path: str) -> str | None:
    data = _read_bytes(path)
    if data is None:
        return None
    return hashlib.sha256(data).hexdigest()


def load_exceptions(path: str) -> dict[str, str]:
    """Returns {path: sha256} or raises ValueError with a precise reason.
    Every failure mode here is deliberately its own named error -- missing,
    empty, unparseable, wrong schema, and malformed entries are distinct
    causes, not one generic 'bad file' bucket, so a fix targets the right
    thing."""
    raw = _read_bytes(path)
    if raw is None:
        raise ValueError(f"exceptions file {path!r} does not exist")
    if len(raw.strip()) == 0:
        raise ValueError(f"exceptions file {path!r} is empty")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"exceptions file {path!r} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"exceptions file {path!r} top level is not a JSON object")
    if doc.get("schema") != SCHEMA:
        raise ValueError(
            f"exceptions file {path!r} schema field is {doc.get('schema')!r}, "
            f"expected {SCHEMA!r}"
        )
    entries = doc.get("entries")
    if not isinstance(entries, list) or len(entries) == 0:
        raise ValueError(f"exceptions file {path!r} has no entries[] (or it is empty)")
    out: dict[str, str] = {}
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"exceptions file entry {i} is not a JSON object")
        entry_path = entry.get("path")
        entry_sha = entry.get("sha256")
        if not isinstance(entry_path, str) or not entry_path:
            raise ValueError(f"exceptions file entry {i} has no valid 'path'")
        if not isinstance(entry_sha, str) or len(entry_sha) != 64 or not all(
            c in "0123456789abcdef" for c in entry_sha.lower()
        ):
            raise ValueError(f"exceptions file entry {i} ({entry_path!r}) has no valid 'sha256'")
        if entry_path in out:
            raise ValueError(f"exceptions file lists {entry_path!r} more than once")
        out[entry_path] = entry_sha.lower()
    return out


def main() -> int:
    raw_paths = os.environ.get("EMBERD_PATHS", "")
    matched_paths = [line for line in raw_paths.splitlines() if line.strip()]

    # Policy validity is unconditional -- always parse and schema-validate the
    # committed exceptions file, even when there are zero matched paths. A
    # missing/empty/corrupt policy is a hard FAIL regardless of whether there
    # is anything to adjudicate this run; only match adjudication below is
    # conditional on matched_paths being non-empty.
    try:
        exceptions = load_exceptions(EXCEPTIONS_PATH)
    except ValueError as exc:
        print(f"FAIL CLOSED: {exc}")
        return 1

    if not matched_paths:
        print("policy valid; no matched paths supplied; nothing to adjudicate")
        return 0

    failures: list[str] = []
    passes: list[str] = []
    for path in matched_paths:
        current = sha256_of(path)
        if current is None:
            failures.append(f"{path}: could not be read to compute a digest")
            continue
        expected = exceptions.get(path)
        if expected is None:
            failures.append(
                f"{path}: matches the legacy name and is NOT enumerated in "
                f"{EXCEPTIONS_PATH} — path-only presence is never sufficient"
            )
            continue
        if expected != current:
            failures.append(
                f"{path}: was excepted at digest {expected} but its current content "
                f"digest is {current} — the file has changed since it was excepted; "
                "the exemption does not survive an edit"
            )
            continue
        passes.append(f"{path}: matches enumerated exception at digest {current}")

    if failures:
        print("emberd-legacy-name matches not covered by an exact (path, sha256) exception:")
        for line in failures:
            print(f"  - {line}")
        if passes:
            print("(the following DID match their enumerated exception and are fine):")
            for line in passes:
                print(f"  - {line}")
        return 1

    print(f"all {len(passes)} matched path(s) covered by an exact (path, sha256) exception:")
    for line in passes:
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
