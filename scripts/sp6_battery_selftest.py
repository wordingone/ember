#!/usr/bin/env python3
"""sp-6 duty-battery selftest (#269 content half).

Validates the frozen episode set: 20 episodes, 4 families x 5, unique ids,
verbs from the closed enum, target patterns compile. Fail-closed.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

BATTERY = Path(__file__).resolve().parent.parent / "docs" / "sp6-duty-battery.jsonl"

VERB_ENUM = {
    "reply", "ack-begin", "challenge", "no-action", "clarify",
    "gate-pass", "gate-fail", "dedup", "escalate",
    "execute-due", "heartbeat-only", "monitor", "gate-then-next",
    "clear-lock", "repair-escalate", "flag-missing", "report", "clean",
}
FAMILIES = {"mail-triage", "receipt-gating", "schedule", "file-hygiene"}
REQUIRED = {"id", "family", "event", "expected_verb", "target_pattern", "notes"}


def main() -> int:
    fails = []
    rows = [json.loads(l) for l in BATTERY.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(rows) != 20:
        fails.append(f"expected 20 episodes, got {len(rows)}")
    ids = [r.get("id") for r in rows]
    if len(set(ids)) != len(ids):
        fails.append(f"duplicate ids: {[i for i, c in Counter(ids).items() if c > 1]}")
    fam_counts = Counter(r.get("family") for r in rows)
    if set(fam_counts) != FAMILIES or any(v != 5 for v in fam_counts.values()):
        fails.append(f"family balance wrong: {dict(fam_counts)} (need 4 families x 5)")
    for r in rows:
        missing = REQUIRED - set(r)
        if missing:
            fails.append(f"{r.get('id','?')}: missing fields {sorted(missing)}")
        if r.get("expected_verb") not in VERB_ENUM:
            fails.append(f"{r.get('id')}: verb {r.get('expected_verb')!r} not in enum")
        try:
            re.compile(r.get("target_pattern", ""))
        except re.error as exc:
            fails.append(f"{r.get('id')}: target_pattern does not compile: {exc}")
    # selectivity episodes (correct answer = no outward action) must exist
    silent = [r["id"] for r in rows if r["expected_verb"] in {"no-action", "heartbeat-only", "dedup", "clean"}]
    if len(silent) < 3:
        fails.append(f"need >=3 silence-correct episodes (selectivity), got {silent}")
    if fails:
        print("SP6_BATTERY_SELFTEST FAIL:")
        for f in fails:
            print(f"  - {f}")
        return 1
    print(f"SP6_BATTERY_SELFTEST PASS: 20 episodes, 4x5 families, "
          f"{len(silent)} silence-correct, all patterns compile")
    return 0


if __name__ == "__main__":
    sys.exit(main())
