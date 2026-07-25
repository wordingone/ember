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
way tools/repo-guard-names-exclude.txt already exempts other paths for the
plaintext/hashed NAMES check, is a hole: anyone can create or rename a file
into an exempted prefix. This script exempts by (path, sha256) PAIR instead
-- an edit to an excepted file changes its digest and un-exempts it
automatically, and nothing can satisfy an exemption it wasn't enumerated
for. This is a separate, narrower check; the existing NAMES check and its
path-prefix exclude file are untouched.

Reads:
  - the exceptions file at EXCEPTIONS_PATH (default
    tools/emberd-legacy-exceptions.json), schema "emberd-legacy-exceptions-v1"
  - the newline-separated list of tracked paths already found (by the caller,
    via `git grep -nIiE '\bemberd\b'`) to contain the legacy name, passed via
    the EMBERD_PATHS environment variable

FAIL CLOSED, always, on any of: exceptions file missing, empty, unparseable
JSON, wrong/missing schema field, malformed entry, a matched path with no
enumerated exception, or a matched path whose current content digest does not
equal its enumerated digest. Absence of a working exceptions file is never
read as permission -- the branch this script gets wrong if it is only
exercised with a good file present.

Exit 0: every matched path is covered by an exact (path, sha256) pair.
Exit 1: not covered, for a reason printed to stdout (parseable, human-legible).
Called only when the caller has already found at least one match; asked with
zero paths it has nothing to adjudicate and exits 0 trivially (repo-guard.sh
skips the call entirely in that case, but this script does the same if it
were ever invoked directly with no input).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

EXCEPTIONS_PATH = os.environ.get("EMBERD_EXCEPTIONS_PATH", "tools/emberd-legacy-exceptions.json")
SCHEMA = "emberd-legacy-exceptions-v1"


def sha256_of(path: str) -> str | None:
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest()


def load_exceptions(path: str) -> dict[str, str]:
    """Returns {path: sha256} or raises ValueError with a precise reason.
    Every failure mode here is deliberately its own named error -- missing,
    empty, unparseable, wrong schema, and malformed entries are distinct
    causes, not one generic 'bad file' bucket, so a fix targets the right
    thing."""
    p = Path(path)
    if not p.exists():
        raise ValueError(f"exceptions file {path!r} does not exist")
    raw = p.read_bytes()
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
    if not matched_paths:
        print("no matched paths supplied; nothing to adjudicate")
        return 0

    try:
        exceptions = load_exceptions(EXCEPTIONS_PATH)
    except ValueError as exc:
        print(f"FAIL CLOSED: {exc}")
        return 1

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
