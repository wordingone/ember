#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_c_auto.py -- STATUS PROBE for Ember autonomy-ladder-state faithfulness.

Registry text: docs/domains/governance/spec/conditions-v1.md sec 4.2 C-AUTO (gh issue #104).
R: The autonomy-relinquishment ladder contract (issue #92) mandates that every
claimed rung's K>=5 consecutive windows exist, resolve, and postdate each other;
every window binds a real Git commit and carries a closed, hash-linked Ember
provenance token; reversion log entries
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
from datetime import datetime, timezone
from pathlib import Path

from autonomy_claim_evidence import ClaimEvidenceError, validate_claimed_rung

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '..'))
CANDIDATE_ROOTS = [p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT) if p]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

INVALID_TOKENS = [
    "invalid_autonomy_unreceipted_claim",
    "invalid_autonomy_window_gap",
    "invalid_autonomy_provenance_missing",
    "invalid_autonomy_state_claim_mismatch",
    "invalid_autonomy_reversion_ignored",
    "invalid_autonomy_claim_evidence",
]

def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


def parse_utc_timestamp(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must be an ISO-8601 UTC string ending in Z")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo != timezone.utc:
        raise ValueError("timestamp must resolve to UTC")
    return parsed


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C-AUTO: state root not found under any known layout")

    state_path = os.path.join(ROOT, "docs/domains/governance/authority/autonomy-ladder-state.json")
    if not os.path.isfile(state_path):
        emit("RED", "C-AUTO: canonical autonomy ladder state absent -> regression (input-missing)")

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
    validated_claim_times = {}

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
            try:
                parsed_window_ts = parse_utc_timestamp(window_ts)
            except (TypeError, ValueError):
                offenders.append(
                    (
                        rung_name,
                        f"window {idx} receipt ts is not strict ISO-8601 UTC "
                        f"[invalid_autonomy_claim_evidence]",
                    )
                )
                continue

            if prev_ts is not None and parsed_window_ts <= prev_ts:
                offenders.append((rung_name, f"window {idx} ts {window_ts} <= prior {prev_ts} (not strictly increasing) [invalid_autonomy_window_gap]"))
            prev_ts = parsed_window_ts

        # Check that claim receipt exists (one per claimed rung).
        if not os.path.isdir(receipts_dir):
            offenders.append((rung_name, f"receipts/autonomy-ladder/ absent while rung claimed [invalid_autonomy_unreceipted_claim]"))
        else:
            claim_receipts = [f for f in os.listdir(receipts_dir) if f.startswith(f"{rung_name}-claim-") and f.endswith(".json")]
            if not claim_receipts:
                offenders.append((rung_name, f"no claim receipt found for {rung_name} under receipts/autonomy-ladder/ [invalid_autonomy_unreceipted_claim]"))

        try:
            validated_claim_times[rung_name] = validate_claimed_rung(
                root=Path(ROOT),
                repo_root=Path(ROOT),
                rung=rung_name,
                window_refs=windows,
            )
        except ClaimEvidenceError as exc:
            offenders.append(
                (rung_name, f"{exc} [invalid_autonomy_claim_evidence]")
            )

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

    # A claim above the newest reversion target is valid only when the same
    # closed-schema claim validated above postdates a strict UTC reversion.
    if reversion_log and claimed_rungs:
        latest_reversion = reversion_log[-1]
        reverted_target = latest_reversion.get("target_rung")
        reversion_ts = latest_reversion.get("ts")
        if reverted_target and reversion_ts:
            try:
                parsed_reversion_ts = parse_utc_timestamp(reversion_ts)
            except (TypeError, ValueError):
                offenders.append((
                    "reversion",
                    "reversion ts is not strict ISO-8601 UTC "
                    "[invalid_autonomy_reversion_ignored]",
                ))
                parsed_reversion_ts = None
            target_level = int(reverted_target[1:])
            for claimed_rung in claimed_rungs:
                if int(claimed_rung[1:]) <= target_level:
                    continue
                claim_ts = validated_claim_times.get(claimed_rung)
                if claim_ts is None or parsed_reversion_ts is None:
                    offenders.append((
                        "reversion",
                        f"rung {claimed_rung} has no validated fresh claim above "
                        f"reversion target {reverted_target} "
                        "[invalid_autonomy_reversion_ignored]",
                    ))
                elif claim_ts <= parsed_reversion_ts:
                    offenders.append((
                        "reversion",
                        f"rung {claimed_rung} claim ts {claim_ts.isoformat()} <= "
                        f"reversion ts {parsed_reversion_ts.isoformat()}, stale claim "
                        f"above target {reverted_target} "
                        "[invalid_autonomy_reversion_ignored]",
                    ))

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
