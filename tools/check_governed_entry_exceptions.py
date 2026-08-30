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
        "supplement": "tools/ember-restart-3b/launcher-shape-exceptions.json",
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


def _exists(path: str) -> bool:
    """Whether path exists in the adjudicated tree (staged index or worktree)."""
    if _staged():
        probe = subprocess.run(
            ["git", "cat-file", "-e", f":{path}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return probe.returncode == 0
    return os.path.exists(path)


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

    def load_policy(policy_path: str) -> dict | str:
        """Parse one exceptions policy; a str return is the failure message."""
        raw = _read_bytes(policy_path)
        if raw is None:
            return f"{policy_path}: missing or unreadable; policy required"
        if not raw.strip():
            return f"{policy_path}: empty; policy required"
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return f"{policy_path}: unparseable ({exc})"
        if not isinstance(doc, dict):
            return f"{policy_path}: top level must be an object"
        if doc.get("schema_version") != SCHEMA_VERSION:
            return (
                f"{policy_path}: schema_version must be {SCHEMA_VERSION}, "
                f"found {doc.get('schema_version')!r}"
            )
        entries = doc.get("exceptions")
        if not isinstance(entries, list):
            return f"{policy_path}: exceptions must be a list"
        parsed = {}
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                return f"{policy_path}: entry {index} is not an object"
            path = entry.get("path")
            digest = entry.get("sha256")
            if not isinstance(path, str) or not path:
                return f"{policy_path}: entry {index} has no usable path"
            if not isinstance(digest, str) or len(digest) != 64:
                return f"{policy_path}: entry {index} ({path}) has no 64-hex sha256"
            try:
                int(digest, 16)
            except ValueError:
                return f"{policy_path}: entry {index} ({path}) sha256 is not hex"
            if path in parsed:
                return f"{policy_path}: duplicate entry for {path}"
            parsed[path] = digest.lower()
        return parsed

    base = load_policy(EXCEPTIONS_PATH)
    if isinstance(base, str):
        return _fail(base)
    enumerated = base

    # A per-workstream supplemental policy: absent means exactly the legacy
    # (binding keys inside it are validated by the repository's
    # authority-conservation gate, the sole authority on binding values.)
    # behavior; present it must be VALID (a malformed supplement refuses, it
    # is never ignored) and its entries take precedence over the base policy
    # for an exact duplicate path, so a workstream can repin its own files
    # without editing the base registry.
    supplement_count = 0
    SUPPLEMENT_PATH = rule.get("supplement")
    if SUPPLEMENT_PATH and _exists(SUPPLEMENT_PATH):
        supplement = load_policy(SUPPLEMENT_PATH)
        if isinstance(supplement, str):
            return _fail(supplement)
        supplement_count = len(supplement)
        enumerated = {**enumerated, **supplement}

    matched = [
        line.strip()
        for line in os.environ.get(rule["paths_env"], "").splitlines()
        if line.strip()
    ]
    if not matched:
        print(
            f"{rule_name} policy validated ({len(enumerated)} enumerated, "
            f"{supplement_count} supplemental); nothing to adjudicate"
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
