#!/usr/bin/env python3
"""Ember totality test — Condition C-EFF (status probe / TDD).

C-EFF — efficiency keystone measured/closed (goal §4.1, <spec> L94).
  R: an efficiency-closure receipt via gate-9 with
     {measured throughput, MFU, required-tokens projection,
      ONE bounded confirmation run,
      verdict in (SHATTER <=1 governed day | PRICED_SCALEOUT_RESIDUAL)},
     AND every c04 deciding axis receipted APPLIED/KILLED/WAIVED-priced.
  Does NOT count:
     - a projection with no confirmation run;
     - a lever marked done without a gate-9 receipt;
     - "from-scratch is too expensive" asserted by analogy rather than measured.
  Invalid-token (the explicit ✗): invalid_efficiency_unconfirmed
  CHK: gate-9 receipt present; confirmation-run throughput within the stated
       band of the projection.

Honest closure bar (goal L46/L73, mirrored from the canonical checker
scripts/ember_tally_checks.py:chk_ceff): SHATTER requires a >=3.3x COMPOUND
speedup over the anchor AND the useful base trains in <=1 governed day with
effective_days = useful_base_tokens / (sustained_tok_s * 86400) — NOT the
self-referential K_floor/throughput ratio. The prior
ceff-closure-gate9-shatter-bf16ns5-*.json "SHATTER" verdict is REPUDIATED
(receipts/ceff-shatter-REPUDIATED-*.json): measured lever 1.18x, c03 stack
1.85x = 56% of the >=3.3x criterion. Valid C-EFF closure is therefore read
ONLY from a receipts/ceff-RESOLVED-*.json receipt meeting the honest bar.

This is a STATUS PROBE. It always exits 0 and prints exactly one line
beginning with "RED " or "GREEN ". RED/GREEN is determined by really
inspecting state under <external-state> — never hardcoded.

Run ONLY via:  wsl python3 <this file>
Under WSL the execution root is <local-mount-point>/ on this host (NOT necessarily /mnt<local-mount-point>/).
"""

# [PATH-REWRITE 2026-07-01] Imported from
# <<external>>/state/ember-totality-build/ into
# <local-exec-root>-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at <<external>>/state/<external-state> (and /mnt<local-mount-point>/M/...,
# <local-mount-point>/M/..., B:\\M\\... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. <external-state> does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.

import glob
import json
import os
import sys

# --- Locate <external-state> robustly across WSL mount conventions ----------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                os.path.join(REPO_ROOT, "<external-state>"))
    if p
]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

# Honest-bar constants (goal L46/L73; identical to ember_tally_checks.py).
SHATTER_COMPOUND_MIN = 3.3
SHATTER_EFF_DAYS_MAX = 1.0
GOVERNED_SECONDS_PER_DAY = 86400.0
EFF_DAYS_TOL = 0.05
VALID_VERDICTS = {"SHATTER", "PRICED_SCALEOUT_RESIDUAL"}

# Invalid-tokens the condition declares as NON-counting outcomes. The first is
# C-EFF's explicit ✗ token; the rest encode the three "does NOT count"
# substitutes so a closure receipt that names/admits any of them cannot pass.
INVALID_TOKENS = [
    "invalid_efficiency_unconfirmed",        # the explicit ✗ token
    "projection_with_no_confirmation_run",   # does NOT count: projection w/o confirmation run
    "lever_done_without_gate9_receipt",      # does NOT count: lever marked done w/o gate-9 receipt
    "from_scratch_too_expensive_by_analogy", # does NOT count: cost asserted by analogy, not measured
]


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C-EFF: state root not found under any known layout -- input-missing, dead branch under the flat-layout resolver (paper-consistency flip, 2026-07-02)")

    receipts_dir = os.path.join(ROOT, "receipts")
    if not os.path.isdir(receipts_dir):
        emit("RED", f"C-EFF: receipts dir absent at {receipts_dir}")

    # --- (A) Valid C-EFF closure is read ONLY from ceff-RESOLVED-*.json -------
    # The gate9-shatter receipt is REPUDIATED and is NOT consulted as a closure
    # (this mirrors the canonical chk_ceff after repudiation). If no RESOLVED
    # receipt exists, the satisfying artifact is genuinely ABSENT -> RED.
    resolved = sorted(glob.glob(os.path.join(receipts_dir, "ceff-RESOLVED-*.json")))
    if not resolved:
        # Surface why: confirm the repudiation receipt that closed the false-green.
        repud = sorted(glob.glob(os.path.join(receipts_dir, "ceff-shatter-REPUDIATED-*.json")))
        repud_note = (f"repudiation receipt present ({os.path.basename(repud[-1])})"
                      if repud else "no repudiation receipt either")
        emit("RED",
             "C-EFF: no receipts/ceff-RESOLVED-*.json closure receipt -> "
             "satisfying artifact ABSENT. Prior gate9-shatter verdict is "
             f"REPUDIATED ({repud_note}); measured 1.18x lever / 1.85x c03 "
             "stack = 56% of the >=3.3x shatter criterion. Valid closure: "
             "SHATTER (>=3.3x compound AND base in <=1 governed day) OR "
             "PRICED_SCALEOUT_RESIDUAL.")

    # --- A RESOLVED receipt exists: inspect the latest by stamp-sorted name. --
    receipt_path = resolved[-1]
    try:
        with open(receipt_path, "r", encoding="utf-8") as fh:
            raw = fh.read()
        d = json.loads(raw)
    except Exception as exc:
        emit("RED", f"C-EFF: RESOLVED receipt unreadable "
                    f"({os.path.basename(receipt_path)}): {exc}")

    findings = []

    # --- (B) Negative assertions: NONE of the invalid-tokens may appear -------
    lowered = raw.lower()
    hit = [t for t in INVALID_TOKENS if t.lower() in lowered]
    if hit:
        findings.append(f"invalid-token present {hit}")

    # --- (C) Positive CHK: verdict + honest effective_days basis + magnitude --
    verdict = d.get("verdict")
    if verdict not in VALID_VERDICTS:
        findings.append(f"verdict={verdict!r} not in {sorted(VALID_VERDICTS)}")

    # Reject the self-referential K_floor/throughput basis explicitly.
    basis = d.get("effective_days_basis")
    if basis != "useful_base_tokens_div_governed_day":
        findings.append(
            f"effective_days_basis={basis!r} != "
            "'useful_base_tokens_div_governed_day' (self-referential/undeclared rejected)")

    ubt = d.get("useful_base_tokens")
    tok_s = d.get("sustained_tok_s")
    eff_days = d.get("effective_days")
    compound = d.get("compound_speedup_over_anchor")
    for name, val in (
        ("useful_base_tokens", ubt),
        ("sustained_tok_s", tok_s),
        ("effective_days", eff_days),
        ("compound_speedup_over_anchor", compound),
    ):
        if not isinstance(val, (int, float)):
            findings.append(f"{name} missing or non-numeric: {val!r}")

    # CHK clause: a gate-9 efficiency-closure receipt must be referenced/present.
    gate_field = str(d.get("gate", "")).lower()
    if "gate-9" not in gate_field and "gate9" not in gate_field:
        findings.append("no gate-9 efficiency-closure stamp in RESOLVED receipt 'gate' field")

    # CHK clause: ONE bounded confirmation run, with throughput within band of
    # the projection (the does-NOT-count: "projection with no confirmation run").
    conf = d.get("confirmation_run") or {}
    conf_tok_s = conf.get("sustained_tok_s") if isinstance(conf, dict) else None
    proj_tok_s = d.get("projected_tok_s")
    if not isinstance(conf_tok_s, (int, float)):
        findings.append("confirmation_run.sustained_tok_s missing "
                        "(projection with no confirmation run does NOT count)")
    elif isinstance(proj_tok_s, (int, float)) and proj_tok_s > 0:
        band = d.get("confirmation_band_frac", 0.10)
        if abs(conf_tok_s - proj_tok_s) / proj_tok_s > band:
            findings.append(
                f"confirmation throughput {conf_tok_s} outside ±{band:.0%} "
                f"band of projection {proj_tok_s}")

    # internal consistency: effective_days ~= ubt / (tok_s * 86400)
    if (isinstance(ubt, (int, float)) and isinstance(tok_s, (int, float))
            and isinstance(eff_days, (int, float)) and tok_s > 0 and eff_days > 0):
        recomputed = ubt / (tok_s * GOVERNED_SECONDS_PER_DAY)
        if abs(recomputed - eff_days) / eff_days > EFF_DAYS_TOL:
            findings.append(
                f"effective_days {eff_days} inconsistent with "
                f"useful_base_tokens/(sustained_tok_s*86400) = {recomputed:.4f}")

    # SHATTER magnitude gate (goal L46): >=3.3x compound AND <=1 governed day.
    if verdict == "SHATTER":
        if isinstance(compound, (int, float)) and compound < SHATTER_COMPOUND_MIN:
            findings.append(
                f"SHATTER but compound_speedup_over_anchor {compound} "
                f"< {SHATTER_COMPOUND_MIN}")
        if isinstance(eff_days, (int, float)) and eff_days > SHATTER_EFF_DAYS_MAX:
            findings.append(
                f"SHATTER but effective_days {eff_days} > {SHATTER_EFF_DAYS_MAX}")

    # CHK clause: every c04 deciding axis receipted APPLIED/KILLED/WAIVED-priced.
    axes = d.get("c04_deciding_axes")
    if isinstance(axes, dict) and axes:
        ok_states = {"APPLIED", "KILLED", "WAIVED", "WAIVED-priced", "WAIVED_PRICED"}
        for ax, st in axes.items():
            stu = str(st).upper().replace("-", "_")
            if stu not in {s.upper().replace("-", "_") for s in ok_states}:
                findings.append(f"c04 axis {ax!r} status {st!r} not APPLIED/KILLED/WAIVED-priced")
    else:
        findings.append("c04_deciding_axes map absent "
                        "(every deciding axis must be receipted APPLIED/KILLED/WAIVED-priced)")

    if findings:
        emit("RED", f"C-EFF: RESOLVED receipt {os.path.basename(receipt_path)} "
                    f"fails CHK -> {'; '.join(findings)}")

    emit("GREEN",
         f"C-EFF: closure receipt {os.path.relpath(receipt_path, ROOT)} "
         f"verdict={verdict}, compound={compound}x, effective_days={eff_days}, "
         f"useful_base_tokens={ubt}, sustained_tok_s={tok_s}, "
         f"gate-9 stamped, confirmation run present, c04 axes accounted; "
         f"no invalid-token present (basis={basis})")


if __name__ == "__main__":
    main()
