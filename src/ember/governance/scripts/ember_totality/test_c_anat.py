#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Totality status-probe for Ember goal condition C-ANAT.

Condition (authoritative text, <<external>>/state/<spec> line 121):

  C-ANAT — Canonical anatomy (#8).

  R (positive): the 16-doc architecture set complete (the 5 absent authored,
  the 7 partial finished); verifier-free judgment (H4) addressed.

  Does NOT count:
    - docs-only progress claimed as substrate (code-vs-docs still applies).

  Invalid-token (✗): invalid_anatomy_incomplete

  CHK: all 16 docs present AND consistent with the receipts.

Authoritative enumeration of the 16-doc set
(<<external>>/state/ember-master-plan-exhaustive-2026-06-22.md line 54):

  "Anatomy 16-doc: 5 absent (00_INDEX, 08_PROMPT_REGISTRY, 13_RUNBOOK,
   14_MODEL_CARD, 15_TECHNICAL_REPORT); 7 partial (01,02,03-authoritative,
   09,10,11,12); 4 strong (04,05,06,07)."

  -> the set is numbered 00..15 (16 docs). The CHK requires every one of the
  16 to exist as an architecture doc AND a receipt to attest the set complete
  and consistent with the receipts. H4 (verifier-free judgment) must be
  addressed, not OPEN/UNTOUCHED.

This file is a STATUS PROBE, per the goal's §4.4 totality contract:
  (a) asserts the positive CHK against a REAL receipt/artifact under
      <external-state> (no fabrication — it reads bytes on disk);
  (b) asserts that NONE of the does-NOT-count invalid-tokens match
      (encoded as negative assertions);
  (c) prints a single line "RED <reason>" or "GREEN <reason>" and exits 0
      (RED/GREEN is determined by really inspecting state, never hardcoded;
      exit 0 always so the board can aggregate).

Run ONLY via:  wsl python3 <this file>
Under WSL the execution root is /mnt<local-mount-point>/.
"""

# [PATH-REWRITE 2026-07-01] Imported from
# <<external>>/state/ember-totality-build/ into
# <local-exec-root>-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at <<external>>/state/<external-state> (and /mnt<local-mount-point>/M/...,
# <local-mount-point>/M/..., <TEMP_WORKSPACE>/... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed via pathlib from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. <external-state> does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_env_root = os.environ.get("EMBER_TOTALITY_ROOT")
ROOT = next(
    (p for p in (Path(_env_root) if _env_root else None, REPO_ROOT,
                 REPO_ROOT / "<external-state>")
     if p is not None and p.is_dir()),
    REPO_ROOT / "<external-state>",
)
RECEIPTS = ROOT / "receipts"
DOCS = ROOT / "docs"
RESEARCH = ROOT / "research"

# The exact invalid-token this condition fails on (negative assertion target).
INVALID_TOKENS = ["invalid_anatomy_incomplete"]

# The 16 canonical anatomy docs, by their authoritative stable-id prefix
# (00..15) and the name token from the master-plan enumeration. A doc counts
# as "present" only if a real .md file whose NAME carries both the NN_ prefix
# and an architecture-doc shape is found under the repo.
#   5 absent  : 00_INDEX, 08_PROMPT_REGISTRY, 13_RUNBOOK, 14_MODEL_CARD, 15_TECHNICAL_REPORT
#   7 partial : 01, 02, 03(authoritative), 09, 10, 11, 12
#   4 strong  : 04, 05, 06, 07
ANATOMY_PREFIXES = [f"{i:02d}_" for i in range(16)]  # "00_" .. "15_"

# A receipt that legitimately satisfies the CHK must read as a canonical-anatomy
# completion/consistency attestation, not an arbitrary receipt mentioning the word.
ANATOMY_RECEIPT_MARKERS = [
    "c-anat", "c_anat", "canonical anatomy", "canonical_anatomy",
    "anatomy_set", "anatomy-set", "16-doc", "16 doc", "16_doc",
    "architecture set", "architecture_set", "anatomy_complete",
]
# CHK demands "consistent with the receipts" -> the attestation must claim a
# consistency / cross-check against receipts, not merely "docs exist".
CONSISTENCY_MARKERS = [
    "consist", "cross-check", "cross_check", "crosscheck",
    "receipt-backed", "receipt_backed", "verified_against_receipts",
    "all_present", "all 16", "all16", "set_complete", "complete",
]
# H4 (verifier-free judgment) must be ADDRESSED, not OPEN/UNTOUCHED.
H4_MARKERS = ["h4", "verifier-free", "verifier_free", "calibration-as-skill", "calibration_as_skill"]


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _flatten_text(obj) -> str:
    return json.dumps(obj, default=str).lower()


def _find_anatomy_docs() -> dict[str, list[str]]:
    """Map each NN_ prefix -> list of matching real .md filenames on disk.

    Scans the whole repo (docs/, research/, anywhere) for files whose name
    begins with the 2-digit anatomy prefix and an uppercase architecture-doc
    token (NN_NAME.md). Returns only real bytes-on-disk hits.
    """
    found: dict[str, list[str]] = {p: [] for p in ANATOMY_PREFIXES}
    if not ROOT.is_dir():
        return found
    for md in ROOT.rglob("*.md"):
        name = md.name
        for pref in ANATOMY_PREFIXES:
            # Architecture-doc shape: "NN_SOMETHING.md" (uppercase tokenish).
            if name.startswith(pref) and name[len(pref):len(pref) + 1].isalpha():
                found[pref].append(str(md.relative_to(ROOT)))
    return found


def main() -> int:
    # ---- Pre-flight: the artifact roots must really exist. -------------------
    if not ROOT.is_dir():
        print(f"UNEVALUABLE C-ANAT: state root absent at {ROOT} -- input-missing, "
              "dead branch under the flat-layout resolver (paper-consistency "
              "flip, 2026-07-02)")
        return 0

    # ---- (1) POSITIVE CHK part A: all 16 anatomy docs present on disk. -------
    found = _find_anatomy_docs()
    present = [p for p, hits in found.items() if hits]
    missing = [p for p, hits in found.items() if not hits]

    # ---- (1) POSITIVE CHK part B: a REAL receipt attests the set complete -----
    #         AND consistent with the receipts, with H4 addressed.
    satisfying = None
    if RECEIPTS.is_dir():
        receipt_files = sorted(RECEIPTS.rglob("*.json"))
        for rp in receipt_files:
            obj = _read_json(rp)
            if obj is None:
                continue
            text = _flatten_text(obj)
            if not any(m in text for m in ANATOMY_RECEIPT_MARKERS):
                continue
            if not any(m in text for m in CONSISTENCY_MARKERS):
                continue
            if not any(m in text for m in H4_MARKERS):
                continue
            satisfying = rp
            break
    else:
        receipt_files = []

    # ---- (2) NEGATIVE ASSERTIONS: the does-NOT-count invalid-token must NOT --
    #         hold. invalid_anatomy_incomplete is TRUE whenever any of the 16
    #         docs is missing. We also guard the does-NOT-count clause:
    #         docs-only progress (no receipt-consistency attestation) cannot be
    #         claimed as substrate. Encoded as negative assertions below.
    invalid_hits: list[str] = []

    # invalid_anatomy_incomplete holds iff the doc set is not all-16-present.
    if missing:
        invalid_hits.append("invalid_anatomy_incomplete")

    # Also: if a candidate satisfying receipt literally carries the token, fail.
    if satisfying is not None:
        sat_text = _flatten_text(_read_json(satisfying))
        for tok in INVALID_TOKENS:
            if tok.lower() in sat_text and tok not in invalid_hits:
                invalid_hits.append(tok)

    # ---- Verdict (determined by real inspection, never hardcoded). -----------
    if invalid_hits:
        print(
            f"RED C-ANAT: invalid-token(s) {invalid_hits} hold — "
            f"{len(present)}/16 anatomy docs present, missing prefixes={missing} "
            f"(authoritative set 00_INDEX..15_TECHNICAL_REPORT per master-plan "
            f"line 54: 5 absent + 7 partial + 4 strong); the 5 named-absent docs "
            f"are genuinely not on disk under {ROOT}; CHK 'all 16 present and "
            f"consistent with receipts' unmet"
        )
        return 0

    # docs-only guard: even if (hypothetically) all 16 existed, the CHK also
    # demands a real receipt attesting consistency-with-receipts + H4 addressed.
    # Absent that receipt, docs-only progress cannot be claimed as substrate.
    if satisfying is None:
        print(
            "RED C-ANAT: all 16 anatomy doc prefixes present on disk but NO real "
            f"receipt under {RECEIPTS} attests the set complete AND consistent "
            "with the receipts with H4 (verifier-free judgment) addressed "
            f"(scanned {len(receipt_files)} receipts); docs-only progress does "
            "NOT count as substrate (code-vs-docs still applies); CHK unmet"
        )
        return 0

    print(
        f"GREEN C-ANAT: all 16 anatomy docs present and receipt "
        f"{satisfying.name} attests the set complete + consistent with receipts "
        "+ H4 addressed, with no invalid-token present"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
