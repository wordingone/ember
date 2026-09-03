#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
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
       band of the projection; execution-binding per issue #683 (dry_run/
       no_gpu/synthetic explicitly False, source_commit_sha + harness_sha
       verified against real git objects, governor + FLOPs recompute).

Honest closure bar (goal L46/L73, mirrored from the canonical checker
src/ember/governance/scripts/ember_tally_checks.py:chk_ceff): SHATTER requires a >=3.3x COMPOUND
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
# <local-mount-point>/M/..., <TEMP_WORKSPACE>/... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. <external-state> does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.

import glob
import json
import os
import re
import subprocess
import sys

# --- Locate <external-state> robustly across WSL mount conventions ----------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '..'))
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

# [ISSUE #683 cure, Finding 1] Execution-binding hardening. The pre-cure
# checker verified JSON-internal arithmetic self-consistency and required-
# field vocabulary only -- it never checked harness_sha against anything,
# never inspected dry_run/no_gpu/confirmation_run.synthetic (present in
# schema, uninspected), never verified import_provenance.source_commit_sha
# exists in git, and never checked governor plausibility. A ~15-line
# hand-authored JSON with a self-consistent verdict + one sustained_tok_s
# key could turn C-EFF GREEN with no SHA, no torch, no telemetry (audit
# receipts/ember-totality-audit/audit-20260710T145200Z.json). All four
# checks below tie the receipt's claims to what could physically have
# happened / to real git objects -- never to whether the right JSON keys
# merely exist.
GOVERNOR_TOTAL_GIB_MAX = 200.0  # plausible upper bound for a single GPU's VRAM
GOVERNOR_GIB_TOLERANCE = 0.5    # float-rounding slack for free<=total comparison
FLOPS_RECOMPUTE_TOLERANCE = 0.02  # 2% -- g_budget.detail's cost is text-rounded
GIT_TIMEOUT_SECONDS = 15

# Extracts the "cost=<num> FLOPs" figure out of g_budget.detail's free text
# (e.g. "... total_steps=70, cost=2.535e+15 FLOPs (6*params*tokens estimate) ...").
COST_FLOPS_RE = re.compile(r"cost=([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\s*FLOPs")


def _run_git(args, cwd):
    """Run a git subprocess rooted at cwd. Returns (returncode, stdout, stderr);
    returncode is None on any exception (missing git, timeout, not a repo) so
    callers always get a uniform execution-binding-failure shape, never a
    crash -- this is a status probe and must always exit 0 on its own."""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, see docstring
        return None, "", str(exc)


def _git_object_type(cwd, sha):
    """git cat-file -t <sha> -> the object type string, or None if the sha
    does not resolve to a real git object under cwd's repo."""
    if not isinstance(sha, str) or not sha.strip():
        return None
    rc, out, _err = _run_git(["cat-file", "-t", sha], cwd)
    return out.strip() if rc == 0 else None


def _git_commit_touches_path(cwd, sha, path):
    """True iff the commit's own diff touches `path` (normalized to forward
    slashes for git's pathspec matching)."""
    norm = str(path).replace("\\", "/")
    rc, out, _err = _run_git(
        ["show", "--stat", "--format=", sha, "--", norm], cwd)
    return rc == 0 and bool(out.strip())


def _git_blob_sha256_at_commit(cwd, sha, path):
    """sha256 hexdigest of `path`'s content AT commit `sha`, or None if the
    path cannot be read at that commit (missing/renamed/not a git repo)."""
    import hashlib
    norm = str(path).replace("\\", "/")
    try:
        proc = subprocess.run(
            ["git", "show", f"{sha}:{norm}"], cwd=cwd,
            capture_output=True, timeout=GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return hashlib.sha256(proc.stdout).hexdigest()

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

    # --- [ISSUE #683 cure, point 1] dry_run/no_gpu/synthetic EXPLICITLY False -
    # Absent field = reject, not pass -- a receipt that never declares these
    # flags is exactly as unverifiable as one that declares them true.
    conf = d.get("confirmation_run") or {}
    conf_dict = conf if isinstance(conf, dict) else {}
    _MISSING = object()
    for field_label, val in (
        ("dry_run", d.get("dry_run", _MISSING)),
        ("no_gpu", d.get("no_gpu", _MISSING)),
        ("confirmation_run.synthetic", conf_dict.get("synthetic", _MISSING)),
    ):
        if val is not False:
            got = "ABSENT" if val is _MISSING else repr(val)
            findings.append(
                f"{field_label} != False (execution-binding requires an "
                f"EXPLICIT False; absent/true = reject): {got}")

    # --- [ISSUE #683 cure, points 2+3] source_commit_sha + harness_sha --------
    # If import_provenance.source_commit_sha is present: it must resolve to a
    # real commit in this repo's git history, that commit's own diff must
    # touch the receipt path the provenance block claims, AND harness_sha
    # must equal the real sha256 of src/ember/governance/scripts/ember_ceff_closure_confirmation.py
    # AT that commit -- never an inert cosmetic field copied around unchecked.
    import_prov = d.get("import_provenance") or {}
    import_prov = import_prov if isinstance(import_prov, dict) else {}
    source_sha = import_prov.get("source_commit_sha")
    harness_sha_field = d.get("harness_sha")
    if source_sha:
        obj_type = _git_object_type(ROOT, source_sha)
        if obj_type != "commit":
            findings.append(
                f"import_provenance.source_commit_sha {source_sha!r} does not "
                f"resolve to a git commit under {ROOT} (git cat-file -t -> "
                f"{obj_type!r})")
        else:
            claimed_path = import_prov.get("original_receipt_path")
            if not claimed_path:
                findings.append(
                    "import_provenance.source_commit_sha present but "
                    "original_receipt_path missing -- cannot verify the "
                    "commit touches the receipt path it claims")
            elif not _git_commit_touches_path(ROOT, source_sha, claimed_path):
                findings.append(
                    f"commit {source_sha} diff does not touch claimed "
                    f"receipt path {claimed_path!r}")

            if not harness_sha_field:
                findings.append(
                    "harness_sha missing -- cannot execution-bind to "
                    "src/ember/governance/scripts/ember_ceff_closure_confirmation.py at the "
                    "claimed commit")
            else:
                real_hash = _git_blob_sha256_at_commit(
                    ROOT, source_sha,
                    "src/ember/governance/scripts/ember_ceff_closure_confirmation.py")
                if real_hash is None:
                    findings.append(
                        "could not read "
                        "src/ember/governance/scripts/ember_ceff_closure_confirmation.py at "
                        f"commit {source_sha} to verify harness_sha")
                elif real_hash != harness_sha_field:
                    findings.append(
                        f"harness_sha {harness_sha_field!r} does not match "
                        f"the real sha256 {real_hash!r} of "
                        "src/ember/governance/scripts/ember_ceff_closure_confirmation.py at "
                        f"commit {source_sha} (inert/cosmetic field)")
    elif harness_sha_field:
        # A harness_sha with no commit to check it against can never be
        # execution-bound -- it is decorative by construction.
        findings.append(
            "harness_sha present but import_provenance.source_commit_sha "
            "absent -- harness_sha cannot be bound to a real commit "
            "(inert cosmetic field)")

    # --- [ISSUE #683 cure, point 4] governor plausibility + FLOPs recompute --
    governor = conf_dict.get("governor")
    governor = governor if isinstance(governor, dict) else None
    if not governor:
        findings.append(
            "confirmation_run.governor missing -- cannot verify GPU-VRAM "
            "plausibility")
    else:
        free_gib = governor.get("free_gib")
        total_gib = governor.get("total_gib")
        if not (isinstance(free_gib, (int, float)) and isinstance(total_gib, (int, float))):
            findings.append(
                "confirmation_run.governor.free_gib/total_gib missing or "
                "non-numeric")
        elif not (0 < total_gib <= GOVERNOR_TOTAL_GIB_MAX
                  and 0 <= free_gib <= total_gib + GOVERNOR_GIB_TOLERANCE):
            findings.append(
                f"confirmation_run.governor free_gib={free_gib}/"
                f"total_gib={total_gib} outside plausible GPU-VRAM range "
                f"(0, {GOVERNOR_TOTAL_GIB_MAX}]")

    g_budget = conf_dict.get("g_budget")
    g_budget = g_budget if isinstance(g_budget, dict) else None
    if not g_budget or g_budget.get("status") != "GREEN":
        findings.append(
            "confirmation_run.g_budget.status != 'GREEN' (got "
            f"{g_budget.get('status') if g_budget else g_budget!r})")
    else:
        detail = str(g_budget.get("detail", ""))
        m = COST_FLOPS_RE.search(detail)
        requested_run = conf_dict.get("requested_run")
        requested_run = requested_run if isinstance(requested_run, dict) else None
        if not m:
            findings.append(
                "confirmation_run.g_budget.detail has no parseable "
                "'cost=... FLOPs' figure to cross-check")
        elif not requested_run:
            findings.append(
                "confirmation_run.requested_run missing -- cannot "
                "recompute the 6*params*tokens FLOPs figure")
        else:
            r_params = requested_run.get("params")
            r_batch = requested_run.get("batch")
            r_seq = requested_run.get("seq")
            r_steps = requested_run.get("total_steps")
            if not all(isinstance(v, (int, float))
                       for v in (r_params, r_batch, r_seq, r_steps)):
                findings.append(
                    "confirmation_run.requested_run params/batch/seq/"
                    "total_steps missing or non-numeric -- cannot "
                    "recompute FLOPs")
            else:
                stated_cost = float(m.group(1))
                recomputed_cost = 6.0 * r_params * r_batch * r_seq * r_steps
                rel_diff = (abs(recomputed_cost - stated_cost) / stated_cost
                            if stated_cost else float("inf"))
                if rel_diff > FLOPS_RECOMPUTE_TOLERANCE:
                    findings.append(
                        f"g_budget cost {stated_cost} FLOPs does not match "
                        f"probe-recomputed 6*params*batch*seq*total_steps = "
                        f"{recomputed_cost} FLOPs (rel diff {rel_diff:.4f} "
                        f"> {FLOPS_RECOMPUTE_TOLERANCE})")

    # CHK clause: ONE bounded confirmation run, with throughput within band of
    # the projection (the does-NOT-count: "projection with no confirmation run").
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
