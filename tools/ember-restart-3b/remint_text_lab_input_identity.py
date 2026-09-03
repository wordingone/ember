# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Canonical regeneration path for the text-lab input-identity pin (#1461, #1470).

The checked-in identity file (owned-text-lab-input-identity-v4.json) pins
sha256 hashes of three source modules (text_lab_corpus.py, train.py,
run_vertical_slice.py). Any commit that edits those modules' bytes without
re-running this script strands the pin and reddens test_text_lab_corpus.py
(#1461 root cause; recurred within hours of the #1470 instance fix at commit
e9e0671, proving the class was not killed by a one-off hand edit).

Usage:
    python tools/ember-restart-3b/remint_text_lab_input_identity.py --check
        Exit 0 if the checked-in pins match live module bytes, exit 1 with a
        diff-shaped report otherwise. Read-only; makes no writes. This is the
        form CI runs.

    python tools/ember-restart-3b/remint_text_lab_input_identity.py --write
        Recompute code_files hashes from live module bytes, rewrite
        owned-text-lab-input-identity-v4.json and the downstream
        input_identity.sha256 pin in text-lab-authority-index-v2.json.
        Every other field (corpus_sha256, source_base_commit, schema_version)
        is carried through byte-identical -- this script touches ONLY the
        code-hash-derived fields, never hand-edits.

Never hand-edit either JSON file directly (issue #1461 cure requirement:
"canonical regeneration paths, never hand-edited hashes").
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IDENTITY_PATH = ROOT / "data" / "ember-restart-3b" / "owned-text-lab-input-identity-v4.json"
INDEX_PATH = ROOT / "data" / "ember-restart-3b" / "text-lab-authority-index-v2.json"

EXPECTED_CODE = {
    "run_vertical_slice": "tools/ember-restart-3b/run_vertical_slice.py",
    "text_lab_corpus": "tools/ember-restart-3b/text_lab_corpus.py",
    "train": "tools/ember-restart-3b/train.py",
}
EXPECTED_IDENTITY_KEYS = {"schema_version", "corpus_sha256", "code_files", "source_base_commit"}
EXPECTED_CODE_KEYS = set(EXPECTED_CODE)
EXPECTED_INDEX_KEYS = {"boundary", "corpus", "input_identity", "receipt_bundle", "registry", "result", "schema_version"}
EXPECTED_INDEX_INPUT_KEYS = {"path", "schema", "sha256"}
EXPECTED_SCHEMA_KEYS = {"path", "sha256"}


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dump(obj: object) -> bytes:
    # Matches the checked-in encoding exactly: sorted keys, compact
    # separators, no trailing newline (verified byte-for-byte against #1470).
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def live_code_hashes() -> dict[str, str]:
    return {name: _sha_bytes((ROOT / relative).read_bytes()) for name, relative in EXPECTED_CODE.items()}


def _validate_identity(identity: object) -> dict[str, object]:
    if not isinstance(identity, dict) or set(identity) != EXPECTED_IDENTITY_KEYS:
        raise ValueError("identity authority has a closed schema violation")
    code_files = identity.get("code_files")
    if not isinstance(code_files, dict) or set(code_files) != EXPECTED_CODE_KEYS:
        raise ValueError("identity code_files has a closed schema violation")
    for name, value in code_files.items():
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"identity code_files.{name} is not a lowercase SHA-256")
    for name in ("corpus_sha256", "source_base_commit", "schema_version"):
        if not isinstance(identity[name], str) or not identity[name]:
            raise ValueError(f"identity {name} is invalid")
    if identity["schema_version"] != "ember-text-lab-input-identity-v2":
        raise ValueError("identity schema_version is invalid")
    return identity


def _validate_index(index: object) -> dict[str, object]:
    if not isinstance(index, dict) or set(index) != EXPECTED_INDEX_KEYS:
        raise ValueError("authority index has a closed schema violation")
    if index.get("schema_version") != "ember-text-lab-authority-index-v2":
        raise ValueError("authority index schema_version is invalid")
    input_identity = index.get("input_identity")
    if not isinstance(input_identity, dict) or set(input_identity) != EXPECTED_INDEX_INPUT_KEYS:
        raise ValueError("authority index input_identity has a closed schema violation")
    if input_identity["path"] != "data/ember-restart-3b/owned-text-lab-input-identity-v4.json":
        raise ValueError("authority index input_identity.path is invalid")
    schema = input_identity["schema"]
    if not isinstance(schema, dict) or set(schema) != EXPECTED_SCHEMA_KEYS:
        raise ValueError("authority index input_identity.schema has a closed schema violation")
    if schema["path"] != "data/ember-restart-3b/text-lab-identity-v2.schema.json":
        raise ValueError("authority index input_identity.schema.path is invalid")
    if schema["sha256"] != "69c32fb8a854c4743a33af2e905d908cfd1a5728d0650fdfe58dc329f5fda06d":
        raise ValueError("authority index input_identity.schema.sha256 is invalid")
    digest = input_identity["sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("authority index input_identity.sha256 is not a lowercase SHA-256")
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="verify pins match live bytes; no writes")
    group.add_argument("--write", action="store_true", help="regenerate pins from live bytes")
    args = parser.parse_args()

    try:
        identity = _validate_identity(json.loads(IDENTITY_PATH.read_bytes()))
        index = _validate_index(json.loads(INDEX_PATH.read_bytes()))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"INVALID AUTHORITY INPUT: {exc}")
        return 2
    live = live_code_hashes()
    pinned = identity.get("code_files", {})
    stale = {name: (pinned.get(name), live[name]) for name in EXPECTED_CODE if pinned.get(name) != live[name]}
    identity_sha = _sha_bytes(IDENTITY_PATH.read_bytes())
    index_stale = index["input_identity"]["sha256"] != identity_sha

    if args.check:
        if index_stale:
            print("STALE PIN: text-lab-authority-index-v2.json input_identity.sha256 does not match identity bytes")
            return 1
        if not stale:
            print("text-lab input identity: all code_files pins match live bytes")
            return 0
        print("STALE PIN: owned-text-lab-input-identity-v4.json code_files does not match live module bytes")
        for name, (old, new) in stale.items():
            print(f"  {name} ({EXPECTED_CODE[name]}): pinned={old} live={new}")
        print("Cure: python tools/ember-restart-3b/remint_text_lab_input_identity.py --write")
        return 1

    if not stale and not index_stale:
        print("text-lab input identity: already fresh, no write needed")
        return 0

    if stale:
        identity["code_files"] = live
        IDENTITY_PATH.write_bytes(_dump(identity))
        identity_sha = _sha_bytes(IDENTITY_PATH.read_bytes())

    index["input_identity"]["sha256"] = identity_sha
    INDEX_PATH.write_bytes(_dump(index))

    for name, (old, new) in stale.items():
        print(f"re-minted {name}: {old} -> {new}")
    print(f"re-minted input_identity.sha256 in text-lab-authority-index-v2.json -> {identity_sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
