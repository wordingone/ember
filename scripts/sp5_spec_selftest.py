#!/usr/bin/env python3
"""sp-5 spec selftest: every goal-clause noun maps to a section of the spec.

Fail-closed: missing coverage = exit 1 with the missing term named.
"""
import re
import sys
from pathlib import Path

SPEC = Path(__file__).resolve().parent.parent / "docs" / "sp5-nck-harness-port-spec-v0.md"

# goal-clause noun -> regex that must appear in the spec body
REQUIRED = {
    "clean-room rule": r"## 1\. Clean-room rule",
    "no-source-copy attestation": r"[Pp]rovenance receipt",
    "resident form": r"## 2\. Resident form",
    "event sources": r"\*\*Event sources",
    "process supervision": r"\*\*Process supervision",
    "hook points": r"\*\*Hook points",
    "uniform tool interface": r"\*\*One uniform tool interface",
    "state persistence": r"\*\*State persistence",
    "self-edit behind gate": r"\*\*Self-edit behind the gate",
    "mailbox identity": r"founders\.yaml identity",
    "computer-use surface": r"\*\*Computer use:",
    "un-removable invariants": r"## 5\. Un-removable invariants",
    "boot-time checksum": r"boot-time checksum",
    "eval-through-harness": r"## 6\. Eval-through-harness",
    "paired E2B protocol": r"ember-core vs local Gemma E2B",
    "successor eng issues": r"## 7\. Successor eng issues",
}


def main() -> int:
    if not SPEC.exists():
        print(f"SP5_SELFTEST FAIL: spec missing at {SPEC}")
        return 1
    body = SPEC.read_text(encoding="utf-8")
    missing = [name for name, pat in REQUIRED.items() if not re.search(pat, body)]
    if missing:
        print(f"SP5_SELFTEST FAIL: uncovered goal-clause terms: {missing}")
        return 1
    print(f"SP5_SELFTEST PASS: {len(REQUIRED)}/{len(REQUIRED)} goal-clause terms covered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
