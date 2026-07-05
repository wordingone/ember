#!/usr/bin/env python3
"""Ember totality test � Condition C12 (status probe / TDD).

C12 � State-dependent cognitive modes.
  R: modes selected by state (observe/orient/hypothesize/simulate/act/verify/
     consolidate/sleep/ask/refuse/rollback/report), triggered by evidence/
     uncertainty/verifier-state/headroom/blocker/risk; deleting the mode
     selector or replacing it with fixed time slices degrades the cycle.
  Does NOT count: fixed equal-duration baseline/dream/full-loop phases;
     `idle_think` without a bounded emitted artifact; treating the internal
     scheduler as permission for the executor to pause `/goal`.
  Invalid-token (?): invalid_timer_artifact_modes
  CHK: deleted-mode-selector receipt degrades cycle/next-action/recipe.

Gloss (task): state-dependent cognitive modes (peer selector cognitive-mode policy):
  modes selected by state; deleting the selector or using fixed time slices
  degrades the cycle.
Receipt hint: scripts/ember_cognitive_mode_policy.py + selftest,
  ember_state_substrate.py, state-dependent receipt.

This is a STATUS PROBE. It always exits 0 and prints exactly one line
beginning with "RED " or "GREEN ". RED/GREEN is determined by really
inspecting state under <external-state> � never hardcoded.

Run ONLY via:  wsl python3 <this file>
Under WSL the execution root may mount at <local-mount-point>/ or /mnt<local-mount-point>/ on this host.
"""

# [PATH-REWRITE 2026-07-01] Imported from
# <<external>>/state/ember-totality-build/ into
# <local-exec-root>-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at <<external>>/state/<external-state> (and /mnt<local-mount-point>/M/...,
# <local-mount-point>/M/..., B:\\M\\... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. <external-state> does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.

import json
import os
import re
import sys

# --- Locate <external-state> robustly across WSL mount conventions ----------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                os.path.join(REPO_ROOT, "<external-state>"))
    if p
]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

# The selector source that C12 names ("peer selector cognitive-mode policy").
SELECTOR_REL = os.path.join("scripts", "ember_cognitive_mode_policy.py")

# C12's CHK is satisfied by a *deleted-mode-selector receipt* that shows the
# fixed-timer replacement (or deletion) degrades the cycle/next-action/recipe.
# That receipt is the native cycle receipt, which wires the live selector AND
# carries the fixed_timer_ablation / deletion_ablation degradation blocks.
RECEIPT_GLOB_DIRS = [
    os.path.join("receipts", "ember-mvp", "breakthrough-goal-20260619"),
    os.path.join("receipts", "ember-mvp"),
    "receipts",
]

# --- Invalid-tokens / "does NOT count" substitutes (negative assertions) ------
# C12 explicit ? token. If a receipt is STAMPED with this verdict it has been
# judged a timer-artifact (not a real state-dependent selector) -> RED.
INVALID_TOKEN = "invalid_timer_artifact_modes"

# "Does NOT count" substitutes, encoded so a receipt cannot pass by being one of
# them. These are matched only where they appear as the receipt's own
# mechanism/verdict (not where a doc merely DEFINES/forbids them).
#  - fixed equal-duration baseline/dream/full-loop phases (timer artifact modes)
#  - idle_think WITHOUT a bounded emitted artifact
#  - internal scheduler used as permission for the executor to pause /goal
DOESNT_COUNT_PHRASES = [
    "equal_duration",
    "equal-duration",
    "fixed equal duration",
    "dream_phase",
    "fixed_time_slice_modes",
    "timer_artifact_modes",
    "fixed-timer modes",
]


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


def find_receipts(root):
    """Return candidate receipt file paths most-specific-first."""
    seen = []
    for rel in RECEIPT_GLOB_DIRS:
        d = os.path.join(root, rel)
        if not os.path.isdir(d):
            continue
        try:
            for name in sorted(os.listdir(d)):
                if name.endswith(".json"):
                    p = os.path.join(d, name)
                    if p not in seen:
                        seen.append(p)
        except OSError:
            continue
    return seen


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def walk_strings(obj, acc):
    """Collect all string values (keys + values) from a nested json object."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.append(str(k))
            walk_strings(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            walk_strings(v, acc)
    else:
        acc.append(str(obj))


def find_ablation_block(obj):
    """Search the receipt object for a deletion/fixed-timer ablation block that
    proves removing the state-dependent cognitive-mode selector degrades the
    cycle. Returns (kind, block) or (None, None).

    A satisfying block must (a) name the state-dependent cognitive mode selector
    (or fixed-timer replacement) as the deleted object, and (b) carry a truthy
    'degrade*' flag � i.e. removal really degrades the cycle/decision/evidence.
    """
    results = []

    def rec(node):
        if isinstance(node, dict):
            keys_low = {str(k).lower() for k in node.keys()}
            # Does this dict describe a deletion/fixed-timer ablation?
            mentions_timer = any(
                "fixed_timer" in k or "timer" in k for k in keys_low
            )
            mentions_delete = any(
                "delet" in k or "ablat" in k for k in keys_low
            )
            blob = json.dumps(node, sort_keys=True).lower()
            names_selector = (
                "cognitive mode selector" in blob
                or "cognitive_mode_selector" in blob
                or "state-dependent cognitive mode" in blob
                or "fixed timer slices" in blob
                or "fixed_timer" in blob
            )
            degrade_flags = [
                k for k in node.keys()
                if str(k).lower().startswith("degrade")
                or "degrades_" in str(k).lower()
            ]
            degrades_truthy = any(bool(node[k]) for k in degrade_flags)
            # [HARDENED 2026-07-03] A free 'degrad' text mention is NOT evidence:
            # a null-result receipt described with degradation vocabulary must
            # never pass. Acceptance requires an explicit truthy degrade* flag.
            free_degrade = "degrad" in blob  # reported, never load-bearing
            if (mentions_timer or mentions_delete) and names_selector and degrades_truthy:
                kind = "fixed_timer_ablation" if mentions_timer else "deletion_ablation"
                results.append((kind, node, degrades_truthy, free_degrade))
            for v in node.values():
                rec(v)
        elif isinstance(node, list):
            for v in node:
                rec(v)

    rec(obj)
    # Prefer a block with an explicit truthy degrade flag.
    results.sort(key=lambda r: (not r[2], not r[3]))
    if results:
        kind, node, _, _ = results[0]
        return kind, node
    return None, None


def receipt_wires_selector(obj):
    """True if the receipt references the live state-dependent selector source
    AND logs state-driven mode decisions (not fixed time slices)."""
    blob = json.dumps(obj, sort_keys=True)
    wires = "ember_cognitive_mode_policy.py" in blob
    # [HARDENED 2026-07-03] The old detector matched 5 hardcoded reason strings
    # from a design that never shipped (fixture vocabulary) - no real receipt
    # could ever satisfy it. STRUCTURAL evidence instead: a decision entry must
    # carry BOTH a state vector (>=3 of the selector's six input fields) AND a
    # selected mode string - modes chosen FROM STATE, per decision, not merely
    # named in prose.
    _STATE_FIELDS = ("evidence_strength", "uncertainty", "verifier_state",
                     "headroom", "blocker_present", "risk_level")

    def _entry_state_driven(node):
        if not isinstance(node, dict):
            return False
        st = node.get("state")
        if not isinstance(st, dict) or sum(1 for f in _STATE_FIELDS if f in st) < 3:
            return False
        for k, v in node.items():
            if k == "state":
                continue
            if isinstance(v, str) and v:
                if k == "mode" or k.endswith("_mode"):
                    return True
            if isinstance(v, dict) and isinstance(v.get("mode"), str) and v.get("mode"):
                return True
        return False

    def _walk(node):
        if isinstance(node, dict):
            if _entry_state_driven(node):
                return True
            return any(_walk(v) for v in node.values())
        if isinstance(node, list):
            return any(_walk(v) for v in node)
        return False

    state_driven = _walk(obj)
    return wires, state_driven


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C12: state root not found under any known layout -- input-missing, dead branch under the flat-layout resolver (paper-consistency flip, 2026-07-02)")

    # The selector source must exist (the body the receipt deletes/ablates).
    selector_path = os.path.join(ROOT, SELECTOR_REL)
    selector_present = os.path.isfile(selector_path)

    receipts = find_receipts(ROOT)
    if not receipts:
        emit("RED", "C12: no receipt files found under receipts/ -> "
                    "no deleted-mode-selector degradation receipt exists")

    # --- Scan every receipt for the satisfying deleted-mode-selector block ----
    best = None            # (path, kind, block, wires, state_driven)
    invalid_token_hit = None
    doesnt_count_hit = None

    for path in receipts:
        obj = load_json(path)
        if obj is None:
            continue
        blob = json.dumps(obj, sort_keys=True).lower()

        # (B1) Negative assertion: explicit ? token stamped as a verdict.
        if INVALID_TOKEN in blob:
            # Only a live verdict/stamp counts (a doc defining it is not here,
            # since these are receipts, not the goal spec). Treat any presence
            # in a receipt as a live hit.
            invalid_token_hit = (os.path.basename(path), INVALID_TOKEN)

        # (B2) Negative assertion: a "does NOT count" substitute used as the
        # receipt's own mode mechanism.
        if doesnt_count_hit is None:
            for ph in DOESNT_COUNT_PHRASES:
                if ph in blob:
                    doesnt_count_hit = (os.path.basename(path), ph)
                    break

        kind, block = find_ablation_block(obj)
        if block is not None:
            wires, state_driven = receipt_wires_selector(obj)
            cand = (path, kind, block, wires, state_driven)
            # Prefer a receipt that BOTH wires the live selector AND shows the
            # ablation degradation � that is the strongest C12 evidence.
            if best is None:
                best = cand
            else:
                cur_score = int(best[3]) + int(best[4])
                new_score = int(wires) + int(state_driven)
                if new_score > cur_score:
                    best = cand

    # --- (B) invalid-token / does-NOT-count gate decided FIRST ----------------
    # A matched invalid-token or substitute overrides any positive evidence:
    # the condition is then RED by the negative assertion (TDD: the does-NOT-
    # count clause must be able to flip an otherwise-passing receipt).
    if invalid_token_hit is not None:
        emit("RED",
             f"C12: invalid-token '{invalid_token_hit[1]}' stamped on receipt "
             f"{invalid_token_hit[0]} -> modes judged a timer-artifact, not a "
             f"state-dependent selector (invalid_timer_artifact_modes)")

    if doesnt_count_hit is not None:
        emit("RED",
             f"C12: does-NOT-count substitute '{doesnt_count_hit[1]}' present as "
             f"mode mechanism in {doesnt_count_hit[0]} -> fixed equal-duration / "
             f"timer-artifact modes (invalid_timer_artifact_modes)")

    # --- (C) Positive CHK -----------------------------------------------------
    if best is None:
        # Three-valued correction (2026-07-02, same class as the C9 fail-open
        # fix): the corpus WAS scanned successfully and the answer is "no such
        # artifact" -- that is an evaluated UNMET, never "probe couldn't look".
        # UNEVALUABLE stays reserved for env-failure (root/receipts missing).
        emit("RED",
             "C12: no receipt carries a deleted-mode-selector / fixed-timer "
             "ablation block proving removal degrades the cycle -> CHK unmet, "
             "satisfying artifact genuinely ABSENT (corpus scanned)")

    path, kind, block, wires, state_driven = best

    if not selector_present:
        emit("RED",
             f"C12: ablation receipt {os.path.basename(path)} references the "
             f"selector but the selector source {SELECTOR_REL} is ABSENT on disk "
             f"-> nothing real to delete/ablate")

    # Confirm the chosen block actually carries a truthy degradation signal.
    degrade_flags = {
        k: block[k] for k in block
        if str(k).lower().startswith("degrade") or "degrades_" in str(k).lower()
    }
    degrades_truthy = any(bool(v) for v in degrade_flags.values())
    # [HARDENED 2026-07-03] prose-mention escape removed - flag must be truthy.
    if not degrades_truthy:
        emit("RED",
             f"C12: ablation block in {os.path.basename(path)} ({kind}) names the "
             f"selector but shows NO degradation -> deletion is not "
             f"degrade-sensitive (CHK unmet)")

    # [HARDENED 2026-07-03] was OR - a receipt naming the selector file without
    # per-decision state-driven evidence could pass. Both are required.
    if not (wires and state_driven):
        emit("RED",
             f"C12: receipt {os.path.basename(path)} has an ablation block but "
             f"does not wire the live state-dependent selector nor log state-"
             f"driven mode decisions -> selector not load-bearing")

    # GREEN: a real receipt wires the state-dependent cognitive-mode selector,
    # logs state-driven decisions, and carries a deletion/fixed-timer ablation
    # block proving removal degrades the cycle; no invalid-token or does-NOT-
    # count substitute matched.
    deg_summary = ", ".join(f"{k}={v}" for k, v in degrade_flags.items()) or "free-degrade-text"
    emit("GREEN",
         f"C12: deleted-mode-selector receipt {os.path.basename(path)} carries "
         f"{kind} for the state-dependent cognitive mode selector "
         f"({deg_summary}); selector source {SELECTOR_REL} present; "
         f"wires_selector={wires} state_driven_decisions={state_driven}; "
         f"no invalid_timer_artifact_modes / equal-duration substitute "
         f"-> modes are state-selected and deletion-sensitive")


if __name__ == "__main__":
    main()
