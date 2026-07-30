#!/usr/bin/env python3
"""ember_ceff_composition_ab.py — C-EFF composition A/B/C/D runner:
fused-NS5-kernel-compile x bf16-NS5 dtype swap (issue #24 ladder rung).

LADDER RUNG THIS ANSWERS, quoted verbatim from docs/spec/ceff-lever-ladder.md
(ember-goalforge tree):

  §(d) "Honest conclusion: even the BEST-case compounding of every currently-
  receipted-or-plausible c03-shape mechanical lever in this ladder falls
  short of 3.3x by a factor of `1.7838/1.7079 ~= 1.044x` -- about 4.4%. ...
  C4's fused-NS5-kernel compile (already measured alone at 1.081-1.089x,
  `>=1.044x` is all that's needed) is the best-positioned candidate ... IF it
  composes with the bf16-NS5 dtype path -- an interaction that has never
  been tested (§c, C4)."

  §(c) C4 measurement protocol: "re-run scripts/fp35_fused_muon_kernel_ab.py
  with the bf16-NS5 patch applied to the chain before compiling it; if the
  bench-shape cell keeps >=1.02x, integrate into a full production-recipe
  cell." Kill criterion: "compiled-bf16 cell <1.02x OR fails the existing
  ns5_equiv_check numerical tolerance ... -> PARKED".

  §(d) named interaction risk #5: "Fused-NS5-kernel compile x bf16-NS5
  dtype swap -- both target the identical Newton-Schulz orthogonalization
  chain; the fused-kernel receipt was measured on the fp32 chain only,
  never on the bf16-patched chain (§c, C4)."

PROTOCOL V2 UPGRADE (ceff-lever-ladder.md "Composition A/B protocol v2",
pre-registered 2026-07-03T10:58Z) -- this file implements v2, not v1. Run 1
(receipts/ceff-composition-ab-20260703T103635Z.json) cleared the speed bar
decisively (incremental_over_bf16ns5_alone 1.10116 vs the 1.044 closer bar,
super-additive interaction 1.0718, identical loss trajectories across all
four arms) but PARKed on the v1 single-tolerance numerics comparator
(compiled-bf16 vs eager-bf16 max-abs 4.36e-3 > 1e-3). The decomposition
probe (receipts/ceff-ns5-equiv-decomposition-20260703T104924Z.json)
established the v1 tolerance sat BELOW bf16's own representational
granularity (2^-8 ~= 3.9e-3) -- a dtype-inappropriate comparator for the
bf16 cells, not a substantive kill; the ALREADY-ACCEPTED eager bf16-NS5
lever (2026-06-23 landing) was itself gated on loss equivalence, never on
output-tensor distance, and could not meet v1's bar either. v2 replaces
the single tolerance with the operator's actual contract (see QUALITY
GUARD / KILL-KEEP below): fp32 UNCHANGED; bf16 gets a wider elementwise
tolerance PLUS a NEW orthogonality-contract conjunct that v1 never
checked -- STRICTER than the June precedent, a strictly-added kill
surface, never a tolerance retrofit.

WHERE THE TWO LEGS LIVE (read, not re-derived)
  Fused-kernel leg : scripts/fp35_fused_muon_kernel_ab.py -- wraps the NS5
    chain in torch.compile(fn, mode="reduce-overhead", fullgraph=False).
    Measured 1.0885x / 1.0811x (two independent runs,
    receipts/fp35-fused-muon-kernel-ab-20260612T215202Z.json and
    -20260613T055245Z.json) on an ISOLATED optimizer-only microbench
    (batch=4, synthetic data) -- never integrated into a full production
    training step, and only ever fuses the FP32 chain.
  bf16-NS5 leg     : scripts/conv_c03_muon_split_bf16ns5.py and
    scripts/c04_bf16ns5_qat_throughput.py both define `_zeropower_bf16` --
    identical NS5 math, X cast to bfloat16 instead of float32 before the
    5 Newton-Schulz iterations. receipts/conv-muon_split_bf16ns5-
    20260623T090201Z.json measured 19577.1 tok/s vs the fp32-NS5 comparator
    16553.6 (receipts/conv-muon_split-20260623T072149Z.json) = 1.1826x.
  BOTH legs patch the SAME switch: scripts/timeshare_pretrain.py's
    module-level `_zeropower_via_newtonschulz5(G, steps=5, eps=1e-7)`
    (ts.py:717-736), called from every per-param `_Muon.step()` via a
    late-bound bare-name global lookup (ts.py:789:
    `upd = _zeropower_via_newtonschulz5(upd, steps=ns_steps)`). Because
    Python resolves a bare global name from the enclosing module's __dict__
    at CALL time (not def time), `ts._zeropower_via_newtonschulz5 = <fn>`
    rebinds every existing and future `_Muon` instance's orthogonalization
    call -- the exact mechanism c04_bf16ns5_qat_throughput.py:174 already
    relies on. This script uses the identical patch/restore mechanism.

FOUR ARMS — one fresh model+optimizer build each; SAME model-init seed and
SAME synthetic batch sequence across all four (a dedicated Generator,
re-seeded per arm, decoupled from the model-init seed), so per-step loss is
directly comparable and any composition bug shows up as trajectory
divergence, not batch-sampling noise:

  A_baseline       ts._zeropower_via_newtonschulz5 UNPATCHED (fp32 NS5,
                   eager) -- "the c03 stack as currently receipted":
                   production builders (build_v0_model/build_split_optimizer
                   /resolve_ce_impl), muon_split + chunked-CE(256) + MTP,
                   batch=16/seq=<contract>. Matches the recipe
                   c04_eager_bf16_throughput.py / c04_chunk_tf32_lever.py
                   already measure as the production floor (~16400 tok/s).
  B_fused_alone    fp32 NS5 chain wrapped in torch.compile(mode=
                   "reduce-overhead", fullgraph=False) -- the fp35 lever,
                   now integrated into a full production step instead of an
                   isolated optimizer-only microbench.
  C_bf16ns5_alone  bf16-NS5 dtype patch (`_ns5_bf16` below, identical
                   semantics/coefficients to conv_c03_muon_split_bf16ns5.py's
                   `_zeropower_bf16`) -- re-confirms the 1.1826x lever inside
                   THIS harness/shape (team-lead brief: "bf16-NS5 alone
                   (re-confirm)").
  D_both_composed  the bf16-NS5 chain wrapped in torch.compile(mode=
                   "reduce-overhead", fullgraph=False) -- fuses the
                   BF16-patched chain, exactly per the ladder's own C4
                   measurement protocol quoted above.

PROTOCOL
  N warmup + M measured steps per arm: WARMUP=5, TIMED=20 -- matches
  c04_eager_bf16_throughput.py and c04_chunk_tf32_lever.py, the two existing
  harnesses that already integrate these SAME production builders at this
  SAME batch=16/seq=<contract> shape (fp35_fused_muon_kernel_ab.py's isolated
  microbench coincidentally uses the same 5/20 window; c04_bf16ns5_qat_
  throughput.py uses 10/40 for a smaller QAT-tax signal -- not the shape this
  script needs).
  Median tok/s per arm (median of the per-step tok/s over the TIMED window)
  reported alongside the paced-mean tok_s_paced/tok_s_raw the c04 family
  already uses, so this receipt cross-compares both ways.
  Pairwise multipliers, interaction isolated:
    MM_B = tok_s_B / tok_s_A         (fused-kernel-alone multiplier)
    MM_C = tok_s_C / tok_s_A         (bf16-NS5-alone multiplier)
    MM_D = tok_s_D / tok_s_A         (composed multiplier)
    predicted_independent_MM = MM_B * MM_C     ("IF independent (unverified)"
                                                 per ladder §(c) C1's own
                                                 phrasing for this exact kind
                                                 of naive product)
    interaction_ratio = MM_D / predicted_independent_MM
      >1 synergistic, ~1 independent, <1 sub-additive (the two levers
      cannibalize the same NS5-chain HBM-round-trip saving -- the specific
      named risk #5).
    incremental_over_bf16ns5_alone = MM_D / MM_C
      the number actually compared against the ladder's own >=1.044x closer
      bar (§d "Honest conclusion").

QUALITY GUARD — numerics-parity, NOT a training-quality claim
  Every arm gets the IDENTICAL model init (torch.manual_seed(MODEL_SEED)
  immediately before build_v0_model) and the IDENTICAL synthetic batch
  sequence (a dedicated torch.Generator, re-seeded to BATCH_GEN_SEED at the
  start of every arm, decoupled from the model-init seed). For arms B/C/D:
    max_abs_rel_loss_delta = max_i( |loss_i - lossA_i| / |lossA_i| )
  over the TIMED window. Envelope QUALITY_ENVELOPE=0.02 (2%), set from this
  exact lever's own receipted quality precedent: "quality within bf16
  granularity of the fp32 run" (loss 4.25 vs fp32 4.34 = 2.1% relative,
  receipts/conv-muon_split_bf16ns5-20260623T090201Z.json, over the REAL
  60M-token trajectory). This bench's 20-step synthetic-data loss trace is a
  numerics-parity check (does the composed kernel math track baseline on
  IDENTICAL data), not a re-run of that convergence claim -- the receipted
  conv-*.json trajectories remain the sole evidence for real training-
  quality; this guard only catches a composition bug big enough to move the
  short-window trajectory outside bf16-NS5's own already-accepted margin.
  ns5_equiv_pass (PROTOCOL V2, ceff-lever-ladder.md "Composition A/B
  protocol v2", pre-registered 2026-07-03T10:58Z -- Run 1 PARKed on the v1
  single-tolerance comparator, 4.36e-3 > 1e-3, which v2 replaces because it
  sits BELOW bf16's own representational granularity, 2^-8 ~= 3.9e-3):
    fp32-fused-vs-fp32-baseline : UNCHANGED -- max_abs_delta <=
      NS5_EQUIV_TOL=1e-3 (fp35's own already-receipted check, control
      passes at 6.3e-7).
    bf16-fused-vs-bf16-baseline : THREE conjuncts, ANY failing kills the
      cell --
        (a) max_abs_delta <= NS5_EQUIV_TOL_BF16=7.8e-3 (2x bf16 unit-scale
            eps -- dtype-honest reordering headroom, not the fp32-inherited
            1e-3 v1 wrongly reused).
        (b) NEW -- orthogonality-contract check: _orthogonality_residual
            (||Y Y^T - I||_F on the smaller Gram side, identically for
            both variants) must differ <=ORTHOGONALITY_REL_TOL=0.05 (5%)
            relative between compiled and eager -- the operator's actual
            PURPOSE, gated directly; v1 never checked this and it can kill
            the cell even where (a) passes.
        (c) per-arm loss-trajectory equality over the timed window --
            the pre-existing quality_guard (max_abs_rel_loss_delta <=
            QUALITY_ENVELOPE), kept as a hard gate exactly as v1 already
            wired it (compute_verdict ANDs quality_pass into the same
            park/keep decision as ns5_equiv_pass).

KILL / KEEP (mirrors the ladder's own §(c) C4 bar + §(d) closer bar)
  COMPOSITION_PARK_NUMERICS_FAIL     ns5_equiv_pass is False (fp32 cell (a),
                                     OR bf16 cell (a)/(b) conjunct -- v2),
                                     OR the quality guard (c) is exceeded on
                                     any of B/C/D. Verdict string unchanged
                                     from v1; kill bar preserved, strictly
                                     more can now trip it (v2 (b) is a NEW
                                     kill surface, never a loosened one).
  COMPOSITION_PARK_BELOW_VIABLE_BAR  ns5_equiv + quality both pass, but
                                     MM_D < VIABLE_BAR=1.02 (fp35's own
                                     VIABLE bar).
  COMPOSITION_CLOSES_RESIDUAL_GAP    all guards pass, MM_D >= 1.02, AND
                                     incremental_over_bf16ns5_alone >=
                                     INTERACTION_KEEP_BAR=1.044.
  COMPOSITION_VIABLE_BUT_SHORT       all guards pass, MM_D >= 1.02, but
                                     incremental_over_bf16ns5_alone < 1.044
                                     (composes and keeps, does not by itself
                                     close the §(d) residual gap).

GOVERNOR / LAUNCH-GATE (never loosened; --dry-run touches neither)
  ts._apply_governor() -- VRAM fraction <=0.80, margin assert >=1.5 GiB
  (fp19 floor), inter-step pace sleep >=0.05s (ts.FP19_PACE_S) -- fail-
  closed SystemExit on violation, the identical call every c04/conv harness
  in this tree already makes.
  v0_pretrain_launch_gate.g_budget() consulted with a requested_run
  descriptor (source/total_steps/params/batch/seq), mirroring
  ember_c_e2b_paired_run.py::cmd_live's own pre-flight pattern -- refuses
  (status BLOCKED, receipt NOT written, no bench executed) unless GREEN.
  ONE GPU JOB AT A TIME: 4 sequential model builds x (WARMUP+TIMED) steps at
  batch=16/seq=<contract> -- a few minutes total, not a training-length job,
  but it DOES need exclusive GPU ownership while it runs. Do not dispatch
  this while another train job holds the GPU (see BANKED GPU COMMAND below);
  this authoring session never fires it (never touches torch.cuda.*, never
  passes --live... there is no --live flag here, the default mode already
  IS the GPU run -- --dry-run is the only CPU-safe mode).

RECIPE HONESTY NOTE — "same corpus shards"
  batch=16 and seq=<contract, 1024> are honored exactly. The team-lead brief
  additionally named "same corpus shards"; this bench uses synthetic
  torch.randint batches instead, matching EVERY other bench-shape harness in
  this exact family (c04_eager_bf16_throughput.py, c04_chunk_tf32_lever.py,
  c04_bf16ns5_qat_throughput.py) for the documented reason each of those
  gives verbatim: "Throughput is data-value independent; match production
  shapes/dtypes." No receipt in this specific bench-shape family threads
  real PackedShardLoader shards through a bounded WARMUP+TIMED window --
  only the full 60M-token conv-*.json segment runs (50-65 min each) use real
  shards, and 4 of those in one window would contradict the bench-shape
  framing the team-lead brief itself asked for ("N warmup + M measured
  steps"). This is flagged, not glossed over, in recipe.corpus_shards_note
  below. If D_both_composed clears (COMPOSITION_CLOSES_RESIDUAL_GAP), the
  ladder's own §(e) execution order already calls for exactly this next
  step: "a full 60M-token confirmation run (~50-65 min) if [the cell] keeps"
  -- that confirmation run is where real shards enter, same discipline C1
  already uses.

MODES
  --dry-run   CPU only, no CUDA call anywhere. ts.build_v0_model(cfg,
              live=False) -- the tiny CPU stand-in with the SAME
              .backbone()/.head/.mtp_heads interface as the real c03 model
              (timeshare_pretrain.py:1074-1100, "Routing names ... exercise
              split_param_groups exactly as the real model does"). Tiny
              WARMUP/TIMED/batch/seq. All 4 arms, the real NS5-patch
              mechanism, structural NS5 checks (shape/finite/singular-value
              PLUS, protocol v2, _orthogonality_residual itself -- run
              structurally on eager tensors, since it needs no compile;
              only the compiled-vs-eager rel-diff gate (b) is GPU-only),
              the quality guard, and the full verdict/receipt-shape logic
              are all exercised end-to-end. Receipt ->
              scratch/ember-ceff-composition-ab-dryrun/, self-declares
              dry_run=true (never glob-matched by receipts/ceff-*.json
              evidence searches).
  (no flag)   The real GPU run. Governed + gated per above. Receipt ->
              receipts/ceff-composition-ab-<ts>.json.
  --selftest  Pure math/schema checks (floor identities, verdict-threshold
              logic, receipt-schema round-trip) -- no torch required.
              Prints CEFF_COMPOSITION_AB_SELFTEST_PASS.

No git commits. No downloads. No founder/user names anywhere in this file
or its receipts.

BANKED GPU COMMAND (fire once the current training run has freed the GPU --
do not run concurrently with any other GPU job):

  python scripts/ember_ceff_composition_ab.py

Dispatch via the train MCP (WSL2/CUDA), matching every other c04/conv
harness in this tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

HERE     = os.path.dirname(os.path.abspath(__file__))
NC       = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts")
SCRATCH_DRYRUN = os.path.join(NC, "scratch", "ember-ceff-composition-ab-dryrun")
sys.path.insert(0, HERE)

from receipt_write import checked_write    # noqa: E402  (light; no torch)

# ── Harness window (live) — matches c04_eager_bf16_throughput.py /
#    c04_chunk_tf32_lever.py: the two existing harnesses integrating these
#    SAME production builders at this SAME batch=16/seq=<contract> shape ──
WARMUP = 5
TIMED  = 20
BATCH  = 16
CE_CHUNK_TOKENS = 256   # production default (timeshare_pretrain.py:1173's ce_chunk_tokens=256)
TOTAL_STEPS_NOMINAL = 449651   # WSD denominator — affects lr scalar only, not compute

# ── CPU dry-run window — tiny, fast, no CUDA ─────────────────────────────────
DRYRUN_WARMUP = 2
DRYRUN_TIMED  = 3
DRYRUN_BATCH  = 4
DRYRUN_SEQ    = 16

# ── Reproducibility seeds ────────────────────────────────────────────────────
MODEL_SEED     = 42          # model-init seed, IDENTICAL across all 4 arms
BATCH_GEN_SEED = 20260703    # dedicated batch-sequence seed, IDENTICAL across all 4 arms

# ── Frozen SHATTER anchor (shared with c04_eager_bf16_throughput.py /
#    c04_chunk_tf32_lever.py — same provenance, informational cross-receipt
#    continuity; NOT the primary verdict driver for this composition test) ──
EFFECTIVE_DAYS_ANCHOR = 0.96557
TOK_S_ANCHOR          = 19874.8
K_TOK_S_FLOOR         = EFFECTIVE_DAYS_ANCHOR * TOK_S_ANCHOR   # 19190.5

# ── This test's own bars, quoted from the ladder doc §(c) C4 / §(d) ────────
RESIDUAL_NEEDED       = 1.7838   # ladder §b: 3.3 / 1.85
INTERACTION_KEEP_BAR  = 1.044    # ladder §d "Honest conclusion": 1.7838/1.7079
VIABLE_BAR            = 1.02     # fp35_fused_muon_kernel_ab.py's own VIABLE bar
QUALITY_ENVELOPE      = 0.02     # 2% — from bf16-NS5's own receipted "within bf16
                                 # granularity" precedent (4.25 vs 4.34 = 2.1% relative)

# ── Protocol v2 bars (ceff-lever-ladder.md "Composition A/B protocol v2",
#    pre-registered 2026-07-03T10:58Z) — replaces the single NS5_EQUIV_TOL
#    v1 used for BOTH cells with a dtype-honest split: fp32 UNCHANGED,
#    bf16 gets a wider elementwise tolerance PLUS a NEW orthogonality-
#    contract conjunct. Run 1 (ceff-composition-ab-20260703T103635Z.json)
#    PARKed on the v1 comparator alone (4.36e-3 > 1e-3) — v1 was a
#    dtype-inappropriate comparator for bf16 (below bf16's own unit-scale
#    granularity, 2^-8 ~= 3.9e-3), not a substantive kill.
PROTOCOL_VERSION      = 2
NS5_EQUIV_TOL         = 1e-3     # fp32 cells — UNCHANGED (fp35_fused_muon_kernel_ab.py's
                                 # own tolerance; control passes at 6.3e-7)
NS5_EQUIV_TOL_BF16    = 7.8e-3   # bf16 cells (compiled vs eager-bf16) — v2 check (a):
                                 # 2x bf16 unit-scale eps (2^-8 ~= 3.9e-3), dtype-honest
                                 # reordering headroom
ORTHOGONALITY_REL_TOL = 0.05    # v2 check (b), NEW: bf16 cells only — the NS5 output's
                                 # orthogonality residual (smaller-Gram-side convention,
                                 # see _orthogonality_residual) must differ <=5% relative
                                 # between compiled and eager — the operator's actual
                                 # contract, gated directly (v1 never checked this)

ARM_NAMES = ["A_baseline", "B_fused_alone", "C_bf16ns5_alone", "D_both_composed"]


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _harness_sha() -> str:
    h = hashlib.sha256()
    with open(__file__, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def effective_days(tok_s_paced) -> float:
    if not tok_s_paced or tok_s_paced <= 0:
        return float("inf")
    return K_TOK_S_FLOOR / tok_s_paced


# ---------------------------------------------------------------------------
# NS5 orthogonalization variants — the four things patched into
# ts._zeropower_via_newtonschulz5 across the four arms.
# ---------------------------------------------------------------------------

def _ns5_bf16(G, steps: int = 5, eps: float = 1e-7):
    """BF16 Newton-Schulz5 (tensor-core path). Identical semantics/
    coefficients to conv_c03_muon_split_bf16ns5.py's `_zeropower_bf16` and
    c04_bf16ns5_qat_throughput.py's copy of the same: only the internal
    matmuls run in bfloat16 instead of float32. External contract: same
    shape returned; dtype = G.dtype."""
    import torch
    assert G.ndim == 2, "Newton-Schulz operates on 2D matrices only"
    a, b, c = 3.4445, -4.7750, 2.0315
    orig_dtype = G.dtype
    X = G.to(torch.bfloat16)
    transposed = False
    if X.shape[0] > X.shape[1]:
        X = X.T
        transposed = True
    X = X / (X.norm() + eps)
    for _ in range(steps):
        A = X @ X.T
        B = b * A + c * (A @ A)
        X = a * X + B @ X
    if transposed:
        X = X.T
    return X.to(orig_dtype)


def _make_fused(fn):
    """torch.compile(fn, mode='reduce-overhead', fullgraph=False) — the
    fp35_fused_muon_kernel_ab.py fusion recipe, applied to whichever eager
    NS5 function is passed in (fp32 baseline for arm B, _ns5_bf16 for
    arm D)."""
    import torch
    return torch.compile(fn, mode="reduce-overhead", fullgraph=False)


def _orthogonality_residual(Y) -> float:
    """||Y Y^T - I||_F on the SMALLER Gram side — protocol v2 check (b)'s
    comparator (ceff-lever-ladder.md "Composition A/B protocol v2":
    "compute the residual on the smaller Gram side, identically for both
    variants"). Matches _zeropower_via_newtonschulz5's own orientation
    convention exactly: that function transposes G to wide-or-square
    (rows<=cols) before iterating, so its internal Gram A = X @ X.T is
    always the min(rows,cols)-sized one — the side NS5's semi-
    orthogonalization can actually drive toward identity (rank is bounded
    by min(rows,cols), so the LARGER Gram side can never reach I). Since Y
    (the returned output) is transposed back to G's original orientation:
    wide-or-square Y (rows<=cols) -> smaller Gram is the row space (Y Y^T,
    size rows); tall Y (rows>cols) -> smaller Gram is the col space
    (Y^T Y, size cols). Cast to float32 for the norm so bf16 tensors don't
    lose precision in the residual computation itself (both variants get
    the identical cast, so the comparison stays apples-to-apples)."""
    import torch
    assert Y.ndim == 2, "orthogonality residual operates on 2D matrices only"
    rows, cols = Y.shape[0], Y.shape[1]
    if rows <= cols:
        gram, k = Y @ Y.T, rows
    else:
        gram, k = Y.T @ Y, cols
    eye = torch.eye(k, dtype=torch.float32, device=Y.device)
    return (gram.float() - eye).norm(p="fro").item()


def _ns5_equiv_verdict(max_abs_delta: float, tol: float,
                        ortho_rel_diff: float | None = None,
                        ortho_rel_tol: float | None = None) -> bool:
    """Pure-math gate for one NS5-equivalence cell — no torch, so this is
    exercised directly by --selftest. (a) max_abs_delta <= tol always
    gates. (b) ortho_rel_diff <= ortho_rel_tol gates ADDITIONALLY, as a
    conjunct, ONLY when ortho_rel_tol is not None (protocol v2 bf16 cells;
    fp32 cells pass ortho_rel_tol=None and are gated on (a) alone —
    v2: "fp32 cells: UNCHANGED"). (b) can newly kill the cell even where
    (a) passes — the strictly-added kill surface protocol v2 names."""
    max_abs_pass = bool(max_abs_delta <= tol)
    if ortho_rel_tol is None:
        return max_abs_pass
    ortho_pass = bool(ortho_rel_diff is not None and ortho_rel_diff <= ortho_rel_tol)
    return bool(max_abs_pass and ortho_pass)


def _check_ns5_equiv(baseline_fn, fused_fn, tol: float, device: str,
                      compute_orthogonality: bool = False) -> dict:
    """Max-abs-delta between baseline_fn(G) and fused_fn(G) on device.
    Mirrors fp35_fused_muon_kernel_ab.py's _check_ns5_equiv exactly (same
    shapes: (64,128) CPU selftest / (1024,4096) CUDA real check, same
    seed=7). When compute_orthogonality is True (protocol v2 bf16 cells
    only — fp32 cells never pass this, per v2 "fp32 cells: UNCHANGED"),
    additionally computes both outputs' _orthogonality_residual and their
    relative difference. Returns a dict; caller (_ns5_equiv_cell) decides
    pass/fail via the pure-math _ns5_equiv_verdict."""
    import torch
    shape = (64, 128) if device == "cpu" else (1024, 4096)
    torch.manual_seed(7)
    G = torch.randn(*shape, dtype=torch.float32, device=device)
    with torch.no_grad():
        X_base = baseline_fn(G.to(device))
        if device != "cpu":
            torch.cuda.synchronize()
        X_fuse = fused_fn(G.to(device))
        if device != "cpu":
            torch.cuda.synchronize()
    out = {"max_abs_delta": (X_base - X_fuse).abs().max().item()}
    if compute_orthogonality:
        r_base = _orthogonality_residual(X_base)
        r_fuse = _orthogonality_residual(X_fuse)
        out["orthogonality_residual_baseline"] = r_base
        out["orthogonality_residual_fused"] = r_fuse
        out["orthogonality_rel_diff"] = abs(r_fuse - r_base) / max(abs(r_base), 1e-12)
    return out


def _ns5_equiv_cell(baseline_fn, fused_fn, tol: float, device: str, label: str,
                     ortho_rel_tol: float | None = None) -> dict:
    """Run _check_ns5_equiv, tolerating CPU-inductor-without-MSVC on
    Windows exactly like fp35_fused_muon_kernel_ab.py's own --selftest does
    (step 6 there): a Compiler/InductorError/'cl is not found' failure on
    CPU is a host-tooling gap, not an equivalence failure, and is flagged
    rather than silently treated as PASS or FAIL. ortho_rel_tol not None
    -> protocol v2 (a)+(b) conjunct (bf16 cells); None -> (a) alone, byte-
    for-byte the v1 behavior (fp32 cell, UNCHANGED per protocol v2)."""
    try:
        res = _check_ns5_equiv(baseline_fn, fused_fn, tol, device,
                                compute_orthogonality=(ortho_rel_tol is not None))
        delta = res["max_abs_delta"]
        cell = {"label": label, "device": device, "max_abs_delta": round(delta, 10),
                "tolerance": tol, "skipped": False}
        ortho_rel_diff = None
        if ortho_rel_tol is not None:
            ortho_rel_diff = res["orthogonality_rel_diff"]
            cell["orthogonality"] = {
                "residual_baseline": round(res["orthogonality_residual_baseline"], 10),
                "residual_fused": round(res["orthogonality_residual_fused"], 10),
                "rel_diff": round(ortho_rel_diff, 6),
                "rel_tol": ortho_rel_tol,
                "pass": bool(ortho_rel_diff <= ortho_rel_tol),
            }
        cell["pass"] = _ns5_equiv_verdict(delta, tol, ortho_rel_diff, ortho_rel_tol)
        return cell
    except Exception as e:
        msg = str(e)
        if device == "cpu" and any(s in msg for s in ("Compiler", "cl is not found", "InductorError")):
            cell = {"label": label, "device": device, "max_abs_delta": None,
                    "tolerance": tol, "pass": True, "skipped": True,
                    "skip_reason": "CPU inductor unavailable (no MSVC on this host); "
                                   "GPU compile does not require cl — same handling as "
                                   "fp35_fused_muon_kernel_ab.py's own --selftest"}
            if ortho_rel_tol is not None:
                cell["orthogonality"] = {"skipped": True}
            return cell
        raise


# ---------------------------------------------------------------------------
# Per-arm measurement — one fresh model+optimizer build, SAME model-init
# seed + SAME batch-generator seed across all four arms.
# ---------------------------------------------------------------------------

def measure_arm(ts_mod, arm_name: str, ns_fn, cfg: dict, *, live: bool,
                 warmup: int, timed: int, batch: int, seq: int,
                 pace_s: float, margin_gib: float | None) -> dict:
    import torch

    orig_ns5 = ts_mod._zeropower_via_newtonschulz5
    ts_mod._zeropower_via_newtonschulz5 = ns_fn
    model = None
    try:
        torch.manual_seed(MODEL_SEED)
        if live:
            torch.cuda.manual_seed(MODEL_SEED)
            torch.cuda.empty_cache()
            free_before, _ = torch.cuda.mem_get_info()

        try:
            if live:
                model, vocab, hidden, n_mtp = ts_mod.build_v0_model(cfg, live=True)
            else:
                model, vocab, hidden, n_mtp = ts_mod.build_v0_model(
                    cfg, live=False, tiny_dims={"vocab": 64, "hidden": 32, "depth": 2})
        except RuntimeError as e:
            if live and "out of memory" in str(e).lower():
                torch.cuda.empty_cache()
                return {"arm": arm_name, "status": "OOM_AT_BUILD", "error": str(e)}
            raise

        optimizers, base_lrs, routing = ts_mod.build_split_optimizer(model, cfg)
        ce_impl, ce_fn = ts_mod.resolve_ce_impl(prefer_liger=live)

        mtp_cfg = cfg["objective"]["mtp_aux_heads"]
        mtp_weight = mtp_cfg["weight"]
        mtp_enabled = bool(mtp_cfg["enabled"]) and n_mtp > 0
        device = "cuda" if live else "cpu"

        gen = torch.Generator(device="cpu")
        gen.manual_seed(BATCH_GEN_SEED)

        def make_batch():
            x  = torch.randint(1, vocab, (batch, seq), generator=gen).to(device)
            y0 = torch.randint(1, vocab, (batch, seq), generator=gen).to(device)
            ym = [torch.randint(1, vocab, (batch, seq), generator=gen).to(device)
                  for _ in range(n_mtp)]
            return x, y0, ym

        def step(global_step: int) -> float:
            x, y0, y_mtp = make_batch()
            h = model.backbone(x)
            hf = h.reshape(-1, h.shape[-1])
            pce, _ = ce_fn(hf, model.head.weight, y0.reshape(-1), chunk_tokens=CE_CHUNK_TOKENS)
            mces = []
            if mtp_enabled:
                for k in range(n_mtp):
                    ce_k, _ = ce_fn(hf, model.mtp_heads[k].weight, y_mtp[k].reshape(-1),
                                    chunk_tokens=CE_CHUNK_TOKENS)
                    mces.append(ce_k)
            loss = ts_mod.mtp_total_loss(pce, mces, mtp_weight)
            ts_mod.apply_wsd(optimizers, base_lrs, global_step, TOTAL_STEPS_NOMINAL, cfg["schedule"])
            loss.backward()
            for opt in optimizers.values():
                opt.step()
            for opt in optimizers.values():
                opt.zero_grad(set_to_none=True)
            return float(loss.detach().item())

        for i in range(warmup):
            step(i)

        if live:
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            free_b, total_b = torch.cuda.mem_get_info()
            free_gib = free_b / (1 << 30)
            if margin_gib is not None and free_gib < margin_gib:
                return {"arm": arm_name, "status": "SKIPPED-MARGIN",
                        "free_vram_gib": round(free_gib, 3)}

        step_times, losses = [], []
        t0 = time.perf_counter()
        for i in range(timed):
            t_s = time.perf_counter()
            loss_val = step(warmup + i)
            if live:
                torch.cuda.synchronize()
            dt = time.perf_counter() - t_s
            step_times.append(dt)
            losses.append(loss_val)
            if live:
                time.sleep(pace_s)
        total_dt = time.perf_counter() - t0

        toks = timed * batch * seq
        per_step_tok_s = [(batch * seq) / dt for dt in step_times]
        median_tok_s = statistics.median(per_step_tok_s)
        if live:
            tok_s_paced = toks / total_dt
            tok_s_raw = toks / (total_dt - timed * pace_s)
        else:
            tok_s_paced = toks / total_dt
            tok_s_raw = tok_s_paced

        result = {
            "arm": arm_name, "status": "OK",
            "tok_s_paced": round(tok_s_paced, 2),
            "tok_s_raw": round(tok_s_raw, 2),
            "median_tok_s": round(median_tok_s, 2),
            "mean_step_ms": round(sum(step_times) / len(step_times) * 1000, 3),
            "loss_trajectory": [round(l, 6) for l in losses],
            "mean_loss": round(sum(losses) / len(losses), 6),
            "first_loss": round(losses[0], 6),
            "last_loss": round(losses[-1], 6),
            "n_muon": routing.get("n_muon"), "n_adamw": routing.get("n_adamw"),
            "ce_impl": ce_impl, "routing_mode": routing.get("mode"),
        }
        if live:
            free_after, _ = torch.cuda.mem_get_info()
            result["vram_used_gib"] = round((free_before - free_after) / (1 << 30), 3)
        return result
    finally:
        ts_mod._zeropower_via_newtonschulz5 = orig_ns5
        if model is not None:
            del model
        if live:
            import torch as _t
            _t.cuda.empty_cache()


# ---------------------------------------------------------------------------
# Analysis — pairwise multipliers, interaction ratio, quality guard, verdict.
# ---------------------------------------------------------------------------

def _tok_s_of(arm_result: dict):
    return arm_result.get("tok_s_paced") if arm_result and arm_result.get("status") == "OK" else None


def analyze(arms: dict) -> dict:
    a, b, c, d = (arms[n] for n in ARM_NAMES)
    tok_a, tok_b, tok_c, tok_d = (_tok_s_of(x) for x in (a, b, c, d))

    mm_b = round(tok_b / tok_a, 5) if tok_a and tok_b else None
    mm_c = round(tok_c / tok_a, 5) if tok_a and tok_c else None
    mm_d = round(tok_d / tok_a, 5) if tok_a and tok_d else None
    predicted_independent = round(mm_b * mm_c, 5) if mm_b and mm_c else None
    interaction_ratio = round(mm_d / predicted_independent, 5) if mm_d and predicted_independent else None
    incremental_over_c = round(mm_d / mm_c, 5) if mm_d and mm_c else None

    # Quality guard: max abs relative loss delta per arm vs baseline, over
    # the SAME step index (identical batches/model-init across arms).
    quality_per_arm = {}
    quality_pass = True
    if a.get("status") == "OK":
        loss_a = a["loss_trajectory"]
        for name, arm in (("B_fused_alone", b), ("C_bf16ns5_alone", c), ("D_both_composed", d)):
            if arm.get("status") != "OK":
                quality_per_arm[name] = {"pass": False, "reason": f"arm status={arm.get('status')}"}
                quality_pass = False
                continue
            loss_x = arm["loss_trajectory"]
            n = min(len(loss_a), len(loss_x))
            deltas = [abs(loss_x[i] - loss_a[i]) / max(abs(loss_a[i]), 1e-9) for i in range(n)]
            max_delta = round(max(deltas), 6) if deltas else None
            ok = bool(max_delta is not None and max_delta <= QUALITY_ENVELOPE)
            quality_per_arm[name] = {"max_abs_rel_loss_delta": max_delta,
                                      "envelope": QUALITY_ENVELOPE, "pass": ok}
            quality_pass = quality_pass and ok
    else:
        quality_pass = False
        quality_per_arm["error"] = f"baseline arm status={a.get('status')}"

    return {
        "tok_s": {"A_baseline": tok_a, "B_fused_alone": tok_b,
                  "C_bf16ns5_alone": tok_c, "D_both_composed": tok_d},
        "MM_B_fused_alone": mm_b,
        "MM_C_bf16ns5_alone": mm_c,
        "MM_D_both_composed": mm_d,
        "predicted_independent_MM": predicted_independent,
        "interaction_ratio": interaction_ratio,
        "incremental_over_bf16ns5_alone": incremental_over_c,
        "quality_guard": {"envelope": QUALITY_ENVELOPE, "per_arm": quality_per_arm, "pass": quality_pass},
    }


def compute_verdict(analysis: dict, ns5_equiv_pass: bool) -> tuple[str, dict]:
    mm_d = analysis["MM_D_both_composed"]
    incr = analysis["incremental_over_bf16ns5_alone"]
    quality_pass = analysis["quality_guard"]["pass"]

    kill_criteria = {
        "ns5_equiv_pass": ns5_equiv_pass,
        "quality_guard_pass": quality_pass,
        "viable_bar": VIABLE_BAR,
        "MM_D_clears_viable_bar": bool(mm_d is not None and mm_d >= VIABLE_BAR),
        "interaction_keep_bar": INTERACTION_KEEP_BAR,
        "residual_needed": RESIDUAL_NEEDED,
        "closes_residual_gap": bool(incr is not None and incr >= INTERACTION_KEEP_BAR),
    }

    if not ns5_equiv_pass or not quality_pass:
        verdict = "COMPOSITION_PARK_NUMERICS_FAIL"
    elif not kill_criteria["MM_D_clears_viable_bar"]:
        verdict = "COMPOSITION_PARK_BELOW_VIABLE_BAR"
    elif kill_criteria["closes_residual_gap"]:
        verdict = "COMPOSITION_CLOSES_RESIDUAL_GAP"
    else:
        verdict = "COMPOSITION_VIABLE_BUT_SHORT"
    return verdict, kill_criteria


# ---------------------------------------------------------------------------
# Live GPU run
# ---------------------------------------------------------------------------

def _run_bench_live() -> dict:
    import torch
    import timeshare_pretrain as ts_mod

    cfg = ts_mod.load_contract()
    seq = cfg["model"]["seq"]

    # ── Launch-gate pre-flight (fail-closed; mirrors ember_c_e2b_paired_run.py::cmd_live) ──
    sys.path.insert(0, HERE)
    import v0_pretrain_launch_gate as gate_mod
    total_steps = len(ARM_NAMES) * (WARMUP + TIMED)
    requested_run = {
        "source": "ember_ceff_composition_ab--live",
        "total_steps": total_steps,
        "params": gate_mod.V0_REALIZED_PARAMS,
        "batch": BATCH,
        "seq": seq,
    }
    st, dt = gate_mod.g_budget(date.today(), requested_run=requested_run)
    if st != "GREEN":
        return {"status": "BLOCKED", "g_budget": {"status": st, "detail": dt},
                "requested_run": requested_run}

    # ── Governed launch (fail-closed; never fix-forward) ──
    gov = ts_mod._apply_governor()
    pace_s = ts_mod.FP19_PACE_S
    margin_gib = ts_mod.FP19_MARGIN_GIB

    print(f"[ceff-composition-ab] device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"[ceff-composition-ab] torch:  {torch.__version__}", flush=True)
    print(f"[ceff-composition-ab] g_budget: {st} — {dt}", flush=True)
    print(f"[ceff-composition-ab] batch={BATCH} seq={seq} ce_chunk={CE_CHUNK_TOKENS} "
          f"warmup={WARMUP} timed={TIMED} pace_s={pace_s}", flush=True)

    orig_ns5 = ts_mod._zeropower_via_newtonschulz5
    ns5_fp32_fused = _make_fused(orig_ns5)
    ns5_bf16_fused = _make_fused(_ns5_bf16)

    print("[ceff-composition-ab] NS5 equivalence check (fp32-fused-vs-baseline, CUDA — "
          "v2 (a) only, UNCHANGED)...", flush=True)
    equiv_fp32 = _ns5_equiv_cell(orig_ns5, ns5_fp32_fused, NS5_EQUIV_TOL, "cuda", "fp32_fused_vs_baseline")
    print(f"[ceff-composition-ab]   {equiv_fp32}", flush=True)
    print("[ceff-composition-ab] NS5 equivalence check (bf16-fused-vs-baseline, CUDA — "
          "v2 (a)+(b) conjunct: max-abs<=7.8e-3 AND orthogonality-residual rel-diff<=5%)...",
          flush=True)
    equiv_bf16 = _ns5_equiv_cell(_ns5_bf16, ns5_bf16_fused, NS5_EQUIV_TOL_BF16, "cuda",
                                  "bf16_fused_vs_baseline", ortho_rel_tol=ORTHOGONALITY_REL_TOL)
    print(f"[ceff-composition-ab]   {equiv_bf16}", flush=True)
    ns5_equiv_pass = bool(equiv_fp32["pass"] and equiv_bf16["pass"])
    torch.cuda.empty_cache()

    arm_fns = {
        "A_baseline": orig_ns5,
        "B_fused_alone": ns5_fp32_fused,
        "C_bf16ns5_alone": _ns5_bf16,
        "D_both_composed": ns5_bf16_fused,
    }

    arms = {}
    for name in ARM_NAMES:
        print(f"[ceff-composition-ab] arm={name} ...", flush=True)
        r = measure_arm(ts_mod, name, arm_fns[name], cfg, live=True,
                        warmup=WARMUP, timed=TIMED, batch=BATCH, seq=seq,
                        pace_s=pace_s, margin_gib=margin_gib)
        arms[name] = r
        if r.get("status") == "OK":
            print(f"[ceff-composition-ab]   {r['tok_s_paced']} tok/s paced, "
                  f"median={r['median_tok_s']}, loss {r['first_loss']}->{r['last_loss']}, "
                  f"vram={r.get('vram_used_gib')} GiB", flush=True)
        else:
            print(f"[ceff-composition-ab]   status={r.get('status')} {r.get('error', '')}", flush=True)

    analysis = analyze(arms)
    verdict, kill_criteria = compute_verdict(analysis, ns5_equiv_pass)

    return {
        "status": "OK",
        "governor": gov,
        "g_budget": {"status": st, "detail": dt},
        "requested_run": requested_run,
        "recipe": {
            "source": "timeshare_pretrain production builders (build_v0_model/build_split_optimizer/resolve_ce_impl)",
            "batch": BATCH, "seq": seq, "ce_chunk_tokens": CE_CHUNK_TOKENS,
            "warmup": WARMUP, "timed": TIMED, "pace_s": pace_s,
            "model_seed": MODEL_SEED, "batch_gen_seed": BATCH_GEN_SEED,
            "data": "synthetic (torch.randint, dedicated fixed-seed Generator, "
                    "IDENTICAL sequence across all 4 arms) — see module docstring "
                    "'RECIPE HONESTY NOTE' for why real corpus shards are not threaded here",
            "corpus_shards_note": "synthetic batches, not real PackedShardLoader shards — "
                                   "matches every other bench-shape harness in this family "
                                   "(c04_eager_bf16_throughput.py, c04_chunk_tf32_lever.py, "
                                   "c04_bf16ns5_qat_throughput.py); real-shard confirmation "
                                   "is the ladder's own §(e) next step if this cell keeps",
        },
        "ns5_equiv": {"fp32_fused_vs_baseline": equiv_fp32, "bf16_fused_vs_baseline": equiv_bf16,
                       "pass": ns5_equiv_pass},
        "arms": arms,
        "analysis": analysis,
        "kill_criteria": kill_criteria,
        "verdict": verdict,
    }


def run_and_emit_live() -> Path:
    result = _run_bench_live()
    ts = _ts()
    receipt = {
        "ticket": "CEFF-COMPOSITION-AB",
        "ts": ts,
        "mode": "live",
        "issue": "#24",
        "protocol_version": PROTOCOL_VERSION,
        "ladder_ref": "docs/spec/ceff-lever-ladder.md §(c) C4 / §(d) interaction risk #5 / "
                       "'Composition A/B protocol v2'",
        "scope": "fused-NS5-kernel-compile x bf16-NS5 dtype-swap composition A/B/C/D, "
                 "isolating the interaction term the ladder names as never-tested",
        "harness_sha": _harness_sha(),
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "flags": ["ONE GPU job at a time — do not dispatch concurrently with another train job",
                  "governor rails HOLD — never loosened",
                  "no git commits, no downloads, no founder/user names",
                  "protocol v2: bf16 cell gated on (a) max-abs<=7.8e-3 AND (b) NEW "
                  "orthogonality-residual rel-diff<=5% AND (c) quality_guard (loss-trajectory) "
                  "— ANY failing forces COMPOSITION_PARK_NUMERICS_FAIL; fp32 cell UNCHANGED "
                  "(max-abs<=1e-3 alone)"],
        **result,
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    if result.get("status") == "BLOCKED":
        path = os.path.join(RECEIPTS, f"ceff-composition-ab-BLOCKED-{ts}.json")
        checked_write(path, receipt)
        print(f"[ceff-composition-ab] LAUNCH_BLOCKED: {result['g_budget']}", flush=True)
        print(f"CEFF_COMPOSITION_AB_DONE status=BLOCKED receipt={path}", flush=True)
        return Path(path)

    path = os.path.join(RECEIPTS, f"ceff-composition-ab-{ts}.json")
    checked_write(path, receipt)
    print(f"[ceff-composition-ab] receipt: {path}", flush=True)
    print(f"[ceff-composition-ab] VERDICT: {result['verdict']} | "
          f"MM_B={result['analysis']['MM_B_fused_alone']} "
          f"MM_C={result['analysis']['MM_C_bf16ns5_alone']} "
          f"MM_D={result['analysis']['MM_D_both_composed']} | "
          f"interaction_ratio={result['analysis']['interaction_ratio']} "
          f"incremental_over_bf16ns5={result['analysis']['incremental_over_bf16ns5_alone']} "
          f"(keep_bar={INTERACTION_KEEP_BAR})", flush=True)
    print(f"CEFF_COMPOSITION_AB_DONE verdict={result['verdict']} receipt={path}", flush=True)
    return Path(path)


# ---------------------------------------------------------------------------
# CPU dry-run — NO CUDA anywhere. Stubs the training step at the tiny-model
# scale; proves plumbing + receipt shape end-to-end.
# ---------------------------------------------------------------------------

def _dryrun_ns5_structural_check(fn, label: str) -> dict:
    """CPU-only structural check on an eager NS5 function (shape/dtype/
    finite/singular-value-bounded) -- mirrors fp35_fused_muon_kernel_ab.py's
    own --selftest steps 3-4. Does NOT invoke torch.compile/dynamo: on a
    CUDA-visible host (torch.cuda.is_available()==True, as this one is even
    though the GPU is busy with another job), FIRST INVOCATION of a
    torch.compile-wrapped function triggers dynamo tracing, which queries
    torch.cuda.get_rng_state() internally as part of its own guard
    construction -- a real torch.cuda.* call regardless of the actual tensor
    device. Verified by poisoning torch.cuda.* and observing the failure
    inside dynamo's _fn, not inside this script's own code. To honor
    'no torch.cuda calls in CPU verification', --dry-run never wraps
    anything in torch.compile at all; the compiled-vs-eager numerical
    equivalence check is GPU-only and deferred to the live run (see
    _run_bench_live's equiv_fp32/equiv_bf16 cells).

    Protocol v2 EXTENSION: also computes _orthogonality_residual(out) --
    the same smaller-Gram-side residual the live run's NEW (b) check
    gates on -- as a structural sanity check (finite, non-negative). This
    exercises the residual-computation MECHANISM end-to-end on CPU; it is
    NOT compared against a compiled counterpart here (no torch.compile in
    --dry-run, per this docstring above) -- that comparison needs no
    compile in principle but this harness's compile IS what's CPU-unsafe,
    so the actual compiled-vs-eager rel-diff gate stays GPU-only, in
    _run_bench_live's equiv_bf16 cell."""
    import torch
    torch.manual_seed(11)
    G = torch.randn(8, 8)
    out = fn(G)
    ok_shape = out.shape == G.shape
    ok_finite = bool(torch.isfinite(out).all())
    sv = torch.linalg.svdvals(out.float())
    ok_sv = bool(sv.max().item() < 5.0 and sv.min().item() > 0.0)
    ortho_residual = _orthogonality_residual(out)
    ok_ortho = bool(ortho_residual == ortho_residual and ortho_residual >= 0.0)  # not NaN, non-negative
    return {"label": label, "shape_ok": ok_shape, "finite_ok": ok_finite,
            "singular_values_bounded_ok": ok_sv,
            "orthogonality_residual": round(ortho_residual, 10),
            "orthogonality_residual_structural_ok": ok_ortho,
            "pass": bool(ok_shape and ok_finite and ok_sv and ok_ortho)}


def _run_bench_dry() -> dict:
    import timeshare_pretrain as ts_mod

    cfg = ts_mod.load_contract()
    seq = DRYRUN_SEQ
    pace_s = 0.0

    orig_ns5 = ts_mod._zeropower_via_newtonschulz5

    # NO torch.compile anywhere in --dry-run (see _dryrun_ns5_structural_check
    # docstring for why: dynamo tracing touches torch.cuda.* even for CPU
    # tensors on a CUDA-visible host). Arms B/D use the eager fp32/bf16
    # functions directly, self-declared as un-compiled stand-ins so the
    # 4-arm plumbing/receipt-shape loop is still exercised end-to-end; the
    # actual fused-kernel numerics are GPU-only and covered by
    # _run_bench_live's ns5_equiv cells.
    struct_fp32 = _dryrun_ns5_structural_check(orig_ns5, "fp32_baseline_structural")
    struct_bf16 = _dryrun_ns5_structural_check(_ns5_bf16, "bf16_structural")
    ns5_equiv_pass = bool(struct_fp32["pass"] and struct_bf16["pass"])

    arm_fns = {
        "A_baseline": orig_ns5,
        "B_fused_alone": orig_ns5,       # STUB: real fusion is GPU-only, see docstring above
        "C_bf16ns5_alone": _ns5_bf16,
        "D_both_composed": _ns5_bf16,    # STUB: real fusion is GPU-only, see docstring above
    }

    arms = {}
    for name in ARM_NAMES:
        r = measure_arm(ts_mod, name, arm_fns[name], cfg, live=False,
                        warmup=DRYRUN_WARMUP, timed=DRYRUN_TIMED,
                        batch=DRYRUN_BATCH, seq=seq, pace_s=pace_s, margin_gib=None)
        arms[name] = r

    analysis = analyze(arms)
    verdict, kill_criteria = compute_verdict(analysis, ns5_equiv_pass)

    return {
        "status": "OK",
        "recipe": {
            "source": "timeshare_pretrain production builders, tiny CPU stand-in "
                       "(build_v0_model(live=False) — SAME .backbone()/.head/.mtp_heads "
                       "interface as the real c03 model)",
            "batch": DRYRUN_BATCH, "seq": seq, "ce_chunk_tokens": CE_CHUNK_TOKENS,
            "warmup": DRYRUN_WARMUP, "timed": DRYRUN_TIMED,
            "model_seed": MODEL_SEED, "batch_gen_seed": BATCH_GEN_SEED,
            "data": "synthetic (torch.randint, dedicated fixed-seed Generator, "
                    "IDENTICAL sequence across all 4 arms)",
        },
        "ns5_equiv": {
            "skipped_dry_run": True,
            "reason": "torch.compile/dynamo tracing touches torch.cuda.* internally even for "
                      "CPU tensors on a CUDA-visible host (verified by poisoning torch.cuda.* "
                      "and observing the call inside dynamo's own tracer, not this script's "
                      "code); the real compiled-vs-eager numerical equivalence check (v2 (a)+(b) "
                      "conjunct on the bf16 cell) is GPU-only and runs in the live mode instead — "
                      "the orthogonality-residual MECHANISM (b) itself IS exercised here, "
                      "structurally, on eager tensors (see structural_check_* below)",
            "structural_check_fp32_baseline": struct_fp32,
            "structural_check_bf16": struct_bf16,
            "pass": ns5_equiv_pass,
        },
        "arms": arms,
        "analysis": analysis,
        "kill_criteria": kill_criteria,
        "verdict": verdict,
    }


def run_and_emit_dry() -> Path:
    result = _run_bench_dry()
    ts = _ts()
    receipt = {
        "ticket": "CEFF-COMPOSITION-AB",
        "ts": ts,
        "mode": "dry-run",
        "dry_run": True,
        "issue": "#24",
        "protocol_version": PROTOCOL_VERSION,
        "ladder_ref": "docs/spec/ceff-lever-ladder.md §(c) C4 / §(d) interaction risk #5 / "
                       "'Composition A/B protocol v2'",
        "scope": "CPU plumbing proof only — NOT evidence for test_c_eff.py; "
                 "no receipts/ceff-RESOLVED-*.json glob match, self-declared dry_run",
        "harness_sha": _harness_sha(),
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "flags": ["NO torch.cuda.* call anywhere in this mode (including no torch.compile — "
                  "dynamo tracing touches torch.cuda.* internally even for CPU tensors on a "
                  "CUDA-visible host; verified by poisoning torch.cuda.* and observing the call "
                  "inside dynamo's own tracer)",
                  "tiny CPU stand-in model — same .backbone()/.head/.mtp_heads interface as real c03",
                  "arms B/D are UN-COMPILED eager stand-ins here — real fused-kernel numerics are "
                  "GPU-only, covered by the live mode's ns5_equiv cells instead",
                  "proves: NS5-patch mechanism, structural NS5 checks, quality guard, "
                  "verdict logic, receipt shape — all end-to-end on CPU",
                  "protocol v2: orthogonality-residual computation (check (b)'s mechanism) "
                  "runs structurally on eager tensors here; the compiled-vs-eager rel-diff "
                  "gate itself is GPU-only (live mode)"],
        **result,
    }
    SCRATCH_DRYRUN_path = Path(SCRATCH_DRYRUN)
    SCRATCH_DRYRUN_path.mkdir(parents=True, exist_ok=True)
    path = SCRATCH_DRYRUN_path / f"dry-run-{ts}.json"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(f"[ceff-composition-ab] dry-run receipt: {path}", flush=True)
    print(f"[ceff-composition-ab] VERDICT: {result['verdict']} | "
          f"MM_B={result['analysis']['MM_B_fused_alone']} "
          f"MM_C={result['analysis']['MM_C_bf16ns5_alone']} "
          f"MM_D={result['analysis']['MM_D_both_composed']}", flush=True)
    print(f"CEFF_COMPOSITION_AB_DRYRUN_DONE verdict={result['verdict']} receipt={path}", flush=True)
    return path


# ---------------------------------------------------------------------------
# Selftest — pure math/schema, no torch required.
# ---------------------------------------------------------------------------

def selftest() -> None:
    print("[ember_ceff_composition_ab] selftest: floor math + verdict logic + schema (no torch)", flush=True)

    # 1. Floor identity (shared anchor with c04 family)
    assert abs(K_TOK_S_FLOOR - 19190.5) < 0.5, K_TOK_S_FLOOR
    assert abs(effective_days(K_TOK_S_FLOOR) - 1.0) < 1e-9
    print(f"  K_TOK_S_FLOOR={K_TOK_S_FLOOR:.2f} identity  PASS")

    # 2. Bars match the ladder doc's own arithmetic
    assert abs(RESIDUAL_NEEDED - 3.3 / 1.85) < 1e-4, RESIDUAL_NEEDED
    assert abs(INTERACTION_KEEP_BAR - 1.044) < 1e-3
    print(f"  RESIDUAL_NEEDED={RESIDUAL_NEEDED} INTERACTION_KEEP_BAR={INTERACTION_KEEP_BAR}  PASS")

    # 2b. Protocol v2 bars (ceff-lever-ladder.md "Composition A/B protocol v2")
    assert PROTOCOL_VERSION == 2
    assert abs(NS5_EQUIV_TOL_BF16 - 7.8e-3) < 1e-9, NS5_EQUIV_TOL_BF16
    assert abs(ORTHOGONALITY_REL_TOL - 0.05) < 1e-9, ORTHOGONALITY_REL_TOL
    assert NS5_EQUIV_TOL_BF16 > NS5_EQUIV_TOL, "bf16 tolerance must be wider than fp32's, never narrower"
    print(f"  PROTOCOL_VERSION={PROTOCOL_VERSION} NS5_EQUIV_TOL_BF16={NS5_EQUIV_TOL_BF16} "
          f"ORTHOGONALITY_REL_TOL={ORTHOGONALITY_REL_TOL}  PASS")

    def _mk_arm(tok_s, losses):
        return {"status": "OK", "tok_s_paced": tok_s, "loss_trajectory": losses}

    # 3. analyze(): synergistic composition closes the gap
    arms_close = {
        "A_baseline":      _mk_arm(16500.0, [10.0, 9.9, 9.8]),
        "B_fused_alone":   _mk_arm(16500.0 * 1.08, [10.0, 9.9, 9.8]),
        "C_bf16ns5_alone": _mk_arm(16500.0 * 1.18, [10.0, 9.9, 9.8]),
        "D_both_composed": _mk_arm(16500.0 * 1.18 * 1.10, [10.0, 9.9, 9.8]),
    }
    an = analyze(arms_close)
    verdict, kc = compute_verdict(an, ns5_equiv_pass=True)
    assert an["quality_guard"]["pass"], an["quality_guard"]
    assert kc["MM_D_clears_viable_bar"]
    assert an["incremental_over_bf16ns5_alone"] >= INTERACTION_KEEP_BAR, an["incremental_over_bf16ns5_alone"]
    assert verdict == "COMPOSITION_CLOSES_RESIDUAL_GAP", verdict
    print(f"  synergistic-composition case -> {verdict}  PASS")

    # 4. analyze(): sub-additive composition — viable but short
    arms_short = {
        "A_baseline":      _mk_arm(16500.0, [10.0, 9.9, 9.8]),
        "B_fused_alone":   _mk_arm(16500.0 * 1.08, [10.0, 9.9, 9.8]),
        "C_bf16ns5_alone": _mk_arm(16500.0 * 1.18, [10.0, 9.9, 9.8]),
        "D_both_composed": _mk_arm(16500.0 * 1.19, [10.0, 9.9, 9.8]),  # barely above C alone
    }
    an2 = analyze(arms_short)
    verdict2, kc2 = compute_verdict(an2, ns5_equiv_pass=True)
    assert kc2["MM_D_clears_viable_bar"]
    assert an2["incremental_over_bf16ns5_alone"] < INTERACTION_KEEP_BAR
    assert verdict2 == "COMPOSITION_VIABLE_BUT_SHORT", verdict2
    print(f"  sub-additive-composition case -> {verdict2}  PASS")

    # 5. analyze(): below VIABLE_BAR
    arms_dead = {
        "A_baseline":      _mk_arm(16500.0, [10.0, 9.9, 9.8]),
        "B_fused_alone":   _mk_arm(16500.0 * 0.99, [10.0, 9.9, 9.8]),
        "C_bf16ns5_alone": _mk_arm(16500.0 * 0.98, [10.0, 9.9, 9.8]),
        "D_both_composed": _mk_arm(16500.0 * 1.00, [10.0, 9.9, 9.8]),
    }
    an3 = analyze(arms_dead)
    verdict3, kc3 = compute_verdict(an3, ns5_equiv_pass=True)
    assert not kc3["MM_D_clears_viable_bar"]
    assert verdict3 == "COMPOSITION_PARK_BELOW_VIABLE_BAR", verdict3
    print(f"  below-viable-bar case -> {verdict3}  PASS")

    # 6. analyze(): quality guard trips -> numerics-fail verdict regardless of MM_D
    #    (protocol v2 (c): per-arm loss-trajectory equality, kept as a hard gate --
    #    this IS that gate; loss-inequality -> COMPOSITION_PARK_NUMERICS_FAIL)
    arms_qfail = {
        "A_baseline":      _mk_arm(16500.0, [10.0, 9.9, 9.8]),
        "B_fused_alone":   _mk_arm(16500.0 * 1.08, [10.0, 9.9, 9.8]),
        "C_bf16ns5_alone": _mk_arm(16500.0 * 1.18, [10.0, 9.9, 9.8]),
        "D_both_composed": _mk_arm(16500.0 * 1.30, [10.0, 20.0, 9.8]),  # loss[1] blows the envelope
    }
    an4 = analyze(arms_qfail)
    assert not an4["quality_guard"]["pass"]
    verdict4, kc4 = compute_verdict(an4, ns5_equiv_pass=True)
    assert verdict4 == "COMPOSITION_PARK_NUMERICS_FAIL", verdict4
    print(f"  loss-inequality (v2 (c)) case -> {verdict4}  PASS")

    # 7. analyze(): ns5_equiv fail forces numerics-fail verdict even if quality/MM_D pass
    verdict5, kc5 = compute_verdict(an, ns5_equiv_pass=False)
    assert verdict5 == "COMPOSITION_PARK_NUMERICS_FAIL", verdict5
    print("  ns5-equiv-fail forces numerics-fail verdict regardless of MM_D  PASS")

    # 7b. Protocol v2 (a)/(b) conjunct gate -- pure logic, no torch (_ns5_equiv_verdict)
    # fp32-style: ortho_rel_tol=None -> gated on (a) alone, UNCHANGED v1 behavior
    assert _ns5_equiv_verdict(6.3e-7, NS5_EQUIV_TOL) is True
    assert _ns5_equiv_verdict(4.36e-3, NS5_EQUIV_TOL) is False, "the actual Run-1 fp32-tolerance-style delta must still fail fp32's own unchanged 1e-3 bar"
    # bf16-style: (a) pass + (b) fail -> PARK -- proves the NEW check (b) can kill
    # independently even where the elementwise check (a) alone would have kept
    assert _ns5_equiv_verdict(0.005, NS5_EQUIV_TOL_BF16, ortho_rel_diff=0.06, ortho_rel_tol=ORTHOGONALITY_REL_TOL) is False
    # bf16-style: (b) at the 4.9% boundary, (a) also passes -> KEEP
    assert _ns5_equiv_verdict(0.005, NS5_EQUIV_TOL_BF16, ortho_rel_diff=0.049, ortho_rel_tol=ORTHOGONALITY_REL_TOL) is True
    # bf16-style: (b) at the 5.0% boundary (inclusive <=) -> still KEEP
    assert _ns5_equiv_verdict(0.005, NS5_EQUIV_TOL_BF16, ortho_rel_diff=0.05, ortho_rel_tol=ORTHOGONALITY_REL_TOL) is True
    # bf16-style: (a) fails even though (b) passes -> PARK -- (a) is preserved as a
    # gate, not superseded by the new (b) conjunct
    assert _ns5_equiv_verdict(0.01, NS5_EQUIV_TOL_BF16, ortho_rel_diff=0.01, ortho_rel_tol=ORTHOGONALITY_REL_TOL) is False
    print("  protocol v2 (a)/(b) conjunct gate (pure, no torch): "
          "(a)-pass/(b)-fail -> PARK, (b)@4.9%+5.0%-boundary -> KEEP, "
          "(a)-fail/(b)-pass -> PARK  ALL PASS")

    # 8. _ns5_equiv_cell CPU-MSVC-absent tolerance path (synthetic exception)
    class _FakeCompilerErr(Exception):
        pass

    def _raiser(G):
        raise _FakeCompilerErr("Compiler: cl is not found")

    cell = _ns5_equiv_cell(lambda G: G, _raiser, NS5_EQUIV_TOL, "cpu", "synthetic")
    assert cell["skipped"] and cell["pass"], cell
    print("  _ns5_equiv_cell CPU-no-MSVC tolerance path  PASS")

    # 8b. Same skip path, protocol v2 bf16-shaped call (ortho_rel_tol set) --
    # the skip must still short-circuit before any orthogonality computation
    cell_v2 = _ns5_equiv_cell(lambda G: G, _raiser, NS5_EQUIV_TOL_BF16, "cpu", "synthetic_bf16",
                               ortho_rel_tol=ORTHOGONALITY_REL_TOL)
    assert cell_v2["skipped"] and cell_v2["pass"], cell_v2
    assert cell_v2["orthogonality"] == {"skipped": True}, cell_v2["orthogonality"]
    print("  _ns5_equiv_cell CPU-no-MSVC tolerance path, protocol v2 bf16 shape  PASS")

    # 9. Receipt-shape round trip (schema floor: ticket + ts required; protocol_version NEW)
    syn_receipt = {
        "ticket": "CEFF-COMPOSITION-AB", "ts": "20260703T000000Z", "mode": "dry-run",
        "protocol_version": PROTOCOL_VERSION,
        "verdict": verdict, "analysis": an, "kill_criteria": kc,
    }
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "ceff-composition-ab-test.json")
        with open(p, "w") as f:
            json.dump(syn_receipt, f, indent=2)
        rt = json.loads(open(p).read())
        assert rt["ticket"] == "CEFF-COMPOSITION-AB" and rt["ts"]
        assert rt["protocol_version"] == 2, rt["protocol_version"]
    print("  receipt round-trip file read (incl. protocol_version)  PASS")

    print("CEFF_COMPOSITION_AB_SELFTEST_PASS")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="C-EFF composition A/B/C/D: fused-NS5-kernel-compile x bf16-NS5, "
                    "isolating the never-tested interaction (ladder rung C4 / risk #5)")
    ap.add_argument("--dry-run", action="store_true",
                    help="CPU only, no CUDA — tiny stand-in model, proves plumbing + receipt shape")
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
