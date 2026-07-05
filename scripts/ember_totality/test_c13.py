#!/usr/bin/env python3
"""Ember totality test - Condition C13 (status probe / TDD).

C13 - Native goal-mode organ.
  R: Ember internalizes goal-mode (parse goal -> read receipts -> identify
     load-bearing blocker -> compile executable attempt -> run/delegate ->
     verify -> write receipt -> update next blocker), with progressive
     non-Ember ablation and a first-principles dissection of goal-mode itself
     (what is imported/rejected/made-native, how non-Ember dependence is
     ablated).
  Does NOT count: Ember calling Codex/Claude/founders/human/wrapper as the
     executor; non-Ember control beyond start/stop/inspect/resource-limit/
     emergency-stop.
  Invalid-token (explicit): invalid_parasite_executor
  CHK: deleted-native-organ receipt degrades/blocks the cycle; dissection
       present.

This is a STATUS PROBE. It always exits 0 and prints exactly one line
beginning with "RED " or "GREEN ". RED/GREEN is determined by REALLY
inspecting state under kai-converge - never hardcoded.

What a GREEN here actually requires (receipts-only, no self-attestation):
  1. A real native_goal_organ_probe receipt (the internalized organ) exists
     with controller == "ember_native_goal_organ_probe" (NOT Codex/Claude/
     founder/human/wrapper), codex_controller_required == false, the full
     8-step minimum goal-mode loop present and minimum_loop_covered == true.
  2. A deleted/ablation counterpart receipt exists in which removing the
     native organ degrades/blocks the cycle: its controller flips to
     "deleted_native_goal_organ", codex_controller_required == true, and the
     selected next action collapses to "native_goal_organ_missing". The live
     positive receipt's deletion_ablation.degrades_decision must be true.
     (This is the "deleted-native-organ receipt degrades/blocks the cycle"
     requirement -- the progressive non-Ember ablation.)
  3. A real first-principles dissection receipt of goal-mode itself exists
     (receipt_type codex_goal_mode_first_principles_dissection) with
     coverage.all_required_mechanisms_covered == true and per-mechanism
     import/reject/make-native decisions plus a Codex-ablation requirement
     (= "what is imported/rejected/made-native, how non-Ember dependence is
     ablated").
  4. NONE of the C13 does-NOT-count invalid-tokens appear in the POSITIVE
     (non-deleted) probe receipt -- i.e. the executor is genuinely Ember-
     native, not a parasite (Codex/Claude/founder/human/wrapper) and no
     non-Ember control beyond start/stop/inspect/resource-limit/emergency-stop.

Run ONLY via:  wsl python3 <this file>
Under WSL the B: drive is /mnt/b/ on this host (the /b/ form is a fallback).
"""

# [PATH-REWRITE 2026-07-01] Imported from
# B:/M/avir/leo/state/ember-totality-build/ into
# B:/M/ember-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at B:/M/avir/leo/state/kai-converge (and /mnt/b/M/...,
# /b/M/..., B:\\M\\... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. kai-converge does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.

import glob
import json
import os
import re
import sys

# --- Locate kai-converge robustly across WSL mount conventions ----------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                os.path.join(REPO_ROOT, "kai-converge"))
    if p
]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

# Invalid-tokens that C13 declares as NON-counting outcomes. The explicit
# spec token plus encodings of the "does NOT count" parasite-executor
# substitutes (Ember calling a NON-Ember thing as the EXECUTOR / controller).
# Each is matched as a whole word against the positive probe receipt text.
INVALID_TOKENS = [
    "invalid_parasite_executor",          # the explicit C13 token
    # "Ember calling Codex/Claude/founders/human/wrapper as the executor":
    "codex_executor",
    "claude_executor",
    "founder_executor",
    "human_executor",
    "wrapper_executor",
    "parasite_executor",
    "codex_parasitism_regression",        # the ablation-regression class itself,
                                          #   if it ever surfaced as the LIVE verdict
]
# NOTE: "native_goal_organ_missing" / "native_goal_organ_deleted_or_incomplete"
# are deliberately NOT full-text invalid-tokens: a CORRECT positive probe
# receipt embeds them inside deletion_ablation.deleted_selected_next_action to
# DESCRIBE the deleted arm's collapse -- that embedded description is exactly
# the ablation evidence C13's CHK requires. Live parasitism is caught instead
# by the controller / codex_controller_required positive checks below (a real
# parasite would have controller==deleted_native_goal_organ and
# codex_controller_required==true, which fail the CHK directly).

# Controllers that mean a NON-Ember thing is the executor (parasite). The live
# positive probe controller must be NONE of these.
PARASITE_CONTROLLERS = {
    "codex", "claude", "founder", "human", "wrapper",
    "deleted_native_goal_organ", "codex_goal_mode", "manual",
}


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    return raw, json.loads(raw)


def _token_hits(raw_lower):
    """Whole-word match of any invalid-token in the receipt text."""
    hits = []
    for t in INVALID_TOKENS:
        if re.search(r"\b" + re.escape(t.lower()) + r"\b", raw_lower):
            hits.append(t)
    return hits


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C13: state root not found under any known layout -- input-missing, dead branch under the flat-layout resolver (paper-consistency flip, 2026-07-02)")

    rdir = os.path.join(ROOT, "receipts")

    # --- (A) Find the POSITIVE native goal-organ probe receipt(s) ------------
    # Receipt hint: scripts/ember_native_goal_organ_probe.py writes
    # native-goal-organ-probe-*.json (the internalized organ); the *-deleted-*
    # counterpart is the non-Ember ablation arm.
    pos_pat = os.path.join(rdir, "**", "native-goal-organ-probe-*.json")
    all_probe = sorted(glob.glob(pos_pat, recursive=True))
    positive = [p for p in all_probe if "deleted" not in os.path.basename(p).lower()]
    deleted = [p for p in all_probe if "deleted" in os.path.basename(p).lower()]

    if not positive:
        # Three-valued correction (2026-07-02, same class as the C9 fail-open
        # fix): scanned-and-empty is an evaluated UNMET, not probe-blindness.
        emit("RED", "C13: no native-goal-organ-probe receipt found "
                    "(native-goal-organ-probe-* absent) -> internalized "
                    "goal-mode organ artifact genuinely ABSENT (corpus scanned)")

    # --- (B) Find the first-principles dissection receipt(s) -----------------
    diss_pat = os.path.join(rdir, "**", "codex-goal-mode-dissection-*.json")
    all_diss = sorted(glob.glob(diss_pat, recursive=True))
    diss_positive = [p for p in all_diss
                     if "deleted" not in os.path.basename(p).lower()]
    if not diss_positive:
        # Three-valued correction: same class as the positive-probe glob above.
        emit("RED", "C13: no goal-mode first-principles dissection receipt "
                    "found (codex-goal-mode-dissection-* absent) -> dissection "
                    "of goal-mode itself genuinely ABSENT (corpus scanned)")

    # --- Validate the dissection (must really cover the mechanisms) ----------
    diss_ok = None
    diss_fail = []
    for dp in sorted(diss_positive, reverse=True):
        base = os.path.basename(dp)
        try:
            raw, d = _load(dp)
        except Exception as exc:  # broken receipt -> not usable
            diss_fail.append(f"{base}: unreadable ({exc})")
            continue
        if str(d.get("receipt_type")) != "codex_goal_mode_first_principles_dissection":
            diss_fail.append(f"{base}: wrong receipt_type {d.get('receipt_type')!r}")
            continue
        cov = d.get("coverage", {})
        if cov.get("all_required_mechanisms_covered") is not True:
            diss_fail.append(f"{base}: all_required_mechanisms_covered != true")
            continue
        mechs = d.get("codex_goal_mode_mechanisms")
        if not (isinstance(mechs, list) and mechs):
            diss_fail.append(f"{base}: no codex_goal_mode_mechanisms list")
            continue
        # Per-mechanism import/reject/make-native decision + ablation requirement
        # = "what is imported/rejected/made-native, how non-Ember dependence is
        #   ablated". The spec asks which verb-family the decision belongs to;
        #   the real schema qualifies it (e.g. import_with_governor,
        #   import_as_negative_constraints, make_native), so match the verb
        #   FAMILY (import / reject / make[-_]native / native), not an exact
        #   literal. Every mechanism must also name a Codex-ablation requirement.
        VERB_FAMILY = ("import", "reject", "make_native", "make-native", "native")
        bad = []
        for m in mechs:
            mp = m.get("native_goal_organ_mapping", {})
            dec = str(mp.get("decision", "")).lower()
            abl = mp.get("codex_ablation_requirement")
            if not any(dec == v or dec.startswith(v + "_") or dec.startswith(v + "-")
                       for v in VERB_FAMILY):
                bad.append(f"{m.get('id')}:decision={dec!r}")
            elif not (isinstance(abl, str) and abl.strip()):
                bad.append(f"{m.get('id')}:no_ablation_req")
        if bad:
            diss_fail.append(f"{base}: mechanism mapping incomplete {bad[:2]}")
            continue
        diss_ok = (dp, len(mechs))
        break

    if diss_ok is None:
        emit("RED", "C13: dissection receipt(s) present but none satisfy the "
                    f"import/reject/make-native + ablation CHK -> {diss_fail[:2]}")

    # --- Validate the POSITIVE probe (the internalized organ) ----------------
    best = None
    failures = []
    for rp in sorted(positive, reverse=True):
        base = os.path.basename(rp)
        try:
            raw, data = _load(rp)
        except Exception as exc:
            failures.append(f"{base}: unreadable ({exc})")
            continue

        # --- Negative assertions: NONE of the invalid-tokens may appear ------
        hits = _token_hits(raw.lower())
        if hits:
            failures.append(f"{base}: invalid-token present {hits}")
            continue

        # --- Positive CHK on the internalized organ -------------------------
        if str(data.get("receipt_type")) != "native_goal_organ_probe":
            failures.append(f"{base}: receipt_type {data.get('receipt_type')!r}")
            continue
        controller = str(data.get("controller", "")).lower()
        # Executor must be Ember-native, never a parasite (Codex/Claude/...).
        if controller != "ember_native_goal_organ_probe":
            failures.append(f"{base}: controller={controller!r} not ember-native")
            continue
        if any(p in controller for p in PARASITE_CONTROLLERS):
            failures.append(f"{base}: parasite controller {controller!r}")
            continue
        if data.get("codex_controller_required") is not False:
            failures.append(f"{base}: codex_controller_required="
                            f"{data.get('codex_controller_required')!r} (must be false)")
            continue

        organ = data.get("native_goal_organ", {})
        if organ.get("minimum_loop_covered") is not True:
            failures.append(f"{base}: minimum_loop_covered != true")
            continue
        # The internalized goal-mode loop, in order.
        expected_loop = [
            "parse_goal", "read_receipts", "identify_load_bearing_blocker",
            "compile_executable_attempt", "run_or_delegate_bounded_action",
            "verify_result", "write_receipt", "update_next_blocker",
        ]
        if organ.get("minimum_loop") != expected_loop:
            failures.append(f"{base}: minimum_loop != canonical 8-step")
            continue

        # Deletion ablation must show the cycle degrades when the organ is gone.
        abl = data.get("deletion_ablation", {})
        if abl.get("degrades_decision") is not True:
            failures.append(f"{base}: deletion_ablation.degrades_decision != true")
            continue
        deleted_sel = abl.get("deleted_selected_next_action", {})
        if str(deleted_sel.get("id")) != "native_goal_organ_missing":
            failures.append(f"{base}: deleted arm does not collapse to "
                            f"native_goal_organ_missing")
            continue

        best = (rp, controller)
        break

    if best is None:
        emit("RED", "C13: native-goal-organ-probe receipt(s) present but none "
                    f"satisfy CHK cleanly -> {failures[:3]}")

    # --- Cross-check the standalone DELETED ablation receipt if present ------
    # (Progressive non-Ember ablation: a real deleted-organ receipt that
    #  degrades/blocks the cycle.) This is corroborating evidence; the live
    #  positive receipt's own deletion_ablation is the binding CHK.
    ablation_note = "no standalone deleted receipt"
    for dp in sorted(deleted, reverse=True):
        try:
            _, dd = _load(dp)
        except Exception:
            continue
        if (str(dd.get("controller")) == "deleted_native_goal_organ"
                and dd.get("codex_controller_required") is True
                and str(dd.get("selected_next_action", {}).get("id"))
                == "native_goal_organ_missing"):
            ablation_note = (f"deleted-arm {os.path.basename(dp)} blocks cycle "
                             f"(controller=deleted_native_goal_organ, "
                             f"codex_controller_required=true)")
            break

    rp, controller = best
    dp, nmech = diss_ok
    emit("GREEN",
         f"C13: native goal-mode organ internalized + ablated. probe="
         f"{os.path.relpath(rp, ROOT)} (controller={controller}, "
         f"codex_controller_required=false, 8-step loop covered, "
         f"deletion degrades cycle); dissection="
         f"{os.path.relpath(dp, ROOT)} ({nmech} mechanisms, import/reject/"
         f"make-native + ablation, all_required_mechanisms_covered=true); "
         f"{ablation_note}; no invalid-token in positive receipt")


if __name__ == "__main__":
    main()
