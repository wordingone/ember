#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""
Totality status-probe for Ember goal condition C5 (Positive delta).

Authoritative condition text (<spec>, line 105):
  C5 - Positive delta.
    R: C beats the matched before-baseline AND the A/B controls on the declared
       aggregate, with per-task/per-slice rows.
    Does NOT count: a hidden average without rows.
    invalid-token: invalid_no_rows
    CHK: aggregate delta>0 and per-slice rows present.

Mapping to the fixed A<local-mount-point>/C/deleted contract (<spec> SS6):
  A = no native goal organ, no resident-training update  -> the "matched before-baseline"
  B = clean-room harness + fixed hand-authored / prompt-rule policy, no learned update -> control
  C = same harness with a model-learned RLM/iGRPO neural update -> the candidate
  Per the contract pass_rule: "C beats A and B ... per-row scores present".

This is a STATUS PROBE:
  - exit code is ALWAYS 0
  - it prints exactly one line: "RED <reason>" or "GREEN <reason>"
  - RED/GREEN is determined by REALLY inspecting the receipt under
    <<external>>/state/<external-state> -- never hardcoded.

C5 SCOPE NOTE (deliberate): C5's only does-NOT-count is "a hidden average without
rows" (invalid_no_rows). C5 does NOT itself forbid the SYMBOLIC_PROXY template-selector
pattern -- that guard lives in C14, a separate condition. This probe therefore encodes
ONLY C5's invalid-token, and judges C5 strictly on (aggregate delta>0) + (per-slice rows
present), exactly as the CHK states.

LANE-14 HARDENING (2026-07-02, R8 probe-faithfulness audit,
docs/goalforge-debate-ledger.md row R8): the pre-hardening version trusted
every per_task_rows[].a_score/b_score/c_score number wholesale, with no
check that they trace back to any file this tree can see, and no check that
the numbers even agree with the receipt's OWN best_reward_table entries --
R8: "C4/C5 internally-consistent receipts, binding artifacts off-tree, n=2".
Two new requirements (mirrors the sibling C4 hardening, same underlying
resident_training_candidate manifest schema): ARTIFACT REACHABILITY -- every
"<field>_path"/"<field>_sha256" pair on the candidate block must resolve
in-tree and hash-verify (an off-tree path FAILS, named per the docs/domains/governance/authority/GOAL.md
Execution-surface imports-owed row / anti-gaming S10 import debt) -- and
sample-recompute -- at least one row's b_score/c_score must recompute from
its own best_reward_table, where the receipt carries that structure.

[REDACTION-BROKE-PATH CORRECTION, 2026-07-06, gh #254/#259]: the public-export scrub
tool had rewritten the real receipt directory name into the literal bracketed
placeholder `<peer-gate>` -- which never exists verbatim on disk -- in the functional
path-join constant below, so this probe could never locate its own evidence
(receipts/ember-resident-training-gate/). Restored to the real, already-public name.
"""

# [PATH-REWRITE 2026-07-01] Imported from
# <<external>>/state/ember-totality-build/ into
# <local-exec-root>-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at <<external>>/state/<external-state> (and /mnt<local-mount-point>/M/...,
# <local-mount-point>/M/..., <TEMP_WORKSPACE>/... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. <external-state> does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.

import json
import os
import glob
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lane14_common import check_path_sha_pairs, sample_recompute_row  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '..'))
# [RULING-DRIFT CORRECTION, 2026-07-06, gh #254] dropped the vestigial third
# REPO_ROOT-relative fallback candidate: EMBER_TOTALITY_ROOT and REPO_ROOT already
# cover every real invocation shape, and the dropped candidate never resolved to
# anything -- a latent probe defect if it were ever reached first.
EXTERNAL_STATE = next(
    (p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT)
     if p and os.path.isdir(p)),
    REPO_ROOT,
)
# [REDACTION-BROKE-PATH CORRECTION, 2026-07-06, gh #254/#259] restored the real,
# already-public directory name -- see docstring note above.
RESIDENT_GATE_DIR = os.path.join(EXTERNAL_STATE, "receipts", "ember-resident-training-gate")

# C5's only does-NOT-count invalid token (encoded as a negative assertion below).
C5_INVALID_TOKENS = ["invalid_no_rows"]


def status(color, reason):
    """Single-line status emit; STATUS PROBE always exits 0."""
    print(f"{color} {reason}")
    raise SystemExit(0)


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def find_candidate_block(d):
    """Return (per_task_rows, transfer_rows) from a resident-training receipt,
    handling both the flat layout and the nested resident_training_candidate layout."""
    if "per_task_rows" in d:
        return d.get("per_task_rows", []), d.get("transfer_rows", [])
    cand = d.get("resident_training_candidate")
    if isinstance(cand, dict):
        return cand.get("per_task_rows", []), cand.get("transfer_rows", [])
    return [], []


def row_scores(row):
    """Pull the matched A<local-mount-point>/C scores from one per-task/per-slice row."""
    return row.get("a_score"), row.get("b_score"), row.get("c_score")


def find_candidate_dict(d):
    """Return the manifest-level candidate dict carrying the <field>_path /
    <field>_sha256 artifact pairs (same nested-vs-flat layout as
    find_candidate_block, but returns the whole dict, not just rows)."""
    cand = d.get("resident_training_candidate")
    if isinstance(cand, dict):
        return cand
    return d


def main():
    # ---- locate a REAL resident-training receipt carrying the A<local-mount-point>/C delta rows ----
    if not os.path.isdir(RESIDENT_GATE_DIR):
        status("RED", f"no resident-training-gate receipt dir at {RESIDENT_GATE_DIR}")

    candidates = sorted(glob.glob(os.path.join(RESIDENT_GATE_DIR, "resident-training-gate-*.json")))
    if not candidates:
        status("RED", "no resident-training-gate-*.json receipts found (C5 delta artifact absent)")

    # Prefer a receipt whose own verdict is a PASS (a clear positive-delta claim to verify);
    # among those, prefer the most recent (lexical ts sort). If none PASS, fall back to the
    # newest receipt that actually carries rows so we can still report the real reason.
    chosen = None
    chosen_reason = None
    pass_with_rows = []
    any_with_rows = []
    for path in candidates:
        try:
            d = load_json(path)
        except Exception as exc:
            continue
        ptr, _ = find_candidate_block(d)
        if ptr:
            any_with_rows.append((path, d))
            verdict = str(d.get("verdict", "")).upper()
            statusf = str(d.get("resident_training_gate_status", "")).upper()
            if "PASS" in verdict or statusf == "PASS":
                pass_with_rows.append((path, d))

    if pass_with_rows:
        chosen_path, d = pass_with_rows[-1]
        chosen_reason = "PASS-verdict receipt with rows"
    elif any_with_rows:
        chosen_path, d = any_with_rows[-1]
        chosen_reason = "rows present but no PASS-verdict receipt"
    else:
        status("RED", "resident-training receipts exist but NONE carry per-task/per-slice A<local-mount-point>/C rows -> invalid_no_rows")

    receipt_name = os.path.basename(chosen_path)
    per_task_rows, transfer_rows = find_candidate_block(d)

    # ---------------------------------------------------------------------------
    # (2) Negative assertion: NONE of C5's does-NOT-count invalid-tokens may match.
    #     C5 does-NOT-count = "a hidden average without rows" (invalid_no_rows).
    #     invalid_no_rows MATCHES iff there is an aggregate/average claim but no rows.
    # ---------------------------------------------------------------------------
    cand = d.get("resident_training_candidate", d)
    claims_aggregate = bool(
        cand.get("c_beats_a_and_b") is not None
        or "verdict" in d
        or "resident_training_gate_status" in d
    )
    rows_present = len(per_task_rows) > 0

    # explicit literal scan for the invalid token text appearing as an active code
    invalid_codes = [str(c) for c in (d.get("invalid_codes") or [])]
    literal_invalid_no_rows = any("invalid_no_rows" in c for c in invalid_codes)

    invalid_no_rows_matched = literal_invalid_no_rows or (claims_aggregate and not rows_present)

    if invalid_no_rows_matched:
        why = "literal invalid_no_rows in invalid_codes" if literal_invalid_no_rows \
            else "aggregate/verdict claimed but no per-task rows"
        status("RED", f"{receipt_name}: invalid_no_rows matched ({why}) -> C5 does-NOT-count")

    # ---------------------------------------------------------------------------
    # (1) Positive CHK: aggregate delta>0 AND per-slice rows present.
    #     aggregate = mean over per-task heldout rows; C must beat BOTH
    #     the matched before-baseline (A) AND the controls (B) on the aggregate.
    #     Recompute from the REAL rows, never trust a stored boolean.
    # ---------------------------------------------------------------------------
    if not rows_present:
        status("RED", f"{receipt_name}: zero per-task rows -> invalid_no_rows (no per-slice rows)")

    a_vals, b_vals, c_vals = [], [], []
    malformed = 0
    for row in per_task_rows:
        a, b, c = row_scores(row)
        if a is None or b is None or c is None:
            malformed += 1
            continue
        a_vals.append(float(a))
        b_vals.append(float(b))
        c_vals.append(float(c))

    if malformed:
        status("RED", f"{receipt_name}: {malformed} per-task row(s) missing a<local-mount-point>/c_score -> rows not well-formed")
    if not c_vals:
        status("RED", f"{receipt_name}: per-task rows present but no parsable A<local-mount-point>/C scores")

    n = len(c_vals)
    agg_a = sum(a_vals) / n
    agg_b = sum(b_vals) / n
    agg_c = sum(c_vals) / n
    delta_vs_before = agg_c - agg_a   # C vs matched before-baseline (A arm)
    delta_vs_control = agg_c - agg_b  # C vs A/B control (B arm)

    beats_before = delta_vs_before > 0.0
    beats_control = delta_vs_control > 0.0

    detail = (f"rows={n} aggC={agg_c:.4f} aggA(before)={agg_a:.4f} aggB(ctrl)={agg_b:.4f} "
              f"dC-A={delta_vs_before:+.4f} dC-B={delta_vs_control:+.4f} "
              f"transfer_rows={len(transfer_rows)}")

    if not (beats_before and beats_control):
        missing = []
        if not beats_before:
            missing.append("C does NOT beat before-baseline(A)")
        if not beats_control:
            missing.append("C does NOT beat control(B)")
        status("RED",
               f"{receipt_name}: aggregate delta not positive on both arms ({'; '.join(missing)}). {detail}")

    # ---------------------------------------------------------------------------
    # LANE-14 HARDENING: ARTIFACT REACHABILITY -- the candidate manifest's
    # own <field>_path/<field>_sha256 artifact pairs must resolve in-tree and
    # hash-verify. An off-tree/unreachable path FAILS this receipt outright,
    # regardless of the aggregate-delta arithmetic above.
    # ---------------------------------------------------------------------------
    cand_dict = find_candidate_dict(d)
    reach_ok, n_pairs, reach_detail = check_path_sha_pairs(cand_dict, EXTERNAL_STATE)
    if not reach_ok:
        status("RED",
               f"{receipt_name}: ARTIFACT REACHABILITY failed -- {reach_detail}. "
               f"the aggregate A<local-mount-point>/C delta cannot be trusted without an in-tree "
               f"backing artifact. {detail}")

    # ---------------------------------------------------------------------------
    # LANE-14 HARDENING: sample-recompute at least one row's score fields
    # where the receipt carries the inputs (best_reward_table).
    # ---------------------------------------------------------------------------
    recompute_ok, recompute_detail = sample_recompute_row(per_task_rows)
    if not recompute_ok:
        status("RED",
               f"{receipt_name}: sample-recompute FAILED -- {recompute_detail}")

    status("GREEN",
           f"C5 satisfied by {receipt_name} [{chosen_reason}]: positive aggregate delta, "
           f"C beats before-baseline(A) AND control(B), per-slice rows present, "
           f"no invalid_no_rows; ARTIFACT REACHABILITY verified ({reach_detail}); "
           f"sample-recompute PASSED ({recompute_detail}). {detail}")


if __name__ == "__main__":
    main()
