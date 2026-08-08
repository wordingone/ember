"""Canonical regeneration path for the text-lab input-identity pin (#1461, #1470).

The checked-in identity file (owned-text-lab-input-identity-v2.json) pins
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
        owned-text-lab-input-identity-v2.json and the downstream
        input_identity.sha256 pin in text-lab-authority-index-v1.json.
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
IDENTITY_PATH = ROOT / "data" / "ember-restart-3b" / "owned-text-lab-input-identity-v2.json"
INDEX_PATH = ROOT / "data" / "ember-restart-3b" / "text-lab-authority-index-v1.json"

EXPECTED_CODE = {
    "run_vertical_slice": "tools/ember-restart-3b/run_vertical_slice.py",
    "text_lab_corpus": "tools/ember-restart-3b/text_lab_corpus.py",
    "train": "tools/ember-restart-3b/train.py",
}


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dump(obj: object) -> bytes:
    # Matches the checked-in encoding exactly: sorted keys, compact
    # separators, no trailing newline (verified byte-for-byte against #1470).
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def live_code_hashes() -> dict[str, str]:
    return {name: _sha_bytes((ROOT / relative).read_bytes()) for name, relative in EXPECTED_CODE.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="verify pins match live bytes; no writes")
    group.add_argument("--write", action="store_true", help="regenerate pins from live bytes")
    args = parser.parse_args()

    identity = json.loads(IDENTITY_PATH.read_bytes())
    live = live_code_hashes()
    pinned = identity.get("code_files", {})
    stale = {name: (pinned.get(name), live[name]) for name in EXPECTED_CODE if pinned.get(name) != live[name]}

    if args.check:
        if not stale:
            print("text-lab input identity: all code_files pins match live bytes")
            return 0
        print("STALE PIN: owned-text-lab-input-identity-v2.json code_files does not match live module bytes")
        for name, (old, new) in stale.items():
            print(f"  {name} ({EXPECTED_CODE[name]}): pinned={old} live={new}")
        print("Cure: python tools/ember-restart-3b/remint_text_lab_input_identity.py --write")
        return 1

    if not stale:
        print("text-lab input identity: already fresh, no write needed")
        return 0

    identity["code_files"] = live
    IDENTITY_PATH.write_bytes(_dump(identity))
    new_identity_sha = _sha_bytes(IDENTITY_PATH.read_bytes())

    index = json.loads(INDEX_PATH.read_bytes())
    index["input_identity"]["sha256"] = new_identity_sha
    INDEX_PATH.write_bytes(_dump(index))

    for name, (old, new) in stale.items():
        print(f"re-minted {name}: {old} -> {new}")
    print(f"re-minted input_identity.sha256 in text-lab-authority-index-v1.json -> {new_identity_sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
