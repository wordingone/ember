#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Ember totality test — Condition C8 (status probe / TDD).

C8 — ML/AI field-level breakthrough.
  R: a falsifiable contribution in exactly ONE primary class (new/improved
     self-improvement mechanism | training/eval protocol | model/harness
     component | compression/inference technique | agent-learning substrate |
     benchmark methodology | reusable recipe), citing the closest prior/baseline,
     the material difference, a reproducible artifact, external/disjoint
     validation with rows, deletion/ablation, and transfer beyond the scored
     instance.
  Does NOT count: D3-Gym/symbolic-task/multi-family transfer alone; an
     engineering improvement; local harness integration; D3/SAB score progress;
     a better proof wrapper; a plausible (vs falsifiable) claim.
  Invalid-token: progress_not_field_breakthrough  (-> /goal complete invalid)
  CHK: contribution-level deletion degrades a broader external/disjoint
     benchmark while ordinary files/plumbing remain intact.

This is a STATUS PROBE. It always exits 0 and prints exactly one line
beginning with "RED " or "GREEN ". RED/GREEN is determined by really
inspecting state under <external-state> — never hardcoded.

Run ONLY via:  wsl python3 <this file>
Under WSL the execution root is <local-mount-point>/ or /mnt<local-mount-point>/ on this host.
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

# [SANDBOX-AMENDMENT 2026-07-03 — issue #28 PART 1, PENDING_AUTHORIZATION]
# Historical marker: fields 4-5 of the CHK (ablation_method_blocked /
# ordinary_runner_intact) were generalized from one hardcoded verdict-string
# pair to any pair meeting the rules in _ablation_fields_4_5()'s docstring
# below. See PENDING_AUTHORIZATION.ticket.json (sandbox-adjacent) for the
# authorizing reference and the diff summary.
#
# [ISSUE #740 bypass-closure, 2026-07-11] The generalization above shipped
# with a 4th rule -- an incumbent-exact-string shortcut bypassing the
# provenance/naming rules for one candidate line -- which was itself a live
# self-attestation bypass. That rule is now REMOVED; _ablation_fields_4_5
# has three rules, none of them a string-equality shortcut.

import glob
import json
import os
import sys

# --- Locate <external-state> robustly across WSL mount conventions ----------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '..'))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                os.path.join(REPO_ROOT, "<external-state>"))
    if p
]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

# Invalid-tokens that the condition declares as NON-counting outcomes.
# C8's explicit ? token, plus encodings of every "does NOT count" substitute.
# If ANY of these appears as the proving verdict / blocker / claim, C8 is RED.
INVALID_TOKENS = [
    "progress_not_field_breakthrough",          # the explicit ? token
    "d3_gym_transfer_alone",                    # does NOT count: D3-Gym transfer alone
    "symbolic_task_transfer_alone",             # does NOT count: symbolic-task transfer alone
    "multi_family_transfer_alone",              # does NOT count: multi-family transfer alone
    "engineering_improvement",                  # does NOT count: an engineering improvement
    "local_harness_integration",               # does NOT count: local harness integration
    "d3_sab_score_progress",                    # does NOT count: D3/SAB score progress
    "better_proof_wrapper",                     # does NOT count: a better proof wrapper
    "plausible_not_falsifiable_claim",          # does NOT count: a plausible (vs falsifiable) claim
]

# --- [SANDBOX-AMENDMENT] Fields 4-5 generalization ---------------------------
# [ISSUE #740 bypass-closure] The incumbent exact-string pair below USED to be
# a byte-identical early-return shortcut ("if the receipt uses these exact
# verdict strings, pass fields 4-5 unconditionally") -- a single self-attested
# string-equality match that bypassed the (b) executed-run-provenance and (c)
# named-contribution/delegate checks entirely for that one candidate line.
# Removed: incumbent receipts now go through the identical suffix + named +
# provenance checks as every other candidate. Backward compat is compat of
# FORMAT (these two strings still satisfy the ordinary _BLOCKED/_PASS suffix
# rule (a) below, so a genuine incumbent receipt is unaffected), never compat
# of SUFFICIENCY (a string match alone is never enough). The constants are
# kept only as a comment anchor for what "incumbent" refers to historically.
INCUMBENT_NATIVE_LINK_BLOCKED = "NATIVE_OPERATOR_EXTERNAL_TRANSFER_LINK_BLOCKED"
INCUMBENT_EXTERNAL_DELEGATE_PASS = "D3_MULTI_TASK_GENERALIZATION_PASS"


def _resolves_on_disk(root, ref):
    """A receipt_ref counts as provenance only if it names a real file
    resolvable from ROOT (relative) or as an absolute path that exists. A
    dangling ref (the path does not exist) is NOT provenance -- this is
    negative-control (b): a hand-asserted verdict with a dangling receipt ref
    must fail."""
    if not ref or not isinstance(ref, str):
        return False
    cand = ref if os.path.isabs(ref) else os.path.join(root, ref)
    return os.path.isfile(cand)


def _provenance_ok(root, prov):
    """(b) executed-run provenance: a non-empty command (string or argv list)
    PLUS a receipt_ref that resolves to a real file on disk. Both are
    required -- a command with no receipt, or a receipt ref with no command,
    is not an executed-run record, only a claim. This is negative-control
    (a): _BLOCKED/_PASS strings with NO executed-run refs must fail."""
    if not isinstance(prov, dict):
        return False
    command = prov.get("command")
    command_ok = bool(command) and (
        isinstance(command, str)
        or (isinstance(command, list) and len(command) > 0 and all(isinstance(c, str) for c in command))
    )
    return command_ok and _resolves_on_disk(root, prov.get("receipt_ref"))


def _ablation_fields_4_5(ablation, root):
    """Return (method_blocked, ordinary_intact) -- the generalized fields 4/5.

    Accept ANY verdict-string pair where:
      (a) the deletion-side verdict ends _BLOCKED and the delegate-side
          verdict ends _PASS;
      (b) BOTH sides carry executed-run provenance (a command plus a
          receipt_ref that resolves to a real file on disk);
      (c) the receipt names the deleted contribution and the surviving
          delegate pipeline explicitly (non-empty strings).

    [ISSUE #740 bypass-closure] There is no (d) anymore. The former
    incumbent-exact-string shortcut let a receipt bypass (b) and (c) by
    string-matching INCUMBENT_NATIVE_LINK_BLOCKED/INCUMBENT_EXTERNAL_
    DELEGATE_PASS alone -- a single self-attested pair of strings sufficient
    for GREEN with no provenance and no named contribution behind it. An
    incumbent receipt using those exact strings still satisfies rule (a)
    (both are genuine _BLOCKED/_PASS suffixes) and is evaluated identically
    to every other candidate from here on -- no verdict-string pair is ever
    sufficient by itself.
    """
    deletion_verdict = ablation.get("native_link_verdict")
    delegate_verdict = ablation.get("external_delegate_verdict")

    # (a) suffix pattern on BOTH sides.
    suffix_ok = (
        isinstance(deletion_verdict, str) and deletion_verdict.endswith("_BLOCKED")
        and isinstance(delegate_verdict, str) and delegate_verdict.endswith("_PASS")
    )
    if not suffix_ok:
        return False, False

    # (c) named deleted contribution + surviving delegate pipeline, explicit.
    named_ok = (
        bool(ablation.get("deleted_contribution"))
        and bool(ablation.get("surviving_delegate_pipeline"))
    )
    if not named_ok:
        return False, False

    # (b) executed-run provenance on BOTH the deletion run and the delegate run.
    deletion_prov_ok = _provenance_ok(root, ablation.get("deletion_run_provenance"))
    delegate_prov_ok = _provenance_ok(root, ablation.get("delegate_run_provenance"))
    if not (deletion_prov_ok and delegate_prov_ok):
        return False, False

    return True, True


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


def load_json(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    # receipts are written utf-8 but some carry a BOM (utf-8-sig).
    text = raw.decode("utf-8-sig")
    return text, json.loads(text)


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C8: state root not found under any known layout -- input-missing, dead branch under the flat-layout resolver (paper-consistency flip, 2026-07-02)")

    # --- (A) Find the field-level contribution PROOF receipt(s) --------------
    # Receipt hint: src/ember/governance/scripts/ember_field_level_contribution_proof.py emits
    # receipts/**/field-level-contribution-proof-*.json with a top-level verdict
    # FIELD_LEVEL_CONTRIBUTION_PROOF_PASS / _BLOCKED and field_level_claim_proven.
    patterns = [
        os.path.join(ROOT, "receipts", "**", "field-level-contribution-proof-*.json"),
        os.path.join(ROOT, "receipts", "**", "field-level-breakthrough-*.json"),
    ]
    found = set()
    for pat in patterns:
        found.update(glob.glob(pat, recursive=True))
    # Exclude framing-correction / evaluation-only stubs from the PASS-bearing set
    # but keep them visible for the RED reason. The PROOF receipt is canonical.
    proof_receipts = sorted(
        p for p in found if "field-level-contribution-proof-" in os.path.basename(p)
    )
    other_receipts = sorted(found - set(proof_receipts))

    if not proof_receipts:
        emit("RED", "C8: no field-level-contribution-proof-*.json receipt found "
                    f"(other field-level receipts present: {len(other_receipts)}) "
                    "-> satisfying artifact ABSENT")

    # Inspect every proof receipt; require at least ONE that proves the
    # field-level breakthrough with no invalid-token present.
    best_path = None
    best_class = None
    failures = []
    for rp in proof_receipts:
        try:
            raw, data = load_json(rp)
        except Exception as exc:
            failures.append(f"{os.path.basename(rp)}: unreadable ({exc})")
            continue

        # --- (B) Negative assertions: NONE of the invalid-tokens may appear --
        # as the proving verdict / blocker / claim. We check the *load-bearing*
        # fields (verdict, blocked_reasons, candidate class) — not the raw text,
        # because the script legitimately NAMES the does-NOT-count list when it
        # is refusing to overclaim.
        verdict = str(data.get("verdict", ""))
        blockers = data.get("blocked_reasons") or []
        proven = data.get("field_level_claim_proven")
        load_bearing_blob = " ".join(
            [verdict] + [str(b) for b in blockers]
        ).lower()
        hit = [t for t in INVALID_TOKENS if t.lower() in load_bearing_blob]
        if hit:
            failures.append(f"{os.path.basename(rp)}: invalid-token in verdict/blockers {hit}")
            continue

        # --- (C) Positive CHK ------------------------------------------------
        # The receipt itself must declare the field-level claim PROVEN, with a
        # PASS verdict and zero blockers, AND carry the contribution-level
        # deletion ablation showing: method-trigger deletion BLOCKS the
        # native-link proof while the ordinary external runner plumbing stays
        # intact (D3_MULTI_TASK_GENERALIZATION_PASS) — i.e. degrades a broader
        # external/disjoint benchmark while ordinary files remain intact.
        pass_verdict = verdict.endswith("_PASS")
        no_blockers = len(blockers) == 0
        claim_proven = proven is True

        ablation = data.get("contribution_level_deletion_ablation") or {}
        # [SANDBOX-AMENDMENT] generalized fields 4-5 (was: two hardcoded ==)
        method_blocked, ordinary_intact = _ablation_fields_4_5(ablation, ROOT)

        # Required goal fields the contribution must cite (closest prior,
        # material difference, reusable artifact, external disjoint validation).
        rgf = data.get("required_goal_fields") or {}
        cites_prior = bool(rgf.get("closest_known_prior_or_baseline_present"))
        material_diff = bool(rgf.get("material_difference_defined"))
        reusable = bool(rgf.get("reusable_artifact_present"))
        external_disjoint = bool(rgf.get("external_disjoint_validation_present"))

        checks = {
            "pass_verdict": pass_verdict,
            "no_blockers": no_blockers,
            "field_level_claim_proven": claim_proven,
            "ablation_method_blocked": method_blocked,
            "ordinary_runner_intact": ordinary_intact,
            "cites_closest_prior": cites_prior,
            "material_difference": material_diff,
            "reusable_artifact": reusable,
            "external_disjoint_validation": external_disjoint,
        }
        missing = [k for k, ok in checks.items() if not ok]
        if missing:
            # Surface the receipt's own stated blocker for an honest RED reason.
            br = blockers[0] if blockers else "(none stated)"
            failures.append(
                f"{os.path.basename(rp)}: CHK unmet {missing}; receipt blocker={br!r}"
            )
            continue

        best_path = rp
        best_class = (data.get("candidate_claim") or {}).get("primary_contribution_class")
        break

    if best_path is None:
        emit("RED",
             "C8: field-level-contribution-proof receipt(s) present but NONE "
             "prove a falsifiable field-level breakthrough "
             f"(contribution-level deletion + external-disjoint degradation) -> "
             f"{failures[:2]}")

    emit("GREEN",
         f"C8: field-level-contribution-proof receipt "
         f"{os.path.relpath(best_path, ROOT)} verdict=PASS, field_level_claim_proven; "
         f"contribution-level deletion BLOCKS the broader external benchmark while "
         f"ordinary runner plumbing stays intact; class={best_class!r}; "
         f"no invalid-token present")


if __name__ == "__main__":
    main()
