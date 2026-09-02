#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail closed on changed receipt JSON paths supplied on stdin."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath

# issue2015 exact-local-import:src/ember/governance/scripts/receipt_check.py
import importlib.util as _ember_2ad73f5df12b45ee_importlib
import sys as _ember_2ad73f5df12b45ee_sys
from pathlib import Path as _ember_2ad73f5df12b45ee_Path
_ember_2ad73f5df12b45ee_path = _ember_2ad73f5df12b45ee_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_check.py')
if not _ember_2ad73f5df12b45ee_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_check.py')
_ember_2ad73f5df12b45ee_aliases = ('_ember_issue2015_2ad73f5df12b45ee', 'receipt_check', 'scripts.receipt_check')
_ember_2ad73f5df12b45ee_existing = []
for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
    _ember_2ad73f5df12b45ee_candidate = _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias)
    if _ember_2ad73f5df12b45ee_candidate is not None and all(_ember_2ad73f5df12b45ee_candidate is not item for item in _ember_2ad73f5df12b45ee_existing):
        _ember_2ad73f5df12b45ee_existing.append(_ember_2ad73f5df12b45ee_candidate)
if len(_ember_2ad73f5df12b45ee_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_check.py')
if _ember_2ad73f5df12b45ee_existing:
    _ember_2ad73f5df12b45ee_module = _ember_2ad73f5df12b45ee_existing[0]
    _ember_2ad73f5df12b45ee_observed = getattr(_ember_2ad73f5df12b45ee_module, '__file__', None)
    if _ember_2ad73f5df12b45ee_observed is None or _ember_2ad73f5df12b45ee_Path(_ember_2ad73f5df12b45ee_observed).resolve() != _ember_2ad73f5df12b45ee_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_check.py')
else:
    _ember_2ad73f5df12b45ee_spec = _ember_2ad73f5df12b45ee_importlib.spec_from_file_location('_ember_issue2015_2ad73f5df12b45ee', _ember_2ad73f5df12b45ee_path)
    if _ember_2ad73f5df12b45ee_spec is None or _ember_2ad73f5df12b45ee_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_check.py')
    _ember_2ad73f5df12b45ee_module = _ember_2ad73f5df12b45ee_importlib.module_from_spec(_ember_2ad73f5df12b45ee_spec)
    for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
        _ember_2ad73f5df12b45ee_prior = _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias)
        if _ember_2ad73f5df12b45ee_prior is not None and _ember_2ad73f5df12b45ee_prior is not _ember_2ad73f5df12b45ee_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_check.py')
        _ember_2ad73f5df12b45ee_sys.modules[_ember_2ad73f5df12b45ee_alias] = _ember_2ad73f5df12b45ee_module
    try:
        _ember_2ad73f5df12b45ee_spec.loader.exec_module(_ember_2ad73f5df12b45ee_module)
    except BaseException:
        for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
            if _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias) is _ember_2ad73f5df12b45ee_module:
                _ember_2ad73f5df12b45ee_sys.modules.pop(_ember_2ad73f5df12b45ee_alias, None)
        raise
for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
    _ember_2ad73f5df12b45ee_prior = _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias)
    if _ember_2ad73f5df12b45ee_prior is not None and _ember_2ad73f5df12b45ee_prior is not _ember_2ad73f5df12b45ee_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_check.py')
    _ember_2ad73f5df12b45ee_sys.modules[_ember_2ad73f5df12b45ee_alias] = _ember_2ad73f5df12b45ee_module
receipt_check = _ember_2ad73f5df12b45ee_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_check.py
from oldest_issue_disposition import PacketError, validate_packet


NON_RECEIPT_PATHS = frozenset({"receipts/train_config.json"})
DISPOSITION_PACKET_PREFIX = ("receipts", "oldest-issue-disposition", "approved")

# Frozen evidence copied in verbatim is not a receipt this repository authors,
# and the floor's ticket/ts/sha_convention fields cannot be added to it: every
# entry below is a document whose own sha256 is cited elsewhere, so editing it
# to satisfy the floor would break the citation that makes it evidence. Path
# alone is never sufficient — anyone can move a file to an enumerated path;
# they cannot forge its digest. Same content-addressed shape as
# the legacy-name exceptions policy, and validated the same way: the policy
# is parsed on EVERY run, so a missing, malformed, or unparseable exceptions
# file is a hard failure even when no changed path would consult it.
#
# Digests are taken from the same bytes the floor itself reads (working tree),
# so an exception can never cover bytes other than the ones being validated.
FROZEN_EXCEPTIONS_PATHS = (
    ("tools", "frozen-receipt-exceptions.json"),
    ("src", "ember", "infrastructure", "tools", "frozen-receipt-exceptions.json"),
)
FROZEN_EXCEPTIONS_SCHEMA = "frozen-receipt-exceptions-v1"


def _candidate(root: Path, raw: str, frozen: dict[str, str]) -> Path | None:
    relative = raw.replace("\\", "/")
    if not relative:
        return None
    posix = PurePosixPath(relative)
    if (
        posix.is_absolute()
        or ".." in posix.parts
        or len(posix.parts) < 2
        or posix.parts[0] != "receipts"
        or relative in NON_RECEIPT_PATHS
    ):
        return None
    # issue #1506: a path enumerated in the frozen-receipt exceptions policy is
    # checked against its recorded digest regardless of extension. The frozen
    # list is an explicit per-path opt-in (never a directory glob), so this
    # cannot widen admission for any other growing .jsonl ledger under
    # receipts/ (e.g. receipts/ledger/episodes.jsonl) -- those stay excluded
    # by the .json-only gate below exactly as before. Without this, a frozen
    # non-.json evidence file -- receipts/ember-02-launch-authority/
    # declaration-ledger.jsonl is the motivating case -- would never reach
    # _is_frozen and a silent rewrite of it would pass this gate uninspected.
    if posix.suffix.lower() != ".json" and relative not in frozen:
        return None
    path = root.joinpath(*posix.parts)
    if not path.is_file():
        return None
    return path


def _check_candidate(root: Path, path: Path) -> bool:
    relative = path.relative_to(root).as_posix()
    parts = PurePosixPath(relative).parts
    if parts[:3] != DISPOSITION_PACKET_PREFIX:
        return receipt_check.run_file(str(path)) == 0
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
        if not isinstance(value, dict):
            raise PacketError("packet must be a JSON object")
        master = value.get("master_sha")
        if not isinstance(master, str):
            raise PacketError("packet master SHA is absent")
        validate_packet(value, expected_master=master)
    except (OSError, UnicodeError, json.JSONDecodeError, PacketError) as exc:
        print(
            "approved disposition packet validation failed: "
            f"{relative}: {exc}"
        )
        return False
    return True


class FrozenPolicyError(Exception):
    """The frozen-receipt exceptions policy is absent or unusable."""


def load_frozen_exceptions(root: Path) -> dict[str, str]:
    """Return {repo-relative path: sha256}. Raises when the policy is unusable."""
    present = [parts for parts in FROZEN_EXCEPTIONS_PATHS if root.joinpath(*parts).exists()]
    if len(present) != 1:
        choices = ", ".join("/".join(parts) for parts in FROZEN_EXCEPTIONS_PATHS)
        raise FrozenPolicyError(
            f"policy must exist at exactly one of {choices} (found {len(present)})"
        )
    selected = present[0]
    path = root.joinpath(*selected)
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FrozenPolicyError(f"{'/'.join(selected)}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != FROZEN_EXCEPTIONS_SCHEMA:
        raise FrozenPolicyError(f"schema must be {FROZEN_EXCEPTIONS_SCHEMA}")
    entries = value.get("entries")
    if not isinstance(entries, list):
        raise FrozenPolicyError("entries must be a list")
    out: dict[str, str] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise FrozenPolicyError(f"entries[{index}] must be an object")
        relative = entry.get("path")
        digest = entry.get("sha256")
        reason = entry.get("reason")
        if not isinstance(relative, str) or not relative:
            raise FrozenPolicyError(f"entries[{index}] path is absent")
        if not isinstance(digest, str) or len(digest) != 64:
            raise FrozenPolicyError(f"entries[{index}] sha256 is not a sha256 digest")
        if not isinstance(reason, str) or not reason.strip():
            raise FrozenPolicyError(f"entries[{index}] reason is absent")
        if relative in out:
            raise FrozenPolicyError(f"entries[{index}] duplicates path {relative}")
        out[relative] = digest.lower()
    return out


def _is_frozen(root: Path, path: Path, frozen: dict[str, str]) -> bool | None:
    """True when the path is enumerated AND its bytes match the recorded digest.

    Returns None when the path is not enumerated at all, and False when it is
    enumerated but its content has drifted — a drifted entry is a failure, never
    a silent pass, because the recorded digest is the whole authority.
    """
    relative = path.relative_to(root).as_posix()
    expected = frozen.get(relative)
    if expected is None:
        return None
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual == expected:
        return True
    print(
        "frozen receipt exception does not match its recorded digest: "
        f"{relative}: expected {expected}, got {actual}"
    )
    return False


def check_paths(root: Path, paths: list[str]) -> int:
    try:
        frozen = load_frozen_exceptions(root)
    except FrozenPolicyError as exc:
        print(f"CHANGED_RECEIPTS_FAIL frozen-receipt exceptions policy unusable: {exc}")
        return 1
    checked = 0
    exempt = 0
    failed = 0
    for raw in paths:
        path = _candidate(root, raw, frozen)
        if path is None:
            continue
        verdict = _is_frozen(root, path, frozen)
        if verdict is True:
            exempt += 1
            continue
        if verdict is False:
            failed += 1
            continue
        checked += 1
        if not _check_candidate(root, path):
            failed += 1
    if failed:
        print(f"CHANGED_RECEIPTS_FAIL checked={checked} frozen={exempt} failed={failed}")
        return 1
    print(f"CHANGED_RECEIPTS_PASS count={checked} frozen={exempt}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="validate changed receipts listed as repository-relative paths"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--null",
        action="store_true",
        help="read NUL-delimited paths, as emitted by git diff -z",
    )
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        print(f"CHANGED_RECEIPTS_FAIL invalid UTF-8 path input: {exc}")
        return 1
    paths = raw.split("\0") if args.null else raw.splitlines()
    return check_paths(args.root.resolve(), paths)


if __name__ == "__main__":
    from gate_provenance import emit_gate_provenance

    emit_gate_provenance(__file__)
    raise SystemExit(main())
