#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""
Totality status-probe for Ember goal condition C4 (Before/after).

Authoritative condition text (<spec>, condition C4):
  C4 - Before/after.
    R: pre-change baseline and post-assimilation candidate on the same frozen
       task/metric/seeds/scoring command.
    Does NOT count: a one-shot score with no matched before state.
    invalid-token: invalid_missing_before
    CHK: both rows present with identical scoring command.

Gloss (from the task brief): before/after = matched pre-change baseline +
post-assimilation candidate on the SAME frozen task/metric/seeds/command.
Receipt hint: before/after receipt rows, identical scoring command.

Mapping to the fixed A<local-mount-point>/C/deleted contract (<spec> section C4):
  A      = same task/evaluator/harness envelope, NO native goal organ,
           NO resident update      -> the matched "before" / pre-change baseline state
  C      = same harness with a model-learned RLM/iGRPO neural update that changes
           later action selection   -> the post-assimilation "after" candidate
  The pre/post neural parameter hashes (pre_neural_parameter_hash vs
  post_neural_parameter_hash) are the explicit before/after of the assimilation step.
  Budgets/evaluator/data/seeds matched; per-task rows present; one verifier-conditioned
  scoring/training command governs every arm  -> the "identical scoring command".

This is a STATUS PROBE:
  - exit code is ALWAYS 0
  - it prints exactly one line: "RED <reason>" or "GREEN <reason>"
  - RED/GREEN is determined by REALLY inspecting the receipt under
    <external-state-root> -- never hardcoded.

C4 SCOPE NOTE (deliberate, mirrors the sibling C5 probe): C4's ONLY does-NOT-count is
"a one-shot score with no matched before state" (invalid_missing_before). C4 does NOT
itself forbid the SYMBOLIC_PROXY template-selector pattern, nor the full-parity-harness
conflation -- those guards live in C14 (a separate condition with its own tokens:
SYMBOLIC_PROXY_PASS, etc.). This probe therefore encodes ONLY C4's invalid-token and
judges C4 strictly on (matched before row present per slice) + (single identical scoring
command across before and after), exactly as the CHK states.

LANE-14 HARDENING (2026-07-02, R8 probe-faithfulness audit,
docs/goalforge-debate-ledger.md row R8): the pre-hardening version accepted
pre_neural_parameter_hash / post_neural_parameter_hash as present-and-differ
strings with NO check that they trace back to any file this tree can see --
R8: "C4/C5 internally-consistent receipts, binding artifacts off-tree, n=2".
The candidate manifest's own hash-backing artifact
(policy_update_trace_path/_sha256, the neural_policy_update_trace.json that
actually records the pre/post update) lives, in every real receipt seen so
far, under <external-state>/... -- outside this tree entirely. Two new
requirements, ARTIFACT REACHABILITY:
  (i) every "<field>_path"/"<field>_sha256" pair present on the candidate
      block must resolve to an in-tree file (resolve_in_tree) whose sha256
      matches the claimed value -- an off-tree/unreachable path FAILS the
      receipt outright (named per the docs/domains/governance/authority/GOAL.md Execution-surface imports-owed
      row, anti-gaming S10 import debt), no more trust-the-string pass.
  (ii) when the trace artifact resolves, its OWN recorded
      pre_neural_parameter_hash/post_neural_parameter_hash fields (if
      present) must match the candidate manifest's claimed values -- the
      pre/post hashes must genuinely RE-DERIVE from the in-tree file, not
      merely be copied verbatim into two places.
  (iii) sample-recompute: at least one per-task row's b_score/c_score, where
      the row carries a best_reward_table with matching template entries,
      must recompute from that table -- a stored score that disagrees with
      its own row's inputs FAILS.

[REDACTION-BROKE-PATH CORRECTION, 2026-07-06, gh #254/#259]: the public-export scrub
tool had rewritten the real receipt directory names into literal bracketed
placeholders `<peer-gate>`/`<peer-candidate>` -- which never exist verbatim on disk --
in the functional path-join constants below, so this probe could never locate its own
evidence (receipts/ember-resident-training-gate/, receipts/ember-resident-training-candidate/).
Restored to the real, already-public names.
"""

# [PATH-REWRITE 2026-07-01] Imported from external peer's
# state tree and rewritten for this repository. Original mount-point specific
# candidates replaced with a single REPO_ROOT-relative candidate,
# REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. External state directory does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.

import json
import os
import glob
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lane14_common import check_path_sha_pairs, sample_recompute_row, resolve_in_tree  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
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
# already-public directory names -- see docstring note above.
RESIDENT_GATE_DIR = os.path.join(EXTERNAL_STATE, "receipts", "ember-resident-training-gate")
CANDIDATE_DIR = os.path.join(EXTERNAL_STATE, "receipts", "ember-resident-training-candidate")

# C4's only does-NOT-count invalid token (encoded as a negative assertion below).
C4_INVALID_TOKENS = ["invalid_missing_before"]


def status(color, reason):
    """Single-line status emit; STATUS PROBE always exits 0."""
    print(f"{color} {reason}")
    raise SystemExit(0)


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def find_candidate_block(d):
    """Return the candidate dict (carrying per_task_rows + pre/post hashes), handling
    both the flat layout and the nested resident_training_candidate layout."""
    cand = d.get("resident_training_candidate")
    if isinstance(cand, dict) and ("per_task_rows" in cand or "pre_neural_parameter_hash" in cand):
        return cand
    return d


def scoring_command(cand, d):
    """The single identical scoring/training command that governs all arms.
    C4 requires it to be one shared command across the before and after rows."""
    for src in (cand, d):
        for k in ("verifier_conditioned_training_command", "scoring_command", "rerun_command"):
            v = src.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def main():
    # ---- locate a REAL resident-training receipt carrying the before/after rows ----
    search_dirs = [RESIDENT_GATE_DIR]
    files = []
    if os.path.isdir(RESIDENT_GATE_DIR):
        files += sorted(glob.glob(os.path.join(RESIDENT_GATE_DIR, "resident-training-gate-*.json")))
    if os.path.isdir(CANDIDATE_DIR):
        files += sorted(glob.glob(os.path.join(CANDIDATE_DIR, "*", "resident_training_candidate_manifest.json")))

    if not files:
        status("RED",
               f"no resident-training receipts found under {RESIDENT_GATE_DIR} "
               f"(C4 before/after artifact absent)")

    # Among receipts that actually carry per-task rows, prefer the richest one:
    # a PASS-verdict gate receipt that ALSO carries pre/post neural hashes (the explicit
    # before/after of assimilation). Fall back to newest with rows so we report the real reason.
    best = None          # (path, d, cand) richest: rows + pre/post hashes + PASS
    any_with_rows = None # (path, d, cand) newest with any rows
    for path in files:
        try:
            d = load_json(path)
        except Exception:
            continue
        cand = find_candidate_block(d)
        rows = cand.get("per_task_rows", [])
        if not rows:
            continue
        any_with_rows = (path, d, cand)  # files() is sorted -> last wins == newest
        has_hashes = bool(cand.get("pre_neural_parameter_hash")) and bool(cand.get("post_neural_parameter_hash"))
        verdict = str(d.get("verdict", "")).upper()
        st = str(d.get("resident_training_gate_status", "")).upper()
        is_pass = ("PASS" in verdict) or (st == "PASS")
        if has_hashes and is_pass:
            best = (path, d, cand)  # keep last (newest) such receipt

    if best is not None:
        chosen_path, d, cand = best
        chosen_reason = "PASS gate receipt with per-task rows AND pre/post neural hashes"
    elif any_with_rows is not None:
        chosen_path, d, cand = any_with_rows
        chosen_reason = "per-task rows present (no PASS receipt carrying pre/post hashes)"
    else:
        status("RED",
               "resident-training receipts exist but NONE carry per-task before/after rows "
               "-> invalid_missing_before (no matched before state)")

    receipt_name = os.path.basename(chosen_path)
    per_task_rows = cand.get("per_task_rows", [])

    # ---------------------------------------------------------------------------
    # (2) Negative assertion: NONE of C4's does-NOT-count invalid-tokens may match.
    #     C4 does-NOT-count = "a one-shot score with no matched before state"
    #     (invalid_missing_before). It MATCHES iff there is an after/candidate score
    #     but NO matched before state -- i.e. some row carries the after (C) score
    #     without a paired before (A) baseline, OR there is no before signal at all.
    # ---------------------------------------------------------------------------
    invalid_codes = [str(c) for c in (d.get("invalid_codes") or [])]
    literal_missing_before = any("invalid_missing_before" in c for c in invalid_codes)

    rows_with_after = 0      # rows carrying a post-assimilation candidate (C) score
    rows_missing_before = 0  # ... of those, how many LACK a matched before (A) baseline
    for row in per_task_rows:
        c = row.get("c_score")
        if c is None:
            continue
        rows_with_after += 1
        # matched "before" state for this slice = the A-arm pre-change baseline score.
        if row.get("a_score") is None:
            rows_missing_before += 1

    # Receipt-level before/after of the assimilation step: pre vs post neural param hash.
    pre_hash = cand.get("pre_neural_parameter_hash")
    post_hash = cand.get("post_neural_parameter_hash")
    has_before_after_hashes = bool(pre_hash) and bool(post_hash)
    # A genuine assimilation must actually CHANGE the parameters; identical hashes would
    # mean "after" == "before" (no post-assimilation candidate distinct from baseline).
    hashes_differ = has_before_after_hashes and (pre_hash != post_hash)

    no_before_signal_at_all = (rows_missing_before == rows_with_after) and not has_before_after_hashes

    invalid_missing_before_matched = (
        literal_missing_before
        or (rows_with_after > 0 and no_before_signal_at_all)
    )

    if invalid_missing_before_matched:
        why = ("literal invalid_missing_before in invalid_codes" if literal_missing_before
               else "after/candidate scores present with NO matched before (A) baseline and no pre-hash")
        status("RED", f"{receipt_name}: invalid_missing_before matched ({why}) -> C4 does-NOT-count")

    # ---------------------------------------------------------------------------
    # (1) Positive CHK: BOTH rows present (before + after) with IDENTICAL scoring command.
    #     - per slice: a matched before (A) baseline AND an after (C) candidate.
    #     - exactly one shared scoring/verifier command governs every arm.
    # ---------------------------------------------------------------------------
    if rows_with_after == 0:
        status("RED", f"{receipt_name}: no after/candidate (c_score) rows present -> no after state")
    if rows_missing_before > 0:
        status("RED",
               f"{receipt_name}: {rows_missing_before}/{rows_with_after} after-rows lack a matched "
               f"before (a_score) baseline -> invalid_missing_before")

    cmd = scoring_command(cand, d)
    if not cmd:
        status("RED",
               f"{receipt_name}: before/after rows present but NO single scoring command field "
               f"(cannot confirm identical scoring command)")

    # The before and after rows are scored by the SAME single command string `cmd`
    # (one verifier-conditioned command governs all arms in this receipt layout).
    # If a future receipt records per-row commands, require them identical here.
    per_row_cmds = {row.get("scoring_command") for row in per_task_rows if row.get("scoring_command")}
    if len(per_row_cmds) > 1:
        status("RED",
               f"{receipt_name}: per-row scoring commands differ across before/after "
               f"({len(per_row_cmds)} distinct) -> NOT identical scoring command")

    detail = (f"rows={rows_with_after} before(A)+after(C) paired={rows_with_after - rows_missing_before} "
              f"pre_hash={'set' if pre_hash else 'none'} post_hash={'set' if post_hash else 'none'} "
              f"hashes_differ={hashes_differ} cmd={cmd[:70]!r}")

    if not has_before_after_hashes:
        # Per-slice before/after rows ARE present and paired with one identical command,
        # but the explicit pre/post assimilation hashes are absent -> weaker before/after.
        status("RED",
               f"{receipt_name}: per-slice before(A)/after(C) rows paired with one scoring command, "
               f"but pre/post neural parameter hashes absent (no explicit assimilation before/after). {detail}")

    if not hashes_differ:
        status("RED",
               f"{receipt_name}: pre/post neural parameter hashes are IDENTICAL -> after == before, "
               f"no real post-assimilation candidate distinct from baseline. {detail}")

    # ---------------------------------------------------------------------------
    # LANE-14 HARDENING: ARTIFACT REACHABILITY -- the pre/post hashes must
    # re-derive from files reachable from the execution tree, not merely be
    # strings copied into the manifest. An off-tree/unreachable trace path
    # FAILS this receipt outright, regardless of everything checked above.
    # ---------------------------------------------------------------------------
    reach_ok, n_pairs, reach_detail = check_path_sha_pairs(cand, EXTERNAL_STATE)
    if not reach_ok:
        status("RED",
               f"{receipt_name}: ARTIFACT REACHABILITY failed -- {reach_detail}. "
               f"pre/post neural parameter hashes cannot be trusted without an "
               f"in-tree backing artifact. {detail}")

    trace_path = cand.get("policy_update_trace_path")
    trace_on_disk = None
    if isinstance(trace_path, str) and trace_path:
        trace_on_disk = resolve_in_tree(trace_path, EXTERNAL_STATE)
    if trace_on_disk is not None:
        try:
            trace_data = load_json(trace_on_disk)
        except Exception as exc:
            status("RED", f"{receipt_name}: policy_update_trace resolved in-tree but "
                          f"unreadable ({exc})")
        trace_pre = trace_data.get("pre_neural_parameter_hash")
        trace_post = trace_data.get("post_neural_parameter_hash")
        if trace_pre is not None and trace_pre != pre_hash:
            status("RED", f"{receipt_name}: policy_update_trace's OWN "
                          f"pre_neural_parameter_hash {trace_pre!r} != manifest's "
                          f"claimed {pre_hash!r} -- does not re-derive")
        if trace_post is not None and trace_post != post_hash:
            status("RED", f"{receipt_name}: policy_update_trace's OWN "
                          f"post_neural_parameter_hash {trace_post!r} != manifest's "
                          f"claimed {post_hash!r} -- does not re-derive")

    # ---------------------------------------------------------------------------
    # LANE-14 HARDENING: sample-recompute at least one row's score fields
    # where the receipt carries the inputs (best_reward_table).
    # ---------------------------------------------------------------------------
    recompute_ok, recompute_detail = sample_recompute_row(per_task_rows)
    if not recompute_ok:
        status("RED",
               f"{receipt_name}: sample-recompute FAILED -- {recompute_detail}")

    status("GREEN",
           f"C4 satisfied by {receipt_name} [{chosen_reason}]: matched before(A) baseline + "
           f"after(C) candidate present per slice on the same frozen task, one identical scoring "
           f"command across arms, pre!=post neural parameter hashes (real assimilation before/after), "
           f"no invalid_missing_before; ARTIFACT REACHABILITY verified ({reach_detail}); "
           f"sample-recompute PASSED ({recompute_detail}). {detail}")


if __name__ == "__main__":
    main()
