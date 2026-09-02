#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Ember totality test — Condition C14 (status probe / TDD).

C14 — RLM/iGRPO harness-native training organ (pre-loop gate; non-killable).
  R, conjunctive: unsupervised pretraining created the OWNED base (C-BASE;
    frozen is closed); a CC-level resident harness with the clean-room port of
    `avir-cli` as the visible body at near-99% parity (function/UI/UX/backend/
    launch/process-supervision/hooks/dispatch/state/comms/receipts/rollback/
    native goal mechanics — headless is one surface, not parity); a TRAINABLE
    NEURAL POLICY whose parameters update from verifier-conditioned experience
    during the run (full weights / adapter / LoRA / inspectable state_dict delta
    tied to the action-selecting policy); `train_multimodal_v0.py` inventoried+
    adapted for the fp16 C arm; paper-source preflight read+cited (RLM
    arXiv:2512.24601 / iGRPO arXiv:2602.09000) with a mechanism->implementation
    map; a row-by-row floor_contract_manifest; the fixed A<local-mount-point>/C/deleted contract
    with C beating A and B, Deleted degrading/blocking, per-task rows, transfer
    beyond slice, and the neural delta proven LOAD-BEARING (revert it,
    scaffolding intact, gain degrades).
  Does NOT count: deterministic template selectors / scalar dictionaries /
    handwritten routing / prompt edits / frozen-model inference / rerank-only
    wrappers / symbolic programs / "RLM/iGRPO-style" wording without a neural
    update (= SYMBOLIC_PROXY_PASS); a headless avir-cli bridge / generated docs
    / source inventory / wrapper launch / goal-mode bootstrap adapter as the
    harness; a full-parity PASS NOT paired with a first-hand
    real-`<local-exec-root>/avir-cli/avir.exe` UI/UX/AX observation receipt
    (= PARITY_WITH_MODEL_NOT_TOOL); a neural receipt while the clean-room
    harness is blocked (= RUNNER_OR_PARTIAL_NEURAL_PROGRESS_NOT_RESIDENT_ORGAN_
    CLEARANCE).
  ? tokens: SYMBOLIC_PROXY_PASS, invalid_floor_contract_unaccounted,
    invalid_unread_rlm_igrpo_source, invalid_paper_to_spec_only,
    precondition_scaffold_only, PARITY_WITH_MODEL_NOT_TOOL.
  CHK: a machine-check of the resident-training receipt TOGETHER WITH the
    LATEST full-parity harness receipt confirms every conjunct + manifest row
    + neural-delta ablation.

This is a STATUS PROBE. It ALWAYS exits 0 and prints exactly one line beginning
with "RED " or "GREEN ". RED/GREEN is determined by really inspecting the real
receipts/artifacts under <external-state> — never hardcoded.

What a GREEN here actually requires (receipts-only, no self-attestation):
  1. The LATEST resident-training-gate receipt (newest by internal `ts`, with
     filename ts as tiebreak) reads resident_training_gate_status==PASS,
     verdict==RESIDENT_TRAINING_GATE_PASS, empty invalid_codes, empty errors.
  2. The LATEST avir-cli full-parity harness receipt reads
     verdict==..._GATE_PASS / classification==FULL_PARITY_GATE_PASS with no
     blocked_reasons (the clean-room body is real parity, not headless / docs).
  3. That resident receipt's clean_room_harness_identity binds to a real-avir
     UI/UX/AX observation receipt whose verdict is the PASS form and whose
     observed_real_avir_binary / observed_real_tui / observed_agent_loop /
     observed_uiux_ax are all true (defeats PARITY_WITH_MODEL_NOT_TOOL).
  4. The latest RESIDENT_GATE_CONFLATION_GUARD audit does NOT BLOCK
     (defeats SYMBOLIC_PROXY_PASS / RUNNER_OR_PARTIAL_NEURAL_PROGRESS_...).
  5. NONE of the C14 ? invalid-tokens appear anywhere in the authoritative
     resident receipt or the conflation audit.

Run ONLY via:  wsl python3 <this file>
Under WSL the execution root is /mnt<local-mount-point>/ on this host.
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

import glob
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from receipt_ts_authority import effective_event_ts  # noqa: E402 -- shared
# ordering-authority helper (#60); test_c0.py imports the
# same module so C0's and C14's "latest by ts" resolution can never drift.

# Divergence notes collected across this run (populated by _ts_key), folded
# into the final emitted line so a filename/internal-ts mismatch on any
# receipt this probe actually consulted is never silent.
_DIVERGENCE_NOTES = []

# --- Locate the external state root robustly across invocation conventions --------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
# [RULING-DRIFT CORRECTION, 2026-07-06, gh #254] dropped the vestigial third
# REPO_ROOT-relative fallback candidate: EMBER_TOTALITY_ROOT and REPO_ROOT already
# cover every real invocation shape, and the dropped candidate never resolved to
# anything -- a latent probe defect if it were ever reached first.
CANDIDATE_ROOTS = [p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT) if p]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

# C14's explicit ? invalid-tokens (the does-NOT-count outcomes), encoded as
# strings that must NOT appear anywhere in the authoritative receipt(s).
# Matched case-insensitively. These are the negative assertions.
INVALID_TOKENS = [
    "SYMBOLIC_PROXY_PASS",
    "invalid_floor_contract_unaccounted",
    "invalid_unread_rlm_igrpo_source",
    "invalid_paper_to_spec_only",
    "precondition_scaffold_only",
    "PARITY_WITH_MODEL_NOT_TOOL",
    # The two does-NOT-count classifications that the goal text names inline as
    # the equality-encodings of the substitutes (a neural receipt while the
    # harness is blocked; a partial-neural runner): if either is the
    # interpretation of the authoritative resident receipt, it is NOT a pass.
    "RUNNER_OR_PARTIAL_NEURAL_PROGRESS_NOT_RESIDENT_ORGAN_CLEARANCE",
]


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    if _DIVERGENCE_NOTES:
        reason = reason + " | ts-divergence: " + "; ".join(_DIVERGENCE_NOTES)
    print(f"{color} {reason}")
    sys.exit(0)


def _ts_key(path):
    """Sort key via the shared ordering-authority helper (#60):
    internal `ts` field is authoritative when present+parseable, filename
    stamp is fallback only. Does NOT record divergence here -- this runs once
    per candidate during a sort, and most candidates are never selected;
    divergence is only worth surfacing for the receipt a latest() call
    actually PICKS (see latest())."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        data = {}
    eff_ts, _source, _div_note = effective_event_ts(path, data)
    fname_ts = re.search(r"(\d{8}T\d{6}Z)", os.path.basename(path))
    fname_ts = fname_ts.group(1) if fname_ts else ""
    return (str(eff_ts or ""), fname_ts, path)


def latest(pattern):
    """Newest file matching a glob, by (_ts_key). Records a divergence note
    in _DIVERGENCE_NOTES for the WINNING path only, if its filename and
    internal ts diverge by >120s -- the receipt this probe actually uses to
    decide, not every candidate scanned while sorting."""
    hits = glob.glob(pattern, recursive=True)
    if not hits:
        return None
    winner = sorted(hits, key=_ts_key)[-1]
    try:
        with open(winner, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        data = {}
    _eff_ts, _source, div_note = effective_event_ts(winner, data)
    if div_note and div_note not in _DIVERGENCE_NOTES:
        _DIVERGENCE_NOTES.append(div_note)
    return winner


def load(path):
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    return raw, json.loads(raw)


def tokens_in(*raw_texts):
    """Return the list of invalid-tokens present in any of the raw texts."""
    blob = "\n".join(raw_texts).lower()
    return [t for t in INVALID_TOKENS if t.lower() in blob]


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C14: state root not found under any known layout "
                    f"({CANDIDATE_ROOTS}) -> input-missing, dead branch under the "
                    "flat-layout resolver (paper-consistency flip, 2026-07-02)")

    rec_dir = os.path.join(ROOT, "receipts")

    # --- (1) Latest resident-training-gate receipt ---------------------------
    # [REDACTION-BROKE-PATH CORRECTION, 2026-07-06, gh #254/#259]: the public-export
    # scrub tool had rewritten the real receipt directory name into the literal
    # bracketed placeholder `<peer-gate>` -- which never exists verbatim on disk --
    # in these functional path-join calls, so this probe could never locate its own
    # evidence (live reproduction pre-fix: "RED C14: no resident-training-gate
    # receipt found (receipts/<peer-gate>/ empty)" against a tree where
    # receipts/ember-resident-training-gate/ is real and populated). Restored to
    # the real, already-public name.
    resident_path = latest(os.path.join(
        rec_dir, "ember-resident-training-gate", "resident-training-gate-*.json"))
    if resident_path is None:
        emit("RED", "C14: no resident-training-gate receipt found "
                    "(receipts/ember-resident-training-gate/ empty) "
                    "-> satisfying artifact ABSENT")
    try:
        res_raw, res = load(resident_path)
    except Exception as exc:  # broken receipt -> not a pass
        emit("RED", f"C14: latest resident receipt unreadable "
                    f"({os.path.basename(resident_path)}): {exc}")

    # --- (4) Latest conflation-guard audit (binds SYMBOLIC_PROXY / runner) ---
    # [REDACTION-BROKE-PATH CORRECTION, 2026-07-06, gh #254/#259] restored from
    # `<peer-gate>` -- see note above.
    conflation_path = latest(os.path.join(
        rec_dir, "ember-resident-training-gate", "resident-gate-conflation-audit-*.json"))
    confl_raw, confl = ("", {})
    if conflation_path is not None:
        try:
            confl_raw, confl = load(conflation_path)
        except Exception:
            confl_raw, confl = ("", {})

    # --- (5) NEGATIVE ASSERTIONS: no C14 invalid-token in the authoritative
    #         resident receipt or the conflation audit. ------------------------
    hit = tokens_in(res_raw, confl_raw)
    if hit:
        emit("RED", "C14: invalid-token(s) present in authoritative receipts "
                    f"{hit} -> a does-NOT-count outcome "
                    f"(resident={os.path.basename(resident_path)}, "
                    f"conflation={os.path.basename(conflation_path) if conflation_path else None})")

    # --- conflation guard must not be BLOCKED --------------------------------
    confl_verdict = str(confl.get("verdict", ""))
    if confl_verdict and "BLOCK" in confl_verdict.upper():
        interp = confl.get("resident_pass_interpretation")
        emit("RED", "C14: RESIDENT_GATE_CONFLATION_GUARD audit is BLOCKED "
                    f"(verdict={confl_verdict}; interpretation={interp!r}; "
                    f"full_parity_blocked={confl.get('full_parity_blocked')}) "
                    f"via {os.path.basename(conflation_path)} -> resident pass is "
                    "RUNNER_OR_PARTIAL_NEURAL_PROGRESS / not organ clearance")

    # --- (1) Positive CHK on the resident receipt itself ---------------------
    status = str(res.get("resident_training_gate_status", "")).upper()
    verdict = str(res.get("verdict", "")).upper()
    invalid_codes = res.get("invalid_codes") or []
    errors = res.get("errors") or []
    if status != "PASS":
        emit("RED", "C14: latest resident-training-gate receipt "
                    f"{os.path.basename(resident_path)} status={status!r} != PASS "
                    f"(invalid_codes={invalid_codes[:4]}, errors={errors[:3]})")
    if verdict != "RESIDENT_TRAINING_GATE_PASS":
        emit("RED", f"C14: resident verdict={verdict!r} != "
                    f"RESIDENT_TRAINING_GATE_PASS ({os.path.basename(resident_path)})")
    if invalid_codes:
        emit("RED", f"C14: resident receipt carries invalid_codes={invalid_codes} "
                    f"({os.path.basename(resident_path)})")
    if errors:
        emit("RED", f"C14: resident receipt carries errors={errors[:4]} "
                    f"({os.path.basename(resident_path)})")

    # --- (2) Latest full-parity harness receipt must be a real PASS ----------
    parity_path = latest(os.path.join(
        rec_dir, "ember-preloop-resident-gate",
        "avir-cli-full-parity-harness-gate-*.json"))
    if parity_path is None:
        emit("RED", "C14: no avir-cli full-parity harness receipt found "
                    "-> clean-room body parity unproven")
    try:
        par_raw, par = load(parity_path)
    except Exception as exc:
        emit("RED", f"C14: latest full-parity harness receipt unreadable "
                    f"({os.path.basename(parity_path)}): {exc}")
    par_hit = tokens_in(par_raw)
    if par_hit:
        emit("RED", "C14: invalid-token(s) in latest full-parity harness receipt "
                    f"{par_hit} ({os.path.basename(parity_path)})")
    par_verdict = str(par.get("verdict", "")).upper()
    par_class = str(par.get("classification", "")).upper()
    par_blocked = par.get("blocked_reasons") or par.get("full_parity_blocked_reasons")
    if "PASS" not in par_verdict or "BLOCK" in par_verdict:
        emit("RED", "C14: latest full-parity harness receipt is not PASS "
                    f"(verdict={par_verdict!r}, classification={par_class!r}, "
                    f"blocked_reasons={par_blocked}) "
                    f"via {os.path.basename(parity_path)} "
                    "-> clean-room harness BLOCKED (headless/docs != parity)")
    if par_class and "BLOCK" in par_class:
        emit("RED", "C14: latest full-parity harness classification BLOCKED "
                    f"({par_class}) via {os.path.basename(parity_path)}")
    if par_blocked:
        emit("RED", "C14: latest full-parity harness receipt has blocked_reasons "
                    f"{par_blocked} ({os.path.basename(parity_path)})")

    # --- (3) Real-avir UI/UX/AX first-hand observation (defeats
    #         PARITY_WITH_MODEL_NOT_TOOL) --------------------------------------
    obs_path = latest(os.path.join(
        rec_dir, "ember-preloop-resident-gate",
        "real-avir-uiux-ax-observation-*.json"))
    # NOTE: filter to the actual main observation JSON (not -meta / -process /
    # -log siblings) by requiring the observation verdict key.
    obs_candidates = sorted(
        (p for p in glob.glob(os.path.join(
            rec_dir, "ember-preloop-resident-gate",
            "real-avir-uiux-ax-observation-*.json"))
         if "-meta" not in p and "-process" not in p),
        key=_ts_key)
    obs_path = obs_candidates[-1] if obs_candidates else None
    if obs_path is not None:
        try:
            with open(obs_path, "r", encoding="utf-8") as fh:
                _obs_data_for_ts = json.load(fh)
        except Exception:
            _obs_data_for_ts = {}
        _eff_ts, _source, _obs_div_note = effective_event_ts(obs_path, _obs_data_for_ts)
        if _obs_div_note and _obs_div_note not in _DIVERGENCE_NOTES:
            _DIVERGENCE_NOTES.append(_obs_div_note)
    if obs_path is None:
        emit("RED", "C14: no real-avir UI/UX/AX observation receipt found "
                    "-> PARITY_WITH_MODEL_NOT_TOOL risk unresolved "
                    "(first-hand real-avir.exe observation missing)")
    try:
        obs_raw, obs = load(obs_path)
    except Exception as exc:
        emit("RED", f"C14: real-avir observation receipt unreadable "
                    f"({os.path.basename(obs_path)}): {exc}")
    obs_verdict = str(obs.get("verdict", "")).upper()
    obs_flags = {k: obs.get(k) for k in (
        "observed_real_avir_binary", "observed_real_tui",
        "observed_agent_loop", "observed_uiux_ax")}
    if "PASS" not in obs_verdict or "BLOCK" in obs_verdict:
        emit("RED", "C14: real-avir observation verdict is not PASS "
                    f"(verdict={obs_verdict!r}) via {os.path.basename(obs_path)}")
    missing = [k for k, v in obs_flags.items() if v is not True]
    if missing:
        emit("RED", "C14: real-avir observation flags not all true "
                    f"(missing/false: {missing}) via {os.path.basename(obs_path)} "
                    "-> first-hand real-avir.exe observation incomplete "
                    "(PARITY_WITH_MODEL_NOT_TOOL not cleared)")

    # --- Conjunct-3 hardening (#59): the resident receipt's
    # clean_room_harness_identity must actually BIND to THIS observation
    # receipt (by content hash, recomputed live from disk -- never trusted
    # from either receipt's self-reported field), not merely to "some"
    # observation receipt that happens to independently pass. Without this, a
    # resident receipt could pass conjunct 3 against an observation of a
    # DIFFERENT harness build -- the exact conflation class the guard exists
    # to catch, one level down. Docstring named this conjunct from the start;
    # this is the first executable enforcement of it.
    identity = res.get("clean_room_harness_identity")
    if not isinstance(identity, dict):
        emit("RED", "C14: resident receipt has no clean_room_harness_identity "
                    f"({os.path.basename(resident_path)}) -> HARNESS_IDENTITY_UNBOUND "
                    f"(cannot verify it binds to observation receipt "
                    f"{os.path.basename(obs_path)})")
    bound_obs_ref = (
        (identity.get("full_avir_cli_parity_receipt") or {})
        .get("real_avir_uiux_ax_observation_receipt") or {}
    )
    bound_sha = bound_obs_ref.get("sha256")
    if not bound_sha:
        emit("RED", "C14: clean_room_harness_identity carries no bound "
                    f"observation-receipt sha256 ({os.path.basename(resident_path)}) "
                    f"-> HARNESS_IDENTITY_UNBOUND (cannot verify binding to "
                    f"{os.path.basename(obs_path)})")
    with open(obs_path, "rb") as fh:
        actual_obs_sha = hashlib.sha256(fh.read()).hexdigest()
    if bound_sha != actual_obs_sha:
        emit("RED", "C14: resident receipt's clean_room_harness_identity binds to "
                    f"observation sha256={bound_sha} but the LATEST observation "
                    f"receipt {os.path.basename(obs_path)} actually hashes to "
                    f"{actual_obs_sha} -> HARNESS_IDENTITY_UNBOUND (resident "
                    f"{os.path.basename(resident_path)} identifies a DIFFERENT "
                    "harness build than the one currently latest)")

    # --- All conjuncts satisfied with no invalid-token -> GREEN --------------
    emit("GREEN",
         "C14: RESIDENT_TRAINING_GATE_PASS proven by "
         f"{os.path.relpath(resident_path, ROOT)} (status=PASS, "
         "invalid_codes=[], errors=[]); latest full-parity harness "
         f"{os.path.basename(parity_path)} PASS (no blocked_reasons); real-avir "
         f"first-hand observation {os.path.basename(obs_path)} PASS (binary/tui/"
         "agent-loop/uiux all true); conflation-guard not BLOCKED; "
         "no C14 invalid-token present")


if __name__ == "__main__":
    main()
