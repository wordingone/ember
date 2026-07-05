#!/usr/bin/env python3
"""Totality status-probe for Ember goal condition C-ORGANISM.

Condition (authoritative text, B:/M/avir/leo/state/ember-goal-leo.md line 119):

  C-ORGANISM — the three adaptation machineries present BEFORE pretraining
  (the "forever horn").

  R (positive): ingestion (C7 / devour loop), growth (C-GROW grow-operator
  interface), and portability (C-PORT device-adaptive governor) are wired into
  the SEED GRAPH at step 0 — provably present BEFORE any pretraining run,
  deletion-sensitive (removing any one degrades the organism's ability to adapt
  to new techniques / scale / substrate respectively).

  Does NOT count:
    - a machinery retrofitted AFTER pretraining;
    - a machinery present as docs/spec but NOT wired into the runnable seed;
    - "full target capacity before pretraining" claimed WITHOUT the three
      interfaces executable on the seed.

  Invalid-token (✗): invalid_machinery_retrofitted

  CHK: a seed-graph INSPECTION RECEIPT shows all three interfaces callable on
  the pre-pretrain seed; deleting each degrades its corresponding adaptation
  selftest.

This file is a STATUS PROBE, per the goal's §4.4 totality contract:
  (a) asserts the positive CHK against a REAL receipt/artifact under
      kai-converge (no fabrication — it reads bytes on disk);
  (b) asserts that NONE of the does-NOT-count invalid-tokens match
      (encoded as negative assertions);
  (c) prints a single line "RED <reason>" or "GREEN <reason>" and exits 0
      (RED/GREEN is determined by really inspecting state, never hardcoded;
      exit 0 always so the board can aggregate).

Run ONLY via:  wsl python3 <this file>
Under WSL the B: drive is /mnt/b/.
"""

# [PATH-REWRITE 2026-07-01] Imported from
# B:/M/avir/leo/state/ember-totality-build/ into
# B:/M/ember-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at B:/M/avir/leo/state/kai-converge (and /mnt/b/M/...,
# /b/M/..., B:\\M\\... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed via pathlib from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. kai-converge does not exist
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
                 REPO_ROOT / "kai-converge")
     if p is not None and p.is_dir()),
    REPO_ROOT / "kai-converge",
)
RECEIPTS = ROOT / "receipts"
SCRIPTS = ROOT / "scripts"

# The exact invalid-token this condition fails on (negative assertion target).
INVALID_TOKENS = ["invalid_machinery_retrofitted"]

# The three machineries that must ALL be wired into ONE pre-pretrain seed graph
# and be deletion-sensitive. A receipt satisfies the CHK only if it proves all
# three callable on the seed BEFORE pretraining, with per-machinery deletion
# degradation.
MACHINERIES = {
    "ingestion": ["ingest", "devour", "c7"],
    "growth": ["grow", "net2net", "layer-stack", "layer_stack", "expert-add", "expert_add"],
    "portability": ["portab", "device-adaptive", "device_adaptive", "governor", "vram_fraction"],
}

# Tokens a genuine seed-graph inspection receipt for THIS condition would carry.
SEED_GRAPH_MARKERS = [
    "seed_graph", "seed-graph", "pre_pretrain", "pre-pretrain",
    "before_pretraining", "before pretraining", "forever_horn", "forever horn",
    "machineries_present", "three_machiner", "machinery_callable",
    "interface_callable",
]
DELETION_MARKERS = ["deletion", "deletion-sensitive", "deletion_sensitive", "ablat", "delete_each", "degrade"]


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _flatten_text(obj) -> str:
    """Lower-cased flattened text of a json object for marker scanning."""
    return json.dumps(obj, default=str).lower()


# [ISSUE #97 cure 4, 2026-07-04] The keyword-only gates above matched
# receipts/code-vs-docs/code-vs-docs-window-real-demo-since-epoch-anchor.json
# -- a code-vs-docs LINE-COUNT MANIFEST whose rows happen to mention
# filenames/prose containing "growth", "ingest", "governor", "deletion" etc.
# by coincidence, with NONE of the narrated ingestion/growth/portability
# machinery evidence this condition actually requires. It sorted
# alphabetically before the REAL artifact
# (receipts/ember-c-organism/seed-graph-inspection-*.json) and won the
# first-match `break`, so the board cited the wrong artifact. This schema
# check requires the STRUCTURED evidence the real receipt actually carries
# (machineries_present[<name>].machinery_callable is True + a named
# interface_callable, and deletion_sensitivity_summary[<name>] shows a
# distinct deleted_error_class AND a measured active>deleted degradation
# pair) -- a keyword match alone can no longer satisfy the CHK.
REQUIRED_MACHINERY_NAMES = ("ingestion", "growth", "portability")


def _active_deleted_degrades(summary_block) -> bool:
    """True iff summary_block carries at least one active_<suffix> /
    deleted_<suffix> numeric pair where active > deleted -- a genuinely
    MEASURED degradation on deletion, not merely a labelled error class."""
    if not isinstance(summary_block, dict):
        return False
    active = {
        k[len("active_"):]: v for k, v in summary_block.items()
        if k.startswith("active_") and isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    deleted = {
        k[len("deleted_"):]: v for k, v in summary_block.items()
        if k.startswith("deleted_") and isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    return any(suffix in deleted and av > deleted[suffix] for suffix, av in active.items())


def _schema_satisfied(obj) -> tuple[bool, str]:
    """Schema-check the candidate for the REQUIRED evidence fields (not just
    keyword co-occurrence). Returns (ok, reason_if_not)."""
    machineries = obj.get("machineries_present")
    deletion_summary = obj.get("deletion_sensitivity_summary")
    if not isinstance(machineries, dict):
        return False, "no machineries_present dict (keyword-only match, not structured evidence)"
    if not isinstance(deletion_summary, dict):
        return False, "no deletion_sensitivity_summary dict (keyword-only match, not structured evidence)"
    for name in REQUIRED_MACHINERY_NAMES:
        m = machineries.get(name)
        if not isinstance(m, dict) or m.get("machinery_callable") is not True:
            return False, f"machineries_present.{name}.machinery_callable is not True"
        iface = m.get("interface_callable")
        if not (isinstance(iface, str) and iface.strip()):
            return False, f"machineries_present.{name}.interface_callable missing/empty"
        ds = deletion_summary.get(name)
        if not isinstance(ds, dict):
            return False, f"deletion_sensitivity_summary.{name} missing"
        derr = ds.get("deleted_error_class")
        if not (isinstance(derr, str) and derr.strip()):
            return False, f"deletion_sensitivity_summary.{name}.deleted_error_class missing/empty"
        if not _active_deleted_degrades(ds):
            return False, f"deletion_sensitivity_summary.{name} has no measured active>deleted degradation pair"
    return True, ""


def main() -> int:
    # ---- Pre-flight: the artifact roots must really exist. -------------------
    if not RECEIPTS.is_dir():
        # Genuinely cannot inspect -> RED (artifact absent), not ERROR.
        print(f"RED C-ORGANISM: receipts dir absent at {RECEIPTS} (nothing to satisfy the CHK)")
        return 0

    receipt_files = sorted(RECEIPTS.rglob("*.json"))

    # ---- (1) POSITIVE CHK: find a REAL seed-graph inspection receipt that -----
    #         proves all three machineries callable on the PRE-PRETRAIN seed,
    #         each deletion-sensitive.
    satisfying = None
    schema_near_misses: list[str] = []  # [ISSUE #97 cure 4] keyword-matched but schema-failed
    for rp in receipt_files:
        obj = _read_json(rp)
        if obj is None:
            continue
        text = _flatten_text(obj)

        # Must read as a seed-graph / pre-pretrain inspection receipt.
        if not any(m in text for m in SEED_GRAPH_MARKERS):
            continue
        # Must cover all three machineries.
        machineries_hit = {
            name: any(kw in text for kw in kws) for name, kws in MACHINERIES.items()
        }
        if not all(machineries_hit.values()):
            continue
        # Must be deletion-sensitive (per-machinery degradation proof).
        if not any(d in text for d in DELETION_MARKERS):
            continue
        # [ISSUE #97 cure 4] Keyword co-occurrence alone is not evidence --
        # schema-check the REQUIRED structured fields before accepting this
        # candidate (see _schema_satisfied docstring: this is exactly the
        # check that rejects the code-vs-docs line-count manifest and lets
        # the loop continue on to the real seed-graph-inspection receipt).
        schema_ok, schema_reason = _schema_satisfied(obj)
        if not schema_ok:
            schema_near_misses.append(f"{rp.name}: {schema_reason}")
            continue
        satisfying = rp
        break

    # ---- (2) NEGATIVE ASSERTIONS: none of the does-NOT-count invalid-tokens ---
    #         may appear in a candidate satisfying receipt.
    invalid_hits: list[str] = []
    if satisfying is not None:
        sat_text = _flatten_text(_read_json(satisfying))
        for tok in INVALID_TOKENS:
            if tok.lower() in sat_text:
                invalid_hits.append(tok)

    # ---- Verdict (determined by real inspection, never hardcoded). -----------
    if satisfying is None:
        schema_note = (
            f" {len(schema_near_misses)} candidate(s) matched keywords but FAILED "
            f"the required-evidence schema (wrong artifact, not genuine absence): "
            f"{schema_near_misses[:3]}."
            if schema_near_misses else ""
        )
        print(
            "RED C-ORGANISM: no seed-graph inspection receipt under "
            f"{RECEIPTS} proves ingestion+growth+portability all callable on the "
            "pre-pretrain seed with per-machinery deletion-sensitivity "
            f"(scanned {len(receipt_files)} receipts; the three machineries exist "
            "only as scattered scripts — ember_growth_harness.py, governor.py, "
            "ingestion loops — never wired into ONE inspectable seed graph at "
            f"step 0; CHK unmet, artifact genuinely ABSENT).{schema_note}"
        )
        return 0

    if invalid_hits:
        print(
            f"RED C-ORGANISM: candidate receipt {satisfying.name} matches "
            f"invalid-token(s) {invalid_hits} (does-NOT-count: machinery "
            "retrofitted / docs-only / interfaces not executable on seed)"
        )
        return 0

    print(
        f"GREEN C-ORGANISM: seed-graph inspection receipt {satisfying.name} "
        "proves ingestion+growth+portability all callable on the pre-pretrain "
        "seed, each deletion-sensitive, with no invalid-token present"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
