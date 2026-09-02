#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""chk_controls/run_controls.py -- lane-14 CHK-adequacy pos/neg control driver.

Builds one isolated fixture root per (hardening, pos|neg) pair under
chk_controls/fixtures/, then EXECUTES the real probe (scripts/ember_totality/
test_c*.py) as a subprocess with EMBER_TOTALITY_ROOT pointed at that fixture
root, and asserts the printed status line matches the expected token.

Isolation (anti-gaming S2 CHK-adequacy lane / R8 audit instructions):
  - Every fixture lives under chk_controls/fixtures/, OUTSIDE receipts/ --
    a normal run (no EMBER_TOTALITY_ROOT override, ROOT=repo root) globs
    ROOT/receipts/**, which never reaches into scripts/ember_totality/
    chk_controls/fixtures/; fixtures are only ever seen by a probe when
    EXPLICITLY pointed at them via EMBER_TOTALITY_ROOT, never by default
    scan.
  - Every synthetic JSON fixture carries a top-level `_synthetic_control_
    fixture: true` + `does_not_prove` marker (SYNTHETIC_MARKER below) so a
    fixture can never be mistaken for a real receipt if it ever leaked into
    a real scan.
  - Control authorship is separated from probe authorship (lane-14 CHK-
    adequacy contract, docs/spec/anti-gaming-contract-v1.md S2): this
    control suite is written by a different builder than the probe edits
    it exercises (team-lead assignment, 2026-07-02).

Run:  python run_controls.py
"""

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))                    # .../scripts/ember_totality/chk_controls
PROBES_DIR = os.path.dirname(HERE)                                    # .../scripts/ember_totality
REPO_ROOT = os.path.abspath(os.path.join(PROBES_DIR, "..", ".."))
FIXTURES_DIR = os.path.join(HERE, "fixtures")

# PR955 round-2 repair (reviewer defect P1): the gh #715 C-MANIFEST/C-TALLY
# denominator regression previously lived ONLY as a standalone script under
# chk_controls/ -- neither ember_totality_spec.discover_tests (direct
# test_*.py only) nor this canonical driver ever invoked it, so it had no
# canonical row and no finalization proof. Importing it here (same
# directory, no sys.path surgery needed for a direct `python run_controls.py`
# invocation) reuses its production-shaped fixture builders and its
# structured parse_missing_condition_ids() (P2 fix) rather than duplicating
# either.
import test_issue_715_denominator_regression as issue715  # noqa: E402
from c_auto_v2_fixture import build_fresh_reversion_climb as build_c_auto_v2_fixture  # noqa: E402

SYNTHETIC_MARKER = {
    "_synthetic_control_fixture": True,
    "does_not_prove": (
        "lane-14 CHK control fixture (docs/goalforge-debate-ledger.md row R8) "
        "-- synthetic, not a real receipt; must never be accepted as evidence "
        "by a probe scanning the real tree"
    ),
}


# --- generic helpers ---------------------------------------------------------

def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    merged = dict(SYNTHETIC_MARKER)
    merged.update(obj)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2)


def write_json_no_marker(path, obj):
    """Write `obj` verbatim, WITHOUT the SYNTHETIC_MARKER merge write_json()
    does. test_c_scale.py and test_c_e2b.py both hard-reject any candidate
    receipt carrying `_synthetic_control_fixture` (`failures.append(f"{name}:
    synthetic control fixture, never evidence")`, never reaching the real
    CHK check) -- so the one receipt file in each POS/NEG fixture that must
    actually be evaluated (accepted for POS, evaluated-and-rejected-for-the-
    sharp-reason for NEG) has to land on disk marker-free. Everything else in
    these two fixtures (referenced-but-not-glob-scanned support artifacts)
    still goes through write_json() normally; the fixture-root README.txt
    documents this split so it is never mistaken for a real, non-synthetic
    receipt if it leaks outside chk_controls/fixtures/."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)


def write_jsonl(path, rows):
    """Write `rows` (a list of dicts) as one JSON object per line, marker-
    free -- test_c_ladm.py reads ledger/episodes.jsonl and ledger/
    control_pool.jsonl as raw ledger data, never as candidate `receipts/`
    evidence, so the SYNTHETIC_MARKER convention (which governs receipt
    files a probe might glob-scan by default) does not apply to these rows;
    isolation is by EMBER_TOTALITY_ROOT override only, same as every other
    fixture here."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def write_readme(root, note):
    with open(os.path.join(root, "README.txt"), "w", encoding="utf-8") as fh:
        fh.write(note.strip() + "\n")


def _rmtree_onerror(func, path, exc_info):
    """[ISSUE #97 cure3-fixture] git marks .git/objects/** read-only on
    Windows; a plain shutil.rmtree() PermissionErrors on rerun. Clear the
    read-only bit and retry once."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def fresh_dir(path):
    if os.path.isdir(path):
        shutil.rmtree(path, onerror=_rmtree_onerror)
    os.makedirs(path, exist_ok=True)
    return path


def pinned_fixture_root(name, required_paths):
    """Return a committed fixture root without rewriting its pinned bytes."""
    root = os.path.join(FIXTURES_DIR, name)
    missing = [rel for rel in required_paths if not os.path.isfile(os.path.join(root, rel))]
    if missing:
        raise FileNotFoundError(f"pinned fixture {name!r} is incomplete: {missing!r}")
    return root


def run_probe(probe_name, fixture_root, env_var="EMBER_TOTALITY_ROOT"):
    """Execute the real probe as a subprocess with `env_var` set to
    fixture_root (default EMBER_TOTALITY_ROOT; test_surface2.py instead reads
    EMBER_EXEC_ROOT since its evidence lives on the separate execution tree
    -- pass env_var="EMBER_EXEC_ROOT" for that probe). Returns
    (status_token, full_first_line, stderr_tail)."""
    env = dict(os.environ)
    env[env_var] = fixture_root
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(PROBES_DIR, probe_name)],
            cwd=PROBES_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return "<timeout>", "", "probe exceeded 120s"
    out_lines = (proc.stdout or "").strip().splitlines()
    line = out_lines[0] if out_lines else "<no stdout>"
    status = line.split(" ", 1)[0] if line else "<empty>"
    return status, line, (proc.stderr or "")[:400]


RESULTS = []  # rows for the final table


def record(hardening, control, probe, fixture_root, expected, env_var="EMBER_TOTALITY_ROOT",
           expected_missing_ids=None):
    """Run one control and append its row to RESULTS.

    `expected_missing_ids`, when not None (reviewer defect P2 -- structured
    ids, never a substring guess), asserts the EXACT parsed
    missing_condition_ids list from the probe's own "missing=..." segment
    (via issue715.parse_missing_condition_ids) equals the given list; a
    mismatch fails the row even if the status token alone matched. The
    parsed list is always recorded under row["details"]["missing_condition_ids"]
    when requested, so a --receipt-out receipt carries it structurally.
    """
    status, line, err = run_probe(probe, fixture_root, env_var=env_var)
    ok = (status == expected)
    details = {}
    if expected_missing_ids is not None:
        actual_missing_ids = issue715.parse_missing_condition_ids(line)
        details["missing_condition_ids"] = actual_missing_ids
        if actual_missing_ids != expected_missing_ids:
            ok = False
    RESULTS.append({
        "hardening": hardening, "control": control, "probe": probe,
        "expected": expected, "actual": status, "ok": ok, "line": line, "stderr": err,
        "details": details,
    })
    return ok


# --- (1) C-TALLY: recompute from live board rows ------------------------------

def build_c_tally():
    pos_root = fresh_dir(os.path.join(FIXTURES_DIR, "c_tally_pos"))
    neg_root = fresh_dir(os.path.join(FIXTURES_DIR, "c_tally_neg"))

    write_json(
        os.path.join(pos_root, "receipts-totality", "ember-totality-20990101T000000Z.json"),
        {
            "ts": "20990101T000000Z",
            "rows": [
                {"condition": "C-FAKE1", "status": "GREEN", "is_process_invariant": False, "reason": "synthetic pos"},
                {"condition": "C-FAKE2", "status": "GREEN", "is_process_invariant": False, "reason": "synthetic pos"},
                {"condition": "C-FAKE-INV", "status": "AUDIT-OK", "is_process_invariant": True, "reason": "synthetic pos"},
            ],
        },
    )

    # NEG: board is NOT all-green, AND a future-dated tally-*.json claims
    # pct=100 -- must not flip the verdict (the whole point of hardening #1).
    write_json(
        os.path.join(neg_root, "receipts-totality", "ember-totality-20990101T000000Z.json"),
        {
            "ts": "20990101T000000Z",
            "rows": [
                {"condition": "C-FAKE1", "status": "GREEN", "is_process_invariant": False, "reason": "synthetic neg"},
                {"condition": "C-FAKE2", "status": "RED", "is_process_invariant": False, "reason": "synthetic neg -- genuinely unmet"},
                {"condition": "C-FAKE-INV", "status": "AUDIT-OK", "is_process_invariant": True, "reason": "synthetic neg"},
            ],
        },
    )
    write_json(
        os.path.join(neg_root, "receipts", "tally-20991231T235959Z.json"),
        {"pct": 100, "total": 2, "implemented": 2, "missing": []},
    )
    return pos_root, neg_root


# --- (2) C(-1): verdict-linkage + all-decisive-claims zero-spend --------------

def build_c_neg1():
    pos_root = fresh_dir(os.path.join(FIXTURES_DIR, "c_neg1_pos"))
    neg_root = fresh_dir(os.path.join(FIXTURES_DIR, "c_neg1_neg"))

    write_json(
        os.path.join(pos_root, "receipts", "synthetic-pass-20990101T000000Z.json"),
        {"verdict": "SYNTHETIC_DEMO_PASS", "api_spend_usd": 0, "paid_api_surface_used": False},
    )
    write_json(
        os.path.join(pos_root, "receipts", "synthetic-support-20990101T000100Z.json"),
        {"verdict": "SYNTHETIC_DEMO_SUPPORT_PASS", "api_spend_usd": 0, "paid_api_surface_used": False},
    )

    # NEG: reproduces the exact R8 finding -- a single decisive-claim receipt,
    # zero-cost fields declared cleanly, but its OWN verdict is BLOCKED.
    write_json(
        os.path.join(neg_root, "receipts", "synthetic-blocked-20990101T000000Z.json"),
        {"verdict": "SYNTHETIC_DEMO_BLOCKED", "api_spend_usd": 0, "paid_api_surface_used": False},
    )
    return pos_root, neg_root


# --- (5) C1: hash-verify mandatory against an in-tree artifact ----------------

def build_c1():
    pos_root = fresh_dir(os.path.join(FIXTURES_DIR, "c1_pos"))
    neg_root = fresh_dir(os.path.join(FIXTURES_DIR, "c1_neg"))

    artifact_bytes = json.dumps({"synthetic": True, "rows": [1, 2, 3]}, indent=2).encode("utf-8")
    artifact_sha = sha256_bytes(artifact_bytes)
    artifact_rel = os.path.join("receipts", "ember-post-resident-discovery", "synthetic-frozen-rows.json")

    def candidate(local_path):
        return {
            "primary_sources": ["http://example.com/dataset"],
            "license_or_access_basis": "CC-BY-4.0 (synthetic)",
            "task_evaluator_form": "exact_match (synthetic)",
            "fit_to_goal": "best self-improvement-by-action proxy (synthetic)",
            "frozen_rows_sha256": artifact_sha,
            "local_task_rows_path": local_path,
        }

    # POS: artifact IN-TREE under pos_root.
    pos_artifact_abs = os.path.join(pos_root, artifact_rel)
    os.makedirs(os.path.dirname(pos_artifact_abs), exist_ok=True)
    with open(pos_artifact_abs, "wb") as fh:
        fh.write(artifact_bytes)
    write_json(
        os.path.join(pos_root, "receipts", "ember-post-resident-discovery", "benchmark-discovery-20990101T000000Z.json"),
        {"candidates": [candidate(pos_artifact_abs)], "selection": {"why": "synthetic selection rationale"}},
    )

    # NEG: mirrors today's real off-tree scenario -- artifact exists on disk
    # but OUTSIDE neg_root (the probe's resolved execution tree).
    off_tree_dir = fresh_dir(os.path.join(FIXTURES_DIR, "_off_tree_c1"))
    off_tree_abs = os.path.join(off_tree_dir, "synthetic-frozen-rows.json")
    with open(off_tree_abs, "wb") as fh:
        fh.write(artifact_bytes)
    write_json(
        os.path.join(neg_root, "receipts", "ember-post-resident-discovery", "benchmark-discovery-20990101T000000Z.json"),
        {"candidates": [candidate(off_tree_abs)], "selection": {"why": "synthetic selection rationale"}},
    )
    return pos_root, neg_root


# --- (4) C4/C5: artifact reachability + sample-recompute ----------------------

def build_resident_fixture(root, in_tree):
    receipts_dir = os.path.join(root, "receipts", "ember-resident-training-gate")
    os.makedirs(receipts_dir, exist_ok=True)

    pre_hash = "sha256:" + sha256_bytes(b"synthetic-pre-parameter-state")
    post_hash = "sha256:" + sha256_bytes(b"synthetic-post-parameter-state")
    trace_bytes = json.dumps({
        "pre_neural_parameter_hash": pre_hash,
        "post_neural_parameter_hash": post_hash,
        "note": "synthetic lane-14 control fixture trace",
    }, indent=2).encode("utf-8")
    trace_sha = sha256_bytes(trace_bytes)

    if in_tree:
        trace_path = os.path.join(receipts_dir, "synthetic_policy_update_trace.json")
    else:
        off_dir = fresh_dir(os.path.join(FIXTURES_DIR, "_off_tree_resident_" + os.path.basename(root)))
        trace_path = os.path.join(off_dir, "synthetic_policy_update_trace.json")
    os.makedirs(os.path.dirname(trace_path), exist_ok=True)
    with open(trace_path, "wb") as fh:
        fh.write(trace_bytes)

    per_task_rows = [{
        "task_id": "synthetic_task_1",
        "a_score": 0.0,
        "b_score": 0.3,
        "b_template": "instruction_only",
        "c_score": 1.0,
        "c_selected_template": "eval_script_recursive",
        "best_reward_table": [
            {"template": "instruction_only", "reward": 0.3},
            {"template": "eval_script_recursive", "reward": 1.0},
        ],
    }]
    candidate = {
        "per_task_rows": per_task_rows,
        "pre_neural_parameter_hash": pre_hash,
        "post_neural_parameter_hash": post_hash,
        "policy_update_trace_path": trace_path,
        "policy_update_trace_sha256": trace_sha,
        "scoring_command": "python synthetic_score.py",
    }
    write_json(
        os.path.join(receipts_dir, "resident-training-gate-20990101T000000Z.json"),
        {
            "verdict": "SYNTHETIC_RESIDENT_TRAINING_GATE_PASS",
            "resident_training_gate_status": "PASS",
            "resident_training_candidate": candidate,
        },
    )


def build_c4_c5():
    pos_root = fresh_dir(os.path.join(FIXTURES_DIR, "c4c5_pos"))
    neg_root = fresh_dir(os.path.join(FIXTURES_DIR, "c4c5_neg"))
    build_resident_fixture(pos_root, in_tree=True)
    build_resident_fixture(neg_root, in_tree=False)
    return pos_root, neg_root


# --- (12) C0/C14 timestamp authority: filename stamp vs internal ts ----------
# #60. A gate receipt's on-disk filename can be pre-generated
# with a rounded-forward stamp independently of when its content was actually
# built (the real 2026-06-22 15:03/15:50 incident this hardens against). Both
# fixtures share an epoch acceptance receipt so test_c0.py runs its real
# post-epoch AUDIT-OK/AUDIT-INCIDENT path rather than the pre-epoch
# informational one, and neither cites any Ember loop receipt -- isolating
# the supersession tooth specifically, not the separate loop-timing CHK.

def build_c0_ts_authority():
    pos_root = fresh_dir(os.path.join(FIXTURES_DIR, "c0_ts_authority_pos"))
    neg_root = fresh_dir(os.path.join(FIXTURES_DIR, "c0_ts_authority_neg"))

    for root in (pos_root, neg_root):
        write_json(
            os.path.join(root, "receipts", "acceptance", "goalforge-clear-20990101.json"),
            {"schema": "acceptance/v1", "scope": "goalforge-clear", "ts": "20990101T000000Z"},
        )

    # POS ("forward-named-block-precedes-pass"): the BLOCKED receipt's
    # filename claims T125000Z (after the PASS's T120000Z) but its own
    # internal ts is T113000Z -- it actually happened BEFORE the PASS. Under
    # ordering-authority-by-internal-ts, the PASS must survive (not
    # superseded).
    gate_dir_pos = os.path.join(pos_root, "receipts", "ember-resident-training-gate")
    write_json(
        os.path.join(gate_dir_pos, "resident-training-gate-20990101T120000Z.json"),
        {"ts": "20990101T120000Z", "verdict": "RESIDENT_TRAINING_GATE_PASS",
         "resident_training_gate_status": "PASS", "component_status": {"x": "PASS"}},
    )
    write_json(
        os.path.join(gate_dir_pos, "resident-training-gate-20990101T125000Z-blocked.json"),
        {"ts": "20990101T113000Z", "verdict": "RESIDENT_TRAINING_GATE_BLOCKED",
         "resident_training_gate_status": "BLOCKED"},
    )

    # NEG ("genuinely-later-blocked"): filename AND internal ts both agree the
    # BLOCK (T130000Z) is later than the PASS (T120000Z) -- the PASS must be
    # superseded, same as today's real, correct behavior for a true regression.
    gate_dir_neg = os.path.join(neg_root, "receipts", "ember-resident-training-gate")
    write_json(
        os.path.join(gate_dir_neg, "resident-training-gate-20990101T120000Z.json"),
        {"ts": "20990101T120000Z", "verdict": "RESIDENT_TRAINING_GATE_PASS",
         "resident_training_gate_status": "PASS", "component_status": {"x": "PASS"}},
    )
    write_json(
        os.path.join(gate_dir_neg, "resident-training-gate-20990101T130000Z-blocked.json"),
        {"ts": "20990101T130000Z", "verdict": "RESIDENT_TRAINING_GATE_BLOCKED",
         "resident_training_gate_status": "BLOCKED"},
    )
    return pos_root, neg_root


# --- (13) C14 conjunct-3 hardening: clean_room_harness_identity binding ------
# #59. test_c14.py's docstring for conjunct 3 has always said
# the resident receipt's clean_room_harness_identity "binds to" the
# observation receipt, but the executable code never checked any such
# binding -- only that SOME latest observation receipt independently passed.
# This fixture pair proves the new binding check: BOUND (identity's recorded
# sha256 matches the real, on-disk observation receipt's live-recomputed
# hash) reads GREEN same as before; UNBOUND (a mismatched sha256, i.e. the
# resident receipt names a DIFFERENT harness build than the one currently
# latest) reads RED with HARNESS_IDENTITY_UNBOUND. Every other conjunct is
# built to independently PASS in both fixtures, isolating the identity-
# binding tooth specifically.

def _c59_common_receipts(root):
    """Write the conjunct-1/2/4/5-satisfying receipts identical between the
    POS and NEG fixtures, and return the observation receipt's own path plus
    its live-recomputed sha256 (the ground truth the resident receipt's
    identity block is then either matched or deliberately mismatched
    against)."""
    obs_path = os.path.join(
        root, "receipts", "ember-preloop-resident-gate",
        "real-avir-uiux-ax-observation-20990101T000000Z.json")
    write_json(obs_path, {
        "ts": "20990101T000000Z",
        "verdict": "REAL_AVIR_UIUX_AX_OBSERVATION_PASS",
        "observed_real_avir_binary": True,
        "observed_real_tui": True,
        "observed_agent_loop": True,
        "observed_uiux_ax": True,
    })
    with open(obs_path, "rb") as fh:
        obs_sha = hashlib.sha256(fh.read()).hexdigest()

    write_json(
        os.path.join(root, "receipts", "ember-preloop-resident-gate",
                     "avir-cli-full-parity-harness-gate-20990101T000000Z.json"),
        {
            "ts": "20990101T000000Z",
            "verdict": "AVIR_CLI_FULL_PARITY_HARNESS_GATE_PASS",
            "classification": "FULL_PARITY_GATE_PASS",
        },
    )
    return obs_path, obs_sha


def build_c14_identity_binding():
    pos_root = fresh_dir(os.path.join(FIXTURES_DIR, "c14_identity_pos"))
    neg_root = fresh_dir(os.path.join(FIXTURES_DIR, "c14_identity_neg"))

    _obs_path_pos, obs_sha_pos = _c59_common_receipts(pos_root)
    _obs_path_neg, _obs_sha_neg = _c59_common_receipts(neg_root)

    # POS: identity's recorded sha256 matches the real observation receipt's
    # live-recomputed hash -- genuinely bound, must stay GREEN.
    write_json(
        os.path.join(pos_root, "receipts", "ember-resident-training-gate",
                     "resident-training-gate-20990101T000000Z.json"),
        {
            "ts": "20990101T000000Z",
            "verdict": "RESIDENT_TRAINING_GATE_PASS",
            "resident_training_gate_status": "PASS",
            "invalid_codes": [], "errors": [],
            "clean_room_harness_identity": {
                "full_avir_cli_parity_receipt": {
                    "real_avir_uiux_ax_observation_receipt": {"sha256": obs_sha_pos},
                },
            },
        },
    )

    # NEG: a deliberately WRONG sha256 -- reproduces "resident receipt names a
    # different harness build than the one currently latest," the exact
    # conflation class one level down. Everything else is byte-identical to
    # POS (built by the same _c59_common_receipts helper).
    write_json(
        os.path.join(neg_root, "receipts", "ember-resident-training-gate",
                     "resident-training-gate-20990101T000000Z.json"),
        {
            "ts": "20990101T000000Z",
            "verdict": "RESIDENT_TRAINING_GATE_PASS",
            "resident_training_gate_status": "PASS",
            "invalid_codes": [], "errors": [],
            "clean_room_harness_identity": {
                "full_avir_cli_parity_receipt": {
                    "real_avir_uiux_ax_observation_receipt": {
                        "sha256": "0" * 64,  # deliberately wrong, well-formed hash
                    },
                },
            },
        },
    )
    return pos_root, neg_root


# --- (3) C7: evidence-in-receipt (numeric per-arm scores) ---------------------

def build_c7():
    required = (
        os.path.join("scripts", "ember_phase5_c7", "c7_selftest.py"),
        os.path.join("scripts", "ember_phase5_c7", "regime_operator.py"),
    )
    pos_root = pinned_fixture_root("c7_pos", required)
    neg_root = pinned_fixture_root("c7_neg", required)

    for root in (pos_root, neg_root):
        fresh_dir(os.path.join(root, "receipts"))

    # Compute the operator_constants_hash from the pinned fixture itself.
    # The fixture deliberately carries receipt-returning hardening that the
    # older live C7 helper does not, so copying or importing the live helper
    # would silently weaken the control.
    pinned_pkg = os.path.join(pos_root, "scripts", "ember_phase5_c7")
    spec = importlib.util.spec_from_file_location(
        "c7_selftest_fixture_builder", os.path.join(pinned_pkg, "c7_selftest.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["c7_selftest_fixture_builder"] = mod
    spec.loader.exec_module(mod)
    live_hash = mod.OperatorConstants.canonical_hash()

    common = {
        "verdict": "PASS",
        "operator_constants_hash": live_hash,
        "held_out_slices": [1, 2],
        "degenerate_slice": [0],
        "proves_load_bearing": True,
    }

    write_json(
        os.path.join(pos_root, "receipts", "c7-selftest-20990101T000000Z.json"),
        {**common, "real_trained_pass_rate": 0.85, "real_deleted_pass_rate": 0.10},
    )
    # NEG: mirrors today's real receipts -- booleans-only, no numeric evidence.
    write_json(os.path.join(neg_root, "receipts", "c7-selftest-20990101T000000Z.json"), common)
    return pos_root, neg_root


# --- (6) C2: git-anchor disclosure + non-self-labeled leak check --------------

def build_c2():
    pos_root = fresh_dir(os.path.join(FIXTURES_DIR, "c2_pos"))
    neg_root = fresh_dir(os.path.join(FIXTURES_DIR, "c2_neg"))

    # POS: snapshot the REAL winning C2 receipt + its frozen-rows dependency
    # UNMODIFIED into an isolated root -- proves the hardening does not
    # regress the one probe R8 graded FAITHFUL-leaning.
    real_receipt = os.path.join(REPO_ROOT, "receipts", "ember-d3-native-loop",
                                 "d3-native-loop-20260620T230519Z.json")
    real_frozen = os.path.join(REPO_ROOT, "receipts", "ember-d3-native-loop",
                                "d3-gym-fresh-rows-offset8-len12-20260620T230700Z.json")
    dst_dir = os.path.join(pos_root, "receipts", "ember-d3-native-loop")
    os.makedirs(dst_dir, exist_ok=True)
    shutil.copy2(real_receipt, os.path.join(dst_dir, os.path.basename(real_receipt)))
    shutil.copy2(real_frozen, os.path.join(dst_dir, os.path.basename(real_frozen)))

    # NEG: a non-self-labeled leak -- the frozen row's gold_answer value
    # reappears VERBATIM in arm-C's output WITHOUT using any of the existing
    # LEAK_POLICIES marker strings (proving only the NEW content-match check
    # catches it -- the pre-existing marker-string scan would have missed
    # this exact fixture).
    frozen_dir = os.path.join(neg_root, "receipts", "ember-d3-native-loop")
    os.makedirs(frozen_dir, exist_ok=True)
    frozen_obj = dict(SYNTHETIC_MARKER)
    frozen_obj.update({
        "ts": "20990101T000000Z",
        "dataset": "osunlp/D3-Gym",
        "source_url": "https://huggingface.co/datasets/osunlp/D3-Gym",
        "rows": [
            {"row_idx": 0, "row": {"task_id": "synthetic_task_1",
                                    "gold_answer": "SECRET_GOLD_VALUE_42"}},
        ],
    })
    frozen_bytes = json.dumps(frozen_obj, indent=2).encode("utf-8")
    frozen_path = os.path.join(frozen_dir, "frozen-rows.json")
    with open(frozen_path, "wb") as fh:
        fh.write(frozen_bytes)
    frozen_sha = sha256_bytes(frozen_bytes)

    write_json(
        os.path.join(neg_root, "receipts", "ember-d3-native-loop", "d3-native-loop-20990101T010000Z.json"),
        {
            "ts": "20990101T010000Z",
            "external_task_source": {
                "source_url": "https://huggingface.co/datasets/osunlp/D3-Gym",
                "dataset": "osunlp/D3-Gym",
            },
            "fresh_rows_sha256": frozen_sha,
            "fresh_rows_path": "C:\\tmp\\synthetic\\frozen-rows.json",
            "per_task_rows": [
                {
                    "task_id": "synthetic_task_1",
                    "split": "heldout",
                    "arm_predictions": {
                        "C": {
                            "policy": "resident_eval_script_recursive",
                            "artifacts": ["SECRET_GOLD_VALUE_42 leaked verbatim in output"],
                        },
                    },
                },
            ],
        },
    )
    return pos_root, neg_root


# --- (7) C-OBS: evidence-surface scoping (lane-14 repair 1, 2026-07-02) -------

_C_OBS_ISOLATION_NOTE = (
    "LANE-14 CHK CONTROL FIXTURE (docs/goalforge-debate-ledger.md row R8) -- "
    "fabricated evidence for control-suite verification only; this file must "
    "never be treated as a real receipt if it leaks into a real board scan."
)


def build_c_obs():
    pos_root = fresh_dir(os.path.join(FIXTURES_DIR, "c_obs_pos"))
    neg_root = fresh_dir(os.path.join(FIXTURES_DIR, "c_obs_neg"))

    # NEG: a doc-only governing-text description satisfying all four (a)-(d)
    # positive checks by PROSE ALONE, with receipts/ absent entirely --
    # reproduces the pre-repair false-GREEN vector (positive evidence scanned
    # tree-wide, including docs/). Deliberately avoids the literal
    # INVALID_TOKENS strings AND the is_stub trigger words, so a pre-repair
    # scan accepts it as satisfying evidence with zero actual receipts.
    neg_doc = os.path.join(neg_root, "docs", "observatory-design-note.md")
    os.makedirs(os.path.dirname(neg_doc), exist_ok=True)
    with open(neg_doc, "w", encoding="utf-8") as fh:
        fh.write(
            "<!-- " + _C_OBS_ISOLATION_NOTE + " -->\n\n"
            "# Observatory Design Note (fixture doc prose, NOT a receipt)\n\n"
            "The EmberWorldState adapter binds GOAL, ledger, and receipts into "
            "live organism state. This is the real production binding used by "
            "the observatory.\n\n"
            "The system offers a click-to-evidence surface for every claim "
            "rendered to the user.\n\n"
            "A confirm-only encounter membrane exists; there is no silent "
            "steer path -- never silent steering permitted.\n\n"
            "The observatory proof-pack lets the user MONITOR live state, "
            "UNDERSTAND organ anatomy, and INTERACT with the organism.\n"
        )
    # receipts/ (and ledger/, baseline/) deliberately absent under neg_root --
    # no evidence-surface artifact exists, only the docs/ prose above.

    # POS: the same four conjuncts, but as genuine evidence-surface artifacts
    # under receipts/ (never docs/, never .py). The worldstate-binding note is
    # written raw (not via write_json) because write_json's SYNTHETIC_MARKER
    # contains the literal word "synthetic", which would trip the probe's
    # own is_stub heuristic for THAT file; the other three conjuncts have no
    # such guard so write_json is used normally for them.
    pos_worldstate = os.path.join(pos_root, "receipts", "worldstate-binding-note.md")
    os.makedirs(os.path.dirname(pos_worldstate), exist_ok=True)
    with open(pos_worldstate, "w", encoding="utf-8") as fh:
        fh.write(
            "<!-- " + _C_OBS_ISOLATION_NOTE + " -->\n\n"
            "# Fixture: EmberWorldState adapter binding evidence\n\n"
            "This receipt records that the EmberWorldState adapter binds real "
            "GOAL state, ledger entries, and receipts into the live organism "
            "world-state object. This is the production binding path, "
            "exercised end to end.\n"
        )
    write_json(
        os.path.join(pos_root, "receipts", "click-to-evidence-note.json"),
        {"note": "fixture receipt recording a click-to-evidence surface for every rendered claim"},
    )
    write_json(
        os.path.join(pos_root, "receipts", "membrane-note.json"),
        {"note": "confirm-only encounter membrane in place; no silent steer path -- never silent"},
    )
    write_json(
        os.path.join(pos_root, "receipts", "proofpack-note.json"),
        {"note": "observatory proof-pack: user MONITOR, UNDERSTAND, INTERACT commands all run"},
    )
    return pos_root, neg_root


# --- (8) C-MANIFEST: denominator regex + <20 floor (lane-14 repair 2, 2026-07-02) --

_C_MANIFEST_ISOLATION_NOTE = (
    "<!-- LANE-14 CHK CONTROL FIXTURE (docs/goalforge-debate-ledger.md row R8) -- "
    "synthetic goal/manifest fixture, NOT the real goal file; must never be "
    "treated as real by a probe scanning the real tree. -->\n\n"
)

# 25 fixture conditions across the 4 separator styles the repaired regex must
# tolerate: double-dash (already matched pre-repair), en-dash, colon+bold-
# close, and bare bold-close (all three MISSED pre-repair).
_C_MANIFEST_GROUPS = [
    ("--", range(1, 11)),
    ("–", range(11, 16)),
    (":**", range(16, 21)),
    ("**", range(21, 26)),
]


def _c_manifest_goal_text():
    lines = [_C_MANIFEST_ISOLATION_NOTE.rstrip("\n"), "",
             "## 4. EXPLICIT GOAL CONDITIONS (fixture)", ""]
    for sep, idxs in _C_MANIFEST_GROUPS:
        for i in idxs:
            cid = f"C-CTRL{i:02d}"
            if sep == "--":
                lines.append(f"- **{cid} -- fixture condition {i}.** R: fixture requirement text.")
            elif sep == "–":
                lines.append(f"- **{cid} – fixture condition {i} (en dash).** R: fixture requirement text.")
            elif sep == ":**":
                lines.append(f"- **{cid}:** fixture condition {i} (colon bold-close). R: fixture requirement text.")
            else:
                lines.append(f"- **{cid}** fixture condition {i} (bare bold-close). R: fixture requirement text.")
    lines += ["", "## 5. GLOBAL INVARIANTS (fixture)", "", "(end)"]
    return "\n".join(lines) + "\n"


def _c_manifest_rows_text(ids):
    lines = [_C_MANIFEST_ISOLATION_NOTE.rstrip("\n"), "",
             "| id | subgoal | piece | AC | receipt | status |",
             "|----|---------|-------|----|---------|--------|"]
    for cid in ids:
        lines.append(f"| {cid} | S1 | fixture piece {cid} | fixture AC | fixture receipt | DONE |")
    return "\n".join(lines) + "\n"


def build_c_manifest():
    pos_root = fresh_dir(os.path.join(FIXTURES_DIR, "c_manifest_pos"))
    neg_root = fresh_dir(os.path.join(FIXTURES_DIR, "c_manifest_neg"))

    goal_text = _c_manifest_goal_text()
    all_ids = [f"C-CTRL{i:02d}" for i in range(1, 26)]
    dashdash_only_ids = [f"C-CTRL{i:02d}" for i in range(1, 11)]

    # NEG: goal file has all 25 (mixed separators); manifest rows ONLY the 10
    # double-dash ones. Pre-repair, the regex only ever extracted those 10
    # into the denominator, so the other 15 silently never existed as
    # "planned pieces" and the probe false-GREENed. Post-repair all 25 are in
    # the denominator, so the 15 un-rowed ones must surface as RED.
    # POS: same 25-condition goal file, but all 25 rowed -> GREEN both ways.
    for root, ids in ((neg_root, dashdash_only_ids), (pos_root, all_ids)):
        goal_path = os.path.join(root, "docs", "spec", "conditions-v1.md")
        os.makedirs(os.path.dirname(goal_path), exist_ok=True)
        with open(goal_path, "w", encoding="utf-8") as fh:
            fh.write(goal_text)
        manifest_path = os.path.join(root, "docs", "ember-completeness.md")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            fh.write(_c_manifest_rows_text(ids))

    return pos_root, neg_root


# --- (23) gh #715 C-MANIFEST/C-TALLY denominator, PRODUCTION-SHAPED fixtures --
# (lane-14/PR955 round-2 repair, reviewer defect P1: the regression must be
# executed by the canonical driver itself, not left as a standalone script).
# Deliberately reuses issue715's own seeding/removal helpers against the
# REAL docs/domains/governance/spec/conditions-v1.md + docs/domains/governance/contracts/ember-completeness.md bytes --
# never a re-typed synthetic shape like build_c_manifest() above, because
# issue #715's own audit finding was specifically about the production
# file's literal separator characters.

def build_issue715_pos():
    root = fresh_dir(os.path.join(FIXTURES_DIR, "issue715_pos"))
    issue715._seed_production_fixture(Path(root))
    return root


def build_issue715_neg(condition_id):
    slug = condition_id.lower().replace("-", "_").replace("(", "").replace(")", "")
    root = fresh_dir(os.path.join(FIXTURES_DIR, f"issue715_neg_{slug}"))
    _spec_dst, manifest_dst = issue715._seed_production_fixture(Path(root))
    issue715._delete_manifest_row(manifest_dst, condition_id)
    return root


# --- (9) C-IND: five IND receipt classes + fail-closed [A] script-authorship --

_C_IND_ISOLATION_NOTE = (
    "<!-- LANE-14 CHK CONTROL FIXTURE (docs/goalforge-debate-ledger.md row R8) -- "
    "synthetic C-IND fixture, NOT a real receipt; must never be treated as real "
    "by a probe scanning the real tree. -->\n\n"
)

_C_IND_OPERATOR_DOCS = {
    "docs/domains/governance/operator/README.md": "# Operator entry point (fixture)\n",
    "docs/operator/interact.md": "# Interact (fixture)\n",
    "docs/operator/operate-launch.md": "# Launch (fixture)\n",
    "docs/operator/operate-teardown.md": "# Teardown (fixture)\n",
    "docs/operator/operate-resume.md": "# Resume (fixture)\n",
    "docs/operator/customize.md": "# Customize (fixture)\n",
    "docs/operator/experiment-reproduction.md": "# Experiment reproduction (fixture)\n",
    "docs/operator/worlds-and-verifiers.md": "# Worlds+verifiers (fixture)\n",
    "docs/operator/ledger.md": "# Ledger (fixture)\n",
    "docs/operator/resident-learner.md": "# Resident learner (fixture)\n",
    "docs/operator/growth.md": "# Growth (fixture)\n",
    "docs/operator/harness.md": "# Harness (fixture)\n",
    "docs/operator/cockpit.md": "# Cockpit (fixture)\n",
    "docs/operator/error-assimilation.md": "# Error assimilation (fixture)\n",
    "docs/operator/federation.md": "# Federation (fixture)\n",
    "docs/operator/baseline.md": "# Baseline (fixture)\n",
    "docs/operator/publication.md": "# Publication (fixture)\n",
}


def _c_ind_write_shared_fixture(root):
    """Write the content IDENTICAL between the POS and NEG C-IND fixtures:
    the operator-facing doc set every doc_pointer cites, the C-OBS
    four-conjunct evidence (so the IND-2 imported leg is GREEN on both --
    the NEG control must isolate ONLY the IND-5 [A] script-authorship flip),
    and conforming IND-1/IND-3/IND-4/IND-5[S] receipts."""
    for rel, content in _C_IND_OPERATOR_DOCS.items():
        p = os.path.join(root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(_C_IND_ISOLATION_NOTE + content)

    # IND-2 leg: identical to build_c_obs()'s POS fixture shape, so C-OBS
    # (the real probe, imported not duplicated) reports GREEN on this root.
    # Uses _C_OBS_ISOLATION_NOTE (not _C_IND_ISOLATION_NOTE) deliberately --
    # the latter's word "synthetic" trips C-OBS's own is_stub heuristic for
    # THIS file specifically, the same trap build_c_obs()'s pos fixture
    # already documents and avoids.
    pos_worldstate = os.path.join(root, "receipts", "worldstate-binding-note.md")
    os.makedirs(os.path.dirname(pos_worldstate), exist_ok=True)
    with open(pos_worldstate, "w", encoding="utf-8") as fh:
        fh.write(
            "<!-- " + _C_OBS_ISOLATION_NOTE + " -->\n\n"
            "# Fixture: EmberWorldState adapter binding evidence\n\n"
            "This receipt records that the EmberWorldState adapter binds real "
            "GOAL state, ledger entries, and receipts into the live organism "
            "world-state object. This is the production binding path, "
            "exercised end to end.\n"
        )
    write_json(
        os.path.join(root, "receipts", "click-to-evidence-note.json"),
        {"note": "fixture receipt recording a click-to-evidence surface for every rendered claim"},
    )
    write_json(
        os.path.join(root, "receipts", "membrane-note.json"),
        {"note": "confirm-only encounter membrane in place; no silent steer path -- never silent"},
    )
    write_json(
        os.path.join(root, "receipts", "proofpack-note.json"),
        {"note": "observatory proof-pack: user MONITOR, UNDERSTAND, INTERACT commands all run"},
    )

    ind_dir = os.path.join(root, "receipts", "ember-operator-independence")

    write_json(os.path.join(ind_dir, "ind1-interact-20990101T000000Z.json"), {
        "receipt_class": "IND-1",
        "documented_boot_command": "ember-cli --interactive (fixture)",
        "doc_pointer": "docs/operator/interact.md",
        "rendered_frame_evidence": {"screen_capture_path": "fixture-frame.png", "prompt_turn_rendered": True},
        "clean_exit": True,
        # [issue #61] test_c_ind.py's _validate_ind1 was hardened 2026-07-02
        # (commit 73a5656) to require an attested-complete session matrix --
        # this fixture predates that hardening and was never re-synced.
        # Matches the shape real production IND-1 receipts now carry
        # (e.g. receipts/ind1-interact-session-matrix-v2-*-import-edition.json).
        "matrix_complete": True,
        "matrix_missing": [],
        # [ISSUE #97 cure 6] producer-provenance field, required for class 1
        # discovery -- matches the real corpus's own "generator" convention.
        "generator": "fixture-harness",
    })
    write_json(os.path.join(ind_dir, "ind3-launch-20990101T000000Z.json"), {
        "receipt_class": "IND-3", "leg": "launch",
        "doc_pointer": "docs/operator/operate-launch.md",
        "documented_command": "ember-cli --start (fixture)",
        "heartbeat_ready": {"status": "ready"},
        "verified_alive": True,
        "governed_vram_fraction_respected": True,
        "generator": "fixture-harness",  # [ISSUE #97 cure 6]
    })
    write_json(os.path.join(ind_dir, "ind3-teardown-20990101T000000Z.json"), {
        "receipt_class": "IND-3", "leg": "teardown",
        "doc_pointer": "docs/operator/operate-teardown.md",
        "documented_command": "ember-cli --stop (fixture)",
        "exit_code": 0,
        "final_heartbeat": {"status": "stopped"},
        "post_stop_process_table": {"survivors": [], "orphaned_gpu_state": False},
        "generator": "fixture-harness",  # [ISSUE #97 cure 6]
    })
    write_json(os.path.join(ind_dir, "ind3-resume-20990101T000000Z.json"), {
        "receipt_class": "IND-3", "leg": "interrupted_resume",
        "doc_pointer": "docs/operator/operate-resume.md",
        "interrupt_command_exit_code": 0,
        "interrupted_pid_verified_dead": True,
        "interrupted_launcher_pid_verified_dead": True,
        "resumed_ready_heartbeat": {"status": "ready"},
        "resumed_verified_alive": True,
        "final_cleanup": {"exit_code": 0, "post_stop_survivors": []},
        "resumable_state": True, "corrupt": False,
        "generator": "fixture-harness",  # [ISSUE #97 cure 6]
    })
    write_json(os.path.join(ind_dir, "ind4-customize-20990101T000000Z.json"), {
        "receipt_class": "IND-4", "leg": "customize",
        "doc_pointer": "docs/operator/customize.md",
        "config_file_edited": "config/fixture.toml",
        "before": {"flag": False}, "after": {"flag": True},
    })
    write_json(os.path.join(ind_dir, "ind4-experiment-reproduction-20990101T000000Z.json"), {
        "receipt_class": "IND-4", "leg": "experiment_reproduction",
        "doc_pointer": "docs/operator/experiment-reproduction.md",
        "banked_receipt_ref": "receipts/fixture-banked-20990101T000000Z.json",
        "fresh_receipt_ref": "receipts/fixture-fresh-20990101T000200Z.json",
        "within_tolerance": True,
    })
    write_json(os.path.join(ind_dir, "ind5-s-checkable-20990101T000000Z.json"), {
        "receipt_class": "IND-5", "leg": "s_checkable",
        "organism_component_docs": {
            "worlds_and_verifiers": "docs/operator/worlds-and-verifiers.md",
            "ledger": "docs/operator/ledger.md",
            "resident_learner": "docs/operator/resident-learner.md",
            "growth_operator": "docs/operator/growth.md",
            "harness_self_edits": "docs/operator/harness.md",
            "observatory_cockpit": "docs/operator/cockpit.md",
            "error_assimilation": "docs/operator/error-assimilation.md",
            "federation": "docs/operator/federation.md",
            "baseline_packet": "docs/operator/baseline.md",
            "publication": "docs/operator/publication.md",
        },
        "single_entry_path": "docs/domains/governance/operator/README.md",
        "no_dead_links": True,
    })
    # [issue #88] IND-5 re-spec: comprehend_v2 is now the ONLY receipt shape
    # that gates GREEN (the retired s_checkable/a_attested fields above stay
    # for audit continuity but no longer count). Written identically into
    # BOTH pos_ind_dir and neg_ind_dir -- the NEG control's whole point is
    # that the RETIRED [A] script-authorship trap fires REGARDLESS of what
    # else is satisfying, so giving NEG a fully-passing comprehend_v2 receipt
    # too makes that fail-closed proof strictly stronger, not weaker.
    write_json(os.path.join(ind_dir, "ind5-comprehend-v2-20990101T000000Z.json"), {
        "receipt_class": "IND-5", "leg": "comprehend_v2",
        "spec_amendment": {
            "date": "2026-07-04", "issue": "#88",
            "rationale": "fixture: operator directive, no operator-gated board conditions",
            "supersedes": "the two-leg [S]+[A] shape",
        },
        "attestation_superseded_by": {
            "note": "fixture: OLD [A]/[S] fields retained for audit continuity, not evaluated here",
            "old_receipts_found": [],
        },
        "legs": {
            "entry_point_integrity": {"passed": True, "dead_links": [], "reason": "fixture: all linked docs resolve"},
            "completeness": {"passed": True, "undocumented_commands": [], "reason": "fixture: every live command documented"},
            "freshness": {"passed": True, "stale_citations": {}, "reason": "fixture: every cited command is live"},
            "executability": {"passed": True, "examples": [], "reason": "fixture: every example exited 0"},
        },
        "all_four_legs_passed": True,
        "ts": "20990101T000000Z",
    })
    return ind_dir


def build_c_ind():
    pos_root = fresh_dir(os.path.join(FIXTURES_DIR, "c_ind_pos"))
    neg_root = fresh_dir(os.path.join(FIXTURES_DIR, "c_ind_neg"))

    pos_ind_dir = _c_ind_write_shared_fixture(pos_root)
    neg_ind_dir = _c_ind_write_shared_fixture(neg_root)

    # POS: a genuine, dated, transcription-marked operator-attestation object
    # (schema modeled on docs/spec/operator-acceptance-v1.md's acceptance/v1).
    write_json(os.path.join(pos_ind_dir, "ind5-a-attested-20990101T000000Z.json"), {
        "receipt_class": "IND-5", "leg": "a_attested", "schema": "acceptance/v1",
        "scope": "c-ind-comprehension-fixture", "accepted_by": "operator", "channel": "chat",
        "verbatim": "Fixture: I have read and understood the organism's operator documentation end to end.",
        "ts": "20990101T000000Z",
    })

    # NEG: the spec's named control (operator-independence-v1.md §3/§4) --
    # a planted ASSISTANT-AUTHORED / mechanically-generated attestation. This
    # is the ONLY difference from the POS fixture -- proves the hardening
    # catches invalid_comprehension_by_script specifically, fail-closed, even
    # though every other IND class (including the imported C-OBS leg) is
    # otherwise conforming.
    write_json(os.path.join(neg_ind_dir, "ind5-a-attested-20990101T000000Z.json"), {
        "receipt_class": "IND-5", "leg": "a_attested", "schema": "acceptance/v1",
        "scope": "c-ind-comprehension-fixture", "accepted_by": "assistant",
        "generated_by": "automated_transcription_script",
        "channel": "chat",
        "verbatim": "Auto-generated comprehension summary produced without operator review.",
        "ts": "20990101T000000Z",
    })

    return pos_root, neg_root


# --- (10) C-SCALE: ratio re-derivation + full CHK -----------------------------

_C_SCALE_README = """
LANE-14 CHK CONTROL FIXTURE (docs/domains/governance/spec/conditions-v1.md S4.2 C-SCALE;
docs/goalforge-debate-ledger.md row R8) -- synthetic, far-future-dated
control fixture, NOT a real receipt.

Deviation from the write_json()/SYNTHETIC_MARKER convention used by the
other builders in this file: test_c_scale.py hard-rejects any candidate
receipt carrying `_synthetic_control_fixture` before it ever reaches the
CHK check (`failures.append(f"{name}: synthetic control fixture, never
evidence")`). So the one file per fixture root that the probe must actually
EVALUATE (accepted for POS / evaluated-and-rejected-for-the-sharp-reason
for NEG) -- scale-credibility-*.json -- is written marker-free via a local
write_json_no_marker() helper (plain json.dump). Every other file in this
fixture (the W2 free_cognitive_mode_transition_receipt support artifact)
still carries the marker via write_json(), since it is only ever resolved
by path/existence (resolve_in_tree), never itself glob-matched or content-
inspected by the probe. This isolation note stands in for the marker on the
one file that cannot carry it: this fixture root must never be treated as
real evidence if it leaks outside chk_controls/fixtures/.
"""


def _c_scale_receipt(claimed_capability_ratio, mode_receipt_rel):
    return {
        "operating_capability_point": 4.2e9,
        "W1": {
            "measured_tokens_to_base": 8.4e10,
            "projected_dense_tokens_to_base": 1.68e11,
            "token_bill_collapse_ratio": 2.0,
            "growth_lineage_from_cbase_seed": "grown-from-cbase-seed-fixture-v1",
            "no_borrowed_weights_load_bearing": True,
        },
        "W2": {
            "native_finetune_mechanism_id": "native-inloop-adapter-fixture-v1",
            "per_update_cost_at_scale": 0.42,
            "free_cognitive_mode_transition_receipt": mode_receipt_rel,
            "no_borrowed_base": True,
        },
        "measured_flops_to_capability": 5.0e21,
        "projected_dense_flops_to_capability": 1.1e22,
        "capability_per_compute_ratio": claimed_capability_ratio,
        "contribution_deletion_collapses_excess": True,
        "active_working_set_bytes": 2.0e10,
        "device_working_set_floor_bytes": 2.4e10,
    }


def build_c_scale():
    pos_root = fresh_dir(os.path.join(FIXTURES_DIR, "c_scale_pos"))
    neg_root = fresh_dir(os.path.join(FIXTURES_DIR, "c_scale_neg"))

    fixture_dir_rel = os.path.join("receipts", "ember-c-scale-fixture")
    mode_receipt_rel = os.path.join(fixture_dir_rel, "mode-transition-note.json").replace("\\", "/")

    for root in (pos_root, neg_root):
        write_readme(root, _C_SCALE_README)
        # W2 support artifact: referenced only via free_cognitive_mode_
        # transition_receipt (resolve_in_tree checks path+existence, never
        # content), so it is safe to carry the SYNTHETIC_MARKER.
        write_json(
            os.path.join(root, fixture_dir_rel, "mode-transition-note.json"),
            {"note": "fixture free-cognitive-mode-transition receipt (path-only reference)"},
        )

    # POS: full conforming receipt -- both ratios re-derive within tolerance.
    write_json_no_marker(
        os.path.join(pos_root, fixture_dir_rel, "scale-credibility-20990101T000000Z.json"),
        _c_scale_receipt(claimed_capability_ratio=2.2, mode_receipt_rel=mode_receipt_rel),
    )

    # NEG: memory-fit-style corruption -- capability_per_compute_ratio claims
    # 2.0 while measured_flops_to_capability/projected_dense_flops_to_
    # capability actually re-derive to 1.1e22/5.0e21 = 2.2 (a 10% gap, well
    # outside the 1% tolerance). Everything else conforms, isolating the
    # re-derivation tooth specifically (a claimed ratio that does not
    # re-derive is self-refuting, never trusted -- CHK docstring).
    write_json_no_marker(
        os.path.join(neg_root, fixture_dir_rel, "scale-credibility-20990101T000000Z.json"),
        _c_scale_receipt(claimed_capability_ratio=2.0, mode_receipt_rel=mode_receipt_rel),
    )

    return pos_root, neg_root


# --- (11) C-E2B: paired-both-legs + frozen-before-verdict ---------------------

_C_E2B_README = """
LANE-14 CHK CONTROL FIXTURE (docs/domains/governance/spec/conditions-v1.md S4.2 C-E2B;
docs/goalforge-debate-ledger.md row R8) -- synthetic, far-future-dated
control fixture, NOT a real receipt.

Deviation from the write_json()/SYNTHETIC_MARKER convention: test_c_e2b.py
hard-rejects any candidate receipt carrying `_synthetic_control_fixture`
before it reaches the CHK check, identically to test_c_scale.py. The one
file per fixture root the probe must actually EVALUATE --
e2b-paired-surpass-*.json -- is written marker-free via
write_json_no_marker(). The referenced protocol_frozen_ref support artifact
(e2b-protocol-frozen-*.json) still carries the marker via write_json() --
it is only resolved by path/existence + a timestamp regex over its own
filename (never content-inspected), and it sorts alphabetically AFTER the
paired-surpass receipt within the same directory, so the probe's glob loop
evaluates and emits/exits on the real target before ever reaching the
marked support file. This isolation note stands in for the marker on the
file that cannot carry it.
"""


def _c_e2b_receipt(legs):
    return {
        "ts": "20990102T000000Z",
        "legs": legs,
        "matched_budget": {"owned_arm": 100, "e2b_arm": 100},
        "owned_core_identity": {
            "id": "ember-owned-core-fixture-v1",
            "no_borrowed_weights": True,
            "quantized": False,
        },
        "protocol_frozen_ref": os.path.join(
            "receipts", "ember-e2b-fixture", "e2b-protocol-frozen-20990101T000000Z.json"
        ).replace("\\", "/"),
    }


def build_c_e2b():
    pos_root = fresh_dir(os.path.join(FIXTURES_DIR, "c_e2b_pos"))
    neg_root = fresh_dir(os.path.join(FIXTURES_DIR, "c_e2b_neg"))

    fixture_dir_rel = os.path.join("receipts", "ember-e2b-fixture")

    for root in (pos_root, neg_root):
        write_readme(root, _C_E2B_README)
        # protocol_frozen_ref support artifact -- resolved by path+filename-
        # timestamp only, never content-inspected, safe to carry the marker.
        # Filename timestamp (20990101...) is strictly earlier than the
        # receipt's own ts (20990102...) -- frozen-before-verdict.
        write_json(
            os.path.join(root, fixture_dir_rel, "e2b-protocol-frozen-20990101T000000Z.json"),
            {"note": "fixture paired-protocol freeze artifact (path+filename-ts reference only)"},
        )

    # POS: both legs surpass at matched governed budget, owned+unquantized
    # identity, protocol frozen strictly before the receipt ts.
    write_json_no_marker(
        os.path.join(pos_root, fixture_dir_rel, "e2b-paired-surpass-20990102T000000Z.json"),
        _c_e2b_receipt({
            "ember_work": {"owned_core_score": 0.82, "e2b_score": 0.55},
            "founder_likeness": {"owned_core_score": 0.91, "e2b_score": 0.60},
        }),
    )

    # NEG: registry's own named does-NOT-count -- single-leg surpass. Only
    # ember_work is present; founder_likeness is absent entirely. Everything
    # else (matched_budget, owned_core_identity, protocol_frozen_ref) is
    # identical to the POS fixture, isolating the leg-pairing tooth.
    write_json_no_marker(
        os.path.join(neg_root, fixture_dir_rel, "e2b-paired-surpass-20990102T000000Z.json"),
        _c_e2b_receipt({
            "ember_work": {"owned_core_score": 0.82, "e2b_score": 0.55},
        }),
    )

    return pos_root, neg_root


# --- (14) ISSUE #97 cure 7: meta-audit-family exclusion (C-FED + C-PORT) -----
# 2026-07-04. The #89 board-integrity audit's own receipt family
# (receipts/ember-totality-audit/**) DESCRIBES probe findings/attack strings
# verbatim -- it never COMMITS one. Pre-cure, test_c_fed.py's
# negative_scan_files() and test_c_port.py's find_portability_receipt()
# scanned it as ordinary evidence, flipping BOTH conditions RED live on
# 2026-07-04 (audit-20260704T144656Z.json quoted "invalid_unapproved_egress"
# as a finding string and was independently selected as C-PORT's "newest
# candidate" too). Fixtures below isolate the tooth: POS proves the
# audit-family receipt is excluded (GREEN survives); NEG proves a REAL
# violation/candidate OUTSIDE the audit family is still caught (RED), so the
# exclusion is scoped to the meta-audit dirname only, never a blanket bypass.

_CURE7_ISOLATION_NOTE = (
    "LANE-14/ISSUE-97 CHK CONTROL FIXTURE -- synthetic, far-future-dated "
    "control fixture, NOT a real receipt or a real audit finding; must never "
    "be treated as real by a probe scanning the real tree."
)


def _cure7_fed_positive_doc_text():
    return (
        "<!-- " + _CURE7_ISOLATION_NOTE + " -->\n\n"
        "# Federation design (fixture)\n\n"
        "This is a checkpoint-portability design across substrates. It "
        "implements work-sharding across compute for federation. "
        "Receipt-merge combines partial results from each shard.\n\n"
        "Avenues: kaggle, colab, hf (huggingface).\n\n"
        "This document names an EGRESS MANIFEST enumerating exactly what "
        "would leave the PC, to whom, per avenue.\n\n"
        "Zero outbound transfer has occurred; this is design-only, nothing "
        "has left the PC. Per-avenue approval required before any transfer.\n"
    )


def build_cure7_c_fed():
    pos_root = fresh_dir(os.path.join(FIXTURES_DIR, "cure7_fed_pos"))
    neg_root = fresh_dir(os.path.join(FIXTURES_DIR, "cure7_fed_neg"))

    # Both fixtures share the identical genuine positive artifact -- isolates
    # ONLY the invalid-token location tooth.
    for root in (pos_root, neg_root):
        write_readme(root, _CURE7_ISOLATION_NOTE)
        doc_path = os.path.join(root, "docs", "c-fed-federation-design.md")
        os.makedirs(os.path.dirname(doc_path), exist_ok=True)
        with open(doc_path, "w", encoding="utf-8") as fh:
            fh.write(_cure7_fed_positive_doc_text())

    # POS: the invalid token appears ONLY inside the meta-audit receipt
    # family -- must NOT trip C-FED (this is the exact 2026-07-04 live shape).
    write_json(
        os.path.join(pos_root, "receipts", "ember-totality-audit",
                     "audit-fixture-20990101T000000Z.json"),
        {
            "finding": "spot-verify: probe scan detected the literal string "
                       "'invalid_unapproved_egress' quoted inside a receipt's "
                       "text; this audit report quotes the token as a finding "
                       "description, it does not commit the violation",
        },
    )

    # NEG: the identical token, but in a REAL (non-audit) receipt -- a
    # genuine disqualifying admission. Must still trip RED, proving the
    # exclusion is scoped to receipts/ember-totality-audit/** only.
    write_json(
        os.path.join(neg_root, "receipts", "some-other-surface",
                     "real-violation-20990101T000000Z.json"),
        {"note": "invalid_unapproved_egress occurred without recorded "
                 "per-avenue approval"},
    )
    return pos_root, neg_root


def _cure7_port_positive_receipt():
    return {
        "device": "simulated 3090-class (Ampere, sm_86, non-4090 profile)",
        "forward_pass": {"no_crash": True},
        "governor": {"total_gib": 24.0, "ember_vram_fraction": 0.9},
        "throughput_basis": "device-relative roofline-derived threshold",
        "fp8_note": "fp8 path gated on sm>=89; bf16 fallback used for sm<89",
        "note": "governor change is tighten only, never loosen the 4090 floor",
    }


def _cure7_port_audit_fixture(root, filename):
    write_json(
        os.path.join(root, "receipts", "ember-totality-audit", filename),
        {
            "finding": "spot-verify: candidate receipt quoted forward_pass "
                       "no_crash: true device_portability markers verbatim "
                       "from the inspected artifact; this audit finding text "
                       "is itself not a portability receipt",
        },
    )


def build_cure7_c_port():
    pos_root = fresh_dir(os.path.join(FIXTURES_DIR, "cure7_port_pos"))
    neg_root = fresh_dir(os.path.join(FIXTURES_DIR, "cure7_port_neg"))

    # POS: a genuine, CHK-satisfying device-portability receipt, PLUS a
    # later-timestamped meta-audit receipt that (pre-cure) would have sorted
    # as "newest candidate" and wrongly displaced it. Must be GREEN, citing
    # the real receipt.
    write_readme(pos_root, _CURE7_ISOLATION_NOTE)
    write_json_no_marker(
        os.path.join(pos_root, "receipts",
                     "c-port-device-portability-fixture-20990101T000000Z.json"),
        _cure7_port_positive_receipt(),
    )
    _cure7_port_audit_fixture(pos_root, "audit-fixture-20990601T000000Z.json")

    # NEG: the genuine candidate is a REAL violation (4090-only device
    # identity, the registry's own named does-NOT-count), PLUS the same
    # later-timestamped audit receipt. Must be RED, sourced from the real
    # 4090-only candidate -- proving the exclusion doesn't swallow a genuine
    # negative.
    write_readme(neg_root, _CURE7_ISOLATION_NOTE)
    write_json_no_marker(
        os.path.join(neg_root, "receipts",
                     "c-port-device-portability-fixture-20990101T000000Z.json"),
        {
            "kind": "device_portability_probe",
            "device": "NVIDIA RTX 4090",
            "forward_pass": {"no_crash": True},
            "governor": {"total_gib": 24.0, "ember_vram_fraction": 0.9},
        },
    )
    _cure7_port_audit_fixture(neg_root, "audit-fixture-20990601T000000Z.json")

    return pos_root, neg_root


# --- (15) ISSUE #107: test_c11.py experience-horizon contract ---------------
# 2026-08-03. The retired fixtures here exercised the 1h/3h/24h wall-clock
# re-earn contract, which conditions-v1.md superseded: C11 is an
# experience-horizon capability delta, and duration is a timer, not a lever.
# These fixtures exercise the sharp tooth of each of the nine recomputed
# checks in docs/domains/governance/design/c11-experience-horizon-spec.md, one at a time, against an
# otherwise fully-conforming short/medium/long + deletion receipt set.

_C11_RECEIPT_DIR_REL = os.path.join("receipts", "ember-mvp", "c11-experience-horizon")
_C11_FILES = {
    "short": "horizon-short.json",
    "medium": "horizon-medium.json",
    "long": "horizon-long.json",
    "deletion": "deletion.json",
}


def _c11_merkle_root(leaf_hexes):
    """Same tree rule test_c11.py recomputes with: pairwise sha256 over hex
    concatenation, odd node promoted."""
    level = list(leaf_hexes)
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                nxt.append(hashlib.sha256((level[i] + level[i + 1]).encode()).hexdigest())
            else:
                nxt.append(level[i])
        level = nxt
    return level[0]


def _c11_items(n_total, n_passed, prefix, with_execution=True):
    """Held-out rows. `passed` is always kept consistent with the row's own
    exit_code -- the probe re-derives one from the other."""
    items = []
    for i in range(n_total):
        passed = i < n_passed
        row = {"item_id": f"{prefix}-ho-{i:04d}", "passed": passed}
        if with_execution:
            row["execution"] = {
                "executor": "fixture-sandbox-runner",
                "exit_code": 0 if passed else 1,
                "stdout_sha256": hashlib.sha256(
                    f"{prefix}-{i}-{passed}".encode()).hexdigest(),
                "duration_s": 0.5 + i * 0.01,
            }
        items.append(row)
    return items


def _c11_horizon_receipt(horizon, n_novel, n_total, n_passed, post_seed,
                          stray_gradient_problem_id=None,
                          strip_execution_on_first_row=False):
    problem_ids = [f"np-{i:04d}" for i in range(n_novel)]
    steps = [{"step": i, "problem_id": problem_ids[i % len(problem_ids)],
              "grad_norm": 0.4 + i * 0.01}
             for i in range(min(8, n_novel))]
    if stray_gradient_problem_id is not None:
        steps[-1]["problem_id"] = stray_gradient_problem_id
    leaves = [hashlib.sha256(f"{s['step']}:{s['problem_id']}".encode()).hexdigest()
              for s in steps]
    items = _c11_items(n_total, n_passed, horizon)
    if strip_execution_on_first_row:
        items[0].pop("execution", None)
    return {
        "ticket": "EMBER-C11-EXPERIENCE-HORIZON",
        "ts": "20990101T000000Z",
        "horizon": horizon,
        "ordering_basis": "novel_problem_count",
        "substrate": {"model_id": "fixture-3b", "param_count": 3000000000},
        "novel_problems": {
            "problem_ids": problem_ids,
            "pretrain_overlap_ids": [],
            "corpus_exclusion_digest": sha256_bytes(b"fixture-corpus"),
        },
        "learning_update": {
            "pre_param_hash": f"sha256:{sha256_bytes(('pre-' + horizon).encode())}",
            "post_param_hash": f"sha256:{sha256_bytes(post_seed.encode())}",
            "hash_algorithm": "sha256 over the sorted state_dict tensor bytes",
            "merkle_leaf_recipe": 'sha256(f"{step}:{problem_id}")',
            "merkle_root": f"sha256:{_c11_merkle_root(leaves)}",
            "gradient_steps": steps,
        },
        "heldout": {
            "suite_id": "c11-heldout-v1",
            "claimed_score": n_passed / float(n_total),
            "items": items,
        },
        "wall_seconds": 3600.0 * (1 + n_novel),
    }


def _c11_deletion_receipt(baseline_hash, strip_arm_execution=False):
    def arm(tag, n_passed, seed):
        items = _c11_items(20, n_passed, tag)
        if strip_arm_execution:
            # [rev-107 B-1] The exact hole the reviewer executed: arm rows with
            # the execution block removed and the pass counts hand-set. Before
            # the cure this still scored GREEN.
            for row in items:
                row.pop("execution", None)
        return {
            "checkpoint_hash": f"sha256:{sha256_bytes(seed.encode())}",
            "items": items,
        }
    return {
        "ticket": "EMBER-C11-EXPERIENCE-HORIZON-DELETION",
        "ts": "20990101T000000Z",
        "deleted_component": "long_horizon_consolidation",
        "baseline_label": "short_horizon_checkpoint",
        "baseline_checkpoint_hash": baseline_hash,
        "arms": {
            # short 0.50, long 0.90, deleted 0.55 -- deleting the long-horizon
            # consolidation drags capability back toward the short-horizon level.
            "short": arm("del-short", 10, "post-short"),
            "long": arm("del-long", 18, "post-long"),
            "long_minus_consolidation": arm("del-cut", 11, "post-long-cut"),
        },
    }


def build_c11_horizon(variant):
    """POS is a fully-conforming short/medium/long + deletion set. Each NEG
    targets one check's sharp tooth; every one of the nine checks has a negative
    control. Variants:

      pos, neg_ordering (CHK-1), neg_duplicate_ids (CHK-2),
      neg_identical_checkpoint (CHK-3), neg_merkle (CHK-4), neg_empty_steps
      (CHK-4 present-but-empty), neg_noise_floor (CHK-5), neg_contamination
      (CHK-6), neg_fabricated (CHK-7), neg_wrong_baseline (CHK-8),
      neg_arm_fabricated (CHK-8 arm re-execution), neg_invalid_token (CHK-9).

    [rev-107] neg_ordering is the one variant that trips two checks (CHK-1 and,
    because the superset rule implies increasing counts, CHK-2). That coupling
    is inherent to the nested-horizon reading, not a fixture defect."""
    root = fresh_dir(os.path.join(FIXTURES_DIR, f"c11_{variant}"))
    write_readme(root, _CURE7_ISOLATION_NOTE)

    # Held-out scores 0.50 / 0.70 / 0.90 -- each gap well above the 0.02
    # pre-registered noise floor. Novel-problem counts 4 < 8 < 12, and the id
    # sets nest (np-0000..) so each longer horizon strictly supersets the
    # shorter one.
    short = _c11_horizon_receipt("short", 4, 20, 10, "post-short")
    medium = _c11_horizon_receipt("medium", 8, 20, 14, "post-medium")

    long_novel = 12
    long_post_seed = "post-long"
    long_passed = 18
    stray = None
    strip_exec = False
    if variant == "neg_ordering":
        # Fewer novel problems than medium -> the ordering claim is not carried
        # by experience; only wall_seconds still rises (clock_in_disguise).
        long_novel = 6
    if variant == "neg_identical_checkpoint":
        long_post_seed = "post-medium"
    if variant == "neg_merkle":
        stray = "np-9999"
    if variant == "neg_fabricated":
        strip_exec = True
    if variant == "neg_noise_floor":
        # Long reaches exactly medium's held-out score -> no delta above the
        # pre-registered floor, so the longer horizon buys nothing.
        long_passed = 14
    long_r = _c11_horizon_receipt("long", long_novel, 20, long_passed,
                                   long_post_seed,
                                   stray_gradient_problem_id=stray,
                                   strip_execution_on_first_row=strip_exec)

    if variant == "neg_duplicate_ids":
        # A repeated row re-hashed is not new experience.
        long_r["novel_problems"]["problem_ids"].append("np-0000")
    if variant == "neg_contamination":
        # A held-out item that was actually trained on.
        long_r["heldout"]["items"][0]["item_id"] = "np-0000"
    if variant == "neg_empty_steps":
        # Present-but-EMPTY claim: learning_update is there, still asserts a
        # merkle_root, and backs it with no steps at all (rev-107 B-2).
        long_r["learning_update"]["gradient_steps"] = []
    if variant == "neg_invalid_token":
        long_r["verdict"] = "unearned_duration"

    baseline = short["learning_update"]["post_param_hash"]
    if variant == "neg_wrong_baseline":
        # Deletion measured against the untrained base instead of the
        # short-horizon checkpoint.
        baseline = f"sha256:{sha256_bytes(b'untrained-base')}"
    deletion = _c11_deletion_receipt(
        baseline, strip_arm_execution=(variant == "neg_arm_fabricated"))

    for key, obj in (("short", short), ("medium", medium),
                     ("long", long_r), ("deletion", deletion)):
        write_json(os.path.join(root, _C11_RECEIPT_DIR_REL, _C11_FILES[key]), obj)

    return root


# --- (16) ISSUE #97 cure 2: test_c3.py reads equal_within_tolerance value --
# 2026-07-04. Pre-cure, test_c3.py's dimension_present() only checked whether
# a budget-dimension KEY existed in the equal_budget block, never whether a
# measured equal_within_tolerance sub-field actually read True. The live
# repo's real receipt (d3-native-loop-20260703T034643Z-c3-wall-time-rerun.
# json) self-reports equal_within_tolerance: false with a ~7600x spread
# across arms (A=3e-06s, C=0.022839s) and was STILL scored GREEN pre-cure.
# Fixtures isolate the tooth: POS's wall_time dimension genuinely measures
# equal (within tolerance); NEG mirrors the real receipt's own shape.

def _c3_receipt(wall_time_equal_within_tolerance):
    return {
        "equal_budget": {
            "attempts_per_arm_per_task": 1,
            "cpu_gpu": "CPU only, no GPU, deterministic local parser per arm",
            "data_access": "same fresh row object for every arm",
            "verifier": "same target parser over external eval_script for every arm",
            "wall_time": {
                "declared": "each arm timed individually with perf_counter()",
                "equal_within_tolerance": wall_time_equal_within_tolerance,
                "equality_tolerance_seconds": 0.01,
                "measured_per_arm_total_seconds": (
                    {"A": 0.0500, "B": 0.0503, "C": 0.0498, "Deleted": 0.0501}
                    if wall_time_equal_within_tolerance
                    else {"A": 3e-06, "B": 0.003686, "C": 0.022839, "Deleted": 6e-06}
                ),
                "unit": "seconds",
            },
        },
        "arm_contract": {
            "A": "fixture: no native goal organ",
            "B": "fixture: fixed instruction-only extractor",
            "C": "fixture: resident-trained recursive policy",
            "Deleted": "fixture: C with recursive policy removed",
        },
        "reproducibility": {"seeds": {"A": 1, "B": 1, "C": 1, "Deleted": 1}},
    }


def build_cure2_c3(variant):
    """variant: 'pos' (equal_within_tolerance true) | 'neg' (false, mirrors
    the real live receipt's own measured-unequal shape)."""
    root = fresh_dir(os.path.join(FIXTURES_DIR, f"cure2_c3_{variant}"))
    write_readme(root, _CURE7_ISOLATION_NOTE)
    write_json_no_marker(
        os.path.join(root, "receipts", "ember-d3-native-loop",
                     "d3-native-loop-20990101T000000Z-fixture.json"),
        _c3_receipt(wall_time_equal_within_tolerance=(variant == "pos")),
    )
    return root


# --- (17) ISSUE #97 cure 3: test_surface2.py rejects non-live provenance ---
# 2026-07-04. The live execution tree's newest surface-2 receipt
# (receipts/ember-surface2-telemetry/2026-07-03T07-03-09Z/receipt.json)
# self-declares provenance="replay_of_completed_run", live_process_touched=
# false, gpu_used=false, events_rendered=0, render_evidence.telemetry_
# status_bar_rendered=false -- it replays a PAST completed C14 run's console
# log through the surface-2 capture harness, citing receipts/ember-c14-
# owned-run/* (a different receipt family) as its "source_run.sources".
# Pre-cure this satisfied all 3 CHK clauses and was scored GREEN for a
# "visible-LIVE" claim. Fixtures isolate the tooth against an otherwise
# fully-conforming receipt (fresh, has a steer verb, has token-delta>0).
#
# test_surface2.py reads EMBER_EXEC_ROOT (not EMBER_TOTALITY_ROOT) AND shells
# out to `git log -1 --format=%ct HEAD` on that root for the freshness
# check -- so each fixture root must be a real, minimal git repo with one
# commit, timestamped to sit within STALE_DAYS(=14) of the receipt's own ts.

def _git_init_single_commit(root, commit_iso_date):
    """Init a throwaway git repo at root with exactly one commit, dated
    commit_iso_date (e.g. '2099-01-01T06:00:00'), so test_surface2.py's
    `git log -1 --format=%ct HEAD` freshness check has real git history to
    read -- never a second copy of the timestamp the probe itself decides."""
    def run(*args):
        env = dict(os.environ)
        env["GIT_AUTHOR_NAME"] = "cure3-fixture"
        env["GIT_AUTHOR_EMAIL"] = "cure3-fixture@example.invalid"
        env["GIT_COMMITTER_NAME"] = "cure3-fixture"
        env["GIT_COMMITTER_EMAIL"] = "cure3-fixture@example.invalid"
        env["GIT_AUTHOR_DATE"] = commit_iso_date
        env["GIT_COMMITTER_DATE"] = commit_iso_date
        subprocess.run(["git", "-C", root, *args], check=True,
                        capture_output=True, text=True, env=env)
    run("init", "-q")
    marker = os.path.join(root, "README.txt")
    with open(marker, "w", encoding="utf-8") as fh:
        fh.write(_CURE7_ISOLATION_NOTE + "\n")
    run("add", "-A")
    run("commit", "-q", "-m", "cure3 fixture commit")


def _surface2_receipt(provenance, live_process_touched, telemetry_rendered,
                       events_rendered_count):
    return {
        "ts": "2099-01-01T04:00:00.000000Z",
        "surface": "C-SURFACE2",
        "provenance": provenance,
        "live_process_touched": live_process_touched,
        "gpu_used": False,
        "events_ingest_attempted": 6,
        "events_rendered": events_rendered_count,
        "render_evidence": {
            "expected_status_bar_label": "train r=fixture step 1",
            "telemetry_status_bar_rendered": telemetry_rendered,
        },
        "metrics_delta": 42,
    }


def build_cure3_surface2(variant):
    """variant: 'pos' (genuinely live+rendered) | 'neg' (mirrors the real
    2026-07-03T07-03-09Z replay receipt's exact self-declared field shape)."""
    root = fresh_dir(os.path.join(FIXTURES_DIR, f"cure3_surface2_{variant}"))
    tel_dir = os.path.join(root, "receipts", "ember-surface2-telemetry", "2099-01-01T04-00-00Z")
    os.makedirs(tel_dir, exist_ok=True)

    if variant == "pos":
        receipt = _surface2_receipt(provenance="live_capture",
                                     live_process_touched=True,
                                     telemetry_rendered=True,
                                     events_rendered_count=6)
    else:
        receipt = _surface2_receipt(provenance="replay_of_completed_run",
                                     live_process_touched=False,
                                     telemetry_rendered=False,
                                     events_rendered_count=0)
    write_json_no_marker(os.path.join(tel_dir, "receipt.json"), receipt)
    # sibling control-channel event -- satisfies clause (b), identical in
    # both fixtures, isolating ONLY the cure-3 tooth.
    write_json_no_marker(
        os.path.join(tel_dir, "finetune-control-event.json"),
        {"verb": "pause", "runId": "fixture-run", "ts": "2099-01-01T03:59:00Z",
         "metrics_delta": 42},
    )

    _git_init_single_commit(root, "2099-01-02T00:00:00")
    return root


# --- (18) ISSUE #97 cure 4: test_c_organism.py schema-checks the cited ------
# artifact. 2026-07-04. The live board cited receipts/code-vs-docs/code-vs-
# docs-window-real-demo-since-epoch-anchor.json -- a code-vs-docs line-count
# manifest whose rows happen to mention filenames/prose containing
# "growth"/"ingest"/"governor"/"deletion" by coincidence -- because it sorts
# alphabetically BEFORE the real artifact (receipts/ember-c-organism/seed-
# graph-inspection-*.json) and won the keyword-only first-match `break`.
# Fixtures reproduce this EXACT shape: POS has both the decoy (sorting
# first) and the real schema-satisfying receipt -- must cite the REAL one,
# not the decoy. NEG has only the decoy -- no genuine artifact exists, so
# the row must be honestly RED (never fabricate a citation).

_C_ORGANISM_DECOY = {
    # [ISSUE #97 cure 4] mirrors the REAL decoy's own shape: a code-vs-docs
    # line-count manifest whose rows happen to mention a "seed-graph" doc
    # path plus growth/ingest/governor/deletion words, so it authentically
    # passes the pre-existing KEYWORD gates (SEED_GRAPH_MARKERS/MACHINERIES/
    # DELETION_MARKERS) -- proving the new schema check, not the old keyword
    # gate, is what rejects it.
    "rows": [
        {"path": "docs/audit/seed-graph-notes.md", "category": "documentation_receipt_spec",
         "added_lines": 12, "deleted_lines": 0},
        {"path": "src/ember/governance/scripts/governor.py", "category": "code", "added_lines": 5, "deleted_lines": 0},
        {"path": "docs/growth-notes.md", "category": "documentation_receipt_spec",
         "added_lines": 3, "deleted_lines": 0,
         "note": "discusses ingestion pipelines and deletion of stale rows"},
        {"path": "scripts/net2net_helper.py", "category": "code", "added_lines": 2, "deleted_lines": 0},
    ],
}


def _c_organism_real_receipt():
    return {
        "seed_graph": "pre_pretrain seed-graph inspection (fixture)",
        "machineries_present": {
            "ingestion": {"machinery_callable": True,
                          "interface_callable": "fixture.PackedShardLoader"},
            "growth": {"machinery_callable": True,
                       "interface_callable": "fixture.net2net_grow"},
            "portability": {"machinery_callable": True,
                             "interface_callable": "fixture.governor.device_capability"},
        },
        "deletion_sensitivity_summary": {
            "ingestion": {"active_n_windows": 5, "deleted_n_windows": 0,
                          "deleted_error_class": "ValueError"},
            "growth": {"active_param_delta": 2506752, "deleted_param_delta": 0,
                       "deleted_error_class": "TypeError"},
            "portability": {"active_devices_adapted": 4, "deleted_devices_adapted": 0,
                             "deleted_error_class": "AttributeError"},
        },
        "invalid_tokens_present": [],
    }


def build_cure4_c_organism(variant):
    """variant: 'pos' (decoy + real receipt both present, decoy sorts first)
    | 'neg' (decoy only -- no genuine artifact exists anywhere)."""
    root = fresh_dir(os.path.join(FIXTURES_DIR, f"cure4_organism_{variant}"))
    write_readme(root, _CURE7_ISOLATION_NOTE)
    write_json_no_marker(
        os.path.join(root, "receipts", "code-vs-docs", "decoy-manifest.json"),
        _C_ORGANISM_DECOY,
    )
    if variant == "pos":
        write_json_no_marker(
            os.path.join(root, "receipts", "ember-c-organism",
                         "seed-graph-inspection-fixture.json"),
            _c_organism_real_receipt(),
        )
    return root


# --- (19) ISSUE #97 cure 5: test_c_legib.py excluded-dirs gains tooling ----
# artifacts. 2026-07-04. The board flapped RED->GREEN 3m15s apart when a
# `.pytest_cache/` directory materialized at repo root mid-session (an
# unrelated pytest run elsewhere in the same tree) and the pre-cure
# EXCLUDED_DIRS={".git"} treated it as a real, must-be-mapped working
# directory. Fixtures isolate the tooth: POS has a stray `.pytest_cache/`
# present (must NOT cause RED); NEG has a GENUINELY unmapped real working
# directory instead (must still correctly cause RED, proving the exclusion
# is scoped to tooling caches only, never a blanket bypass).

_C_LEGIB_AGENTS_MD = """# AGENTS (fixture)

## Repo map

| dir | purpose | type |
|-----|---------|------|
| `docs/` | fixture docs | docs |
| `scripts/` | fixture scripts | code |
| `receipts/` | fixture receipts | data |
"""

def build_cure5_c_legib(variant):
    """variant: 'pos' (stray .pytest_cache/, no genuine unmapped dir) |
    'neg' (a genuinely unmapped real working dir alongside the same stray
    tooling cache)."""
    if variant not in {"pos", "neg"}:
        raise ValueError(f"unsupported C-LEGIB fixture variant: {variant!r}")
    root = pinned_fixture_root(
        f"cure5_legib_{variant}",
        (os.path.join("scripts", "check_goal_citations.py"),),
    )

    for generated_name in ("docs", "receipts", ".pytest_cache", "unmapped_real_dir"):
        generated_path = os.path.join(root, generated_name)
        if os.path.isdir(generated_path):
            shutil.rmtree(generated_path, onerror=_rmtree_onerror)
        elif os.path.exists(generated_path):
            os.remove(generated_path)

    with open(os.path.join(root, "AGENTS.md"), "w", encoding="utf-8") as fh:
        fh.write(_C_LEGIB_AGENTS_MD)
    os.makedirs(os.path.join(root, "docs"), exist_ok=True)

    write_json_no_marker(
        os.path.join(root, "receipts", "cold-read-reprobe", "cure5-fixture-20990101T000000Z.json"),
        {"verdict": "PASS", "failures": []},
    )

    # Stray auto-generated tooling cache -- present in BOTH fixtures,
    # isolating ONLY the genuine-vs-tooling-cache tooth.
    os.makedirs(os.path.join(root, ".pytest_cache"), exist_ok=True)
    with open(os.path.join(root, ".pytest_cache", "README.md"), "w", encoding="utf-8") as fh:
        fh.write("fixture: auto-generated pytest cache placeholder\n")

    if variant == "neg":
        # A REAL working directory the entry map genuinely never mapped.
        os.makedirs(os.path.join(root, "unmapped_real_dir"), exist_ok=True)
        with open(os.path.join(root, "unmapped_real_dir", "placeholder.txt"), "w", encoding="utf-8") as fh:
            fh.write("fixture: a genuine working dir with no entry-map row\n")

    return root


# --- (20) ISSUE #97 cure 6: test_c_ind.py directory+provenance binding -----
# 2026-07-04. Discovery was receipt_class-field-keyed with NO directory or
# provenance binding: ANY *.json anywhere under receipts/ could self-declare
# "receipt_class": "IND-1" (or any class) and be accepted as real evidence,
# even sitting in a directory wholly unrelated to operator-independence and
# carrying none of the producer-identity fields every genuine IND-1/IND-3
# receipt in this repo's own corpus always carries. Fixture reuses the
# EXISTING build_c_ind() conforming base (already proven GREEN/RED for the
# fail-closed [A] script-authorship control, hardening #9) and, for the NEG
# case, additionally strips the genuine IND-1 receipt and substitutes ONLY a
# shape-complete IND-1 self-declaration sitting in an unrelated directory
# with no producer field and no "ind" token anywhere in its own path --
# pre-cure this alone would have satisfied IND-1; post-cure it must be
# rejected at discovery, leaving IND-1 genuinely unsatisfied.

def build_cure6_c_ind(variant):
    """variant: 'pos' (the standard fully-conforming base, unmodified -- no
    regression check) | 'neg' (IND-1's real receipt replaced by a shape-
    complete self-declaration sitting in an unbound, unrelated directory)."""
    if variant == "pos":
        pos_root, _neg_root = build_c_ind()
        return pos_root

    root = fresh_dir(os.path.join(FIXTURES_DIR, "cure6_ind_neg"))
    ind_dir = _c_ind_write_shared_fixture(root)
    # _c_ind_write_shared_fixture() already wrote a genuine, fully-conforming
    # IND-1 receipt at this exact path -- REMOVE it, leaving only the
    # unbound decoy below to stand (alone) for class 1.
    os.remove(os.path.join(ind_dir, "ind1-interact-20990101T000000Z.json"))

    # The unbound decoy: same shape-complete fields (would satisfy
    # _validate_ind1 on content alone), but sitting under a directory with
    # NO "ind" token anywhere in its own relative path, and carrying NONE of
    # the real corpus's producer-identity fields.
    write_json_no_marker(
        os.path.join(root, "receipts", "totally-unrelated-family", "sneaky-claim.json"),
        {
            "receipt_class": "IND-1",
            "documented_boot_command": "ember-cli --interactive (decoy)",
            "doc_pointer": "docs/operator/interact.md",
            "rendered_frame_evidence": {"screen_capture_path": "decoy-frame.png", "prompt_turn_rendered": True},
            "clean_exit": True,
            "matrix_complete": True,
            "matrix_missing": [],
        },
    )
    return root


# --- (21) ISSUE #95 C-LADM: ledger admission integrity, initial pos/neg -----
# coverage (gh issue #95/#102, named defect from the pubgate gate verdict:
# the frozen contract required these two RED-then-GREEN pairs delivered as
# chk_controls cases, not a standalone scratchpad proof). Two independent
# pairs: (a) an inadmissible row -- dangling receipt + no matched control --
# smuggled into an otherwise-clean sandbox ledger copy; (b) a non-seed row
# with `receipt` entirely absent (the documented seed-origin exception must
# not over-suppress a genuine non-seed violation).

_C_LADM_ISOLATION_NOTE = (
    "ISSUE-95/102 C-LADM CHK CONTROL FIXTURE -- synthetic sandbox ledger copy, "
    "NOT the real ledger/episodes.jsonl or ledger/control_pool.jsonl; must "
    "never be treated as real ledger data outside chk_controls/fixtures/."
)

# The exact dependency chain test_c_ladm.py's R5 dual-source check shells out
# to (src/ember/governance/scripts/ledger_dedup.py --backfill) -- copied verbatim from the live
# tree (never hand-duplicated) so each fixture root's own subprocess
# invocation resolves precisely as it does live. v_compare.py is copied for
# the R2 verifier-instrument-presence check.
_C_LADM_SUPPORT_FILES = [
    "v_compare.py",
    "ledger_dedup.py",
    "receipt_write.py",
    "receipt_check.py",
    "fp13_concentration.py",
    "fp10_idiom.py",
    "fp6_provenance.py",
]


def _c_ladm_copy_scripts_support(root):
    dst_dir = os.path.join(root, "scripts")
    os.makedirs(dst_dir, exist_ok=True)
    for name in _C_LADM_SUPPORT_FILES:
        shutil.copyfile(os.path.join(REPO_ROOT, "scripts", name), os.path.join(dst_dir, name))


_C_LADM_BASE_EPISODES = [
    {"key": "seedtask:1:aaa", "task": "seedtask:1", "src": "fixture", "verified": True,
     "ts": "20260610T000000Z", "origin": "seed-import"},  # no receipt -- seed exception
    {"key": "fixturetask:1:bbb", "task": "fixturetask:1", "src": "fixture", "verified": True,
     "ts": "20260704T000000Z", "origin": "Qwen/Fixture-Model", "sampler": "Qwen/Fixture-Model",
     "receipt": "fixture-w1-20260704T000000Z.json"},
]
_C_LADM_BASE_CONTROL = [
    {"key": "fixturetask:1:ctrl:ccc", "task": "fixturetask:1", "src": "fixture", "verified": False,
     "ts": "20260704T000000Z", "origin": "seed-control"},
]


def _c_ladm_base_sandbox(name):
    """A clean, individually-admissible minimal ledger (1 seed row exempted
    by the documented-absence exception, 1 non-seed row with a resolvable
    receipt and a matched control) -- the shared starting point both pairs
    add exactly one violation onto."""
    root = fresh_dir(os.path.join(FIXTURES_DIR, name))
    write_readme(root, _C_LADM_ISOLATION_NOTE)
    _c_ladm_copy_scripts_support(root)
    write_json_no_marker(
        os.path.join(root, "receipts", "t3-seed-20260610T021308Z.json"),
        {"note": "fixture seed blanket receipt, not real"},
    )
    write_json_no_marker(
        os.path.join(root, "receipts", "fixture-w1-20260704T000000Z.json"),
        {"note": "fixture receipt, not real"},
    )
    return root


def build_c_ladm_smuggled(variant):
    """Pair 1: variant 'pos' (clean base, no smuggled row) | 'neg' (one
    inadmissible row smuggled in: non-seed origin, receipt names a file that
    does not exist, task has zero matched-control rows)."""
    root = _c_ladm_base_sandbox(f"c_ladm_smuggled_{variant}")
    episodes = list(_C_LADM_BASE_EPISODES)
    if variant == "neg":
        episodes.append({
            "key": "smuggled:1:zzz", "task": "smuggled:1", "src": "fixture",
            "verified": True, "ts": "20260704T000000Z", "origin": "Qwen/Fixture-Model",
            "receipt": "does-not-exist-20260704T000000Z.json",
        })
    write_jsonl(os.path.join(root, "ledger", "episodes.jsonl"), episodes)
    write_jsonl(os.path.join(root, "ledger", "control_pool.jsonl"), _C_LADM_BASE_CONTROL)
    return root


def build_c_ladm_unreceipted(variant):
    """Pair 2: variant 'pos' (clean base) | 'neg' (a non-seed row with
    `receipt` entirely absent -- the documented seed-origin exception must
    NOT over-suppress this)."""
    root = _c_ladm_base_sandbox(f"c_ladm_unreceipted_{variant}")
    episodes = list(_C_LADM_BASE_EPISODES)
    if variant == "neg":
        episodes.append({
            "key": "unreceipted:1:yyy", "task": "fixturetask:1", "src": "fixture",
            "verified": True, "ts": "20260704T000000Z", "origin": "Qwen/Fixture-Model",
        })
    write_jsonl(os.path.join(root, "ledger", "episodes.jsonl"), episodes)
    write_jsonl(os.path.join(root, "ledger", "control_pool.jsonl"), _C_LADM_BASE_CONTROL)
    return root


# --- (22) C-AUTO: autonomy-ladder-state faithfulness (gh issue #104) ---------
# Probe: every claimed rung has K>=5 consecutive windows with resolvable receipts,
# strictly-increasing timestamps, and rung-specific provenance fields ember-
# attributed; reversion log entries resolve; current_rung matches highest claimed
# (or null when none claimed). Zero claimed rungs = GREEN "no rung claimed (honest)".
# Fixtures isolate individual RED failure modes: unreceipted claim, dangling window
# receipt ref, provenance field absent, state/claim mismatch. All POS variants
# must GREEN.

_C_AUTO_ISOLATION_NOTE = (
    "LANE-14 CHK CONTROL FIXTURE (gh issue #104, C-AUTO autonomy-ladder probe) -- "
    "synthetic ladder state + receipts for fixture verification only; must never "
    "be treated as a real autonomy ladder if it leaks into a real board scan."
)


def build_c_auto_base():
    """Shared base for all C-AUTO variants: honest zero-claim state that GREEN.
    Returns a fixture root already configured for GREEN with no claimed rungs."""
    root = fresh_dir(os.path.join(FIXTURES_DIR, "c_auto_base"))
    write_readme(root, _C_AUTO_ISOLATION_NOTE)

    # Write the honest zero-claim canonical autonomy ladder state.
    state = {
        "schema": "autonomy-ladder-state/v1",
        "contract": "docs/domains/governance/spec/autonomy-relinquishment-ladder-v1.md",
        "current_rung": None,
        "rungs": {
            "R0": {"status": "IN_BUILD", "claimed": False, "windows": []},
            "R1": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R2": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R3": {"status": "BLOCKED_ON_C_E2B", "claimed": False, "windows": []},
            "R4": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R5": {"status": "BLOCKED_ON_ISSUE_91", "claimed": False, "windows": []},
        },
        "reversion_log": [],
        "promotion_rule": "K=5 consecutive clean receipted windows per rung; claim itself is a receipt under receipts/autonomy-ladder/",
        "safety_floor": "operator escalation set + governor caps + kill-discipline NEVER transfer",
    }
    write_json_no_marker(os.path.join(root, "docs/domains/governance/authority/autonomy-ladder-state.json"), state)

    # Write the contract file so the probe can resolve it.
    contract_path = os.path.join(root, "docs", "spec", "autonomy-relinquishment-ladder-v1.md")
    os.makedirs(os.path.dirname(contract_path), exist_ok=True)
    with open(contract_path, "w", encoding="utf-8") as fh:
        fh.write("# Autonomy-relinquishment ladder v1 (fixture)\n\nFixture contract document.\n")

    return root


def build_c_auto_unreceipted_claim():
    """NEG: claimed rung with no claim receipt found under receipts/autonomy-ladder/."""
    root = fresh_dir(os.path.join(FIXTURES_DIR, "c_auto_unreceipted_claim"))
    write_readme(root, _C_AUTO_ISOLATION_NOTE)

    # Write state with R0 claimed but no claim receipt.
    state = {
        "schema": "autonomy-ladder-state/v1",
        "contract": "docs/domains/governance/spec/autonomy-relinquishment-ladder-v1.md",
        "current_rung": "R0",
        "rungs": {
            "R0": {
                "status": "IN_BUILD",
                "claimed": True,
                "windows": [
                    "R0-window-20990101T000000Z.json",
                    "R0-window-20990101T001000Z.json",
                    "R0-window-20990101T002000Z.json",
                    "R0-window-20990101T003000Z.json",
                    "R0-window-20990101T004000Z.json",
                ]
            },
            "R1": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R2": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R3": {"status": "BLOCKED_ON_C_E2B", "claimed": False, "windows": []},
            "R4": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R5": {"status": "BLOCKED_ON_ISSUE_91", "claimed": False, "windows": []},
        },
        "reversion_log": [],
        "promotion_rule": "K=5 consecutive clean receipted windows per rung; claim itself is a receipt under receipts/autonomy-ladder/",
        "safety_floor": "operator escalation set + governor caps + kill-discipline NEVER transfer",
    }
    write_json_no_marker(os.path.join(root, "docs/domains/governance/authority/autonomy-ladder-state.json"), state)

    # Write contract.
    contract_path = os.path.join(root, "docs", "spec", "autonomy-relinquishment-ladder-v1.md")
    os.makedirs(os.path.dirname(contract_path), exist_ok=True)
    with open(contract_path, "w", encoding="utf-8") as fh:
        fh.write("# Autonomy-relinquishment ladder v1 (fixture)\n\nFixture contract document.\n")

    # Write 5 window receipts but NO claim receipt -- isolates the unreceipted-claim tooth.
    receipts_dir = os.path.join(root, "receipts", "autonomy-ladder")
    for i, ts in enumerate([
        "20990101T000000Z", "20990101T001000Z", "20990101T002000Z",
        "20990101T003000Z", "20990101T004000Z"
    ]):
        write_json_no_marker(
            os.path.join(receipts_dir, f"R0-window-{ts}.json"),
            {"ts": ts, "rung": "R0", "window": i}
        )

    return root


def build_c_auto_dangling_window():
    """NEG: claimed rung with window receipt ref that does not resolve on disk."""
    root = fresh_dir(os.path.join(FIXTURES_DIR, "c_auto_dangling_window"))
    write_readme(root, _C_AUTO_ISOLATION_NOTE)

    # Write state with R0 claimed; one window ref does not exist.
    state = {
        "schema": "autonomy-ladder-state/v1",
        "contract": "docs/domains/governance/spec/autonomy-relinquishment-ladder-v1.md",
        "current_rung": "R0",
        "rungs": {
            "R0": {
                "status": "IN_BUILD",
                "claimed": True,
                "windows": [
                    "R0-window-20990101T000000Z.json",
                    "R0-window-20990101T001000Z.json",
                    "does-not-exist.json",  # This one dangles.
                    "R0-window-20990101T003000Z.json",
                    "R0-window-20990101T004000Z.json",
                ]
            },
            "R1": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R2": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R3": {"status": "BLOCKED_ON_C_E2B", "claimed": False, "windows": []},
            "R4": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R5": {"status": "BLOCKED_ON_ISSUE_91", "claimed": False, "windows": []},
        },
        "reversion_log": [],
        "promotion_rule": "K=5 consecutive clean receipted windows per rung; claim itself is a receipt under receipts/autonomy-ladder/",
        "safety_floor": "operator escalation set + governor caps + kill-discipline NEVER transfer",
    }
    write_json_no_marker(os.path.join(root, "docs/domains/governance/authority/autonomy-ladder-state.json"), state)

    # Write contract.
    contract_path = os.path.join(root, "docs", "spec", "autonomy-relinquishment-ladder-v1.md")
    os.makedirs(os.path.dirname(contract_path), exist_ok=True)
    with open(contract_path, "w", encoding="utf-8") as fh:
        fh.write("# Autonomy-relinquishment ladder v1 (fixture)\n\nFixture contract document.\n")

    # Write most window receipts; deliberately omit the "does-not-exist.json" one.
    receipts_dir = os.path.join(root, "receipts", "autonomy-ladder")
    for i, ts in enumerate([
        "20990101T000000Z", "20990101T001000Z",
        "20990101T003000Z", "20990101T004000Z"
    ]):
        write_json_no_marker(
            os.path.join(receipts_dir, f"R0-window-{ts}.json"),
            {"ts": ts, "rung": "R0", "window": i}
        )

    # Write claim receipt to satisfy that part.
    write_json_no_marker(
        os.path.join(receipts_dir, "R0-claim-20990101T000000Z.json"),
        {"ts": "20990101T000000Z", "rung": "R0", "claim": True}
    )

    return root


def build_c_auto_missing_provenance():
    """NEG: claimed rung's window receipt missing the required provenance field."""
    root = fresh_dir(os.path.join(FIXTURES_DIR, "c_auto_missing_provenance"))
    write_readme(root, _C_AUTO_ISOLATION_NOTE)

    # Write state with R1 claimed (requires scheduler_provenance field).
    state = {
        "schema": "autonomy-ladder-state/v1",
        "contract": "docs/domains/governance/spec/autonomy-relinquishment-ladder-v1.md",
        "current_rung": "R1",
        "rungs": {
            "R0": {"status": "IN_BUILD", "claimed": False, "windows": []},
            "R1": {
                "status": "NOT_STARTED",
                "claimed": True,
                "windows": [
                    "R1-window-20990101T000000Z.json",
                    "R1-window-20990101T001000Z.json",
                    "R1-window-20990101T002000Z.json",
                    "R1-window-20990101T003000Z.json",
                    "R1-window-20990101T004000Z.json",
                ]
            },
            "R2": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R3": {"status": "BLOCKED_ON_C_E2B", "claimed": False, "windows": []},
            "R4": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R5": {"status": "BLOCKED_ON_ISSUE_91", "claimed": False, "windows": []},
        },
        "reversion_log": [],
        "promotion_rule": "K=5 consecutive clean receipted windows per rung; claim itself is a receipt under receipts/autonomy-ladder/",
        "safety_floor": "operator escalation set + governor caps + kill-discipline NEVER transfer",
    }
    write_json_no_marker(os.path.join(root, "docs/domains/governance/authority/autonomy-ladder-state.json"), state)

    # Write contract.
    contract_path = os.path.join(root, "docs", "spec", "autonomy-relinquishment-ladder-v1.md")
    os.makedirs(os.path.dirname(contract_path), exist_ok=True)
    with open(contract_path, "w", encoding="utf-8") as fh:
        fh.write("# Autonomy-relinquishment ladder v1 (fixture)\n\nFixture contract document.\n")

    # Write window receipts WITHOUT the required scheduler_provenance field.
    receipts_dir = os.path.join(root, "receipts", "autonomy-ladder")
    for i, ts in enumerate([
        "20990101T000000Z", "20990101T001000Z", "20990101T002000Z",
        "20990101T003000Z", "20990101T004000Z"
    ]):
        write_json_no_marker(
            os.path.join(receipts_dir, f"R1-window-{ts}.json"),
            {"ts": ts, "rung": "R1", "window": i}
            # NOTE: deliberately omit scheduler_provenance field
        )

    # Write claim receipt.
    write_json_no_marker(
        os.path.join(receipts_dir, "R1-claim-20990101T000000Z.json"),
        {"ts": "20990101T000000Z", "rung": "R1", "claim": True}
    )

    return root


def build_c_auto_state_claim_mismatch():
    """NEG: current_rung does not match the highest claimed rung."""
    root = fresh_dir(os.path.join(FIXTURES_DIR, "c_auto_state_claim_mismatch"))
    write_readme(root, _C_AUTO_ISOLATION_NOTE)

    # Write state with R1 claimed but current_rung set to R0.
    state = {
        "schema": "autonomy-ladder-state/v1",
        "contract": "docs/domains/governance/spec/autonomy-relinquishment-ladder-v1.md",
        "current_rung": "R0",  # Mismatch: should be R1.
        "rungs": {
            "R0": {"status": "IN_BUILD", "claimed": False, "windows": []},
            "R1": {
                "status": "NOT_STARTED",
                "claimed": True,
                "windows": [
                    "R1-window-20990101T000000Z.json",
                    "R1-window-20990101T001000Z.json",
                    "R1-window-20990101T002000Z.json",
                    "R1-window-20990101T003000Z.json",
                    "R1-window-20990101T004000Z.json",
                ]
            },
            "R2": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R3": {"status": "BLOCKED_ON_C_E2B", "claimed": False, "windows": []},
            "R4": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R5": {"status": "BLOCKED_ON_ISSUE_91", "claimed": False, "windows": []},
        },
        "reversion_log": [],
        "promotion_rule": "K=5 consecutive clean receipted windows per rung; claim itself is a receipt under receipts/autonomy-ladder/",
        "safety_floor": "operator escalation set + governor caps + kill-discipline NEVER transfer",
    }
    write_json_no_marker(os.path.join(root, "docs/domains/governance/authority/autonomy-ladder-state.json"), state)

    # Write contract.
    contract_path = os.path.join(root, "docs", "spec", "autonomy-relinquishment-ladder-v1.md")
    os.makedirs(os.path.dirname(contract_path), exist_ok=True)
    with open(contract_path, "w", encoding="utf-8") as fh:
        fh.write("# Autonomy-relinquishment ladder v1 (fixture)\n\nFixture contract document.\n")

    # Write window receipts with scheduler_provenance (R1 requires it).
    receipts_dir = os.path.join(root, "receipts", "autonomy-ladder")
    for i, ts in enumerate([
        "20990101T000000Z", "20990101T001000Z", "20990101T002000Z",
        "20990101T003000Z", "20990101T004000Z"
    ]):
        write_json_no_marker(
            os.path.join(receipts_dir, f"R1-window-{ts}.json"),
            {"ts": ts, "rung": "R1", "window": i, "scheduler_provenance": "ember-scheduler"}
        )

    # Write claim receipt.
    write_json_no_marker(
        os.path.join(receipts_dir, "R1-claim-20990101T000000Z.json"),
        {"ts": "20990101T000000Z", "rung": "R1", "claim": True}
    )

    return root


# --- (23) C-AUTO CURES: defect 1-3 (missing receipts dir, empty provenance, stale reversion) --

def build_c_auto_receipts_dir_absent():
    """Cure Defect 1 (crash path): claimed rung, receipts/autonomy-ladder/ dir entirely absent.
    NEG: os.listdir(receipts_dir) would have crashed with FileNotFoundError; now guarded."""
    root = fresh_dir(os.path.join(FIXTURES_DIR, "c_auto_receipts_dir_absent"))
    write_readme(root, _C_AUTO_ISOLATION_NOTE)

    # Write state with R0 claimed.
    state = {
        "schema": "autonomy-ladder-state/v1",
        "contract": "docs/domains/governance/spec/autonomy-relinquishment-ladder-v1.md",
        "current_rung": "R0",
        "rungs": {
            "R0": {
                "status": "IN_BUILD",
                "claimed": True,
                "windows": [
                    "R0-window-20990101T000000Z.json",
                    "R0-window-20990101T001000Z.json",
                    "R0-window-20990101T002000Z.json",
                    "R0-window-20990101T003000Z.json",
                    "R0-window-20990101T004000Z.json",
                ]
            },
            "R1": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R2": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R3": {"status": "BLOCKED_ON_C_E2B", "claimed": False, "windows": []},
            "R4": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R5": {"status": "BLOCKED_ON_ISSUE_91", "claimed": False, "windows": []},
        },
        "reversion_log": [],
        "promotion_rule": "K=5 consecutive clean receipted windows per rung; claim itself is a receipt under receipts/autonomy-ladder/",
        "safety_floor": "operator escalation set + governor caps + kill-discipline NEVER transfer",
    }
    write_json_no_marker(os.path.join(root, "docs/domains/governance/authority/autonomy-ladder-state.json"), state)

    # Write contract.
    contract_path = os.path.join(root, "docs", "spec", "autonomy-relinquishment-ladder-v1.md")
    os.makedirs(os.path.dirname(contract_path), exist_ok=True)
    with open(contract_path, "w", encoding="utf-8") as fh:
        fh.write("# Autonomy-relinquishment ladder v1 (fixture)\n\nFixture contract document.\n")

    # Deliberately do NOT create receipts/autonomy-ladder/ directory -- it's absent.

    return root


def build_c_auto_empty_provenance():
    """Cure Defect 2 (theater hole): window receipt with empty provenance field.
    NEG: `"scheduler_provenance": ""` is caught as empty/falsy and violates."""
    root = fresh_dir(os.path.join(FIXTURES_DIR, "c_auto_empty_provenance"))
    write_readme(root, _C_AUTO_ISOLATION_NOTE)

    # Write state with R1 claimed (requires scheduler_provenance).
    state = {
        "schema": "autonomy-ladder-state/v1",
        "contract": "docs/domains/governance/spec/autonomy-relinquishment-ladder-v1.md",
        "current_rung": "R1",
        "rungs": {
            "R0": {"status": "IN_BUILD", "claimed": False, "windows": []},
            "R1": {
                "status": "NOT_STARTED",
                "claimed": True,
                "windows": [
                    "R1-window-20990101T000000Z.json",
                    "R1-window-20990101T001000Z.json",
                    "R1-window-20990101T002000Z.json",
                    "R1-window-20990101T003000Z.json",
                    "R1-window-20990101T004000Z.json",
                ]
            },
            "R2": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R3": {"status": "BLOCKED_ON_C_E2B", "claimed": False, "windows": []},
            "R4": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R5": {"status": "BLOCKED_ON_ISSUE_91", "claimed": False, "windows": []},
        },
        "reversion_log": [],
        "promotion_rule": "K=5 consecutive clean receipted windows per rung; claim itself is a receipt under receipts/autonomy-ladder/",
        "safety_floor": "operator escalation set + governor caps + kill-discipline NEVER transfer",
    }
    write_json_no_marker(os.path.join(root, "docs/domains/governance/authority/autonomy-ladder-state.json"), state)

    # Write contract.
    contract_path = os.path.join(root, "docs", "spec", "autonomy-relinquishment-ladder-v1.md")
    os.makedirs(os.path.dirname(contract_path), exist_ok=True)
    with open(contract_path, "w", encoding="utf-8") as fh:
        fh.write("# Autonomy-relinquishment ladder v1 (fixture)\n\nFixture contract document.\n")

    # Write window receipts with EMPTY scheduler_provenance field.
    receipts_dir = os.path.join(root, "receipts", "autonomy-ladder")
    for i, ts in enumerate([
        "20990101T000000Z", "20990101T001000Z", "20990101T002000Z",
        "20990101T003000Z", "20990101T004000Z"
    ]):
        write_json_no_marker(
            os.path.join(receipts_dir, f"R1-window-{ts}.json"),
            {"ts": ts, "rung": "R1", "window": i, "scheduler_provenance": ""}
        )

    # Write claim receipt.
    write_json_no_marker(
        os.path.join(receipts_dir, "R1-claim-20990101T000000Z.json"),
        {"ts": "20990101T000000Z", "rung": "R1", "claim": True}
    )

    return root


def build_c_auto_stale_reversion_claim():
    """Cure Defect 3 (stale after reversion): claimed rung above reversion target,
    with claim receipt ts BEFORE the reversion ts (stale claim ignoring reversion).
    NEG: violation detected."""
    root = fresh_dir(os.path.join(FIXTURES_DIR, "c_auto_stale_reversion_claim"))
    write_readme(root, _C_AUTO_ISOLATION_NOTE)

    state = {
        "schema": "autonomy-ladder-state/v1",
        "contract": "docs/domains/governance/spec/autonomy-relinquishment-ladder-v1.md",
        "current_rung": "R1",
        "rungs": {
            "R0": {"status": "IN_BUILD", "claimed": False, "windows": []},
            "R1": {
                "status": "NOT_STARTED",
                "claimed": True,
                "windows": [
                    "R1-window-20990101T000000Z.json",
                    "R1-window-20990101T001000Z.json",
                    "R1-window-20990101T002000Z.json",
                    "R1-window-20990101T003000Z.json",
                    "R1-window-20990101T004000Z.json",
                ]
            },
            "R2": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R3": {"status": "BLOCKED_ON_C_E2B", "claimed": False, "windows": []},
            "R4": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R5": {"status": "BLOCKED_ON_ISSUE_91", "claimed": False, "windows": []},
        },
        "reversion_log": [
            {
                "ts": "20990101T002000Z",
                "target_rung": "R0",
                "incident_receipt": "receipts/autonomy-ladder/reversion-20990101T002000Z.json",
                "reason": "fixture reversion for testing stale-claim detection"
            }
        ],
        "promotion_rule": "K=5 consecutive clean receipted windows per rung; claim itself is a receipt under receipts/autonomy-ladder/",
        "safety_floor": "operator escalation set + governor caps + kill-discipline NEVER transfer",
    }
    write_json_no_marker(os.path.join(root, "docs/domains/governance/authority/autonomy-ladder-state.json"), state)

    contract_path = os.path.join(root, "docs", "spec", "autonomy-relinquishment-ladder-v1.md")
    os.makedirs(os.path.dirname(contract_path), exist_ok=True)
    with open(contract_path, "w", encoding="utf-8") as fh:
        fh.write("# Autonomy-relinquishment ladder v1 (fixture)\n\nFixture contract document.\n")

    receipts_dir = os.path.join(root, "receipts", "autonomy-ladder")
    for i, ts in enumerate([
        "20990101T000000Z", "20990101T001000Z", "20990101T002000Z",
        "20990101T003000Z", "20990101T004000Z"
    ]):
        write_json_no_marker(
            os.path.join(receipts_dir, f"R1-window-{ts}.json"),
            {"ts": ts, "rung": "R1", "window": i, "scheduler_provenance": "ember-scheduler"}
        )

    write_json_no_marker(
        os.path.join(receipts_dir, "R1-claim-20990101T001000Z.json"),
        {"ts": "20990101T001000Z", "rung": "R1", "claim": True}
    )

    write_json_no_marker(
        os.path.join(receipts_dir, "reversion-20990101T002000Z.json"),
        {"ts": "20990101T002000Z", "target_rung": "R0", "incident": "fixture"}
    )

    return root


def build_c_auto_fresh_reversion_climb():
    """Build the production-shaped v2 positive re-climb fixture."""
    return build_c_auto_v2_fixture(
        fixtures_dir=FIXTURES_DIR,
        repo_root=REPO_ROOT,
        isolation_note=_C_AUTO_ISOLATION_NOTE,
        fresh_dir=fresh_dir,
        write_readme=write_readme,
        write_json_no_marker=write_json_no_marker,
    )


# --- end C-AUTO section -----


def preflight_check_probe_files():
    """Preflight: assert all referenced control probe files exist before suite starts.

    If any referenced probe file is missing, fail loud at t=0 with a list of all
    missing files, rather than crashing mid-suite.
    """
    # Hardcoded list of all probe files referenced in record() calls below.
    # Maintain this list in sync with the record() calls in main().
    EXPECTED_PROBES = [
        "test_c_tally.py",
        "test_c_neg1.py",
        "test_c1.py",
        "test_c0.py",
        "test_c4.py",
        "test_c5.py",
        "test_c3.py",
        "test_c7.py",
        "test_c2.py",
        "src/ember/governance/scripts/ember_totality/test_c_obs.py",
        "test_c11.py",
        "test_c_scale.py",
        "test_c_e2b.py",
        "test_c14.py",
        "test_c_fed.py",
        "test_c_ind.py",
        "test_c_legib.py",
        "test_c_manifest.py",
        "test_c_organism.py",
        "test_c_port.py",
        "test_c_ladm.py",
        "test_c_auto.py",
    ]

    missing_files = []
    for probe_name in EXPECTED_PROBES:
        probe_path = os.path.join(REPO_ROOT, probe_name) if "/" in probe_name else os.path.join(PROBES_DIR, probe_name)
        if not os.path.isfile(probe_path):
            missing_files.append(probe_name)

    if missing_files:
        print("PREFLIGHT FAIL: CHK control suite references missing probe files at t=0:")
        for f in sorted(missing_files):
            print(f"  {f}")
        sys.exit(1)


_CHK_RECEIPT_RE = re.compile(r"^chk-controls-(\d{8}T\d{6}Z)\.json$")


def _sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _list_chk_receipts(receipts_dir):
    """Sorted (name, path) tuples for every chk-controls-*.json receipt in
    receipts_dir, ordered by the canonical timestamp in the filename."""
    if not os.path.isdir(receipts_dir):
        return []
    items = []
    for name in os.listdir(receipts_dir):
        m = _CHK_RECEIPT_RE.match(name)
        if m:
            items.append((m.group(1), name, os.path.join(receipts_dir, name)))
    items.sort(key=lambda x: x[0])
    return [(name, path) for _, name, path in items]


def _chk_chain_verify(receipts_dir):
    """Chain-continuity check for this driver's OWN chk-controls-*.json
    receipts (a genuinely separate artifact family from the totality
    board's receipts-totality/ chain -- never touches or reuses that
    directory or filename pattern). Mirrors receipt_chain_verify.py's
    chain_ok/chain_break contract: walks every receipt currently in
    receipts_dir (including ones written by earlier runs) and reports
    chain_ok=False on the FIRST detected break, so a pre-existing broken
    chain blocks this run's finalization too (reviewer defect P1-second:
    a chain problem must never be silently absorbed)."""
    receipts_list = _list_chk_receipts(receipts_dir)
    breaks = []
    for idx, (name, path) in enumerate(receipts_list):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            breaks.append(f"{name}: cannot parse ({e})")
            continue
        prev_field = data.get("prev_totality_receipt_sha256")
        if prev_field is None:
            continue  # pre-chain epoch boundary, not a break
        if idx == 0:
            if prev_field != "0" * 64:
                breaks.append(f"{name}: first receipt must reference 0*64, got {prev_field[:16]}...")
            continue
        prev_name, prev_path = receipts_list[idx - 1]
        try:
            prev_actual = _sha256_file(prev_path)
        except OSError as e:
            breaks.append(f"{name}: cannot hash predecessor {prev_name}: {e}")
            continue
        if prev_field != prev_actual:
            breaks.append(
                f"{name}: prev sha mismatch against {prev_name} "
                f"(expected {prev_field[:16]}..., actual {prev_actual[:16]}...)"
            )
    chain_ok = not breaks
    detail = "; ".join(breaks) if breaks else f"{len(receipts_list)} receipt(s), chain intact"
    return {"chain_ok": chain_ok, "summary": {"details": detail}}


def _finalize_receipt(receipt_out_dir, results, controls_ok):
    """Write a hermetic, chain-linked chk-controls receipt to receipt_out_dir.

    Transactional / fail-closed (reviewer defect P1-second, the exact
    anti-pattern found in ember_totality_spec.py's own finalization: that
    driver writes its receipt, calls add_chain_verification_to_receipt,
    gets chain_ok=False back, and STILL leaves the file on disk and prints
    the board regardless -- a broken chain "publishes" exactly as if
    nothing were wrong). Here, on EITHER a final-write failure (unwritable
    destination) OR a chain-verification failure: the just-written bytes
    (if any made it to disk) are removed, NOTHING is printed claiming a
    receipt exists, and this function returns False so main() exits
    nonzero. Only a durably-written, chain-verified-GREEN receipt is ever
    allowed to survive and be reported.

    Returns True iff a receipt was durably written and chain-verified GREEN.
    """
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    receipt_name = f"chk-controls-{ts}.json"

    try:
        os.makedirs(receipt_out_dir, exist_ok=True)
    except OSError as e:
        print(f"RECEIPT FINALIZE FAILED: cannot create receipt directory {receipt_out_dir}: {e}")
        return False

    receipt_path = os.path.join(receipt_out_dir, receipt_name)

    prior = _list_chk_receipts(receipt_out_dir)
    try:
        prev_sha = _sha256_file(prior[-1][1]) if prior else ("0" * 64)
    except OSError as e:
        print(f"RECEIPT FINALIZE FAILED: cannot hash predecessor receipt: {e}")
        return False

    receipt = {
        "schema": "chk-controls/v1",
        "ts": ts,
        "controls_ok": controls_ok,
        "n_ok": sum(1 for r in results if r["ok"]),
        "n_total": len(results),
        "rows": [
            {
                "hardening": r["hardening"], "control": r["control"], "probe": r["probe"],
                "expected": r["expected"], "actual": r["actual"], "ok": r["ok"],
                "details": r.get("details", {}),
            }
            for r in results
        ],
        "prev_totality_receipt_sha256": prev_sha,
    }

    try:
        with open(receipt_path, "w", encoding="utf-8") as fh:
            json.dump(receipt, fh, indent=2)
            fh.write("\n")
    except OSError as e:
        print(f"RECEIPT FINALIZE FAILED: cannot write {receipt_path}: {e}")
        try:
            if os.path.isfile(receipt_path):
                os.remove(receipt_path)
        except OSError:
            pass
        return False

    chain = _chk_chain_verify(receipt_out_dir)
    if not chain["chain_ok"]:
        try:
            os.remove(receipt_path)
        except OSError:
            pass
        print(f"RECEIPT FINALIZE FAILED: chain verification broken -- {chain['summary']['details']}")
        return False

    print(f"receipt written: {receipt_path} (chain_ok=True)")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="lane-14 CHK control battery driver")
    ap.add_argument(
        "--receipt-out", default=None,
        help="Directory to write a hermetic, chain-linked chk-controls-<ts>.json "
             "receipt to (chain-links against any prior receipts already in that "
             "directory). Omit to skip receipt finalization entirely.",
    )
    args = ap.parse_args(argv)

    os.makedirs(FIXTURES_DIR, exist_ok=True)
    preflight_check_probe_files()

    tally_pos, tally_neg = build_c_tally()
    record("1 C-TALLY recompute-from-live-rows", "POS all-GREEN board", "test_c_tally.py", tally_pos, "GREEN")
    record("1 C-TALLY recompute-from-live-rows", "NEG not-all-green board + future pct=100 tally file", "test_c_tally.py", tally_neg, "RED")

    neg1_pos, neg1_neg = build_c_neg1()
    record("2 C(-1) verdict-linkage + all-decisive-claims", "POS all decisive claims zero-cost, one PASS-class", "test_c_neg1.py", neg1_pos, "GREEN")
    record("2 C(-1) verdict-linkage + all-decisive-claims", "NEG zero-cost BLOCKED packet (today's real bug)", "test_c_neg1.py", neg1_neg, "RED")

    c1_pos, c1_neg = build_c1()
    record("5 C1 hash-verify mandatory", "POS in-tree artifact, hash matches", "test_c1.py", c1_pos, "GREEN")
    record("5 C1 hash-verify mandatory", "NEG off-tree artifact (today's real scenario)", "test_c1.py", c1_neg, "RED")

    c4c5_pos, c4c5_neg = build_c4_c5()
    record("4 C4 artifact reachability + sample-recompute", "POS in-tree trace, hashes re-derive, scores recompute", "test_c4.py", c4c5_pos, "GREEN")
    record("4 C4 artifact reachability + sample-recompute", "NEG off-tree trace (today's real scenario)", "test_c4.py", c4c5_neg, "RED")
    record("4 C5 artifact reachability + sample-recompute", "POS in-tree trace, hashes re-derive, scores recompute", "test_c5.py", c4c5_pos, "GREEN")
    record("4 C5 artifact reachability + sample-recompute", "NEG off-tree trace (today's real scenario)", "test_c5.py", c4c5_neg, "RED")

    c7_pos, c7_neg = build_c7()
    record("3 C7 evidence-in-receipt", "POS numeric per-arm scores, degradation>0", "test_c7.py", c7_pos, "GREEN")
    record("3 C7 evidence-in-receipt", "NEG booleans-only receipt (today's real receipts)", "test_c7.py", c7_neg, "RED")

    c2_pos, c2_neg = build_c2()
    record("6 C2 git-anchor + non-self-labeled leak", "POS real winning receipt snapshot, unmodified", "test_c2.py", c2_pos, "GREEN")
    record("6 C2 git-anchor + non-self-labeled leak", "NEG verbatim gold leak, no marker-string used", "test_c2.py", c2_neg, "RED")

    c_obs_pos, c_obs_neg = build_c_obs()
    record("7 C-OBS evidence-surface scoping", "POS four conjuncts as receipts/ artifacts", "src/ember/governance/scripts/ember_totality/test_c_obs.py", c_obs_pos, "GREEN")
    record("7 C-OBS evidence-surface scoping", "NEG docs-only glowing prose, receipts/ absent (today's false-GREEN vector)", "src/ember/governance/scripts/ember_totality/test_c_obs.py", c_obs_neg, "RED")

    c_manifest_pos, c_manifest_neg = build_c_manifest()
    record("8 C-MANIFEST denominator regex + <20 floor", "POS 25 mixed-separator conditions, all 25 rowed", "test_c_manifest.py", c_manifest_pos, "GREEN")
    record("8 C-MANIFEST denominator regex + <20 floor", "NEG 25 mixed-separator conditions, only 10 double-dash rowed", "test_c_manifest.py", c_manifest_neg, "RED")

    c_ind_pos, c_ind_neg = build_c_ind()
    record("9 C-IND five receipt classes + fail-closed [A] script check", "POS five conforming classes + genuine operator attestation", "test_c_ind.py", c_ind_pos, "GREEN")
    record("9 C-IND five receipt classes + fail-closed [A] script check", "NEG assistant/script-authored attestation (spec-named control)", "test_c_ind.py", c_ind_neg, "RED")

    scale_pos, scale_neg = build_c_scale()
    record("10 C-SCALE ratio re-derivation + full CHK", "POS conforming apex receipt (synthetic far-future)", "test_c_scale.py", scale_pos, "GREEN")
    record("10 C-SCALE ratio re-derivation + full CHK", "NEG claimed ratio does not re-derive (memory-fit-class fake)", "test_c_scale.py", scale_neg, "RED")

    e2b_pos, e2b_neg = build_c_e2b()
    record("11 C-E2B paired-both-legs + frozen-before-verdict", "POS both legs surpass, matched budget, frozen protocol", "test_c_e2b.py", e2b_pos, "GREEN")
    record("11 C-E2B paired-both-legs + frozen-before-verdict", "NEG single-leg surpass (registry does-NOT-count)", "test_c_e2b.py", e2b_neg, "RED")

    ts_pos, ts_neg = build_c0_ts_authority()
    record("12 C0/C14 ts-authority (internal ts over filename)", "POS forward-named block internal-ts-precedes PASS -> PASS survives", "test_c0.py", ts_pos, "AUDIT-OK")
    record("12 C0/C14 ts-authority (internal ts over filename)", "NEG genuinely-later block -> PASS superseded", "test_c0.py", ts_neg, "AUDIT-INCIDENT")

    id_pos, id_neg = build_c14_identity_binding()
    record("13 C14 conjunct-3 harness-identity binding", "POS identity sha256 matches real observation receipt", "test_c14.py", id_pos, "GREEN")
    record("13 C14 conjunct-3 harness-identity binding", "NEG identity sha256 mismatched (different harness build)", "test_c14.py", id_neg, "RED")

    fed7_pos, fed7_neg = build_cure7_c_fed()
    record("14 ISSUE#97-cure7 meta-audit-family exclusion", "POS token only inside ember-totality-audit/ -> excluded", "test_c_fed.py", fed7_pos, "GREEN")
    record("14 ISSUE#97-cure7 meta-audit-family exclusion", "NEG token in a real non-audit receipt -> still caught", "test_c_fed.py", fed7_neg, "RED")

    port7_pos, port7_neg = build_cure7_c_port()
    record("14 ISSUE#97-cure7 meta-audit-family exclusion", "POS real candidate GREEN, later audit receipt not selected", "test_c_port.py", port7_pos, "GREEN")
    record("14 ISSUE#97-cure7 meta-audit-family exclusion", "NEG real 4090-only candidate still RED, audit receipt not selected", "test_c_port.py", port7_neg, "RED")

    _C11_LANE = "15 ISSUE#107 C11 experience-horizon contract"
    record(_C11_LANE, "POS short/medium/long + deletion, all 9 checks conform", "test_c11.py", build_c11_horizon("pos"), "GREEN")
    record(_C11_LANE, "NEG CHK-1 long horizon has FEWER novel problems than medium, only wall_seconds rises (clock_in_disguise)", "test_c11.py", build_c11_horizon("neg_ordering"), "RED")
    record(_C11_LANE, "NEG CHK-2 a repeated problem_id re-hashed as new experience (novelty_spoof)", "test_c11.py", build_c11_horizon("neg_duplicate_ids"), "RED")
    record(_C11_LANE, "NEG CHK-3 long post_param_hash identical to medium's (same checkpoint, nothing learned)", "test_c11.py", build_c11_horizon("neg_identical_checkpoint"), "RED")
    record(_C11_LANE, "NEG CHK-4 a gradient step cites a problem_id outside the horizon's novel set (steps not Merkle-bound to novelty)", "test_c11.py", build_c11_horizon("neg_merkle"), "RED")
    record(_C11_LANE, "NEG CHK-4 present-but-EMPTY gradient_steps still asserting a merkle_root (rev-107 B-2: empty is a failed claim, not an absent input)", "test_c11.py", build_c11_horizon("neg_empty_steps"), "RED")
    record(_C11_LANE, "NEG CHK-5 long held-out score equals medium's, no delta above the noise floor", "test_c11.py", build_c11_horizon("neg_noise_floor"), "RED")
    record(_C11_LANE, "NEG CHK-6 a held-out item_id is also a trained novel problem (contamination)", "test_c11.py", build_c11_horizon("neg_contamination"), "RED")
    record(_C11_LANE, "NEG CHK-7 a held-out row asserts passed with no execution block (fabricated_outcomes)", "test_c11.py", build_c11_horizon("neg_fabricated"), "RED")
    record(_C11_LANE, "NEG CHK-8 deletion measured against the untrained base, not the short-horizon checkpoint (deletion_uses_wrong_baseline)", "test_c11.py", build_c11_horizon("neg_wrong_baseline"), "RED")
    record(_C11_LANE, "NEG CHK-8 deletion arm rows assert pass counts with NO execution block (rev-107 B-1: the ablation was hand-typeable)", "test_c11.py", build_c11_horizon("neg_arm_fabricated"), "RED")
    record(_C11_LANE, "NEG CHK-9 a receipt stamps itself with the unearned_duration invalid-token", "test_c11.py", build_c11_horizon("neg_invalid_token"), "RED")

    c3_pos = build_cure2_c3("pos")
    record("16 ISSUE#97-cure2 C3 equal_within_tolerance value", "POS wall_time measured equal within tolerance", "test_c3.py", c3_pos, "GREEN")
    c3_neg = build_cure2_c3("neg")
    record("16 ISSUE#97-cure2 C3 equal_within_tolerance value", "NEG wall_time equal_within_tolerance=false (real 2026-07-04 receipt shape)", "test_c3.py", c3_neg, "RED")

    surf2_pos = build_cure3_surface2("pos")
    record("17 ISSUE#97-cure3 C-SURFACE2 non-live provenance", "POS genuinely live+rendered receipt", "test_surface2.py", surf2_pos, "GREEN", env_var="EMBER_EXEC_ROOT")
    surf2_neg = build_cure3_surface2("neg")
    record("17 ISSUE#97-cure3 C-SURFACE2 non-live provenance", "NEG replay_of_completed_run + unrendered (real 2026-07-03 receipt shape)", "test_surface2.py", surf2_neg, "RED", env_var="EMBER_EXEC_ROOT")

    organism_pos = build_cure4_c_organism("pos")
    record("18 ISSUE#97-cure4 C-ORGANISM schema-check cited artifact", "POS decoy manifest (sorts first) + real schema-satisfying receipt -> cites the real one", "test_c_organism.py", organism_pos, "GREEN")
    organism_neg = build_cure4_c_organism("neg")
    record("18 ISSUE#97-cure4 C-ORGANISM schema-check cited artifact", "NEG decoy only, no genuine artifact anywhere (real 2026-07-04 bug shape)", "test_c_organism.py", organism_neg, "RED")

    legib_pos = build_cure5_c_legib("pos")
    record("19 ISSUE#97-cure5 C-LEGIB tooling-artifact exclusion", "POS stray .pytest_cache/ present, no genuine unmapped dir -> stays GREEN", "test_c_legib.py", legib_pos, "GREEN")
    legib_neg = build_cure5_c_legib("neg")
    record("19 ISSUE#97-cure5 C-LEGIB tooling-artifact exclusion", "NEG genuine unmapped real dir alongside the same tooling cache -> still RED", "test_c_legib.py", legib_neg, "RED")

    ind6_pos = build_cure6_c_ind("pos")
    record("20 ISSUE#97-cure6 C-IND directory+provenance binding", "POS standard conforming base (all 5 classes bound+provenanced) -> GREEN, no regression", "test_c_ind.py", ind6_pos, "GREEN")
    ind6_neg = build_cure6_c_ind("neg")
    record("20 ISSUE#97-cure6 C-IND directory+provenance binding", "NEG genuine IND-1 replaced by shape-complete decoy in an unbound, unrelated dir -> IND-1 unsatisfied", "test_c_ind.py", ind6_neg, "RED")

    ladm_smuggled_pos = build_c_ladm_smuggled("pos")
    record("21 ISSUE#95 C-LADM ledger admission integrity", "POS clean minimal sandbox ledger, no smuggled row", "test_c_ladm.py", ladm_smuggled_pos, "GREEN")
    ladm_smuggled_neg = build_c_ladm_smuggled("neg")
    record("21 ISSUE#95 C-LADM ledger admission integrity", "NEG inadmissible row smuggled in (dangling receipt + no matched control) -> named RED", "test_c_ladm.py", ladm_smuggled_neg, "RED")

    ladm_unreceipted_pos = build_c_ladm_unreceipted("pos")
    record("21 ISSUE#95 C-LADM ledger admission integrity", "POS clean minimal sandbox ledger, no unreceipted row", "test_c_ladm.py", ladm_unreceipted_pos, "GREEN")
    ladm_unreceipted_neg = build_c_ladm_unreceipted("neg")
    record("21 ISSUE#95 C-LADM ledger admission integrity", "NEG non-seed row with receipt entirely absent -> seed exception must not over-suppress", "test_c_ladm.py", ladm_unreceipted_neg, "RED")

    auto_base = build_c_auto_base()
    record("22 C-AUTO autonomy-ladder-state faithfulness", "POS zero claims (honest baseline)", "test_c_auto.py", auto_base, "GREEN")

    auto_unreceipt = build_c_auto_unreceipted_claim()
    record("22 C-AUTO autonomy-ladder-state faithfulness", "NEG claimed rung with no claim receipt found", "test_c_auto.py", auto_unreceipt, "RED")

    auto_dangling = build_c_auto_dangling_window()
    record("22 C-AUTO autonomy-ladder-state faithfulness", "NEG window receipt ref does not resolve on disk", "test_c_auto.py", auto_dangling, "RED")

    auto_provenance = build_c_auto_missing_provenance()
    record("22 C-AUTO autonomy-ladder-state faithfulness", "NEG window receipt missing required provenance field", "test_c_auto.py", auto_provenance, "RED")

    auto_mismatch = build_c_auto_state_claim_mismatch()
    record("22 C-AUTO autonomy-ladder-state faithfulness", "NEG current_rung does not match highest claimed rung", "test_c_auto.py", auto_mismatch, "RED")

    auto_absent_dir = build_c_auto_receipts_dir_absent()
    record("22 C-AUTO CURE-1 receipts dir absent", "NEG claimed rung, receipts/autonomy-ladder/ dir entirely absent (crash path fixed)", "test_c_auto.py", auto_absent_dir, "RED")

    auto_empty_prov = build_c_auto_empty_provenance()
    record("22 C-AUTO CURE-2 empty provenance", "NEG window receipt with empty provenance field (theater hole fixed)", "test_c_auto.py", auto_empty_prov, "RED")

    auto_stale_rev = build_c_auto_stale_reversion_claim()
    record("22 C-AUTO CURE-3 stale reversion claim", "NEG claimed rung above reversion target with stale claim ts (before reversion ts)", "test_c_auto.py", auto_stale_rev, "RED")

    auto_fresh_rev = build_c_auto_fresh_reversion_climb()
    record("22 C-AUTO CURE-3 fresh reversion climb", "POS claimed rung above reversion target with fresh claim ts (after reversion ts, legitimate re-climb)", "test_c_auto.py", auto_fresh_rev, "GREEN")

    # --- gh #715 wiring (PR955 round-2 repair, reviewer defect P1) -----------
    # Executed by THIS canonical driver, through its own record()/RESULTS
    # bookkeeping, against byte-for-byte production-shaped inputs -- never a
    # standalone script neither ember_totality_spec.discover_tests nor this
    # driver ever ran. Structured missing_condition_ids (P2) asserted via
    # issue715.parse_missing_condition_ids(), not substring matching.
    issue715_pos = build_issue715_pos()
    record("23 ISSUE#715 C-MANIFEST/C-TALLY denominator (production-shaped)",
           "POS unmodified production docs/spec+completeness -> GREEN, no missing ids",
           "test_c_manifest.py", issue715_pos, "GREEN", expected_missing_ids=[])

    issue715_neg_manifest = build_issue715_neg("C-MANIFEST")
    record("23 ISSUE#715 C-MANIFEST/C-TALLY denominator (production-shaped)",
           "NEG production manifest with C-MANIFEST row deleted -> RED naming only C-MANIFEST",
           "test_c_manifest.py", issue715_neg_manifest, "RED", expected_missing_ids=["C-MANIFEST"])

    issue715_neg_tally = build_issue715_neg("C-TALLY")
    record("23 ISSUE#715 C-MANIFEST/C-TALLY denominator (production-shaped)",
           "NEG production manifest with C-TALLY row deleted -> RED naming only C-TALLY",
           "test_c_manifest.py", issue715_neg_tally, "RED", expected_missing_ids=["C-TALLY"])

    # --- report --------------------------------------------------------------
    print("=" * 100)
    print("LANE-14 CHK HARDENING -- POS/NEG CONTROL RESULTS")
    print("=" * 100)
    width_h = max(len(r["hardening"]) for r in RESULTS)
    width_c = max(len(r["control"]) for r in RESULTS)
    for r in RESULTS:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"[{mark}] {r['hardening']:<{width_h}}  {r['control']:<{width_c}}  "
              f"expected={r['expected']:<5} actual={r['actual']:<6}")
        if not r["ok"]:
            print(f"       line: {r['line']}")
            if r["stderr"]:
                print(f"       stderr: {r['stderr']}")
    print("-" * 100)
    n_ok = sum(1 for r in RESULTS if r["ok"])
    print(f"{n_ok}/{len(RESULTS)} controls PASSED")
    print("=" * 100)

    controls_ok = (n_ok == len(RESULTS))

    if args.receipt_out:
        finalize_ok = _finalize_receipt(args.receipt_out, RESULTS, controls_ok)
        return 0 if (controls_ok and finalize_ok) else 1

    return 0 if controls_ok else 1


if __name__ == "__main__":
    sys.exit(main())
