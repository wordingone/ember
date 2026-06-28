#!/usr/bin/env python3
"""fp-33 prereg selftest: the frozen surpass protocol carries every binding element.

Fail-closed: a missing element = exit 1 with the element named. Guards the
freeze against silent edits — run output is compared against the frozen
element list, so a section rename or bar deletion fails loudly.
"""
import re
import sys
from pathlib import Path

PREREG = Path(__file__).resolve().parent.parent / "docs" / "fp33-surpass-prereg-v1.md"

# binding element -> regex that must appear in the prereg body
REQUIRED = {
    "frozen status line": r"Status: FROZEN",
    "deviation protocol": r"fp-30b deviation protocol",
    "means/measurement split": r"does NOT freeze the means",
    "opponent weights pinned": r"sha256 of the weight files",
    "seat-swap rule": r"swapped into\s+ember's OWN harness",
    "matched compute tolerance": r"match within 10%",
    "pinned seeds": r"\{16, 17, 18\}",
    "paired bootstrap 10k": r"10,000 resamples",
    "mcnemar duty test": r"McNemar",
    "A1 floor-world": r"\*\*A1 — floor-world paired eval",
    "A2 loop differential": r"\*\*A2 — accumulation-loop differential",
    "A2 three-test gate": r"held-out transfer,\s+matched\s+control,\s+deletion\s+test",
    "A3 public slices": r"\*\*A3 — public slices",
    "A3 mbpp": r"MBPP validation slice",
    "A3 gsm8k-200": r"GSM8K test slice, first 200",
    "B1 answers": r"\*\*B1 — answers when spoken to",
    "B2 agency": r"\*\*B2 — agency",
    "B3 duty battery": r"\*\*B3 — duty battery",
    "B4 evals-through-harness": r"\*\*B4 — evals-through-harness",
    "verdict conjunction": r"SURPASS = A1 ∧ A2 ∧ A3 ∧ B1 ∧ B2 ∧ B3 ∧ B4",
    "deadline": r"2026-06-22",
    "measured-distance fallback": r"measured-distance receipt",
    "user-only retirement": r"by name",
    "named successors": r"## Named successors",
}


def main() -> int:
    if not PREREG.exists():
        print(f"FP33_PREREG_SELFTEST FAIL: prereg missing at {PREREG}")
        return 1
    body = PREREG.read_text(encoding="utf-8")
    missing = [name for name, pat in REQUIRED.items() if not re.search(pat, body)]
    if missing:
        print(f"FP33_PREREG_SELFTEST FAIL: missing binding elements: {missing}")
        return 1
    print(f"FP33_PREREG_SELFTEST PASS: {len(REQUIRED)}/{len(REQUIRED)} binding elements present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
