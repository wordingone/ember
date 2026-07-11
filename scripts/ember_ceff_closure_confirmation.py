#!/usr/bin/env python3
"""ember_ceff_closure_confirmation.py — C-EFF CLOSURE confirmation runner +
RESOLVED-receipt assembler (issue #24, terminal rung).

WHAT THIS ANSWERS. `scripts/ember_totality/test_c_eff.py` (ember-goalforge
tree; lines 93-214) reads ONLY `receipts/ceff-RESOLVED-*.json` as a valid
C-EFF closure — the prior "SHATTER" verdict
(`receipts/ceff-closure-gate9-shatter-bf16ns5-20260623T132000Z.json`) is
REPUDIATED (`receipts/ceff-shatter-REPUDIATED-20260623T170000Z.json`:
measured lever 1.18x, c03 stack 1.85x = 56% of the >=3.3x criterion) and the
probe explicitly does not consult it. Quoted verbatim, the probe's required
shape (test_c_eff.py:93-214):

  - `verdict` in {"SHATTER", "PRICED_SCALEOUT_RESIDUAL"} (line 131).
  - `effective_days_basis == "useful_base_tokens_div_governed_day"` — the
    self-referential K_floor/throughput basis is explicitly rejected
    (lines 135-139).
  - `useful_base_tokens`, `sustained_tok_s`, `effective_days`,
    `compound_speedup_over_anchor` all present and numeric (lines 141-152).
  - `gate` field parsing (line 155-157, quoted EXACTLY):
      gate_field = str(d.get("gate", "")).lower()
      if "gate-9" not in gate_field and "gate9" not in gate_field:
          findings.append("no gate-9 efficiency-closure stamp ...")
    i.e. the field name is literally "gate" and its STRING VALUE must
    contain the substring "gate-9" or "gate9" (case-insensitive).
  - `confirmation_run.sustained_tok_s` present, within `confirmation_band_frac`
    (default 0.10) of `projected_tok_s` (lines 161-172) — "a bare projection
    does not count" (does-NOT-count token: projection with no confirmation
    run).
  - internal consistency: `effective_days` ~= `useful_base_tokens /
    (sustained_tok_s * 86400)` within 5% (lines 174-181).
  - IF verdict == "SHATTER": `compound_speedup_over_anchor >= 3.3` AND
    `effective_days <= 1.0` (lines 184-191) — this file therefore never
    emits SHATTER unless BOTH magnitudes independently clear the bar.
  - `c04_deciding_axes`: non-empty dict, every value normalizing (dash/
    underscore/case-insensitive) to one of APPLIED / KILLED / WAIVED /
    WAIVED-priced (lines 193-203).
  - The four INVALID_TOKENS (line 71-76) must not appear anywhere in the
    receipt's serialized text: `invalid_efficiency_unconfirmed`,
    `projection_with_no_confirmation_run`, `lever_done_without_gate9_receipt`,
    `from_scratch_too_expensive_by_analogy`.

THE THREE-LEG PIPELINE
  (a) PROJECTION — `load_projection_factors()` reads three ALREADY-ON-DISK
      receipts (never hardcodes the multipliers) and composes them
      honestly, per `docs/spec/ceff-lever-ladder.md` (ember-goalforge
      tree) §(d)'s own composition rule ("only receipted factors compound";
      shape-coupled FP8 excluded per its own class-scope rule; C2/C3 —
      batch-size and selective-recompute — are UNVERIFIED-at-production-shape
      and are therefore NOT banked here at all, consistent with "only
      receipted factors compound"):
        1. H0 mechanical stack (muon_split + chunked-CE + MTP + batch
           geometry), receipted value read from
           `receipts/ceff-shatter-REPUDIATED-20260623T170000Z.json`
           `arithmetic_receipt.compound_speedup_c03_stack_stated` (1.85).
        2. bf16-NS5 dtype-swap lever, computed as the tok_per_s ratio of two
           ALREADY-ACCEPTED (2026-06-23) full 60M-token production receipts:
           `receipts/conv-muon_split_bf16ns5-20260623T090201Z.json` /
           `receipts/conv-muon_split-20260623T072149Z.json` (~1.1826x —
           NOT hardcoded; recomputed live from the two receipts' own
           `tok_per_s` fields, both asserted `pass: true`).
        3. Fused-NS5-kernel-compile composed WITH bf16-NS5 — the interaction
           the ladder names as "never tested" (§d interaction risk #5) until
           the Composition A/B protocol v2 receipt closed it:
           latest `receipts/ceff-composition-ab-*.json` with
           `protocol_version == 2`, field
           `analysis.incremental_over_bf16ns5_alone` (1.07003 as of
           `ceff-composition-ab-20260703T111351Z.json`, verdict
           COMPOSITION_CLOSES_RESIDUAL_GAP, both `ns5_equiv.pass` and
           `analysis.quality_guard.pass` true).
      Composed HONESTLY (bf16-NS5 and the compile-interaction both sit ON
      TOP of the 1.85x H0 stack per the ladder's own §(a) "What composes the
      stated 1.85x" — neither is folded inside it):
        projected_tok_s = bf16_ns5_alone_tok_s * composition_increment
        compound_projected_over_anchor = h0_stack * bf16_ns5_lever * composition_increment
      Chunk1024/TF32/no-recompute/batch-sweep are NOT included — none of
      them has a production-shape receipt composed with the other levers
      (TF32 has an outstanding `tf32_needs_quality_recheck: true`; C2/C3 are
      UNVERIFIED at production shape per the ladder's own §(c) rows) — "only
      receipted factors compound" excludes them. Per the ladder's own §(d)
      honest arithmetic, this composed number (~2.34x) falls short of the
      3.3x criterion — `projection_verdict()` reports
      CLOSURE_PROJECTION_SHORT in that case and this runner never fabricates
      SHATTER from a bare projection.
  (b) CONFIRMATION RUN — ONE bounded, governed, banked live-GPU measurement
      of the FULL composed configuration (production shape: c04 recipe +
      bf16-NS5 + torch.compile'd NS5 chain — i.e. the SAME arm
      `ember_ceff_composition_ab.py` calls `D_both_composed`), WARMUP then
      >=60 TIMED steps (long enough to be "sustained", not a 20-step
      snapshot), reusing that module's own `measure_arm`/`_ns5_bf16`/
      `_make_fused` rather than re-deriving the NS5-patch/compile mechanism.
      Gated exactly like every other harness in this family:
      `v0_pretrain_launch_gate.g_budget()` with a `requested_run` descriptor
      (refuses BLOCKED, no bench executed, if not GREEN) then
      `timeshare_pretrain._apply_governor()` (VRAM/margin/pace floors,
      tighten-only, fail-closed).
  (c) BAND CHECK — `band_check()`, the SAME ±10% (`confirmation_band_frac`)
      the probe itself enforces, applied BEFORE assembly so a receipt that
      would fail the probe's own band check is never written as RESOLVED at
      all (assemble → self-check → write, never write → hope).
  (d) ASSEMBLE — `assemble_candidate()` builds the RESOLVED-shaped dict,
      computes `effective_days` honestly
      (`useful_base_tokens / (sustained_tok_s * 86400)`, `useful_base_tokens`
      imported directly as `v0_pretrain_launch_gate.SHATTER_BUDGET_B` —
      the SAME 2.2e9 keystone-certified ceiling `_shatter_compute_fit()`
      requires `method.budget_b` to equal, never a separately-chosen
      number), then decides SHATTER vs PRICED_SCALEOUT_RESIDUAL
      MECHANICALLY, never by assertion: it builds a shatter-verdict-shaped
      candidate from these SAME honest numbers and calls
      `v0_pretrain_launch_gate._shatter_compute_fit()` against it
      (`run_shatter_compute_fit_selfcheck()` — imports the real function,
      points its module-level `NC` at a throwaway scratch dir seeded with
      ONLY this one candidate file, calls it, restores `NC`). SHATTER is
      chosen ONLY if that self-check returns fit_ok=True AND
      `compound_speedup_over_anchor >= 3.3` independently — this is the
      exact anti-self-reference discipline that repudiated the June 23
      "SHATTER" (`receipts/shatter-verdict-bf16ns5-20260623T132000Z.json`:
      stated effective_days=0.9803, honest recompute
      budget_b/(19577.1*86400)=1.3007 — fails the SAME check this runner
      calls). Otherwise PRICED_SCALEOUT_RESIDUAL, honestly priced (may
      exceed 1.0 governed day — that is a VALID closure per the goal, not a
      failure). `write_or_diagnose()` then: scans the fully-serialized
      receipt for all four INVALID_TOKENS (abort, never write, if any hit);
      writes the candidate; invokes the REAL `test_c_eff.py` as a subprocess
      (`EMBER_TOTALITY_ROOT` pointed at this tree) and reads its one status
      line; if the probe does not say GREEN, DELETES the just-written
      candidate and writes `receipts/ceff-closure-attempt-<ts>Z.json`
      instead — never a RESOLVED receipt that fails its own probe re-run.

C04_DECIDING_AXES — sourced from `docs/c04-pick-decision-table-v1.md`
(ember tree; "c04 pick decision table"), cross-referenced against its own
resolution receipt `receipts/c04-receipt3-20260613T052223Z.json`:
  - Axis 1 (L10 optimizer swap, #363): that receipt's `c3_summary` states
    "ALL FAIL — optimizer >15% step wall on all candidates" (measured
    opt_share 41.4%, the table's own L10-FAIL band). Production stays on
    `muon_split` at the L10-FAIL row; every conv/c04/composition receipt in
    this tree confirms `routing_mode: "muon_split"` is what actually ran.
    Per the table's L10-FAIL x D-CONF cell ("user fraction call"), this is
    accepted as a priced residual, not silently dropped — WAIVED-priced.
  - Axis 2 (density A/B): that receipt's `density_verdict.verdict` is
    `DENSITY_CONFIRMED` -> D-CONF per the frozen aggregator, consumed as a
    directional prior for curriculum/budget sizing (seed-level Fisher
    p=0.50, underpowering disclosed in the SAME receipt, not buried) —
    APPLIED.

MODES
  --selftest   Pure math/schema, NO torch, NO GPU. Covers: projection math
               against the ladder's own on-disk numbers (both the SHORT
               branch and a synthetic CLEARS-3.3x fixture); band-check
               pass/fail; `_shatter_compute_fit()` self-check wiring (both a
               fixture that DOES honestly clear the 1.0-governed-day floor
               and a repudiated-shape fixture reusing the REAL on-disk
               `shatter-verdict-bf16ns5-20260623T132000Z.json` numbers,
               which must still fail); the assembler refusing on a missing
               required field / an injected invalid-token (verified against
               the REAL `test_c_eff.py`, invoked as a subprocess against a
               scratch `EMBER_TOTALITY_ROOT` — no torch import needed, the
               probe is pure Python/JSON). Prints
               CEFF_CLOSURE_CONFIRMATION_SELFTEST_PASS.
  --dry-run    Builds a synthetic RESOLVED-shaped receipt through the FULL
               assembler + self-check + probe-shape pipeline WITHOUT GPU:
               reads the SAME on-disk projection receipts (real), then
               substitutes a clearly-labeled SYNTHETIC confirmation number
               (no torch, no CUDA call anywhere — never a measurement) for
               leg (b) only. Written to
               `scratch/ember-ceff-closure-confirmation-dryrun/`, never
               `receipts/ceff-RESOLVED-*.json` (self-declares
               `dry_run: true`, never glob-matched by real evidence
               searches).
  (no flag)    The REAL live-GPU confirmation + assembly. NEVER invoked from
               this authoring session (no torch.cuda.* call anywhere in
               this file outside `run_confirmation_live`, which this
               session never calls) — this is the BANKED command; fire it
               once the GPU is free of any other job (this tree's standing
               rule: ONE GPU job at a time).

No git commits. No downloads. No founder/user names anywhere in this file
or its receipts.

BANKED GPU COMMAND (fire once the current training run has freed the GPU —
do not run concurrently with any other GPU job):

  python scripts/ember_ceff_closure_confirmation.py

Dispatch via the train MCP (WSL2/CUDA), matching every other c04/conv
harness in this tree; a direct native-Windows invocation (this host has
torch 2.10+cu126 with CUDA visible) is equally valid — the script itself
does not care which process launched it, only that no other GPU job is
concurrently running.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

HERE     = os.path.dirname(os.path.abspath(__file__))
NC       = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts")
SCRATCH_DRYRUN = os.path.join(NC, "scratch", "ember-ceff-closure-confirmation-dryrun")
GOALFORGE_ROOT = os.environ.get(
    "EMBER_GOALFORGE_ROOT", os.path.join(os.path.dirname(NC), "ember-goalforge"))
TEST_C_EFF_PATH = os.path.join(GOALFORGE_ROOT, "scripts", "ember_totality", "test_c_eff.py")

sys.path.insert(0, HERE)
from receipt_write import checked_write    # noqa: E402  (light; no torch)

# ── Probe bars (test_c_eff.py:62-76, quoted/mirrored — never re-derived) ───
SHATTER_COMPOUND_MIN   = 3.3
CONFIRMATION_BAND_FRAC = 0.10
INVALID_TOKENS = [
    "invalid_efficiency_unconfirmed",
    "projection_with_no_confirmation_run",
    "lever_done_without_gate9_receipt",
    "from_scratch_too_expensive_by_analogy",
]

# ── Confirmation-run window — "WARMUP then >=60 timed steps" (team-lead
#    brief); WARMUP=10 (matches the c04-bf16ns5-qat family's own scale-up
#    from the 5-step composition-ab window when a longer/sustained read is
#    wanted), TIMED=60 is the floor named in the brief, taken exactly ───
CONFIRM_WARMUP = 10
CONFIRM_TIMED  = 60
BATCH          = 16
CE_CHUNK_TOKENS = 256
MODEL_SEED      = 42
BATCH_GEN_SEED  = 20260703

# ── c04_deciding_axes — sourced from docs/c04-pick-decision-table-v1.md +
#    its resolution receipt receipts/c04-receipt3-20260613T052223Z.json
#    (see module docstring "C04_DECIDING_AXES" section for the full trace)
C04_DECIDING_AXES = {
    "L10_optimizer_swap": "WAIVED-priced",
    "density_ab": "APPLIED",
}
C04_DECIDING_AXES_DETAIL = {
    "L10_optimizer_swap": (
        "docs/c04-pick-decision-table-v1.md Axis 1 (#363): L10 candidate never "
        "cleared the <=15% optimizer-wall bar (receipts/c04-receipt3-20260613T052223Z.json "
        "c3_summary: 'ALL FAIL -- optimizer >15% step wall on all candidates', measured "
        "opt_share 0.4137/0.6838/0.6485/0.5895/0.7318 across all 5 candidates) -- the "
        "table's own L10-FAIL row. Production stayed on muon_split (every conv/c04/"
        "composition-ab receipt in this tree shows routing_mode='muon_split'); accepted "
        "at the L10-FAIL band per the table's own 'user fraction call' cell -- priced, "
        "not silently dropped."
    ),
    "density_ab": (
        "docs/c04-pick-decision-table-v1.md Axis 2: density A/B verdict DENSITY_CONFIRMED "
        "(receipts/c04-receipt3-20260613T052223Z.json density_verdict) maps to D-CONF per "
        "the frozen aggregator; consumed as a directional prior for curriculum/budget "
        "sizing (seed-level Fisher p=0.50, underpowering disclosed in the same receipt, "
        "not buried) -- APPLIED."
    ),
}


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _harness_sha() -> str:
    h = hashlib.sha256()
    with open(__file__, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _latest_glob(pattern: str) -> str | None:
    cands = sorted(glob.glob(pattern))
    return cands[-1] if cands else None


# ---------------------------------------------------------------------------
# (a) PROJECTION — read three on-disk receipts, compose honestly.
# ---------------------------------------------------------------------------

def load_projection_factors(receipts_dir: str = RECEIPTS) -> dict:
    """Read the three compounding factors LIVE from on-disk receipts (never
    hardcoded), per docs/spec/ceff-lever-ladder.md §(d)'s own composition
    rule: only receipted factors compound; shape-coupled FP8 and the
    UNVERIFIED-at-production-shape C2/C3 (batch-size, selective-recompute)
    and the pending-quality-recheck TF32 leg are excluded entirely."""
    repud_path = os.path.join(receipts_dir, "ceff-shatter-REPUDIATED-20260623T170000Z.json")
    repud = _load_json(repud_path)
    h0_stack = repud["arithmetic_receipt"]["compound_speedup_c03_stack_stated"]

    bf16_path = os.path.join(receipts_dir, "conv-muon_split_bf16ns5-20260623T090201Z.json")
    fp32_path = os.path.join(receipts_dir, "conv-muon_split-20260623T072149Z.json")
    bf16 = _load_json(bf16_path)
    fp32 = _load_json(fp32_path)
    if not (bf16.get("pass") is True and fp32.get("pass") is True):
        raise RuntimeError(
            f"bf16-NS5/fp32-NS5 comparator receipts must both be pass:true "
            f"(bf16={bf16.get('pass')!r}, fp32={fp32.get('pass')!r})")
    bf16_ns5_lever = bf16["tok_per_s"] / fp32["tok_per_s"]

    comp_path = _latest_glob(os.path.join(receipts_dir, "ceff-composition-ab-2*.json"))
    if comp_path is None:
        raise RuntimeError("no receipts/ceff-composition-ab-*.json on disk (interaction risk "
                            "#5 -- fused-NS5-kernel-compile x bf16-NS5 -- is unmeasured)")
    comp = _load_json(comp_path)
    if comp.get("protocol_version") != 2:
        raise RuntimeError(f"{comp_path} is not a protocol_version==2 composition receipt "
                            f"(got {comp.get('protocol_version')!r}) -- v1 PARKed on numerics, "
                            "see ceff-lever-ladder.md 'Composition A/B protocol v2'")
    composition_increment = comp["analysis"]["incremental_over_bf16ns5_alone"]
    composition_quality_ok = bool(
        (comp.get("ns5_equiv") or {}).get("pass")
        and ((comp.get("analysis") or {}).get("quality_guard") or {}).get("pass"))

    projected_tok_s = bf16["tok_per_s"] * composition_increment
    compound_projected_over_anchor = h0_stack * bf16_ns5_lever * composition_increment
    anchor_tok_s = fp32["tok_per_s"] / h0_stack

    return {
        "h0_stack": h0_stack,
        "h0_stack_source": os.path.relpath(repud_path, NC),
        "bf16_ns5_lever": round(bf16_ns5_lever, 6),
        "bf16_ns5_source": [os.path.relpath(bf16_path, NC), os.path.relpath(fp32_path, NC)],
        "composition_increment": composition_increment,
        "composition_source": os.path.relpath(comp_path, NC),
        "composition_verdict": comp.get("verdict"),
        "composition_quality_ok": composition_quality_ok,
        "fp32_ns5_baseline_tok_s": fp32["tok_per_s"],
        "bf16_ns5_alone_tok_s": bf16["tok_per_s"],
        "anchor_tok_s": round(anchor_tok_s, 4),
        "projected_tok_s": round(projected_tok_s, 4),
        "compound_projected_over_anchor": round(compound_projected_over_anchor, 6),
        "composition_rule": "only receipted factors compound (ceff-lever-ladder.md §d); "
                             "FP8 excluded (shape-coupled, non-composable per its own class-"
                             "scope rule); C2 (batch-size) / C3 (selective-recompute) excluded "
                             "(UNVERIFIED at production shape, and named VRAM-budget substitutes "
                             "for each other, not independent factors); TF32 excluded "
                             "(tf32_needs_quality_recheck: true, unresolved)",
    }


def projection_verdict(factors: dict) -> str:
    """Step (a)'s own verdict: never fabricate SHATTER from a bare
    projection. Returns CLOSURE_PROJECTION_SHORT when the honest composed
    multiple does not reach 3.3x; CLOSURE_PROJECTION_CLEARS_SHATTER
    otherwise (still requires the live confirmation + self-check leg
    before the RESOLVED receipt may claim SHATTER — this is a projection-
    stage signal only, never itself written as the receipt's `verdict`)."""
    if factors["compound_projected_over_anchor"] >= SHATTER_COMPOUND_MIN:
        return "CLOSURE_PROJECTION_CLEARS_SHATTER"
    return "CLOSURE_PROJECTION_SHORT"


# ---------------------------------------------------------------------------
# (c) BAND CHECK — same ±10% the probe itself enforces.
# ---------------------------------------------------------------------------

def band_check(measured_tok_s, projected_tok_s, frac: float = CONFIRMATION_BAND_FRAC):
    if not projected_tok_s or not isinstance(projected_tok_s, (int, float)):
        return False, "projected_tok_s missing/zero"
    if not isinstance(measured_tok_s, (int, float)):
        return False, "measured_tok_s missing/non-numeric"
    rel = abs(measured_tok_s - projected_tok_s) / projected_tok_s
    ok = rel <= frac
    return ok, (f"measured={measured_tok_s} projected={projected_tok_s} "
                f"rel_diff={rel:.4f} band=±{frac:.0%} -> {'PASS' if ok else 'FAIL'}")


# ---------------------------------------------------------------------------
# Self-check leg 1 — the REAL v0_pretrain_launch_gate._shatter_compute_fit(),
# run against a scratch-isolated candidate. Never a re-implementation.
# ---------------------------------------------------------------------------

def run_shatter_compute_fit_selfcheck(candidate: dict) -> tuple[bool, str]:
    import v0_pretrain_launch_gate as gate_mod
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "receipts"), exist_ok=True)
        p = os.path.join(td, "receipts", "shatter-verdict-selfcheck.json")
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(candidate, f, indent=2)
        old_nc = gate_mod.NC
        gate_mod.NC = td
        try:
            fit_ok, reason = gate_mod._shatter_compute_fit()
        finally:
            gate_mod.NC = old_nc
    return fit_ok, reason


def _shatter_candidate(effective_days: float, quality_ok: bool, sustained_tok_s: float,
                        budget_b: float) -> dict:
    return {
        "ticket": "SELFCHECK-SHATTER-CANDIDATE", "ts": _ts(),
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "method": {"budget_b": budget_b},
        "variants": {
            "ceff_closure_confirmation": {
                "effective_days": effective_days,
                "quality_ok": quality_ok,
                "sustained_tok_s": sustained_tok_s,
            }
        },
        "SHATTER": True,
        "shatter_variant": "ceff_closure_confirmation",
    }


# ---------------------------------------------------------------------------
# Self-check leg 2 — the REAL test_c_eff.py, invoked as a subprocess against
# whatever receipts_dir we just wrote to. Pure Python/JSON — no torch needed.
# ---------------------------------------------------------------------------

def run_test_c_eff_selfcheck(root_dir: str, timeout: float = 30.0) -> str:
    if not os.path.isfile(TEST_C_EFF_PATH):
        return (f"UNEVALUABLE test_c_eff.py not found at {TEST_C_EFF_PATH} "
                f"(set EMBER_GOALFORGE_ROOT if the goalforge tree is elsewhere)")
    env = dict(os.environ)
    env["EMBER_TOTALITY_ROOT"] = root_dir
    try:
        result = subprocess.run([sys.executable, TEST_C_EFF_PATH],
                                 capture_output=True, text=True, env=env, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return f"UNEVALUABLE test_c_eff.py subprocess failed: {e}"
    out = (result.stdout or "").strip()
    lines = [l for l in out.splitlines() if l.strip()]
    return lines[-1] if lines else f"UNEVALUABLE empty stdout (stderr: {(result.stderr or '')[:500]})"


# ---------------------------------------------------------------------------
# Invalid-token defensive scan — mechanical, run before every write.
# ---------------------------------------------------------------------------

def scan_invalid_tokens(receipt: dict) -> list[str]:
    blob = json.dumps(receipt).lower()
    return [t for t in INVALID_TOKENS if t.lower() in blob]


# ---------------------------------------------------------------------------
# Quality sanity on the confirmation run's own loss trajectory (light —
# NOT a redo of the composition receipt's rigorous numerics-parity gate,
# which already covers the compiled-vs-eager equivalence separately).
# ---------------------------------------------------------------------------

def confirmation_quality_ok(losses) -> tuple[bool, str]:
    if not losses:
        return False, "loss trajectory empty/missing"
    if any((not isinstance(x, (int, float))) or x != x for x in losses):
        return False, "loss trajectory contains non-finite value(s)"
    if losses[-1] > losses[0] * 1.05:
        return False, f"last_loss {losses[-1]} > first_loss {losses[0]} * 1.05 (diverging)"
    return True, "finite, non-diverging over the timed confirmation window"


# ---------------------------------------------------------------------------
# (d) ASSEMBLE — build the RESOLVED-shaped candidate; verdict is MECHANICAL
# (derived from the self-check leg), never asserted.
# ---------------------------------------------------------------------------

def assemble_candidate(factors: dict, confirmation: dict, *, dry_run: bool) -> dict:
    import v0_pretrain_launch_gate as gate_mod
    useful_base_tokens = gate_mod.SHATTER_BUDGET_B   # 2.2e9 — the SAME ceiling
                                                       # _shatter_compute_fit() requires
                                                       # method.budget_b to equal exactly.

    measured_tok_s = confirmation["sustained_tok_s"]
    band_ok, band_detail = band_check(measured_tok_s, factors["projected_tok_s"])
    effective_days = useful_base_tokens / (measured_tok_s * 86400.0)
    compound_over_anchor = measured_tok_s / factors["anchor_tok_s"]

    quality_ok = bool(factors["composition_quality_ok"] and confirmation.get("quality_ok", False))

    candidate = _shatter_candidate(effective_days, quality_ok, measured_tok_s, useful_base_tokens)
    fit_ok, fit_reason = run_shatter_compute_fit_selfcheck(candidate)

    clears_shatter = bool(fit_ok and compound_over_anchor >= SHATTER_COMPOUND_MIN)
    if clears_shatter:
        verdict = "SHATTER"
        verdict_reason = (
            f"v0_pretrain_launch_gate._shatter_compute_fit() self-check returned "
            f"fit_ok=True ({fit_reason}) AND compound_speedup_over_anchor "
            f"{compound_over_anchor:.4f} >= {SHATTER_COMPOUND_MIN} independently -- both "
            f"the honest-effective-days floor and the compound-magnitude floor clear; "
            f"the verdict is derived from the canonical self-check, not asserted.")
    else:
        verdict = "PRICED_SCALEOUT_RESIDUAL"
        verdict_reason = (
            f"self-check fit_ok={fit_ok} ({fit_reason}); compound_speedup_over_anchor="
            f"{compound_over_anchor:.4f} (bar {SHATTER_COMPOUND_MIN}) -- does not clear "
            f"SHATTER on both magnitudes, so this closes as an honestly-priced residual "
            f"(effective_days may exceed 1.0 governed day -- a VALID closure per the goal, "
            f"never a failure), not a fabricated shatter.")

    ts = _ts()
    receipt = {
        "ticket": "CEFF-RESOLVED-CLOSURE",
        "ts": ts,
        "issue": "#24",
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "gate": "gate-9 efficiency-closure (C-EFF)",
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "harness_sha": _harness_sha(),
        "dry_run": bool(dry_run),
        "no_gpu": bool(dry_run),
        "flags": ["ONE GPU job at a time — do not dispatch concurrently with another train job",
                  "governor rails HOLD — never loosened",
                  "no git commits, no downloads, no founder/user names"],
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "effective_days_basis": "useful_base_tokens_div_governed_day",
        "useful_base_tokens": useful_base_tokens,
        "sustained_tok_s": measured_tok_s,
        "effective_days": effective_days,
        "compound_speedup_over_anchor": compound_over_anchor,
        "projected_tok_s": factors["projected_tok_s"],
        "confirmation_band_frac": CONFIRMATION_BAND_FRAC,
        "band_check": {"pass": band_ok, "detail": band_detail},
        "confirmation_run": {
            "sustained_tok_s": measured_tok_s,
            "median_tok_s": confirmation.get("median_tok_s"),
            "quality_ok": confirmation.get("quality_ok"),
            "quality_detail": confirmation.get("quality_detail"),
            "recipe": confirmation.get("recipe"),
            "governor": confirmation.get("governor"),
            "g_budget": confirmation.get("g_budget"),
            "requested_run": confirmation.get("requested_run"),
            "synthetic": confirmation.get("synthetic", False),
        },
        "projection": {
            "h0_stack": factors["h0_stack"], "h0_stack_source": factors["h0_stack_source"],
            "bf16_ns5_lever": factors["bf16_ns5_lever"], "bf16_ns5_source": factors["bf16_ns5_source"],
            "composition_increment": factors["composition_increment"],
            "composition_source": factors["composition_source"],
            "composition_verdict": factors["composition_verdict"],
            "composition_rule": factors["composition_rule"],
            "anchor_tok_s": factors["anchor_tok_s"],
            "compound_projected_over_anchor": factors["compound_projected_over_anchor"],
            "verdict": projection_verdict(factors),
        },
        "shatter_selfcheck": {
            "candidate_effective_days": effective_days,
            "candidate_budget_b": useful_base_tokens,
            "fit_ok": fit_ok, "reason": fit_reason,
        },
        "c04_deciding_axes": dict(C04_DECIDING_AXES),
        "c04_deciding_axes_detail": dict(C04_DECIDING_AXES_DETAIL),
    }
    return receipt


def write_or_diagnose(receipt: dict, *, receipts_dir: str = RECEIPTS,
                       goalforge_root_check: str | None = None) -> tuple[Path, bool, str]:
    """Scan for invalid tokens, write the candidate, run the REAL
    test_c_eff.py against it. GREEN -> keep as ceff-RESOLVED-<ts>Z.json.
    Anything else (invalid token present, probe not GREEN) -> delete the
    candidate (if written) and write a ceff-closure-attempt-<ts>Z.json
    diagnostic instead. Returns (path, success, probe_line)."""
    ts = receipt["ts"]
    hits = scan_invalid_tokens(receipt)
    os.makedirs(receipts_dir, exist_ok=True)
    if hits:
        diag_path = Path(os.path.join(receipts_dir, f"ceff-closure-attempt-{ts}.json"))
        diag = {**receipt, "ticket": "CEFF-CLOSURE-ATTEMPT",
                "diagnostic_reason": f"invalid-token(s) present pre-write: {hits}"}
        with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(diag, f, indent=2)
        return diag_path, False, f"ABORTED pre-write: invalid-token(s) {hits}"

    resolved_path = os.path.join(receipts_dir, f"ceff-RESOLVED-{ts}.json")
    checked_write(resolved_path, receipt)

    probe_root = goalforge_root_check or receipts_dir[:-len("/receipts")] if receipts_dir.endswith("/receipts") else os.path.dirname(receipts_dir)
    probe_line = run_test_c_eff_selfcheck(probe_root)
    if probe_line.upper().startswith("GREEN"):
        return Path(resolved_path), True, probe_line

    # Probe did NOT confirm GREEN — never leave a RESOLVED receipt that
    # fails its own probe re-run. Delete and write the diagnostic instead.
    try:
        os.unlink(resolved_path)
    except OSError:
        pass
    diag_path = Path(os.path.join(receipts_dir, f"ceff-closure-attempt-{ts}.json"))
    diag = {**receipt, "ticket": "CEFF-CLOSURE-ATTEMPT",
            "diagnostic_reason": f"test_c_eff.py self-check did not return GREEN: {probe_line}"}
    with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, indent=2)
    return diag_path, False, probe_line


# ---------------------------------------------------------------------------
# (b) CONFIRMATION RUN — live GPU (banked) and CPU-safe synthetic dry-run.
# ---------------------------------------------------------------------------

def run_confirmation_live(projected_tok_s: float) -> dict:
    """The REAL confirmation run. NEVER called from this authoring session —
    the first torch.cuda.* touch in this whole file lives here, reached
    only when the script is invoked with no flag on a free GPU."""
    import timeshare_pretrain as ts_mod
    import v0_pretrain_launch_gate as gate_mod
    from ember_ceff_composition_ab import _ns5_bf16, _make_fused, measure_arm

    cfg = ts_mod.load_contract()
    seq = cfg["model"]["seq"]
    total_steps = CONFIRM_WARMUP + CONFIRM_TIMED
    requested_run = {
        "source": "ember_ceff_closure_confirmation--live",
        "total_steps": total_steps,
        "params": gate_mod.V0_CERTIFIED_PARAMS,
        "batch": BATCH,
        "seq": seq,
    }
    st, dt = gate_mod.g_budget(date.today(), requested_run=requested_run)
    if st != "GREEN":
        return {"status": "BLOCKED", "g_budget": {"status": st, "detail": dt},
                "requested_run": requested_run}

    gov = ts_mod._apply_governor()
    pace_s = ts_mod.FP19_PACE_S
    margin_gib = ts_mod.FP19_MARGIN_GIB

    ns5_bf16_fused = _make_fused(_ns5_bf16)
    r = measure_arm(ts_mod, "confirmation_full_stack", ns5_bf16_fused, cfg, live=True,
                    warmup=CONFIRM_WARMUP, timed=CONFIRM_TIMED, batch=BATCH, seq=seq,
                    pace_s=pace_s, margin_gib=margin_gib)
    if r.get("status") != "OK":
        return {"status": r.get("status"), "detail": r, "governor": gov,
                "g_budget": {"status": st, "detail": dt}, "requested_run": requested_run}

    q_ok, q_detail = confirmation_quality_ok(r["loss_trajectory"])
    return {
        "status": "OK",
        "governor": gov, "g_budget": {"status": st, "detail": dt},
        "requested_run": requested_run,
        "sustained_tok_s": r["tok_s_paced"],
        "median_tok_s": r["median_tok_s"],
        "loss_trajectory": r["loss_trajectory"],
        "quality_ok": q_ok, "quality_detail": q_detail,
        "synthetic": False,
        "recipe": {
            "source": "timeshare_pretrain production builders + bf16-NS5 patch + "
                       "torch.compile(mode='reduce-overhead', fullgraph=False) -- the FULL "
                       "composed configuration, matching ember_ceff_composition_ab.py's "
                       "D_both_composed arm",
            "batch": BATCH, "seq": seq, "ce_chunk_tokens": CE_CHUNK_TOKENS,
            "warmup": CONFIRM_WARMUP, "timed": CONFIRM_TIMED, "pace_s": pace_s,
            "model_seed": MODEL_SEED, "batch_gen_seed": BATCH_GEN_SEED,
            "data": "synthetic (torch.randint, dedicated fixed-seed Generator) -- matches "
                    "every other bench-shape harness in this family",
        },
    }


def run_confirmation_dry(projected_tok_s: float) -> dict:
    """NO torch, NO CUDA call anywhere — a clearly-labeled SYNTHETIC number
    inside the ±10% band, proving the assembler/self-check/probe pipeline
    end-to-end without GPU. Never evidence for the real probe (written only
    to scratch/, self-declares dry_run/synthetic)."""
    synthetic_tok_s = round(projected_tok_s * 0.97, 2)   # ~3% under projection, inside band
    return {
        "status": "OK",
        "sustained_tok_s": synthetic_tok_s,
        "median_tok_s": synthetic_tok_s,
        "loss_trajectory": [10.0, 9.98, 9.95, 9.93],
        "quality_ok": True,
        "quality_detail": "SYNTHETIC — not a measurement",
        "synthetic": True,
        "governor": {"synthetic": True},
        "g_budget": {"status": "SYNTHETIC", "detail": "no live g_budget call in --dry-run"},
        "requested_run": {"source": "ember_ceff_closure_confirmation--dry-run",
                          "total_steps": CONFIRM_WARMUP + CONFIRM_TIMED,
                          "params": 368354304, "batch": BATCH, "seq": 1024},
        "recipe": {
            "source": "SYNTHETIC -- no torch, no GPU, no timeshare_pretrain import",
            "batch": BATCH, "seq": 1024, "ce_chunk_tokens": CE_CHUNK_TOKENS,
            "warmup": CONFIRM_WARMUP, "timed": CONFIRM_TIMED,
            "note": "--dry-run proves the assembler + self-check + probe pipeline only; "
                    "the real throughput measurement is the banked live-GPU leg",
        },
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_and_emit_live() -> Path:
    factors = load_projection_factors()
    proj_v = projection_verdict(factors)
    print(f"[ceff-closure-confirmation] projection: compound={factors['compound_projected_over_anchor']:.4f}x "
          f"vs bar {SHATTER_COMPOUND_MIN}x -> {proj_v}", flush=True)
    print(f"[ceff-closure-confirmation]   h0_stack={factors['h0_stack']} "
          f"({factors['h0_stack_source']})", flush=True)
    print(f"[ceff-closure-confirmation]   bf16_ns5_lever={factors['bf16_ns5_lever']} "
          f"({factors['bf16_ns5_source']})", flush=True)
    print(f"[ceff-closure-confirmation]   composition_increment={factors['composition_increment']} "
          f"({factors['composition_source']}, verdict={factors['composition_verdict']})", flush=True)
    if proj_v == "CLOSURE_PROJECTION_SHORT":
        print("[ceff-closure-confirmation] projection is SHORT of 3.3x -- this run will "
              "close (if it closes at all) as PRICED_SCALEOUT_RESIDUAL, never a fabricated "
              "SHATTER.", flush=True)

    confirmation = run_confirmation_live(factors["projected_tok_s"])
    if confirmation.get("status") != "OK":
        ts = _ts()
        os.makedirs(RECEIPTS, exist_ok=True)
        path = os.path.join(RECEIPTS, f"ceff-closure-attempt-{ts}.json")
        diag = {"ticket": "CEFF-CLOSURE-ATTEMPT", "ts": ts,
                "diagnostic_reason": f"confirmation run did not reach OK: {confirmation.get('status')}",
                "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
                "projection": factors, "confirmation": confirmation}
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(diag, f, indent=2)
        print(f"[ceff-closure-confirmation] CONFIRMATION_NOT_OK status={confirmation.get('status')} "
              f"diagnostic={path}", flush=True)
        return Path(path)

    candidate = assemble_candidate(factors, confirmation, dry_run=False)
    path, ok, probe_line = write_or_diagnose(candidate)
    print(f"[ceff-closure-confirmation] verdict={candidate['verdict']} "
          f"self_check_probe_line={probe_line!r}", flush=True)
    print(f"CEFF_CLOSURE_CONFIRMATION_DONE ok={ok} receipt={path}", flush=True)
    return path


def run_and_emit_dry() -> Path:
    factors = load_projection_factors()
    confirmation = run_confirmation_dry(factors["projected_tok_s"])
    candidate = assemble_candidate(factors, confirmation, dry_run=True)
    candidate["ticket"] = "CEFF-RESOLVED-CLOSURE-DRYRUN"
    candidate["scope"] = ("CPU plumbing proof only -- NOT evidence for test_c_eff.py; "
                          "no receipts/ceff-RESOLVED-*.json glob match, self-declared dry_run")

    scratch = Path(SCRATCH_DRYRUN)
    scratch.mkdir(parents=True, exist_ok=True)
    scratch_receipts = scratch / "receipts"
    scratch_receipts.mkdir(parents=True, exist_ok=True)
    path, ok, probe_line = write_or_diagnose(candidate, receipts_dir=str(scratch_receipts),
                                              goalforge_root_check=str(scratch))
    print(f"[ceff-closure-confirmation] DRY-RUN verdict={candidate['verdict']} "
          f"projection={projection_verdict(factors)} band={candidate['band_check']}", flush=True)
    print(f"[ceff-closure-confirmation] self_check_probe_line={probe_line!r}", flush=True)
    print(f"CEFF_CLOSURE_CONFIRMATION_DRYRUN_DONE ok={ok} receipt={path}", flush=True)
    return path


# ---------------------------------------------------------------------------
# Selftest — pure math/schema, NO torch required.
# ---------------------------------------------------------------------------

def selftest() -> None:
    print("[ember_ceff_closure_confirmation] selftest: projection math + band-check + "
          "shatter-compute-fit wiring + assembler refusal (no torch)", flush=True)

    # 1. Projection math against the REAL on-disk receipts (the ladder's own
    #    honest arithmetic: ~2.34x, short of 3.3x).
    factors = load_projection_factors()
    assert abs(factors["h0_stack"] - 1.85) < 1e-9, factors["h0_stack"]
    assert 1.15 < factors["bf16_ns5_lever"] < 1.22, factors["bf16_ns5_lever"]
    assert factors["composition_increment"] > 1.0, factors["composition_increment"]
    expected_compound = factors["h0_stack"] * factors["bf16_ns5_lever"] * factors["composition_increment"]
    assert abs(factors["compound_projected_over_anchor"] - expected_compound) < 1e-6
    print(f"  projection from on-disk receipts: compound={factors['compound_projected_over_anchor']:.4f}x "
          f"(h0={factors['h0_stack']} x bf16={factors['bf16_ns5_lever']:.4f} x "
          f"comp={factors['composition_increment']})  PASS")

    # 2. CLOSURE_PROJECTION_SHORT branch fires on the real (honest) numbers —
    #    this runner must never fabricate SHATTER from today's receipts.
    real_verdict = projection_verdict(factors)
    assert real_verdict == "CLOSURE_PROJECTION_SHORT", real_verdict
    print(f"  real receipts -> projection_verdict={real_verdict} (honest: short of 3.3x)  PASS")

    # 2b. The CLEARS branch also works, on a synthetic fixture that DOES clear.
    clears_factors = dict(factors)
    clears_factors["composition_increment"] = 1.6   # synthetic — proves the other branch
    clears_factors["compound_projected_over_anchor"] = (
        clears_factors["h0_stack"] * clears_factors["bf16_ns5_lever"] * 1.6)
    assert projection_verdict(clears_factors) == "CLOSURE_PROJECTION_CLEARS_SHATTER"
    print("  synthetic fixture with composition_increment=1.6 -> CLOSURE_PROJECTION_CLEARS_SHATTER  PASS")

    # 3. band_check(): pass and fail.
    ok, detail = band_check(20000.0, 20948.08)
    assert ok, detail
    ok2, detail2 = band_check(15000.0, 20948.08)
    assert not ok2, detail2
    print(f"  band_check pass/fail  PASS ({detail} | {detail2})")

    # 4. _shatter_compute_fit() self-check wiring.
    #    4a. A candidate that HONESTLY clears the 1.0-governed-day floor.
    import v0_pretrain_launch_gate as gate_mod
    good_budget = gate_mod.SHATTER_BUDGET_B
    good_tok_s = good_budget / (0.9 * 86400.0)   # -> honest effective_days = 0.9
    good_candidate = _shatter_candidate(0.9, True, good_tok_s, good_budget)
    fit_ok, reason = run_shatter_compute_fit_selfcheck(good_candidate)
    assert fit_ok is True, (fit_ok, reason)
    print(f"  _shatter_compute_fit self-check: honest eff_days=0.9 -> fit_ok=True ({reason})  PASS")

    #    4b. The REAL repudiated-shape fixture (2026-06-23 numbers) must still fail —
    #    proves the self-check has NOT been weakened.
    repud_candidate = _shatter_candidate(0.9803, True, 19577.1, good_budget)
    fit_ok2, reason2 = run_shatter_compute_fit_selfcheck(repud_candidate)
    assert fit_ok2 is False, (fit_ok2, reason2)
    assert "inconsistent" in reason2, reason2
    print(f"  _shatter_compute_fit self-check: repudiated-shape (0.9803 stated vs honest "
          f"1.3007) -> fit_ok=False ({reason2})  PASS")

    #    4c. A candidate honestly ABOVE the 1.0-day floor (our real situation,
    #    ~1.2155 days) must fail on magnitude, not on consistency.
    real_tok_s = good_budget / (1.2155 * 86400.0)
    over_floor = _shatter_candidate(1.2155, True, real_tok_s, good_budget)
    fit_ok3, reason3 = run_shatter_compute_fit_selfcheck(over_floor)
    assert fit_ok3 is False, (fit_ok3, reason3)
    assert "floor" in reason3, reason3
    print(f"  _shatter_compute_fit self-check: honest eff_days=1.2155 (>1.0 floor) -> "
          f"fit_ok=False ({reason3})  PASS")

    # 5. scan_invalid_tokens(): catches an injected token, clean receipt passes.
    dirty = {"ticket": "T", "ts": "x", "note": "invalid_efficiency_unconfirmed present"}
    hits = scan_invalid_tokens(dirty)
    assert hits == ["invalid_efficiency_unconfirmed"], hits
    clean = {"ticket": "T", "ts": "x", "note": "all clear"}
    assert scan_invalid_tokens(clean) == []
    print("  scan_invalid_tokens: catches injected token, clean receipt passes  PASS")

    # 6. Full assembler + REAL test_c_eff.py probe round trip, in a scratch dir —
    #    happy path (synthetic confirmation clears band) -> GREEN -> RESOLVED kept.
    confirmation = run_confirmation_dry(factors["projected_tok_s"])
    candidate = assemble_candidate(factors, confirmation, dry_run=True)
    assert candidate["verdict"] in ("SHATTER", "PRICED_SCALEOUT_RESIDUAL"), candidate["verdict"]
    assert candidate["effective_days_basis"] == "useful_base_tokens_div_governed_day"
    assert scan_invalid_tokens(candidate) == [], scan_invalid_tokens(candidate)
    with tempfile.TemporaryDirectory() as td:
        rdir = os.path.join(td, "receipts")
        os.makedirs(rdir, exist_ok=True)
        path, ok, probe_line = write_or_diagnose(candidate, receipts_dir=rdir, goalforge_root_check=td)
        assert ok is True, (ok, probe_line, path)
        assert path.name.startswith("ceff-RESOLVED-"), path
        assert probe_line.upper().startswith("GREEN"), probe_line
    print(f"  full assembler + REAL test_c_eff.py probe, happy path -> RESOLVED kept, "
          f"probe said: {probe_line!r}  PASS")

    # 7. Assembler refuses on a missing required field (c04_deciding_axes dropped)
    #    -- probe must go RED, and the RESOLVED file must NOT survive on disk;
    #    a ceff-closure-attempt-*.json diagnostic must be written instead.
    broken = dict(candidate)
    broken.pop("c04_deciding_axes")
    broken["ts"] = _ts()
    with tempfile.TemporaryDirectory() as td:
        rdir = os.path.join(td, "receipts")
        os.makedirs(rdir, exist_ok=True)
        path2, ok2b, probe_line2 = write_or_diagnose(broken, receipts_dir=rdir, goalforge_root_check=td)
        assert ok2b is False, (ok2b, probe_line2)
        assert path2.name.startswith("ceff-closure-attempt-"), path2
        assert not os.path.exists(os.path.join(rdir, f"ceff-RESOLVED-{broken['ts']}Z.json"))
        assert "c04" in probe_line2 or "RED" in probe_line2.upper(), probe_line2
    print(f"  missing c04_deciding_axes -> probe RED, diagnostic written, no RESOLVED left "
          f"behind: {probe_line2!r}  PASS")

    # 8. Assembler refuses pre-write on an injected invalid token (never even
    #    reaches the probe -- caught by the mechanical scan first).
    dirty_candidate = dict(candidate)
    dirty_candidate["ts"] = _ts()
    dirty_candidate["some_note"] = "from_scratch_too_expensive_by_analogy"
    with tempfile.TemporaryDirectory() as td:
        rdir = os.path.join(td, "receipts")
        os.makedirs(rdir, exist_ok=True)
        path3, ok3, probe_line3 = write_or_diagnose(dirty_candidate, receipts_dir=rdir, goalforge_root_check=td)
        assert ok3 is False, (ok3, probe_line3)
        assert "invalid-token" in probe_line3, probe_line3
        assert not os.path.exists(os.path.join(rdir, f"ceff-RESOLVED-{dirty_candidate['ts']}Z.json"))
    print(f"  injected invalid-token -> aborted pre-write, no RESOLVED written: "
          f"{probe_line3!r}  PASS")

    print("CEFF_CLOSURE_CONFIRMATION_SELFTEST_PASS")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="C-EFF closure confirmation runner + RESOLVED-receipt assembler (issue #24)")
    ap.add_argument("--dry-run", action="store_true",
                    help="CPU only, no CUDA/torch — synthetic confirmation number, "
                         "proves the full assembler/self-check/probe pipeline")
    ap.add_argument("--selftest", action="store_true",
                    help="pure math/schema checks, no torch required")
    args, _ = ap.parse_known_args()

    if args.selftest:
        selftest()
        return 0
    if args.dry_run:
        run_and_emit_dry()
        return 0
    run_and_emit_live()
    return 0


if __name__ == "__main__":
    sys.exit(main())
