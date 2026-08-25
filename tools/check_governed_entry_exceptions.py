#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""check_governed_entry_exceptions.py — content-addressed adjudication for the
launcher checks in tools/repo-guard.sh.

Purpose: a governed training run is born through the sanctioned entry homes and
nowhere else. A tracked script outside those homes that reaches for the
training-segment API is launcher-shaped, and a launcher outside the sanctioned
path is the class this check exists to keep out of the tree.

Two rules share this adjudicator, selected by a single positional argument:

  governed-entry   a script outside the sanctioned homes NAMES the
                   training-segment API. Broad by construction: it catches
                   references in prose, manifests, and analysis code as well as
                   in executable paths, so every one of them is enumerated with
                   its bytes and re-adjudicated whenever it changes.

  launcher-shape   a script outside runtime/ember-lab and tools/ember-cli is
                   both directly runnable (`__main__`) AND creates a child
                   process running a training entrypoint. That conjunction is
                   the launcher itself, not a mention of one: it is the thing a
                   person runs by hand instead of running the daemon.

The two rules have deliberately different sanctioned homes. governed-entry
admits the 3B toolkit because analysis code there legitimately refers to the
training entry; launcher-shape does not, because a hand-runnable launcher in
the toolkit is exactly the standalone dispatcher issue 898 exists to remove.
The run bodies the daemon dispatches — which do re-exec worker children and so
match the shape — are enumerated with their digests rather than exempted by
prefix.

Adjudication is by (path, sha256) PAIR, never by path alone. Path-only
exemption is a hole: a file can be created or renamed into an exempted prefix,
but its digest cannot be forged. An edit to an enumerated file changes its
digest and un-exempts it automatically, which is the intended behaviour — a
file that starts consuming the training API differently must be re-adjudicated.

Reads:
  - the exceptions file, ALWAYS a hardcoded relative path selected by the rule
    name from the RULES table below. It is deliberately NOT taken from an
    environment variable: fail-closed validation is worthless if the policy it
    validates against can be pointed at bytes the subject under test chose. The
    rule name selects among fixed entries and cannot introduce a new path.
  - the newline-separated list of tracked paths the caller matched, via the
    environment variable named by the rule.

Byte source follows REPO_GUARD_SCOPE, mirroring repo-guard.sh:
  - REPO_GUARD_SCOPE=staged: every byte from the git INDEX (`git show :path`),
    the exact bytes about to be committed. Reading the working tree while
    committing staged bytes is a real bypass — stage divergent content, restore
    the working tree to the enumerated original, and the guard adjudicates
    bytes that never land.
  - any other scope: working-tree bytes.

FAIL CLOSED on any of: exceptions file missing, empty, unparseable, wrong
schema, malformed entry, duplicate path, a matched path with no enumerated
exception, or a matched path whose digest does not equal its enumerated digest.
Absence of a usable policy is never read as permission.

Exit 0: policy present, valid, and every matched path covered exactly.
Exit 1: policy invalid, or a matched path uncovered, with the reason printed.

Policy validity is unconditional; only match adjudication is conditional. A
zero-match run still validates the policy, so a corrupt policy cannot ride
along silently on a tree with nothing to adjudicate.
"""

import hashlib
import json
import os
import subprocess
import sys

RULES = {
    "governed-entry": {
        "policy": "tools/governed-entry-exceptions.json",
        "schema": "ember-governed-entry-exceptions-v1",
        "paths_env": "GOVERNED_ENTRY_PATHS",
        "uncovered": "references the governed training entry and is not enumerated",
    },
    "launcher-shape": {
        "policy": "tools/launcher-shape-exceptions.json",
        "schema": "ember-launcher-shape-exceptions-v1",
        "paths_env": "LAUNCHER_SHAPE_PATHS",
        "uncovered": (
            "is directly runnable and starts a training child outside the daemon, "
            "and is not enumerated"
        ),
    },
}
DEFAULT_RULE = "governed-entry"


def _staged() -> bool:
    return os.environ.get("REPO_GUARD_SCOPE", "") == "staged"


def _read_bytes(path: str):
    """Return the adjudicated bytes for path, or None when unreadable."""
    if _staged():
        try:
            return subprocess.run(
                ["git", "show", f":{path}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            ).stdout
        except (subprocess.CalledProcessError, OSError):
            return None
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def _fail(message: str) -> int:
    print(message)
    return 1


def main() -> int:
    argv = sys.argv[1:]
    if len(argv) > 1:
        return _fail(f"usage: {sys.argv[0]} [{'|'.join(sorted(RULES))}]")
    rule_name = argv[0] if argv else DEFAULT_RULE
    rule = RULES.get(rule_name)
    if rule is None:
        return _fail(f"unknown rule {rule_name!r}; known: {', '.join(sorted(RULES))}")
    EXCEPTIONS_PATH = rule["policy"]
    SCHEMA_VERSION = rule["schema"]

    raw = _read_bytes(EXCEPTIONS_PATH)
    if raw is None:
        return _fail(f"{EXCEPTIONS_PATH}: missing or unreadable; policy required")
    if not raw.strip():
        return _fail(f"{EXCEPTIONS_PATH}: empty; policy required")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _fail(f"{EXCEPTIONS_PATH}: unparseable ({exc})")
    if not isinstance(doc, dict):
        return _fail(f"{EXCEPTIONS_PATH}: top level must be an object")
    if doc.get("schema_version") != SCHEMA_VERSION:
        return _fail(
            f"{EXCEPTIONS_PATH}: schema_version must be {SCHEMA_VERSION}, "
            f"found {doc.get('schema_version')!r}"
        )
    entries = doc.get("exceptions")
    if not isinstance(entries, list):
        return _fail(f"{EXCEPTIONS_PATH}: exceptions must be a list")

    enumerated = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            return _fail(f"{EXCEPTIONS_PATH}: entry {index} is not an object")
        path = entry.get("path")
        digest = entry.get("sha256")
        if not isinstance(path, str) or not path:
            return _fail(f"{EXCEPTIONS_PATH}: entry {index} has no usable path")
        if not isinstance(digest, str) or len(digest) != 64:
            return _fail(f"{EXCEPTIONS_PATH}: entry {index} ({path}) has no 64-hex sha256")
        try:
            int(digest, 16)
        except ValueError:
            return _fail(f"{EXCEPTIONS_PATH}: entry {index} ({path}) sha256 is not hex")
        if path in enumerated:
            return _fail(f"{EXCEPTIONS_PATH}: duplicate entry for {path}")
        enumerated[path] = digest.lower()

    matched = [
        line.strip()
        for line in os.environ.get(rule["paths_env"], "").splitlines()
        if line.strip()
    ]
    if not matched:
        print(
            f"{rule_name} policy validated ({len(enumerated)} enumerated); "
            "nothing to adjudicate"
        )
        return 0

    uncovered = []
    for path in sorted(set(matched)):
        expected = enumerated.get(path)
        if expected is None:
            uncovered.append(f"{path}: {rule['uncovered']}")
            continue
        content = _read_bytes(path)
        if content is None:
            uncovered.append(f"{path}: enumerated but its adjudicated bytes are unreadable")
            continue
        actual = hashlib.sha256(content).hexdigest()
        if actual != expected:
            uncovered.append(
                f"{path}: content digest {actual} does not equal enumerated {expected}"
            )

    if uncovered:
        for line in uncovered:
            print(line)
        return 1

    print(
        f"{rule_name}: {len(set(matched))} matched path(s) covered by an exact "
        "(path, sha256) exception"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
