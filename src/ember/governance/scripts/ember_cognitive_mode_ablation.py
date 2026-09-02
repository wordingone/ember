#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""C12 ablation runner -- real decision-point replay for the state-dependent
cognitive-mode selector (src/ember/governance/scripts/ember_cognitive_mode_policy.py).

What this does (all real, all executed, nothing hand-crafted):

1. Loads every REAL ember totality board-run receipt under
   scripts/ember_totality/receipts-totality/*.json (11 dated runs as of
   authoring, spanning 2026-06-24 .. 2026-07-09). Each one is a genuine,
   already-on-disk record of the repo's own board state at that moment
   (green/red/unevaluable condition counts, audit health, chain
   verification, working-set hygiene) -- these are the "real repo decision
   points" this receipt replays through the selector, not invented inputs.

2. Derives a 6-field CognitiveState per receipt via a fixed, disclosed,
   deterministic mapping (see `derive_state` below and each decision's
   `state_derivation` block) -- documented so it is auditable, not opaque.

3. Runs THREE arms on every decision:
     arm_a_selector_active     -- the real selector: ember_cognitive_mode_policy.select_mode(state)
     arm_b_deletion_fallback   -- what a consuming cycle collapses to with NO
                                  selector at all: a single constant mode
                                  ("act", the selector's own most-permissive
                                  default branch), ignoring state entirely.
     arm_c_fixed_timer_degraded -- selector replaced by a fixed round-robin
                                  schedule over the 12 registry modes,
                                  advancing one step per decision regardless
                                  of state.
   For every arm, every decision, the runner also resolves the real
   MODE_GATE consequence via ember_cognitive_mode_policy.gate_for_mode() --
   this is the load-bearing behavior change (forced_promotion / skip_act /
   retry_verifier / budget_multiplier) a consuming cycle would apply, so the
   comparison is a measured behavioral divergence, not a label divergence.

4. Aggregates measured divergence per ablation arm and writes ONE receipt to
   receipts/ember-mvp/c12-cognitive-mode-ablation-<UTC_TS>.json.

Run:  python src/ember/governance/scripts/ember_cognitive_mode_ablation.py
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

import ember_cognitive_mode_policy as cmp  # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py  # noqa: E402

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"

TOTALITY_RECEIPTS_GLOB = str(SCRIPT_DIR / "ember_totality" / "receipts-totality" / "ember-totality-*.json")

# Fixed round-robin sequence for the degraded arm C -- the 12 registry modes
# in their canonical registry order, advanced one step per decision,
# irrespective of state. This is exactly the "replace the selector with a
# fixed schedule" ablation C12 names.
ROUND_ROBIN_SEQUENCE: tuple[str, ...] = cmp.MODES

# The deletion-fallback mode for arm B: "act" is the selector's own
# most-permissive terminal branch (forced_promotion=None, skip_act=False,
# retry_verifier=False, budget_multiplier=1.0) -- i.e. exactly what a
# consuming cycle collapses to when there is no selector at all and it just
# proceeds with its default behavior regardless of state.
DELETION_FALLBACK_MODE = "act"


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def git_head_sha(cwd: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(cwd), capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except Exception as exc:  # pragma: no cover - environment issue, not logic
        return f"UNAVAILABLE: {exc}"


def git_branch(cwd: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(cwd), capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except Exception as exc:  # pragma: no cover
        return f"UNAVAILABLE: {exc}"


def load_totality_receipts() -> list[tuple[str, dict[str, Any]]]:
    """Return (relpath, parsed_json) for every real totality board receipt,
    sorted by filename (== chronological, since names carry a UTC ts)."""
    paths = sorted(glob.glob(TOTALITY_RECEIPTS_GLOB))
    out = []
    for p in paths:
        with open(p, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
        rel = os.path.relpath(p, REPO_ROOT).replace("\\", "/")
        out.append((rel, obj))
    return out


def derive_state(summary: dict[str, Any], index: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Deterministic, disclosed mapping from a REAL totality-run `summary`
    block to a 6-field CognitiveState-compatible dict. Every formula is
    named in the returned `derivation` block so the mapping is auditable,
    not a black box. Defaults are used ONLY when a real field is genuinely
    absent from that historical receipt (older runs predate some fields),
    and every default use is disclosed per-field, never silently.
    """
    pct_green = float(summary.get("pct_green", 0.0))
    state_condition_total = summary.get("state_condition_total", summary.get("total"))
    unevaluable = summary.get("unevaluable")
    audit_ok = summary.get("audit_ok")
    audit_incident = summary.get("audit_incident")
    audit_pending_epoch = summary.get("audit_pending_epoch")
    working_set = summary.get("working_set")

    derivation: dict[str, Any] = {}

    # evidence_strength: direct real board evidence -- fraction of
    # conditions currently GREEN. Present on every one of the 11 receipts.
    evidence_strength = round(pct_green / 100.0, 6)
    derivation["evidence_strength"] = "summary.pct_green / 100.0"

    # uncertainty: real ambiguity signal -- fraction of conditions the board
    # run could not even evaluate (UNEVALUABLE), over the state-condition
    # denominator. Defaults to 0 unevaluable when the field predates the
    # UNEVALUABLE bucket (disclosed).
    if unevaluable is None:
        unevaluable = 0
        derivation["uncertainty"] = (
            "summary.unevaluable / summary.state_condition_total; "
            "unevaluable field absent on this historical receipt -> defaulted to 0 (disclosed)"
        )
    else:
        derivation["uncertainty"] = "summary.unevaluable / summary.state_condition_total"
    denom = state_condition_total if state_condition_total else summary.get("total", 1)
    denom = denom or 1
    uncertainty = round(float(unevaluable) / float(denom), 6)

    # verifier_state: real audit-health signal.
    #   audit_incident > 0            -> fail  (a real recorded audit failure)
    #   elif audit_pending_epoch > 0  -> pending
    #   elif audit_ok > 0             -> pass
    #   else                          -> none  (receipt predates the audit fields)
    if audit_incident is not None and audit_incident > 0:
        verifier_state = "fail"
        derivation["verifier_state"] = "summary.audit_incident > 0 -> fail"
    elif audit_pending_epoch is not None and audit_pending_epoch > 0:
        verifier_state = "pending"
        derivation["verifier_state"] = "summary.audit_pending_epoch > 0 -> pending"
    elif audit_ok is not None and audit_ok > 0:
        verifier_state = "pass"
        derivation["verifier_state"] = "summary.audit_ok > 0 -> pass"
    else:
        verifier_state = "none"
        derivation["verifier_state"] = "no audit fields on this historical receipt -> none (disclosed)"

    # headroom: real operational-hygiene proxy -- untracked receipt debris on
    # disk (working_set.untracked_receipts_on_disk). More untracked debris
    # means less real operational headroom. Only present on the 5 most
    # recent receipts (working_set is a newer field); older receipts default
    # to a neutral 0.5 (disclosed, never silently).
    if isinstance(working_set, dict) and "untracked_receipts_on_disk" in working_set:
        untracked = float(working_set["untracked_receipts_on_disk"])
        headroom = round(1.0 / (1.0 + untracked / 2000.0), 6)
        derivation["headroom"] = "1 / (1 + working_set.untracked_receipts_on_disk / 2000.0)"
    else:
        headroom = 0.5
        derivation["headroom"] = (
            "working_set.untracked_receipts_on_disk absent on this historical receipt -> "
            "defaulted to neutral 0.5 (disclosed)"
        )

    # blocker_present: real audit-incident / broken-chain signal.
    chain_verification = summary.get("chain_verification")
    chain_ok = None
    if isinstance(chain_verification, dict):
        chain_ok = chain_verification.get("chain_ok")
    blocker_present = bool((audit_incident is not None and audit_incident > 0) or (chain_ok is False))
    derivation["blocker_present"] = "summary.audit_incident > 0 OR chain_verification.chain_ok is False"

    # risk_level: real derived category from board completion -- how much of
    # the live board is currently red is a genuine repo-risk signal.
    if pct_green < 10.0:
        risk_level = "high"
    elif pct_green < 50.0:
        risk_level = "medium"
    else:
        risk_level = "low"
    derivation["risk_level"] = "pct_green < 10 -> high; < 50 -> medium; else low"

    state = {
        "evidence_strength": evidence_strength,
        "uncertainty": uncertainty,
        "verifier_state": verifier_state,
        "headroom": headroom,
        "blocker_present": blocker_present,
        "risk_level": risk_level,
    }
    return state, derivation


def gate_dict(mode: str) -> dict[str, Any]:
    return dict(cmp.gate_for_mode(mode))


def gates_differ(g1: dict[str, Any], g2: dict[str, Any]) -> bool:
    return any(g1[k] != g2[k] for k in ("forced_promotion", "skip_act", "retry_verifier", "budget_multiplier"))


def run() -> dict[str, Any]:
    receipts = load_totality_receipts()
    if not receipts:
        raise SystemExit("no totality board receipts found under scripts/ember_totality/receipts-totality/*.json")

    decisions: list[dict[str, Any]] = []
    source_provenance: list[dict[str, Any]] = []

    arm_b_mode_diffs = 0
    arm_b_gate_diffs = 0
    arm_b_skip_act_diffs = 0
    arm_b_forced_promotion_diffs = 0

    arm_c_mode_diffs = 0
    arm_c_gate_diffs = 0
    arm_c_skip_act_diffs = 0
    arm_c_forced_promotion_diffs = 0

    budget_a_sum = 0.0
    budget_b_sum = 0.0
    budget_c_sum = 0.0

    for i, (rel_path, receipt_obj) in enumerate(receipts):
        summary = receipt_obj.get("summary", {})
        state, derivation = derive_state(summary, i)

        cognitive_state = cmp.CognitiveState(**state)
        mode_a, reason_a = cmp.select_mode(cognitive_state)
        gate_a = gate_dict(mode_a)

        mode_b = DELETION_FALLBACK_MODE
        gate_b = gate_dict(mode_b)

        mode_c = ROUND_ROBIN_SEQUENCE[i % len(ROUND_ROBIN_SEQUENCE)]
        gate_c = gate_dict(mode_c)

        a_vs_b_mode = mode_a != mode_b
        a_vs_b_gate = gates_differ(gate_a, gate_b)
        a_vs_b_skip_act = gate_a["skip_act"] != gate_b["skip_act"]
        a_vs_b_forced = gate_a["forced_promotion"] != gate_b["forced_promotion"]

        a_vs_c_mode = mode_a != mode_c
        a_vs_c_gate = gates_differ(gate_a, gate_c)
        a_vs_c_skip_act = gate_a["skip_act"] != gate_c["skip_act"]
        a_vs_c_forced = gate_a["forced_promotion"] != gate_c["forced_promotion"]

        arm_b_mode_diffs += int(a_vs_b_mode)
        arm_b_gate_diffs += int(a_vs_b_gate)
        arm_b_skip_act_diffs += int(a_vs_b_skip_act)
        arm_b_forced_promotion_diffs += int(a_vs_b_forced)

        arm_c_mode_diffs += int(a_vs_c_mode)
        arm_c_gate_diffs += int(a_vs_c_gate)
        arm_c_skip_act_diffs += int(a_vs_c_skip_act)
        arm_c_forced_promotion_diffs += int(a_vs_c_forced)

        budget_a_sum += gate_a["budget_multiplier"]
        budget_b_sum += gate_b["budget_multiplier"]
        budget_c_sum += gate_c["budget_multiplier"]

        src_sha = sha256_bytes((REPO_ROOT / rel_path).read_bytes())
        source_provenance.append({"path": rel_path, "sha256": src_sha, "receipt_ts": receipt_obj.get("ts")})

        decisions.append(
            {
                "decision_index": i,
                "source_totality_receipt": rel_path,
                "source_totality_receipt_ts": receipt_obj.get("ts"),
                "source_summary_used": {
                    k: summary.get(k)
                    for k in (
                        "pct_green",
                        "green",
                        "red",
                        "unevaluable",
                        "state_condition_total",
                        "total",
                        "audit_ok",
                        "audit_incident",
                        "audit_pending_epoch",
                    )
                    if k in summary
                },
                "state": state,
                "state_derivation": derivation,
                "mode": mode_a,
                "arm_a_selector_active": {"mode": mode_a, "reason": reason_a, "gate": gate_a},
                "arm_b_deletion_fallback": {
                    "mode": mode_b,
                    "gate": gate_b,
                    "note": "constant mode -- no state read at all (selector deleted)",
                },
                "arm_c_fixed_timer_degraded": {
                    "mode": mode_c,
                    "gate": gate_c,
                    "round_robin_position": i % len(ROUND_ROBIN_SEQUENCE),
                    "note": "advances one step per decision on a fixed round-robin schedule -- no state read at all",
                },
                "divergence": {
                    "a_vs_b_mode_differs": a_vs_b_mode,
                    "a_vs_b_gate_differs": a_vs_b_gate,
                    "a_vs_b_skip_act_differs": a_vs_b_skip_act,
                    "a_vs_b_forced_promotion_differs": a_vs_b_forced,
                    "a_vs_c_mode_differs": a_vs_c_mode,
                    "a_vs_c_gate_differs": a_vs_c_gate,
                    "a_vs_c_skip_act_differs": a_vs_c_skip_act,
                    "a_vs_c_forced_promotion_differs": a_vs_c_forced,
                },
            }
        )

    n = len(decisions)
    mode_agreement_b = round(1.0 - arm_b_mode_diffs / n, 6)
    gate_agreement_b = round(1.0 - arm_b_gate_diffs / n, 6)
    mode_agreement_c = round(1.0 - arm_c_mode_diffs / n, 6)
    gate_agreement_c = round(1.0 - arm_c_gate_diffs / n, 6)

    degrades_b = bool(arm_b_gate_diffs > 0)
    degrades_c = bool(arm_c_gate_diffs > 0)

    now = datetime.now(timezone.utc)
    ts_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    receipt = {
        "ticket": "EMBER-C12-COGNITIVE-MODE-ABLATION",
        "ts": ts_iso,
        "sha_convention": SHA_CONVENTION,
        "invariant_sha256": INVARIANT_SHA256,
        "selector": "cognitive_mode_selector",
        "selector_script": "src/ember/governance/scripts/ember_cognitive_mode_policy.py",
        "description": (
            "Replays REAL ember totality board-run receipts (real repo decision points, "
            "not invented inputs) through the live state-dependent cognitive mode selector "
            "and two independently-executed degraded arms, recording per-decision state "
            "vectors, selected modes, and real MODE_GATE behavioral consequences."
        ),
        "provenance": {
            "runner_script": "src/ember/governance/scripts/ember_cognitive_mode_ablation.py",
            "git_sha": git_head_sha(REPO_ROOT),
            "git_branch": git_branch(REPO_ROOT),
            "python_version": sys.version,
            "command": "python src/ember/governance/scripts/ember_cognitive_mode_ablation.py",
            "source_totality_receipts": source_provenance,
            "n_decisions": n,
        },
        "decisions": decisions,
        "ablation": {
            "selector": "cognitive_mode_selector",
            "description": (
                "Two independent ablation legs executed on the SAME 11 real decisions as "
                "arm_a_selector_active above: arm B deletes the state-dependent cognitive "
                "mode selector (constant fallback mode, no state read); arm C replaces the "
                "selector with a fixed_timer round-robin schedule over the 12 registry modes "
                "(no state read). Both are compared against the real selector's actual "
                "per-decision MODE_GATE behavior."
            ),
            "arm_b_deletion_ablation": {
                "ablation_kind": "deletion_ablation",
                "selector": "cognitive_mode_selector",
                "description": (
                    "state-dependent cognitive mode selector deleted -> consuming cycle "
                    "falls back to a single constant mode with no state-conditioning at all"
                ),
                "deleted_object": "src/ember/governance/scripts/ember_cognitive_mode_policy.py:select_mode",
                "fallback_mode": DELETION_FALLBACK_MODE,
                "n_decisions": n,
                "mode_agreement_rate": mode_agreement_b,
                "gate_agreement_rate": gate_agreement_b,
                "skip_act_divergences": arm_b_skip_act_diffs,
                "forced_promotion_divergences": arm_b_forced_promotion_diffs,
                "budget_multiplier_mean_arm_a": round(budget_a_sum / n, 6),
                "budget_multiplier_mean_arm_b": round(budget_b_sum / n, 6),
                "degrades_cycle": degrades_b,
                "degrades_next_action": degrades_b,
            },
            "arm_c_fixed_timer_ablation": {
                "ablation_kind": "fixed_timer_ablation",
                "selector": "cognitive_mode_selector",
                "description": (
                    "state-dependent cognitive mode selector replaced with a fixed_timer "
                    "round-robin schedule over the 12 registry modes, ignoring state entirely"
                ),
                "round_robin_sequence": list(ROUND_ROBIN_SEQUENCE),
                "n_decisions": n,
                "mode_agreement_rate": mode_agreement_c,
                "gate_agreement_rate": gate_agreement_c,
                "skip_act_divergences": arm_c_skip_act_diffs,
                "forced_promotion_divergences": arm_c_forced_promotion_diffs,
                "budget_multiplier_mean_arm_a": round(budget_a_sum / n, 6),
                "budget_multiplier_mean_arm_c": round(budget_c_sum / n, 6),
                "degrades_cycle": degrades_c,
                "degrades_next_action": degrades_c,
            },
        },
        "summary": {
            "n_decisions": n,
            "distinct_modes_selected_by_real_policy": sorted({d["mode"] for d in decisions}),
            "arm_b_mode_agreement_rate": mode_agreement_b,
            "arm_c_mode_agreement_rate": mode_agreement_c,
            "arm_b_gate_agreement_rate": gate_agreement_b,
            "arm_c_gate_agreement_rate": gate_agreement_c,
            "verdict": (
                "MEASURED_DIVERGENCE" if (degrades_b or degrades_c) else "NO_MEASURED_DIVERGENCE_HONEST_NULL"
            ),
        },
    }
    return receipt


def main() -> int:
    receipt = run()
    out_path = REPO_ROOT / "receipts" / "ember-mvp" / f"c12-cognitive-mode-ablation-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    checked_write(str(out_path), receipt)
    print(f"wrote {out_path.relative_to(REPO_ROOT).as_posix()}")
    print(json.dumps(receipt["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
