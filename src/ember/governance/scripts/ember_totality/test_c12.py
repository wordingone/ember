#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
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
Receipt hint: src/ember/governance/scripts/ember_cognitive_mode_policy.py + selftest,
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
# <local-mount-point>/M/..., <TEMP_WORKSPACE>/... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. <external-state> does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys

from evidence_scan_hygiene import is_board_render_output

# --- Locate <external-state> robustly across WSL mount conventions ----------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '..'))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                os.path.join(REPO_ROOT, "<external-state>"))
    if p
]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

GIT_TIMEOUT_SECONDS = 15

# [ISSUE #683 class extension] arm-B (deletion) divergence uses the a-vs-b
# key prefix; arm-C (fixed-timer) uses a-vs-c. This maps the ablation `kind`
# find_ablation_block() returns to the matching per-decision divergence key,
# so the mode_agreement_rate can be recomputed from raw decisions[] instead
# of trusted from the receipt's own summary of itself.
DIVERGENCE_MODE_KEY_BY_KIND = {
    "deletion_ablation": "a_vs_b_mode_differs",
    "fixed_timer_ablation": "a_vs_c_mode_differs",
}

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
                    if p not in seen and not is_board_render_output(p):
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


# ---------------------------------------------------------------------------
# [ISSUE #683 class extension] execution-binding hardening for C12.
# ---------------------------------------------------------------------------

def _import_selector_module(repo_root):
    """Import src/ember/governance/scripts/ember_cognitive_mode_policy.py from repo_root via
    importlib (not a relative package import -- this probe runs standalone).
    Returns (module, None) on success or (None, error_string) on failure."""
    path = os.path.join(repo_root, SELECTOR_REL)
    if not os.path.isfile(path):
        return None, f"selector source missing at {path}"
    mod_name = "ember_cognitive_mode_policy_recompute"
    try:
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        # The selector module defines a @dataclass whose field-type resolution
        # looks itself up via sys.modules[cls.__module__] -- the module MUST be
        # registered in sys.modules before exec_module runs, or dataclass
        # processing raises AttributeError on a None module lookup.
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001 -- status probe, must not crash
        sys.modules.pop(mod_name, None)
        return None, f"selector import failed: {exc}"
    return mod, None


def _recompute_decision_modes(decisions, selector_mod):
    """Re-run select_mode() on EVERY decision's claimed state vector using the
    live selector module; a claimed mode is never trusted without this. Returns
    a list of mismatch description strings (empty list == all decisions agree)."""
    mismatches = []
    for i, dec in enumerate(decisions):
        if not isinstance(dec, dict):
            mismatches.append(f"decision[{i}]: not a dict")
            continue
        st = dec.get("state")
        claimed_mode = dec.get("mode")
        if not isinstance(st, dict) or not claimed_mode:
            mismatches.append(f"decision[{i}]: missing state dict or claimed mode")
            continue
        try:
            state = selector_mod.CognitiveState(
                evidence_strength=st.get("evidence_strength"),
                uncertainty=st.get("uncertainty"),
                verifier_state=st.get("verifier_state"),
                headroom=st.get("headroom"),
                blocker_present=st.get("blocker_present"),
                risk_level=st.get("risk_level"),
            )
            recomputed_mode, _reason = selector_mod.select_mode(state)
        except Exception as exc:  # noqa: BLE001 -- status probe, must not crash
            mismatches.append(f"decision[{i}]: recompute raised {exc!r} on state {st!r}")
            continue
        if recomputed_mode != claimed_mode:
            mismatches.append(
                f"decision[{i}]: claimed mode={claimed_mode!r} but recomputed "
                f"select_mode(state)={recomputed_mode!r}")
    return mismatches


def _recompute_mode_agreement_rate(decisions, kind):
    """Recompute the mode_agreement_rate DIRECTLY from decisions[].divergence
    entries (count of non-divergent decisions / total) for the ablation arm
    matching `kind` -- never trust the ablation block's self-reported rate,
    or its degrades_cycle/degrades_next_action booleans, without this backing.
    Returns (rate_or_None, error_or_None)."""
    key = DIVERGENCE_MODE_KEY_BY_KIND.get(kind)
    if key is None:
        return None, f"no divergence key mapped for ablation kind {kind!r}"
    if not isinstance(decisions, list) or not decisions:
        return None, "decisions[] is empty or not a list"
    total = len(decisions)
    agree = 0
    missing = []
    for i, dec in enumerate(decisions):
        div = dec.get("divergence") if isinstance(dec, dict) else None
        if not isinstance(div, dict) or key not in div:
            missing.append(i)
            continue
        if not div[key]:
            agree += 1
    if missing:
        return None, f"decisions missing divergence.{key} at indices {missing}"
    return agree / total, None


def _git_show_bytes(repo_root, sha, rel_path):
    """git show <sha>:<rel_path> -- raw bytes, or None on any failure."""
    norm = str(rel_path).replace("\\", "/")
    try:
        proc = subprocess.run(
            ["git", "show", f"{sha}:{norm}"], cwd=repo_root,
            capture_output=True, timeout=GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _verify_selector_sha_pin(obj, repo_root, selector_path):
    """Sha-pin the selector source instead of trusting a bare
    os.path.isfile(selector_path) check. The receipt's provenance.git_sha
    names the commit its ablation run was executed against; the selector's
    real content AT that commit is recomputed via `git show` and hashed.
    If the receipt itself carries a selector sha256 field, it must match the
    recomputed at-commit hash. If the receipt predates such a field, the
    recomputed at-commit hash is accepted ONLY when the CURRENT working-tree
    selector's sha256 also matches it -- guarding against a silent selector
    swap between the ablation run and this probe's evaluation.
    Returns (ok: bool, detail: str)."""
    provenance = obj.get("provenance") or {}
    git_sha = provenance.get("git_sha")
    if not git_sha:
        return False, "receipt provenance.git_sha missing -- cannot sha-pin the selector"

    at_commit_bytes = _git_show_bytes(repo_root, git_sha, SELECTOR_REL)
    if at_commit_bytes is None:
        return False, (f"could not read {SELECTOR_REL} at commit {git_sha} via git show "
                       f"-- commit or path unresolvable")
    at_commit_sha = hashlib.sha256(at_commit_bytes).hexdigest()

    receipt_selector_sha = obj.get("selector_sha256") or provenance.get("selector_sha256")
    if receipt_selector_sha:
        if receipt_selector_sha != at_commit_sha:
            return False, (f"receipt selector_sha256={receipt_selector_sha!r} != recomputed "
                           f"at-commit sha256={at_commit_sha!r} of {SELECTOR_REL} at {git_sha}")
        return True, f"receipt selector_sha256 matches recomputed at-commit sha {at_commit_sha}"

    # No selector_sha256 field on this (older) receipt: accept ONLY if the
    # CURRENT working-tree selector also matches the at-commit hash.
    if not os.path.isfile(selector_path):
        return False, f"selector source {selector_path} absent on disk -- nothing to pin"
    with open(selector_path, "rb") as fh:
        working_tree_bytes = fh.read()
    working_tree_sha = hashlib.sha256(working_tree_bytes).hexdigest()
    if working_tree_sha != at_commit_sha:
        return False, (f"receipt predates a selector_sha256 field; working-tree selector "
                       f"sha256={working_tree_sha!r} != at-commit ({git_sha}) "
                       f"sha256={at_commit_sha!r} -- possible silent selector swap")
    return True, (f"receipt predates a selector_sha256 field; working-tree selector sha256 "
                  f"matches at-commit ({git_sha}) sha256={at_commit_sha!r}")


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
    best = None            # (path, kind, block, wires, state_driven, obj)
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
            cand = (path, kind, block, wires, state_driven, obj)
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

    path, kind, block, wires, state_driven, obj = best

    if not selector_present:
        emit("RED",
             f"C12: ablation receipt {os.path.basename(path)} references the "
             f"selector but the selector source {SELECTOR_REL} is ABSENT on disk "
             f"-> nothing real to delete/ablate")

    # [ISSUE #683 class extension] sha-pin the selector instead of trusting the
    # bare isfile check above as the only gate: prove the receipt's ablation
    # ran against the exact selector content its provenance.git_sha names --
    # not merely that SOME file exists at SELECTOR_REL today (no silent swap).
    sha_ok, sha_detail = _verify_selector_sha_pin(obj, REPO_ROOT, selector_path)
    if not sha_ok:
        emit("RED",
             f"C12: ablation receipt {os.path.basename(path)} selector sha-pin "
             f"UNVERIFIED -> {sha_detail}")

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

    # [ISSUE #683 class extension] (a) re-run select_mode() on EVERY decision's
    # claimed state vector -- a claimed mode is never trusted without this.
    selector_mod, import_err = _import_selector_module(REPO_ROOT)
    if selector_mod is None:
        emit("RED",
             f"C12: could not import {SELECTOR_REL} to recompute decisions -> {import_err}")

    decisions = obj.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        emit("RED",
             f"C12: ablation receipt {os.path.basename(path)} has no decisions[] "
             f"array to recompute select_mode() against")

    mode_mismatches = _recompute_decision_modes(decisions, selector_mod)
    if mode_mismatches:
        emit("RED",
             f"C12: ablation receipt {os.path.basename(path)} recomputed "
             f"select_mode() disagrees with the claimed mode -> {mode_mismatches}")

    # (b) recompute mode_agreement_rate DIRECTLY from decisions[].divergence --
    # degrades_cycle/degrades_next_action booleans are never trusted without
    # this independent backing.
    recomputed_rate, rate_err = _recompute_mode_agreement_rate(decisions, kind)
    if rate_err:
        emit("RED",
             f"C12: ablation receipt {os.path.basename(path)} mode_agreement_rate "
             f"could not be recomputed from decisions[].divergence -> {rate_err}")
    claimed_rate = block.get("mode_agreement_rate")
    if not isinstance(claimed_rate, (int, float)):
        emit("RED",
             f"C12: ablation block in {os.path.basename(path)} ({kind}) has no "
             f"numeric mode_agreement_rate field to cross-check")
    if abs(recomputed_rate - claimed_rate) > 1e-6:
        emit("RED",
             f"C12: ablation receipt {os.path.basename(path)} claims "
             f"mode_agreement_rate={claimed_rate} but recomputing from "
             f"decisions[].divergence gives {recomputed_rate} "
             f"(tolerance 1e-6 exceeded) -> degrades_cycle/degrades_next_action "
             f"NOT trusted without this backing")

    # GREEN: a real receipt wires the state-dependent cognitive-mode selector,
    # logs state-driven decisions, and carries a deletion/fixed-timer ablation
    # block proving removal degrades the cycle; no invalid-token or does-NOT-
    # count substitute matched. Every decision's mode is independently
    # recomputed via the live (sha-pinned) selector, and the ablation arm's
    # mode_agreement_rate is independently recomputed from raw divergence data.
    deg_summary = ", ".join(f"{k}={v}" for k, v in degrade_flags.items()) or "free-degrade-text"
    emit("GREEN",
         f"C12: deleted-mode-selector receipt {os.path.basename(path)} carries "
         f"{kind} for the state-dependent cognitive mode selector "
         f"({deg_summary}); selector source {SELECTOR_REL} present and "
         f"sha-pinned ({sha_detail}); wires_selector={wires} "
         f"state_driven_decisions={state_driven}; all {len(decisions)} decisions' "
         f"select_mode() recomputed and matched claimed mode; "
         f"mode_agreement_rate recomputed={recomputed_rate} matches claimed="
         f"{claimed_rate}; no invalid_timer_artifact_modes / equal-duration "
         f"substitute -> modes are state-selected and deletion-sensitive")


if __name__ == "__main__":
    main()
