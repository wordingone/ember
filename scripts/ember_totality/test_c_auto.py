#!/usr/bin/env python3
"""test_c_auto.py -- STATUS PROBE for Ember autonomy-ladder-state faithfulness.

Registry text: docs/spec/conditions-v1.md sec 4.2 C-AUTO (gh issue #104).
R: The autonomy-relinquishment ladder contract (issue #92) mandates that every
claimed rung's K>=5 consecutive windows exist, resolve, and postdate each other;
every window carries its rung's required provenance field (scheduler_provenance /
queue_provenance / launch-token per the ladder's rung table); reversion log entries
resolve; and current_rung matches the highest claimed rung (or null when none
claimed). The ladder state is a board-visible surface; the probe asserts that
every ladder claim's receipts exist and are faithfully recorded (receipts-only
truth: real bytes decide, never prose).

Zero claimed rungs = GREEN with detail "no rung claimed (honest)" -- the CHK
guards claim FAITHFULNESS, not progress. Buildable now against the current honest
state (zero claims); becomes load-bearing the moment R0 is claimed.

Fail-closed: state file missing = RED (it IS the regression), never UNEVALUABLE.
UNEVALUABLE is reserved for missing contract root only.

DISCIPLINE: status probe -- always exits 0, one line, real bytes decide, no
hardcoded verdict. RED / GREEN / UNEVALUABLE(env).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT) if p]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

INVALID_TOKENS = [
    "invalid_autonomy_unreceipted_claim",
    "invalid_autonomy_window_gap",
    "invalid_autonomy_provenance_missing",
    "invalid_autonomy_state_claim_mismatch",
    "invalid_autonomy_reversion_ignored",
]

# Mapping of rung to its required provenance field (per ladder v1 lever table).
# R0 fires live-run telemetry (V1: Render own activity visibly) - no provenance field yet (in-build).
# R1 carries scheduler_provenance (V2: Board re-runs + audit cadence).
# R2 carries queue_provenance (V4: Fire CPU-safe jobs).
# R3 carries launch_token (V5: Fire governed GPU windows).
# R4 carries spec/execution provenance (V3+V6+V7: Choose next job, Gate verdicts, Spec authorship).
# R5 carries publication_provenance (V8: Publication to public master).
RUNG_PROVENANCE_FIELDS = {
    "R0": None,  # In-build, no provenance field yet
    "R1": "scheduler_provenance",
    "R2": "queue_provenance",
    "R3": "launch_token",
    "R4": "spec_provenance",  # Generic for dispatch/verdict/design
    "R5": "publication_provenance",
}


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C-AUTO: state root not found under any known layout")

    state_path = os.path.join(ROOT, "autonomy-ladder-state.json")
    if not os.path.isfile(state_path):
        emit("RED", "C-AUTO: state file absent at autonomy-ladder-state.json -> regression (input-missing)")

    # Load and parse state file.
    try:
        with open(state_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except Exception as e:
        emit("RED", f"C-AUTO: state file unparseable ({type(e).__name__}) [invalid_autonomy_unreceipted_claim]")

    # Condition 1: State file schema fields present.
    required_fields = {"schema", "contract", "current_rung", "rungs", "reversion_log", "promotion_rule", "safety_floor"}
    missing_fields = required_fields - set(state.keys())
    if missing_fields:
        emit("RED", f"C-AUTO: state schema incomplete, missing fields {missing_fields}")

    # Condition 2: Contract path exists and safety_floor names the three never-transfer items.
    contract_rel = state.get("contract", "")
    contract_path = os.path.join(ROOT, contract_rel)
    if not os.path.isfile(contract_path):
        emit("RED", f"C-AUTO: contract path {contract_rel} does not exist [invalid_autonomy_unreceipted_claim]")

    safety_floor = state.get("safety_floor", "")
    required_safety_items = {"escalation set", "governor caps", "kill-discipline"}
    if not all(item in safety_floor for item in required_safety_items):
        emit("RED", f"C-AUTO: safety_floor missing required items (needs escalation set, governor caps, kill-discipline)")

    rungs = state.get("rungs", {})
    claimed_rungs = {rung: rung_data for rung, rung_data in rungs.items() if rung_data.get("claimed", False)}

    # If no rungs claimed, GREEN with detail "no rung claimed (honest)".
    if not claimed_rungs:
        emit("GREEN", "C-AUTO: no rung claimed (honest) -- ladder state records zero claims, probe guards faithfulness")

    offenders = []

    # Condition 3: For every claimed rung, check window receipts.
    receipts_dir = os.path.join(ROOT, "receipts", "autonomy-ladder")
    for rung_name in sorted(claimed_rungs.keys()):
        rung_data = claimed_rungs[rung_name]
        windows = rung_data.get("windows", [])

        # Check K>=5 consecutive windows.
        if not windows or len(windows) < 5:
            offenders.append((rung_name, f"only {len(windows)} window(s), need >=5 [invalid_autonomy_window_gap]"))
            continue

        # Check that every window receipt ref resolves and timestamps are consecutive.
        prev_ts = None
        for idx, window_ref in enumerate(windows):
            receipt_path = os.path.join(receipts_dir, window_ref)
            if not os.path.isfile(receipt_path):
                offenders.append((rung_name, f"window {idx} receipt {window_ref} does not resolve [invalid_autonomy_window_gap]"))
                continue

            # Load window receipt and check timestamp ordering.
            try:
                with open(receipt_path, "r", encoding="utf-8") as fh:
                    window_receipt = json.load(fh)
            except Exception as e:
                offenders.append((rung_name, f"window {idx} receipt unparseable ({type(e).__name__}) [invalid_autonomy_window_gap]"))
                continue

            window_ts = window_receipt.get("ts")
            if window_ts is None:
                offenders.append((rung_name, f"window {idx} receipt missing ts field [invalid_autonomy_window_gap]"))
                continue

            if prev_ts is not None and window_ts <= prev_ts:
                offenders.append((rung_name, f"window {idx} ts {window_ts} <= prior {prev_ts} (not strictly increasing) [invalid_autonomy_window_gap]"))
            prev_ts = window_ts

            # Check for provenance field if required by this rung.
            provenance_field = RUNG_PROVENANCE_FIELDS.get(rung_name)
            if provenance_field and provenance_field not in window_receipt:
                offenders.append((rung_name, f"window {idx} missing required provenance field {provenance_field} [invalid_autonomy_provenance_missing]"))
            elif provenance_field:
                prov_value = window_receipt.get(provenance_field)
                # Check that provenance is present, non-empty, and ember-attributed.
                # Empty/None/non-string values are theater-dodges and fail-closed.
                if not prov_value or not isinstance(prov_value, str):
                    offenders.append((rung_name, f"window {idx} provenance field {provenance_field} empty or non-string: {prov_value!r} [invalid_autonomy_provenance_missing]"))
                elif "ember" not in prov_value.lower():
                    # Substring heuristic v1: value should contain "ember" (acceptable for v1; documents pattern in comment).
                    offenders.append((rung_name, f"window {idx} provenance field {provenance_field} not ember-attributed: {prov_value!r} [invalid_autonomy_provenance_missing]"))

        # Check that claim receipt exists (one per claimed rung).
        if not os.path.isdir(receipts_dir):
            offenders.append((rung_name, f"receipts/autonomy-ladder/ absent while rung claimed [invalid_autonomy_unreceipted_claim]"))
        else:
            claim_receipts = [f for f in os.listdir(receipts_dir) if f.startswith(f"{rung_name}-claim-") and f.endswith(".json")]
            if not claim_receipts:
                offenders.append((rung_name, f"no claim receipt found for {rung_name} under receipts/autonomy-ladder/ [invalid_autonomy_unreceipted_claim]"))

    # Condition 4: current_rung equals highest claimed rung (or null when none claimed).
    current_rung = state.get("current_rung")
    if claimed_rungs:
        highest_claimed = max(sorted(claimed_rungs.keys()), key=lambda x: int(x[1:]))
        if current_rung != highest_claimed:
            offenders.append(("state", f"current_rung {current_rung!r} != highest claimed {highest_claimed} [invalid_autonomy_state_claim_mismatch]"))
    else:
        if current_rung is not None:
            offenders.append(("state", f"current_rung {current_rung!r} but no rungs claimed [invalid_autonomy_state_claim_mismatch]"))

    # Condition 5: Every reversion_log entry references a resolvable incident receipt.
    reversion_log = state.get("reversion_log", [])
    for entry in reversion_log:
        incident_ref = entry.get("incident_receipt")
        if incident_ref:
            incident_path = os.path.join(ROOT, incident_ref)
            if not os.path.isfile(incident_path):
                offenders.append(("reversion", f"incident receipt {incident_ref} does not resolve [invalid_autonomy_reversion_ignored]"))

    # Also check that no STALE claimed rung is above the latest unresolved reversion's target.
    # Re-earning a rung after reversion via fresh K windows is legitimate; it's only a violation
    # if the claim receipt's ts PREDATES the reversion entry's ts (a stale claim that ignored the reversion).
    if reversion_log and claimed_rungs:
        latest_reversion = reversion_log[-1]
        reverted_target = latest_reversion.get("target_rung")
        reversion_ts = latest_reversion.get("ts")
        if reverted_target and reversion_ts:
            target_level = int(reverted_target[1:])
            for claimed_rung in claimed_rungs.keys():
                claimed_level = int(claimed_rung[1:])
                if claimed_level > target_level:
                    # Rung is above the reversion target -- check if the claim receipt is stale (ts before reversion).
                    # Parse the claim receipt's ts; if it predates the reversion, this is a violation.
                    claim_receipts = [f for f in os.listdir(receipts_dir) if f.startswith(f"{claimed_rung}-claim-") and f.endswith(".json")] if os.path.isdir(receipts_dir) else []
                    if not claim_receipts:
                        # No claim receipt found at all -- fail-closed as stale.
                        offenders.append(("reversion", f"rung {claimed_rung} claimed above reversion target {reverted_target}, no claim receipt found (fail-closed stale) [invalid_autonomy_reversion_ignored]"))
                    else:
                        claim_receipt_path = os.path.join(receipts_dir, claim_receipts[0])
                        try:
                            with open(claim_receipt_path, "r", encoding="utf-8") as fh:
                                claim_receipt = json.load(fh)
                            claim_ts = claim_receipt.get("ts")
                            if claim_ts is None:
                                # No ts in claim receipt -- fail-closed as stale (can't verify freshness).
                                offenders.append(("reversion", f"rung {claimed_rung} claim receipt missing ts, above reversion target {reverted_target} (fail-closed stale) [invalid_autonomy_reversion_ignored]"))
                            elif claim_ts <= reversion_ts:
                                # Claim ts predates reversion -- this is a stale claim that ignored the reversion.
                                offenders.append(("reversion", f"rung {claimed_rung} claim ts {claim_ts} <= reversion ts {reversion_ts}, stale claim above target {reverted_target} [invalid_autonomy_reversion_ignored]"))
                            # else: claim ts postdates reversion -- this is a legitimate re-climb, passes.
                        except Exception as e:
                            # Claim receipt unparseable -- fail-closed as stale.
                            offenders.append(("reversion", f"rung {claimed_rung} claim receipt unparseable ({type(e).__name__}), above reversion target {reverted_target} (fail-closed stale) [invalid_autonomy_reversion_ignored]"))

    if offenders:
        shown = offenders[:3]
        more = f" (+{len(offenders) - 3} more)" if len(offenders) > 3 else ""
        by_token = {}
        for _, msg in offenders:
            token_match = [t for t in INVALID_TOKENS if t in msg]
            token = token_match[0] if token_match else "unknown"
            by_token[token] = by_token.get(token, 0) + 1
        emit("RED",
             f"C-AUTO: {len(offenders)} violation(s) across {len(by_token)} rule(s) "
             f"{by_token} -> {shown}{more}")

    # All conditions passed: GREEN with detail.
    emit("GREEN",
         f"C-AUTO: state file valid, schema complete, contract path resolves, "
         f"safety_floor names three never-transfer items, {len(claimed_rungs)} rung(s) "
         f"claimed with conforming windows/provenance/claim-receipts, current_rung consistent, "
         f"reversion log resolved -- ladder state faithfully recorded")


if __name__ == "__main__":
    main()
