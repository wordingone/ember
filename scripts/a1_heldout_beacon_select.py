#!/usr/bin/env python3
"""a1_heldout_beacon_select.py -- ember #631 deliverable 4: the executable consumer
of the non-grindable held-out selection rule (docs/spec/a1-postfreeze-heldout-selection-v2.md).

Given the external beacon value B (NIST Randomness Beacon v2 outputValue hex, from the
pre-registered pulse T), computes the selection deterministically:
    index = int(B[:8], 16) mod 8
with the frozen 8-candidate pool and the v1 never-before-run collision handling
((index+1) mod 8 while the candidate is cited pre-freeze). NO network here: the beacon
value is passed in (fetched + pinned separately), keeping this consumer deterministic and
offline-testable. Without a beacon value the consumer emits a PENDING receipt recording the
frozen mechanism (the pulse cannot exist until T > merge, by design).

Usage:
  python scripts/a1_heldout_beacon_select.py \\
      [--beacon-value <512-bit hex outputValue>] [--beacon-pulse-uri <uri>] \\
      --out receipts/eval-suite-freeze/a1-heldout-selection-v2-<UTCts>.json
  python scripts/a1_heldout_beacon_select.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import receipt_write  # noqa: E402

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"

POOL = [
    ("WinoGrande (winogrande_xl)", "allenai/winogrande", "validation", r"winogrande"),
    ("PIQA", "ybisk/piqa", "validation", r"\bpiqa\b"),
    ("OpenBookQA (main)", "allenai/openbookqa", "test", r"openbookqa|openbook_qa"),
    ("BoolQ", "google/boolq", "validation", r"\bboolq\b"),
    ("CommonsenseQA", "tau/commonsense_qa", "validation", r"commonsense[_-]?qa"),
    ("LAMBADA (standard)", "EleutherAI/lambada_openai", "test", r"lambada"),
    ("TruthfulQA (multiple_choice)", "truthfulqa/truthful_qa", "validation", r"truthful[_-]?qa"),
    ("SciQ", "allenai/sciq", "test", r"\bsciq\b"),
]
POOL_SIZE = len(POOL)


def cited_pre_freeze(name_regex: str) -> bool:
    """never-before-run check: does any tracked receipt cite this candidate?"""
    tracked = subprocess.run(["git", "-C", REPO, "ls-files", "receipts/"],
                             capture_output=True, text=True, check=True).stdout.split()
    pat = re.compile(name_regex, re.I)
    for rel in tracked:
        base = os.path.basename(rel)
        # exclude the selection machinery's own receipts (they legitimately name the
        # selected candidate; a self-reference is not a pre-existing eval citation)
        if base.startswith("a1-heldout-selection") or base.startswith("a1-postfreeze-heldout-selection"):
            continue
        try:
            if pat.search(open(os.path.join(REPO, rel), encoding="utf-8", errors="replace").read()):
                return True
        except OSError:
            continue
    return False


def select(beacon_hex: str, check_collision: bool = True) -> dict:
    beacon_hex = beacon_hex.lower()
    if beacon_hex.startswith("0x"):
        beacon_hex = beacon_hex[2:]
    if not re.fullmatch(r"[0-9a-f]{8,}", beacon_hex):
        raise SystemExit(f"A1_BEACON_BAD_VALUE: expected >=8 hex chars, got {beacon_hex[:16]!r}")
    base_index = int(beacon_hex[:8], 16) % POOL_SIZE
    idx = base_index
    steps = []
    for _ in range(POOL_SIZE):
        name, src, split, rx = POOL[idx]
        collided = check_collision and cited_pre_freeze(rx)
        steps.append({"index": idx, "dataset": name, "collided_pre_freeze": collided})
        if not collided:
            return {"base_index": base_index, "final_index": idx, "dataset": name,
                    "canonical_source": src, "split": split, "collision_steps": steps}
        idx = (idx + 1) % POOL_SIZE
    raise SystemExit("A1_BEACON_ALL_COLLIDE: every pool candidate cited pre-freeze (impossible "
                     "under authorship verification) -- pool must be widened by amendment")


def selftest() -> int:
    # deterministic: no collision check (offline), sample beacon values -> known indices
    cases = {"ccde4a6700": 7, "0000000000": 0, "00000001ff": 1, "0000000aff": 2}
    for hx, want in cases.items():
        got = select(hx, check_collision=False)["final_index"]
        assert got == want, f"selftest FAIL {hx}: got {got} want {want}"
    # index formula matches the spec's one-liner
    assert int("ccde4a67", 16) % 8 == 7
    print("A1_HELDOUT_BEACON_SELECT_SELFTEST_PASS (4 vectors)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--beacon-value", default=None, help="NIST beacon outputValue hex (>=8 hex chars)")
    ap.add_argument("--beacon-pulse-uri", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.out:
        raise SystemExit("A1_BEACON_NO_OUT: --out required unless --selftest")

    if args.beacon_value:
        sel = select(args.beacon_value)
        receipt = {
            "ticket": "A1-HELDOUT-SELECTION-V2",
            "ts": datetime.now(timezone.utc).isoformat(),
            "schema": "a1-heldout-selection/v2",
            "invariant_sha256": INVARIANT_SHA256,
            "sha_convention": SHA_CONVENTION,
            "issue_refs": ["#631", "#123", "#593", "#582"],
            "rule_doc": "docs/spec/a1-postfreeze-heldout-selection-v2.md",
            "status": "RESOLVED",
            "beacon": {"source": "NIST Randomness Beacon v2", "pulse_uri": args.beacon_pulse_uri,
                       "output_value_first16": (args.beacon_value.lower()[2:]
                            if args.beacon_value.lower().startswith("0x")
                            else args.beacon_value.lower())[:16]},
            "selection": sel,
            "note": "the selected dataset's pin joins suite VERSION 2; development-signal-only until then",
        }
    else:
        receipt = {
            "ticket": "A1-HELDOUT-SELECTION-V2",
            "ts": datetime.now(timezone.utc).isoformat(),
            "schema": "a1-heldout-selection/v2",
            "invariant_sha256": INVARIANT_SHA256,
            "sha_convention": SHA_CONVENTION,
            "issue_refs": ["#631", "#123", "#593", "#582"],
            "rule_doc": "docs/spec/a1-postfreeze-heldout-selection-v2.md",
            "status": "PENDING-BEACON",
            "pending_reason": "the pre-registered NIST pulse T is defined as the first pulse after "
                              "this spec's MERGE commit; the beacon value cannot exist in-PR (that is "
                              "the non-grindability property). Resolve post-merge by passing "
                              "--beacon-value from the pulse at T.",
            "pool": [{"index": i, "dataset": p[0], "canonical_source": p[1], "split": p[2]}
                     for i, p in enumerate(POOL)],
            "selection_function": "index = int(beacon_outputValue[:8], 16) mod 8; "
                                  "collision handling (index+1) mod 8 while cited pre-freeze",
            "supersedes_v1_mechanism": "docs/spec/a1-postfreeze-heldout-selection-v1.md (grindable "
                                       "commit-sha beacon); the v1 ccde4a67->SciQ record is byte-law "
                                       "immutable and not re-rolled here (coordinator ruling pending "
                                       "on grandfather-vs-replace, refs ac4_anchoring)",
        }

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    receipt_write.checked_write(args.out, receipt)
    print(f"A1_HELDOUT_BEACON_SELECT: status={receipt['status']} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
