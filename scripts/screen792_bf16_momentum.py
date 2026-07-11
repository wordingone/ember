#!/usr/bin/env python3
"""screen792_bf16_momentum.py -- axis-4 screen-1: bf16 Muon-momentum STORAGE
two-arm screen at 434M c03, per ember issue #792.

Authoritative spec: the #707 comment thread (wordingone/ember), not this
docstring. Where this file and the thread ever disagree, the thread wins --
and AMENDMENT-1 (comment 4946573683) BINDS over the original frozen-draft
prereg (comment 4946214036) on any conflict between the two.

SCOPE (frozen, #707 Section D, quoted): "two-arm, 434M c03 same-scale pilot
-- attribution receipts + step price 11.24-11.38 s/step already banked for
this config. Arm A: production fp32 momentum. Arm B: bf16 momentum storage.
Matched seed, data order, steps; production QAT path ON in both arms (the
QAT coupling IS the contribution)."

"434M c03" is the frozen contract's (configs/v0-pretrain-config.json) NATIVE
live scale -- ts.build_v0_model(cfg, live=True, tiny_dims=None) with the
default intermediate=4096 realizes 433,890,304 params (the receipted "434M"
figure used across #702/#711/#764). This is NOT a mini version of the
separate 2.2B rung-2 config in #707 Section C's byte ledger -- that ledger
is forward-justification for a LARGER grown scale, out of screen-1 scope.

A2 MUST-NOT-CHANGE SET (#707 coupling ruling A2, quoted): "master/shadow
fp32 ... AdamW exp_avg/exp_avg_sq fp32 ... NS compute path; update rule."
Enforced by construction here, not by promise -- see _MuonBF16MomentumFixed
and _install_bf16_momentum below: the ONLY thing that changes between arm A
and arm B is the byte layout the Muon momentum_buffer is stored in.

A1 DATAFLOW (AMENDMENT-1, comment 4946573683, implementation-binding,
quoted verbatim -- "Upcast-only-at-NS-entry is the KNOWN-WRONG
implementation (silent bf16 EMA)"):
    On step() entry, upcast the READ from the bf16 momentum memmap to a
    local fp32 tensor BEFORE any arithmetic: buf_f32 =
    state['momentum_buffer'].to(fp32). Perform BOTH the EMA update
    (buf_f32.mul_(mom).add_(g_f32)) and the Nesterov combination (upd =
    g_f32.add(buf_f32, alpha=mom)) in fp32 -- never on the bf16 tensor
    directly. Feed upd (already fp32) to _zeropower_via_newtonschulz5 (its
    internal G.to(torch.float32) becomes a no-op, not the precision
    boundary). Downcast exactly once, on write-back:
    state['momentum_buffer'].copy_(buf_f32.to(bf16)).

MEASURANDS (4, #707 Section D + AMENDMENT-1 pinned timing):
  (1) commit-footprint delta via governor readings AT STEADY STATE (post-
      warmup, post the one-time construction write-pass -- a
      construction-phase reading is INVALID by definition, not a finding
      either way). Must match the byte arithmetic within band, else
      INVALID (instrument defect, not a kill).
  (2) copies/opt_other bucket delta via the existing #702 attribution
      instrument (cpu_offload_adamw.CPUOffloadOptimizer.attach_span_
      collector, SubphaseCollector) on both arms. "copies" = the three pure
      data-movement subphases (grad_to_cpu_fp32, grad_heap_to_memmap,
      updated_param_to_gpu); "opt_other" = inner_optimizer_step (where the
      A1 dataflow's own arithmetic executes -- the only subphase whose cost
      the momentum-storage-dtype change can plausibly move).
  (3) trajectory equivalence: per-step loss delta inside a pre-registered
      seed-noise band (realized locally: one extra fp32 seed sets the band
      BEFORE arm B ever runs -- unblinding order matters). n=2 band is a
      single-draw noise sample (1 dof, disclosed) -- AMENDMENT-1: "any
      loss-delta within 1.5x of the band edge = INCONCLUSIVE requiring a
      second extra seed, never a clean PROMOTE/KILL."
  (4) momentum-buffer cosine vs fp32 twin at fixed checkpoints (diagnostic,
      fp32-materialized comparison, never a gate).

KILL CONDITIONS (#707 Section D, pre-registered, quoted verbatim -- copied
into REFUSAL_TEXT below and into every refusal/verdict receipt this runner
writes; "No post-hoc band widening"):
    "loss-delta beyond band at matched steps -> bf16-momentum KILLED at
    this scale under QAT (D4 negative, filed); commit delta inside band +
    loss inside band -> PROMOTE to (a) 2.2B config for the capacity claim
    and (b) arm-2 int8-blockwise screen. No post-hoc band widening."

Explicitly NOT claimed by screen-1 (#707 Section D): any 2.2B step-time
number (needs the branch-B receipt), any transplant-fidelity statement (A3
clause), any master-precision statement (A2). AMENDMENT-1 finding 5: no
bf16-Muon-momentum-safety claim outside the QAT-on configuration -- no
non-QAT control exists in this screen, the QAT/precision coupling is
confounded by design, not isolated.

Reuse discipline (no duplicated math, no edits to any existing file): this
script imports timeshare_pretrain (ts), cpu_offload_adamw (_coa), governor,
receipt_write, receipt_check, and cbase_grow_rung2_attribution_702 (attrib,
for SubphaseCollector/install_span_collector/uninstall_span_collector) and
calls their real functions. It does NOT reimplement Muon/AdamW/CE/WSD/QAT
math -- see _run_arm_block, which composes ts._apply_fake_quant/
_restore_weights/mtp_total_loss/apply_wsd (run_v0_segment's own QAT
pattern) with attrib's span-collector profiling hooks (attrib._run_block
itself carries no QAT -- axis-3 doesn't need it; this screen's own
measurand explicitly requires QAT ON, so this composition is necessarily
this file's own, exactly as #702's docstring anticipated: "the outer step
loop is necessarily its own"). timeshare_pretrain.py, cpu_offload_adamw.py,
and cbase_grow_rung2_attribution_702.py are READ-ONLY references -- zero
lines of any of them are edited by this PR.

No git commits from this module. No founder/user names. api_spend_usd=0,
paid_api_surface_used=false (CPU/GPU-local module; no paid API surface).
This module launches NO GPU run by default; --live requires
EMBER_GATE_AUTHORIZED=1 (same interlock convention as every other
live-dispatch entrypoint in this tree) and a real --shard-dir.

HARD TIMING RAIL (builder spawn spec, issue #792): NO EXECUTION on the
authoring host until the coordinator's explicit window-release GO --
--selftest and --schema-probe are safe (CPU-only, no live dispatch) and are
the only legs this build phase runs.

CURE ROUND (external falsifier, head f81728f3, three pre-execution findings,
all addressed below): (1) MEASURAND-1 orchestration -- run_screen used to
retain arm A and arm A2's full model+optimizer state while building arm B,
so the commit-footprint delta included retained-arm + machine-global noise;
_one_arm now tears down each arm's heavy state (model, optimizer wrapper,
memmap file handles) before the next arm is built, enforced by an executable
_assert_no_arm_alive invariant, not just documented as a convention. The
sign was also inverted (bf16_used - fp32_used instead of fp32_used -
bf16_used, since bf16 storage is a REDUCTION vs fp32) -- see
compute_commit_delta_gib. (2) PRODUCTION-PARITY: run_arm_block's per-step
body now calls the SHARED ts._run_production_step (landed master #762) for
the QAT/forward/loss/backward/step body -- previously a hand-copied sibling
with no parity guarantee; only the outer loop (span-collector bracketing,
step-wall timing) remains this file's own. (3) PROVENANCE BINDING: every
live receipt now carries executing_git_sha + source/config/shard sha256
(compute_provenance), the field-name convention pinned by ember #801.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import timeshare_pretrain as ts                                       # noqa: E402
import cpu_offload_adamw as _coa                                      # noqa: E402
import governor                                                       # noqa: E402
import receipt_write                                                  # noqa: E402
import receipt_check                                                  # noqa: E402
import cbase_grow_rung2_attribution_702 as attrib                     # noqa: E402

_REPO = Path(__file__).resolve().parent.parent

TICKET = "SCREEN-792-BF16-MOMENTUM"
ISSUE_REFS = "wordingone/ember#792 #707 #787 #667"

# ---------------------------------------------------------------------------
# #707 pre-registered kill conditions, quoted verbatim -- copied into every
# refusal message and into the final receipt's "kills" field. Never edited
# post-hoc ("No post-hoc band widening" is itself part of the quoted text).
# ---------------------------------------------------------------------------
REFUSAL_TEXT = (
    "#707 Section D pre-registered kill conditions (verbatim): "
    "\"loss-delta beyond band at matched steps -> bf16-momentum KILLED at "
    "this scale under QAT (D4 negative, filed); commit delta inside band + "
    "loss inside band -> PROMOTE to (a) 2.2B config for the capacity claim "
    "and (b) arm-2 int8-blockwise screen. No post-hoc band widening.\" "
    "Measurand (1) timing (AMENDMENT-1, finding 4b): commit-delta governor "
    "readings are taken at STEADY STATE, after warmup and after the "
    "one-time construction write-pass; a construction-phase reading is "
    "INVALID by definition, not a finding either way. Measurand (3) "
    "tightening (AMENDMENT-1, findings 3+4a): the n=2 loss band is a "
    "single-draw noise sample (1 degree of freedom); any loss-delta within "
    "1.5x of the band edge is INCONCLUSIVE requiring a second extra seed, "
    "never a clean PROMOTE/KILL."
)

# AMENDMENT-1 Section C corrected byte ledger (finding 1c), quoted for the
# measurand-(1) INVALID-vs-KILL arithmetic check: "traffic delta ~= 8.389
# GB/step ... commit delta ~= 4.194 GB" at the frozen 2.2B identity
# (p_matrix=2,097,152,000). Screen-1 runs at 434M c03, not 2.2B -- this
# constant is NOT the expected delta for this screen's own commit reading;
# it exists ONLY so _check_byte_arithmetic can scale it by this run's own
# REALIZED p_matrix (per #667: realized counts, never advertised) and flag
# an instrument defect if the measured delta is wildly inconsistent with
# the same per-matrix-byte model the 2.2B ledger used.
AMENDMENT1_BYTES_PER_MATRIX_PARAM_MOMENTUM_DELTA = 2  # bf16 vs fp32 storage: 4B -> 2B/param
AMENDMENT1_2POINT2B_P_MATRIX = 2_097_152_000
AMENDMENT1_2POINT2B_COMMIT_DELTA_GIB = 4.194

# Post-genesis constitutional invariant stamp (receipt_check.py's own
# frozen constants -- read, never hand-copied to risk drift; imported at
# call time inside _build_receipt so a stale duplicate can never diverge).


# ---------------------------------------------------------------------------
# The A1-fixed Muon variant. Additive: timeshare_pretrain.py's _Muon class
# and _zeropower_via_newtonschulz5 function are used UNMODIFIED. Mirrors the
# established in-tree pattern (conv_c03_muon_split_bf16ns5.py's
# _muon_bf16ns5_class(): lazy factory subclassing ts._muon_class(),
# overriding only step()).
# ---------------------------------------------------------------------------
_MUON_BF16_MOM_CLS = None


def _muon_bf16_momentum_fixed_class():
    """Build (once) the AMENDMENT-1 A1-fixed Muon subclass. Lazy so this
    module imports without torch (same discipline as ts._muon_class())."""
    global _MUON_BF16_MOM_CLS
    if _MUON_BF16_MOM_CLS is not None:
        return _MUON_BF16_MOM_CLS
    import torch
    MuonBase = ts._muon_class()

    class _MuonBF16MomentumFixed(MuonBase):
        """Muon with the AMENDMENT-1 A1 fp32-read-modify-writeback dataflow
        for a bf16-STORED momentum buffer. External contract identical to
        the base _Muon: same param groups, same lr/momentum/nesterov/
        ns_steps/weight_decay, same update rule. The ONLY difference from
        the base class is the three lines implementing A1; NS orthogonalization
        (ts._zeropower_via_newtonschulz5, unmodified, fp32) and the final
        p.add_(upd, alpha=-lr*scale) update are copied verbatim from the
        base class -- A2's "NS compute path; update rule" must-not-change
        set is satisfied by literally reusing the same code, not by parallel
        reimplementation."""

        @torch.no_grad()
        def step(self, closure=None):
            loss = None
            if closure is not None:
                with torch.enable_grad():
                    loss = closure()
            for group in self.param_groups:
                lr = group["lr"]
                mom = group["momentum"]
                nesterov = group["nesterov"]
                ns_steps = group["ns_steps"]
                wd = group["weight_decay"]
                for p in group["params"]:
                    if p.grad is None:
                        continue
                    g = p.grad
                    if g.ndim != 2:
                        raise ValueError(
                            "_MuonBF16MomentumFixed received a non-2D "
                            "parameter -- split-routing invariant violated")
                    state = self.state[p]
                    if "momentum_buffer" not in state:
                        # CPUOffloadOptimizer pre-seeds this before step()
                        # ever runs in production use; this fallback exists
                        # only so the class is usable standalone (the
                        # required negative fixture constructs it directly,
                        # without the offload wrapper).
                        state["momentum_buffer"] = torch.zeros_like(
                            g, dtype=torch.bfloat16)
                    buf = state["momentum_buffer"]

                    # --- AMENDMENT-1 A1, implementation-binding, verbatim ---
                    g_f32 = g.to(torch.float32)
                    # Upcast the READ before any arithmetic (never operate
                    # on the bf16 tensor directly -- that is the finding-2
                    # defect this class exists to cure).
                    buf_f32 = buf.to(torch.float32)
                    buf_f32.mul_(mom).add_(g_f32)          # EMA, fp32
                    upd = (g_f32.add(buf_f32, alpha=mom)
                           if nesterov else buf_f32)         # Nesterov, fp32
                    # Feed the already-fp32 upd to the ORIGINAL NS function;
                    # its internal G.to(torch.float32) is a no-op here, not
                    # the precision boundary (AMENDMENT-1's own framing).
                    upd = ts._zeropower_via_newtonschulz5(upd, steps=ns_steps)
                    # Downcast exactly once, on write-back.
                    buf.copy_(buf_f32.to(buf.dtype))
                    # --- end A1; everything below is the UNMODIFIED base-
                    #     class update rule, copied verbatim (A2) ---
                    scale = max(1.0, p.shape[0] / p.shape[1]) ** 0.5
                    if wd != 0.0:
                        p.mul_(1.0 - lr * wd)
                    p.add_(upd, alpha=-lr * scale)
            return loss

    _MUON_BF16_MOM_CLS = _MuonBF16MomentumFixed
    return _MUON_BF16_MOM_CLS


# ---------------------------------------------------------------------------
# The naive in-place-bf16 control class. THIS IS THE DEFECT AMENDMENT-1
# CURED (finding 2), reproduced ONLY as a negative control for the required
# fixture below -- it is NEVER used on any production or screen-arm code
# path, only imported by the test module to prove the fixture actually
# discriminates the two implementations.
# ---------------------------------------------------------------------------
_MUON_BF16_NAIVE_CLS = None


def _muon_bf16_naive_inplace_class():
    """Build (once) the KNOWN-WRONG naive-in-place-bf16 Muon variant
    (AMENDMENT-1 finding 2's defect, reproduced verbatim from the ORIGINAL
    _Muon.step() body with only the momentum buffer's dtype changed to
    bf16): 'upcast at NS entry' with the EMA/Nesterov arithmetic left on
    the bf16 tensor directly -- in-place ops preserve destination dtype, so
    small increments below the bf16 ULP round away silently. Exists ONLY
    for the required negative fixture (test_screen792_bf16_momentum.py);
    never imported by the live runner path."""
    global _MUON_BF16_NAIVE_CLS
    if _MUON_BF16_NAIVE_CLS is not None:
        return _MUON_BF16_NAIVE_CLS
    import torch
    MuonBase = ts._muon_class()

    class _MuonBF16NaiveInPlace(MuonBase):
        """KNOWN-WRONG control: buf.mul_(mom).add_(g) directly on a bf16
        momentum tensor -- the exact defect AMENDMENT-1 replaced A1 to cure."""

        @torch.no_grad()
        def step(self, closure=None):
            loss = None
            if closure is not None:
                with torch.enable_grad():
                    loss = closure()
            for group in self.param_groups:
                lr = group["lr"]
                mom = group["momentum"]
                nesterov = group["nesterov"]
                ns_steps = group["ns_steps"]
                wd = group["weight_decay"]
                for p in group["params"]:
                    if p.grad is None:
                        continue
                    g = p.grad
                    if g.ndim != 2:
                        raise ValueError(
                            "_MuonBF16NaiveInPlace received a non-2D "
                            "parameter -- split-routing invariant violated")
                    state = self.state[p]
                    if "momentum_buffer" not in state:
                        state["momentum_buffer"] = torch.zeros_like(
                            g, dtype=torch.bfloat16)
                    buf = state["momentum_buffer"]
                    # NAIVE (WRONG): in-place EMA directly on the bf16
                    # tensor -- preserves bf16 destination dtype, so a
                    # sub-ULP increment rounds away every step.
                    buf.mul_(mom).add_(g)
                    upd = g.add(buf, alpha=mom) if nesterov else buf
                    upd = ts._zeropower_via_newtonschulz5(
                        upd.to(torch.float32), steps=ns_steps)
                    scale = max(1.0, p.shape[0] / p.shape[1]) ** 0.5
                    if wd != 0.0:
                        p.mul_(1.0 - lr * wd)
                    p.add_(upd, alpha=-lr * scale)
            return loss

    _MUON_BF16_NAIVE_CLS = _MuonBF16NaiveInPlace
    return _MUON_BF16_NAIVE_CLS


# ---------------------------------------------------------------------------
# bf16-storage momentum memmap helper + post-construction state swap.
# ---------------------------------------------------------------------------

def bf16_view_memmap(path: Path, shape: tuple):
    """A fresh, zero-initialized, file-backed bf16 CPU tensor. numpy has no
    native bfloat16 dtype, so this reuses cpu_offload_adamw._memmap_zeros
    UNMODIFIED with dtype=np.int16 (the 2-byte proxy every numpy/torch
    build supports -- Tensor.view(dtype) bitcasts by itemsize, not by
    sign/float-ness, so int16 and bfloat16 are interchangeable storage
    views of the same bytes), then bitcasts the returned tensor to
    torch.bfloat16 via .view(). The file is still zero-commit (file-backed,
    per cpu_offload_adamw.py's own module docstring) and zero-initialized
    (int16 zero bits == bfloat16 zero bits == 0.0)."""
    import numpy as np
    import torch
    i16 = _coa._memmap_zeros(path, shape, dtype=np.int16)
    return i16.view(torch.bfloat16)


def install_bf16_momentum(coa_opt: "_coa.CPUOffloadOptimizer",
                           optstate_dir: Path) -> None:
    """Post-construction state substitution -- CPUOffloadOptimizer.__init__
    already pre-seeded every shadow param's momentum_buffer as an fp32
    memmap (its own untouched default, for ANY non-Adam inner optimizer
    class, per the class's __init__ docstring). This call swaps ONLY the
    tensor object at coa_opt._inner.state[shadow_p]['momentum_buffer'] for
    a bf16-view of a freshly-created int16-backed memmap file. No class
    body anywhere -- cpu_offload_adamw.py included -- is edited; this is a
    state-dict entry replacement performed the same way _snapshot_fork /
    _restore_fork_ in cbase_grow_rung2_attribution_702.py already read/
    write coa_opt._inner.state directly (an established in-repo pattern,
    not a new access path). Caller must construct coa_opt with an
    opt_factory returning a _muon_bf16_momentum_fixed_class() instance --
    this function only swaps the STORAGE dtype; the arithmetic dataflow
    (A1) lives in that class's step()."""
    for name, shadow_p in zip(coa_opt._names, coa_opt._shadow):
        state = coa_opt._inner.state.get(shadow_p)
        if state is None or "momentum_buffer" not in state:
            continue
        stem = optstate_dir / _coa._sanitize_name(name)
        state["momentum_buffer"] = bf16_view_memmap(
            Path(str(stem) + ".momentum.bf16proxy.i16"), tuple(shadow_p.shape))


# ---------------------------------------------------------------------------
# Arm optimizer construction.
# ---------------------------------------------------------------------------

def build_arm_optimizers(model, cfg, *, arm: str, optstate_dir: Path):
    """Returns (optimizers, base_lrs, routing) -- same shape as
    ts.build_split_optimizer's return, so ts.apply_wsd and _run_arm_block
    work unmodified against either arm's dict.

    arm == "fp32": calls ts.build_split_optimizer(..., offload_optimizer_
        state=True) DIRECTLY -- zero new code, this IS "production, current
        code" (#707 Section D: "Arm A: production fp32 momentum").
    arm == "bf16": mirrors build_split_optimizer's own muon+adamw branches
        (adamw branch copied verbatim -- AdamW never changes, A2) but
        substitutes _muon_bf16_momentum_fixed_class() for ts._muon_class()
        on the muon branch, then calls install_bf16_momentum() to swap the
        momentum storage dtype post-construction."""
    import torch
    optstate_dir = Path(optstate_dir)
    optstate_dir.mkdir(parents=True, exist_ok=True)

    if arm == "fp32":
        return ts.build_split_optimizer(
            model, cfg, offload_optimizer_state=True,
            optstate_dir=str(optstate_dir))

    if arm != "bf16":
        raise ValueError(f"build_arm_optimizers: arm must be 'fp32' or 'bf16', got {arm!r}")

    opt_cfg = cfg["optimizer"]
    lr_muon = opt_cfg["lr_muon"]
    lr_adamw = opt_cfg["lr_adamw"]
    wd = opt_cfg["weight_decay"]
    muon_named, adamw_named = ts.split_param_groups(model)
    routing = {
        "muon_params": [n for n, _ in muon_named],
        "adamw_params": [n for n, _ in adamw_named],
        "n_muon": len(muon_named),
        "n_adamw": len(adamw_named),
        "offload_optimizer_state": True,
        "mode": "muon_split_bf16_momentum",
    }
    MuonBF16MomentumFixed = _muon_bf16_momentum_fixed_class()
    opts: dict = {}
    base_lrs: dict = {}
    if muon_named:
        opts["muon"] = _coa.CPUOffloadOptimizer(
            muon_named,
            lambda ps: MuonBF16MomentumFixed(ps, lr=lr_muon, weight_decay=wd),
            optstate_dir=str(optstate_dir))
        install_bf16_momentum(opts["muon"], optstate_dir)
        base_lrs["muon"] = lr_muon
    if adamw_named:
        # Copied verbatim from build_split_optimizer's own adamw branch --
        # AdamW moments stay fp32 (A2), zero divergence from production.
        opts["adamw"] = _coa.CPUOffloadOptimizer(
            adamw_named,
            lambda ps: torch.optim.AdamW(ps, lr=lr_adamw, weight_decay=wd),
            optstate_dir=str(optstate_dir))
        base_lrs["adamw"] = lr_adamw
    return opts, base_lrs, routing


def realized_matrix_split(model, routing: dict) -> dict:
    """REALIZED (not advertised) matrix/non-matrix param counts, per #667's
    interim rule ('advertised counts are not evidence' -- any structured
    pilot spec must receipt realized counts explicitly). Sums .numel() over
    the ACTUAL named parameters routing['muon_params']/['adamw_params']
    name each arm's optimizer split to -- never a hardcoded/config-derived
    guess. muon_params are ALWAYS the matrix-routed (2D, non-embed,
    non-head) set per split_param_groups' own routing predicate."""
    by_name = dict(model.named_parameters())
    matrix = sum(by_name[n].numel() for n in routing["muon_params"] if n in by_name)
    nonmatrix = sum(by_name[n].numel() for n in routing["adamw_params"] if n in by_name)
    return {
        "realized_matrix_params": int(matrix),
        "realized_nonmatrix_params": int(nonmatrix),
        "realized_total_params": int(matrix + nonmatrix),
    }


# ---------------------------------------------------------------------------
# Isolated-arm-lifetime invariant (falsifier finding, #792 cure round,
# ORCHESTRATION). This is what makes "build -> measure -> TEAR DOWN -> next
# arm" a STRUCTURAL guarantee rather than a promise -- the original defect
# (arm A and arm A2 both still resident when arm B was built and measured)
# could not happen with this wired into _one_arm's build/teardown points.
# ---------------------------------------------------------------------------
_ALIVE_ARM_SLOTS: set = set()
_TEARDOWN_SETTLE_S = 2.0  # brief pause after del+gc.collect()+empty_cache()
                          # for Windows' documented del/GC commit-release lag
                          # (named in this repo's own cbase_grow_rung2_
                          # attribution_702.py fork-capacity pricing notes) --
                          # so the NEXT arm's commit reading is not polluted
                          # by a release still in flight.


def _assert_no_arm_alive(context: str) -> None:
    """Raises if another arm's heavy state is still tracked as alive when a
    new arm is about to be built, or when a commit-footprint reading is
    about to be taken. See module docstring CURE ROUND (1)."""
    if _ALIVE_ARM_SLOTS:
        raise RuntimeError(
            f"isolated-arm-lifetime violation ({context}): arm slot(s) "
            f"{sorted(_ALIVE_ARM_SLOTS)!r} still alive -- teardown must "
            f"complete before the next arm is built or measured (falsifier "
            f"finding, #792 cure round)")


def _teardown_arm(model, optimizers: dict, device: str) -> None:
    """Frees the model + optimizer wrapper objects between arms so each
    arm's commit_steady_state_gib reading reflects ONLY that arm's build.
    Momentum-buffer FILES are never deleted (only the in-process Python
    objects) -- momentum_cosine_diagnostic reopens them fresh from disk
    after teardown via momentum_file_manifest. Mirrors this codebase's own
    established del+gc.collect()+empty_cache() pattern (c04_*.py,
    accumulation_law/run_accumulation.py)."""
    import gc
    import torch
    optimizers.clear()
    del model
    gc.collect()
    if device == "cuda" and torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    time.sleep(_TEARDOWN_SETTLE_S)


def compute_commit_delta_gib(*, arm_a_commit: dict, arm_b_commit: dict) -> float:
    """Pins the sign convention (falsifier finding, #792 cure round, SIGN):
    check_byte_arithmetic's expected_delta_bytes is ALWAYS POSITIVE (fp32
    4B/param -> bf16 2B/param is a byte REDUCTION --
    AMENDMENT1_BYTES_PER_MATRIX_PARAM_MOMENTUM_DELTA=2 is a positive
    per-param count), so the measured delta must be fp32_used - bf16_used
    (arm A minus arm B), never the reverse. The original code computed
    arm_b.used_gib - arm_a.used_gib; the falsifier's repro
    (check_byte_arithmetic(commit_delta_gib=-0.5, realized_p_matrix=
    268_435_456) -> rel_err=2.0, INVALID_INSTRUMENT_DEFECT) is exactly what
    that inverted sign produces whenever bf16 genuinely uses less committed
    memory than fp32 -- the EXPECTED, correct direction of the effect this
    screen measures."""
    if not (arm_a_commit.get("applicable") and arm_b_commit.get("applicable")):
        return 0.0
    return arm_a_commit["used_gib"] - arm_b_commit["used_gib"]


# ---------------------------------------------------------------------------
# Steady-state commit-footprint governor read (measurand 1).
# ---------------------------------------------------------------------------

def commit_steady_state_gib(*, construction_complete: bool) -> dict:
    """Wraps governor._commit_status() with AMENDMENT-1's pinned timing
    (finding 4b): a construction-phase reading is INVALID BY DEFINITION,
    not a finding either way -- refuses to even attempt the read before the
    caller asserts construction_complete=True. Three distinct outcomes,
    never conflated (gate-discipline: an unavailable decisive statistic is
    a refusal, not a disclosed skip -- same discipline as
    _preflight_fork_capacity in cbase_grow_rung2_attribution_702.py):
      - construction_complete=False -> raises RuntimeError (caller error,
        never a silent stale/zero reading).
      - non-Windows platform -> {"applicable": False, ...} (disclosed,
        genuinely inapplicable -- commit-charge accounting does not exist
        on this platform, per governor._commit_status's own docstring).
      - Windows but the syscall fails -> propagates OSError uncaught (the
        caller must refuse the run, never proceed on an unmeasured
        decisive statistic)."""
    if not construction_complete:
        raise RuntimeError(
            "commit_steady_state_gib called before construction_complete="
            "True -- AMENDMENT-1 finding 4b pins measurand (1) to STEADY "
            "STATE (post-warmup, post the one-time construction "
            "write-pass); a construction-phase reading is INVALID BY "
            "DEFINITION, not a finding either way.")
    status = governor._commit_status()
    if status is None:
        return {"applicable": False,
                "reason": "non-Windows platform -- commit-charge/page-file "
                          "accounting is a Windows concept with no direct "
                          "POSIX equivalent"}
    avail_bytes, total_bytes = status
    gib = 1024.0 ** 3
    used_bytes = total_bytes - avail_bytes
    return {
        "applicable": True,
        "avail_gib": round(avail_bytes / gib, 4),
        "total_gib": round(total_bytes / gib, 4),
        "used_gib": round(used_bytes / gib, 4),
    }


def check_byte_arithmetic(*, commit_delta_gib: float, realized_p_matrix: int,
                           band_frac: float = 0.35) -> dict:
    """Measurand (1)'s 'must match the byte arithmetic within band, else
    INVALID (instrument defect, not a kill)' check. Scales AMENDMENT-1's
    corrected 2.2B-identity commit delta (4.194 GB for p_matrix=
    2,097,152,000, i.e. AMENDMENT1_BYTES_PER_MATRIX_PARAM_MOMENTUM_DELTA=2
    bytes/matrix-param) by THIS run's own REALIZED p_matrix -- never a
    hardcoded 434M-scale number, since the ledger was only ever corrected
    at the 2.2B identity. band_frac=0.35 is a deliberately loose
    instrument-defect band (this measurand's own text: 'else INVALID
    (instrument defect, not a kill)' -- it exists to catch a governor
    read that is wildly wrong, not to gate the arm comparison itself,
    which is measurand (3)'s loss-band job)."""
    gib = 1024.0 ** 3
    expected_delta_bytes = realized_p_matrix * AMENDMENT1_BYTES_PER_MATRIX_PARAM_MOMENTUM_DELTA
    expected_delta_gib = round(expected_delta_bytes / gib, 4)
    if expected_delta_gib <= 0:
        return {"expected_delta_gib": expected_delta_gib,
                "measured_delta_gib": round(commit_delta_gib, 4),
                "within_band": False,
                "verdict": "INVALID_INSTRUMENT_DEFECT",
                "detail": "expected_delta_gib <= 0 -- realized_p_matrix "
                          "measurement is itself broken"}
    rel_err = abs(commit_delta_gib - expected_delta_gib) / expected_delta_gib
    within = rel_err <= band_frac
    return {
        "expected_delta_gib": expected_delta_gib,
        "measured_delta_gib": round(commit_delta_gib, 4),
        "relative_error": round(rel_err, 4),
        "band_frac": band_frac,
        "within_band": within,
        "verdict": "OK" if within else "INVALID_INSTRUMENT_DEFECT",
    }


# ---------------------------------------------------------------------------
# Copies / opt_other bucket aggregation (measurand 2) from the #702
# attribution instrument's own SubphaseCollector -- zero reimplementation.
# ---------------------------------------------------------------------------

COPIES_SUBPHASES = ("grad_to_cpu_fp32", "grad_heap_to_memmap", "updated_param_to_gpu")
OPT_OTHER_SUBPHASES = ("inner_optimizer_step",)


def copies_opt_other_totals(collector: "attrib.SubphaseCollector") -> dict:
    """Aggregates attrib.SubphaseCollector.phase_totals()/byte_totals() into
    the two buckets #707 Section D measurand (2) names: 'copies' (the three
    pure data-movement subphases) and 'opt_other' (inner_optimizer_step --
    the only subphase whose wall-time the A1 dataflow's own fp32
    upcast/EMA/Nesterov/downcast arithmetic can plausibly move).

    LOAD-BEARING ACCOUNTING LINE, quoted (cpu_offload_adamw.py, unmodified):
        _add_bytes("grad_to_cpu_fp32", g.numel() * g.element_size())
        _add_bytes("grad_heap_to_memmap", g.numel() * g.element_size())
        _add_bytes("updated_param_to_gpu", shadow_p.data.numel() * real_p.element_size())
    Confirmed MEASURED (numel() * element_size() of the actual tensor moved
    at that instant), never a fixed 4B-per-param constant -- so copies_bytes
    is real for the three subphases it covers.

    KNOWN GAP (team-lead review, addressed by momentum_buffer_bytes_sidecar
    below): inner_optimizer_step (opt_other) gets ONLY a time measurement --
    `_add("inner_optimizer_step", ...)` -- cpu_offload_adamw.py's step()
    NEVER calls _add_bytes for this subphase, because self._inner.step() is
    an opaque call into the wrapped Muon/MuonBF16MomentumFixed instance; the
    span collector has no visibility into what happens inside it. The
    momentum buffer's OWN read/write (buf.mul_/add_/copy_, where the fp32-
    vs-bf16 storage delta actually lives) executes entirely inside that
    opaque call. copies_bytes is therefore NOT lying (it correctly excludes
    momentum traffic, which it was never instrumented to see) but it is
    BLIND to exactly the byte delta this screen exists to measure -- the
    existing instrument alone cannot answer measurand (2)'s momentum-storage
    question, only its grad/param-transfer question (which is, correctly,
    identical between arm A and arm B -- neither arm changes grad or param
    handling)."""
    phase_totals = collector.phase_totals()
    byte_totals = collector.byte_totals()
    return {
        "copies_wall_s": round(sum(phase_totals[p] for p in COPIES_SUBPHASES), 6),
        "copies_bytes": int(sum(byte_totals[p] for p in COPIES_SUBPHASES)),
        "copies_bytes_note": "measured (numel*element_size) for grad/param "
                             "transfer only -- excludes momentum traffic; "
                             "see momentum_buffer_bytes_sidecar for that",
        "opt_other_wall_s": round(sum(phase_totals[p] for p in OPT_OTHER_SUBPHASES), 6),
        "n_steps": len(collector.step_records),
    }


def momentum_buffer_bytes_sidecar(optimizers: dict) -> dict:
    """MEASURED-BYTES SIDECAR (team-lead review, issue #792): the #702
    attribution instrument's byte accounting has zero coverage of momentum-
    buffer traffic (see copies_opt_other_totals docstring) -- this function
    fills exactly that gap without editing cpu_offload_adamw.py or
    cbase_grow_rung2_attribution_702.py. Reads each Muon shadow param's
    REALIZED momentum_buffer tensor directly (same established internal-
    state-read pattern as install_bf16_momentum / momentum_cosine_
    diagnostic) and sums numel() * element_size() -- MEASURED from the
    actual tensor object each arm is using, never a hardcoded per-param
    constant, so arm B's halved momentum footprint (bf16, 2 bytes/elem)
    versus arm A's (fp32, 4 bytes/elem) is directly visible here even
    though it is invisible to copies_bytes."""
    muon = optimizers.get("muon")
    if muon is None:
        return {"applicable": False, "reason": "no muon optimizer in this arm"}
    total_bytes = 0
    total_numel = 0
    dtypes_seen = set()
    for shadow_p in muon._shadow:
        state = muon._inner.state.get(shadow_p)
        if state is None or "momentum_buffer" not in state:
            continue
        buf = state["momentum_buffer"]
        total_bytes += buf.numel() * buf.element_size()
        total_numel += buf.numel()
        dtypes_seen.add(str(buf.dtype))
    return {
        "applicable": True,
        "momentum_buffer_bytes_resident": int(total_bytes),
        "momentum_buffer_numel": int(total_numel),
        "momentum_buffer_dtypes": sorted(dtypes_seen),
        # Per-step read+modify+write traffic for the momentum buffer alone
        # (one full read + one full write per step, in EITHER implementation
        # -- A1 additionally upcasts to a transient fp32 tensor for compute,
        # but that transient never touches the memmap/disk, so it is not
        # counted as storage TRAFFIC here, only the persisted bf16/fp32
        # read+write is).
        "momentum_buffer_traffic_bytes_per_step": int(total_bytes * 2),
    }


# ---------------------------------------------------------------------------
# Momentum-buffer cosine diagnostic (measurand 4, diagnostic only).
# Rewritten for isolated arm lifetimes (falsifier finding, #792 cure round,
# ORCHESTRATION): the original version required BOTH arms' live optimizer
# objects resident simultaneously, which is exactly the retention defect the
# teardown cure removes. momentum_file_manifest captures each arm's momentum-
# buffer FILE PATHS (+ shapes) while the arm is still alive -- small (path
# strings and shape tuples, no tensor data) -- and momentum_cosine_diagnostic
# reopens those files fresh, read-only, AFTER both arms have already been
# torn down. File-backed reopens are zero-commit-charge, the same convention
# this codebase's CPUOffloadOptimizer memmap tensors already rely on, so this
# diagnostic-only measurand (#707 Section D: "never a gate") adds no
# meaningful resident-memory footprint of its own.
# ---------------------------------------------------------------------------

def momentum_file_manifest(optimizers: dict, *, arm: str, optstate_dir: "Path") -> dict:
    """Captures {name: {"path", "shape", "dtype"}} for each muon-routed
    param's momentum_buffer file, while the arm is still alive. `arm`
    ("fp32" or "bf16") selects the on-disk naming convention: fp32 is
    cpu_offload_adamw.CPUOffloadOptimizer's own untouched default
    (`<stem>.momentum.f32`, cpu_offload_adamw.py's __init__); bf16 is this
    file's own install_bf16_momentum convention
    (`<stem>.momentum.bf16proxy.i16`). No tensor data is read here -- only
    path strings and shape tuples, so this manifest survives _teardown_arm."""
    muon = optimizers.get("muon")
    if muon is None:
        return {}
    manifest: dict = {}
    for name, shadow_p in zip(muon._names, muon._shadow):
        state = muon._inner.state.get(shadow_p)
        if state is None or "momentum_buffer" not in state:
            continue
        shape = tuple(state["momentum_buffer"].shape)
        stem = Path(optstate_dir) / _coa._sanitize_name(name)
        suffix = ".momentum.bf16proxy.i16" if arm == "bf16" else ".momentum.f32"
        manifest[name] = {"path": str(Path(str(stem) + suffix)),
                          "shape": shape, "dtype": arm}
    return manifest


def _reopen_momentum_fp32(path: str, shape: tuple, dtype_tag: str):
    """Reopens a persisted momentum-buffer memmap file FRESH (read-only,
    zero-commit-charge, same np.memmap(mode='r') pattern
    test_bf16_view_memmap_roundtrip already uses) and returns it
    materialized as an fp32 torch tensor. dtype_tag=='bf16' bitcasts the
    on-disk int16 proxy to bfloat16 first (the SAME reinterpretation
    bf16_view_memmap uses to write it) before upcasting to fp32."""
    import numpy as np
    import torch
    if dtype_tag == "bf16":
        i16 = np.memmap(path, dtype=np.int16, mode="r", shape=shape)
        t = torch.from_numpy(np.asarray(i16)).view(torch.bfloat16)
        return t.to(torch.float32)
    f32 = np.memmap(path, dtype=np.float32, mode="r", shape=shape)
    return torch.from_numpy(np.asarray(f32)).to(torch.float32)


def momentum_cosine_diagnostic(manifest_a: dict, manifest_b: dict) -> dict:
    """fp32-materialized cosine similarity between arm A's (fp32-native) and
    arm B's (bf16-stored, upcast for comparison) Muon momentum buffers,
    reopened fresh from each arm's momentum_file_manifest -- see the section
    docstring above for why this no longer needs both arms' live optimizer
    objects. Diagnostic only -- #707 Section D: 'momentum-buffer cosine vs
    fp32 twin at fixed checkpoints (diagnostic, not a gate)'."""
    common = sorted(set(manifest_a) & set(manifest_b))
    if not common:
        return {"applicable": False,
                "reason": "no common muon param names between the two arms' manifests"}
    cos_by_name = {}
    dot_sum = 0.0
    norm_a_sum = 0.0
    norm_b_sum = 0.0
    for name in common:
        info_a = manifest_a[name]
        info_b = manifest_b[name]
        if tuple(info_a["shape"]) != tuple(info_b["shape"]):
            continue
        shape = tuple(info_a["shape"])
        a32 = _reopen_momentum_fp32(info_a["path"], shape, info_a["dtype"]).flatten()
        b32 = _reopen_momentum_fp32(info_b["path"], shape, info_b["dtype"]).flatten()
        denom = float(a32.norm() * b32.norm())
        cos = float((a32 @ b32) / denom) if denom > 0 else None
        cos_by_name[name] = cos
        dot_sum += float(a32 @ b32)
        norm_a_sum += float(a32.norm() ** 2)
        norm_b_sum += float(b32.norm() ** 2)
    pooled_denom = (norm_a_sum ** 0.5) * (norm_b_sum ** 0.5)
    pooled_cosine = (dot_sum / pooled_denom) if pooled_denom > 0 else None
    return {
        "applicable": True,
        "pooled_cosine": pooled_cosine,
        "n_params_compared": len(cos_by_name),
        "min_cosine": min((v for v in cos_by_name.values() if v is not None), default=None),
    }


# ---------------------------------------------------------------------------
# Loss-delta seed-noise-band + kill-condition evaluation (measurand 3).
# ---------------------------------------------------------------------------

def build_noise_band(losses_seed1: list, losses_seed2: list) -> dict:
    """AMENDMENT-1: 'the n=2 loss band is a single-draw noise sample (1
    degree of freedom) -- disclosed in the kill text.' Band = per-step
    |loss(seed1) - loss(seed2)| at matched steps, both fp32-momentum
    (production) runs -- set BEFORE arm B (bf16) ever runs, per Section D:
    'run one extra fp32 seed to set the band BEFORE unblinding arm B.'"""
    n = min(len(losses_seed1), len(losses_seed2))
    deltas = [abs(losses_seed1[i] - losses_seed2[i]) for i in range(n)]
    band = max(deltas) if deltas else 0.0
    return {"n_steps_compared": n, "per_step_deltas": deltas, "band": band,
            "dof": 1, "disclosed": "single-draw noise sample, 1 degree of "
                                    "freedom (AMENDMENT-1 finding 3)"}


def evaluate_verdict(*, losses_arm_b: list, losses_arm_a: list, band: dict,
                      commit_check: dict, band_tolerance: float = 1.5) -> dict:
    """Applies #707 Section D's pre-registered kill conditions, quoted
    verbatim in REFUSAL_TEXT, plus AMENDMENT-1's INCONCLUSIVE tightening.
    Never widens the band post-hoc ('No post-hoc band widening')."""
    n = min(len(losses_arm_b), len(losses_arm_a))
    deltas = [abs(losses_arm_b[i] - losses_arm_a[i]) for i in range(n)]
    max_delta = max(deltas) if deltas else 0.0
    band_val = band["band"]
    beyond_band = max_delta > band_val
    near_edge = (not beyond_band) and band_val > 0 and (max_delta >= band_val / band_tolerance)

    if commit_check["verdict"] != "OK":
        verdict = "INVALID"
        reason = "measurand (1) commit-footprint delta failed the byte-arithmetic band check -- instrument defect, not a kill"
    elif beyond_band:
        verdict = "KILL"
        reason = "loss-delta beyond the pre-registered seed-noise band at matched steps -- bf16-momentum KILLED at this scale under QAT (D4 negative)"
    elif near_edge:
        verdict = "INCONCLUSIVE"
        reason = "loss-delta within 1.5x of the band edge (AMENDMENT-1 finding 4a) -- requires a second extra seed, never a clean PROMOTE/KILL"
    else:
        verdict = "PROMOTE"
        reason = "commit delta inside band + loss delta inside band -- PROMOTE to (a) 2.2B config for the capacity claim and (b) arm-2 int8-blockwise screen"

    return {
        "verdict": verdict,
        "reason": reason,
        "max_loss_delta": max_delta,
        "band": band_val,
        "n_steps_compared": n,
        "kill_text": REFUSAL_TEXT,
    }


# ---------------------------------------------------------------------------
# Per-arm training block. Composes production QAT (run_v0_segment's own
# pattern) with the #702 attribution instrument's profiling hooks -- no
# optimizer/loss/QAT math is reimplemented, only the outer loop is new
# (per #702's own docstring: "the outer step loop is necessarily its own").
# ---------------------------------------------------------------------------

def run_arm_block(*, model, loader, optimizers, base_lrs, cfg, ce_fn,
                   mtp_enabled, mtp_weight, ce_chunk_tokens, n_steps: int,
                   global_step_start: int, total_steps: int, device: str,
                   batch_size: int, collector=None) -> dict:
    """PRODUCTION-PARITY (team-lead review, #792 cure round, falsifier
    finding 2): the per-step body is now the SHARED ts._run_production_step
    (landed master #762, sha 6332494d) -- this function used to be a
    hand-composed copy of that same body (QAT pre-forward, WSD apply,
    forward/loss/backward, QAT post-backward restore, opt.step()/
    zero_grad()) with no parity guarantee, exactly the sibling-
    reimplementation defect ember #702 ADDENDUM-5 class rule F exists to
    prevent. Only the OUTER loop -- step_walls timing and collector.
    begin_step/end_step bracketing -- remains this file's own, per #702's
    own docstring: "the outer step loop is necessarily its own" (axis-3's
    attrib._run_block doesn't run QAT, so this composition -- a QAT-enabled
    outer loop calling the shared per-step body -- is still new; the
    per-step ARITHMETIC inside it is no longer a sibling copy).
    phase_cb feeds fwd/loss/bwd spans into `collector` under the SAME names
    the pre-extraction inline loop used, so measurand (2)'s copies/
    opt_other bucketing (COPIES_SUBPHASES/OPT_OTHER_SUBPHASES) is
    unaffected; inner_optimizer_step/grad_to_cpu_fp32/grad_heap_to_memmap/
    updated_param_to_gpu still come from attrib.install_span_collector's
    patch on the optimizer objects themselves (unchanged -- _run_production_
    step calls opt.step() on those SAME already-patched objects)."""
    import torch
    sync = (torch.cuda.synchronize if device == "cuda" and torch.cuda.is_available()
            else (lambda: None))
    qat_enabled = bool(cfg.get("precision", {}).get("qat", {}).get("enabled", False))
    step_walls: list = []
    losses: list = []

    def _phase_cb(name, dt):
        collector.add(name, dt)

    for local_step in range(n_steps):
        global_step = global_step_start + local_step
        if collector is not None:
            collector.begin_step()
        sync(); t_step0 = time.perf_counter()

        step_result = ts._run_production_step(
            model=model, loader=loader, optimizers=optimizers, base_lrs=base_lrs,
            cfg=cfg, ce_fn=ce_fn, mtp_enabled=mtp_enabled, mtp_weight=mtp_weight,
            ce_chunk_tokens=ce_chunk_tokens, device=device, batch_size=batch_size,
            global_step=global_step, total_steps=total_steps, grad_accum_steps=1,
            qat_enabled=qat_enabled,
            phase_cb=(_phase_cb if collector is not None else None),
            sync_cb=(sync if collector is not None else None))

        sync(); step_wall = time.perf_counter() - t_step0
        step_walls.append(step_wall)
        losses.append(float(step_result["loss"]))
        if collector is not None:
            collector.end_step(step_wall)
    return {"step_walls": step_walls, "losses": losses}


# ---------------------------------------------------------------------------
# Code/config/shard identity binding (team-lead review finding 3, #792 cure
# round, PROVENANCE BINDING). Field-name convention pinned by ember #801
# ("the receipt gains executing_git_sha [repo HEAD at run time] + sha256 of
# the runner source file(s) actually imported -- absence is a schema-probe
# refusal, fail-closed, same class as the identity gates"). Extends #801's
# narrower runner-file scope to also bind config + shard identity
# (team-lead's explicit ask: "source/config/shard hashes"), reusing
# established in-repo hashers rather than reimplementing:
# manifest_sha.compute_manifest for the shard (the SAME function
# timeshare_pretrain.py's own corpus-cache trust check calls), plain sha256
# of the frozen contract config file and this runner's own source + its
# direct read-only reference imports.
# ---------------------------------------------------------------------------

def _file_sha256(p: "Path") -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_PROVENANCE_REFERENCE_MODULES = (
    "timeshare_pretrain.py", "cpu_offload_adamw.py", "governor.py",
    "receipt_write.py", "receipt_check.py", "cbase_grow_rung2_attribution_702.py",
)


def compute_provenance(*, shard_dir: str | None, config_path: "Path | None" = None) -> dict:
    """Returns the provenance dict every live receipt binds (see section
    docstring above). Never raises on a missing/unavailable input -- each
    leg discloses its own error string so refuse_on_missing_provenance can
    make the fail-closed decision explicitly, rather than an opaque
    exception from deep inside a hash routine."""
    this_file = Path(__file__).resolve()

    try:
        executing_git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(_REPO),
            stderr=subprocess.DEVNULL, text=True).strip()
        git_sha_error = None
    except Exception as e:
        executing_git_sha = None
        git_sha_error = repr(e)

    source_sha256 = {this_file.name: _file_sha256(this_file)}
    for mod_name in _PROVENANCE_REFERENCE_MODULES:
        p = this_file.parent / mod_name
        if p.exists():
            source_sha256[mod_name] = _file_sha256(p)

    config_path = Path(config_path) if config_path is not None else (
        _REPO / "configs" / "v0-pretrain-config.json")
    config_sha256 = _file_sha256(config_path) if config_path.exists() else None

    shard_manifest_sha256 = None
    shard_manifest_error = None
    if shard_dir:
        try:
            from manifest_sha import compute_manifest
            shard_manifest_sha256 = compute_manifest(shard_dir)["combined_sha256"]
        except Exception as e:
            shard_manifest_error = repr(e)

    return {
        "executing_git_sha": executing_git_sha,
        "executing_git_sha_error": git_sha_error,
        "source_sha256": source_sha256,
        "config_path": str(config_path),
        "config_sha256": config_sha256,
        "shard_dir": shard_dir,
        "shard_manifest_sha256": shard_manifest_sha256,
        "shard_manifest_error": shard_manifest_error,
    }


def refuse_on_missing_provenance(provenance: dict, *, live: bool) -> None:
    """Fail-closed enforcement of #801's binding requirement -- since
    receipt_check.py is a READ-ONLY reference (this PR's surface is this
    file plus its own tests only), the refusal lives here rather than in
    the shared schema validator. Applies ONLY to --live (a real dispatch
    with a real shard_dir and a real repo checkout); --schema-probe and
    --selftest run compute_provenance for real (proving the code path) but
    never refuse on it, since a schema-probe/selftest environment may
    legitimately lack a shard_dir."""
    if not live:
        return
    missing = []
    if not provenance.get("executing_git_sha"):
        missing.append(f"executing_git_sha ({provenance.get('executing_git_sha_error')})")
    if not provenance.get("config_sha256"):
        missing.append("config_sha256 (config file not found)")
    if provenance.get("shard_dir") and not provenance.get("shard_manifest_sha256"):
        missing.append(f"shard_manifest_sha256 ({provenance.get('shard_manifest_error')})")
    if missing:
        raise RuntimeError(
            "PROVENANCE_BINDING_REFUSAL (ember #801 convention, fail-closed, "
            "same class as the identity gates): " + "; ".join(missing))


# ---------------------------------------------------------------------------
# Receipt construction -- the SAME function builds the real receipt AND the
# --schema-probe dummy receipt (launch-time schema probe rule, gate-
# discipline-rules.md: "construct the complete real receipt dict through
# the SAME code path with dummy/zero measurement values, run receipt_check.
# validate_receipt, refuse launch on any finding").
# ---------------------------------------------------------------------------

def build_receipt(*, ts_str: str, live: bool, realized_split: dict,
                   commit_delta_gib: float, byte_check: dict,
                   copies_opt_other_a: dict, copies_opt_other_b: dict,
                   momentum_bytes_a: dict, momentum_bytes_b: dict,
                   momentum_cosine: dict, band: dict, verdict: dict,
                   run_config: dict, provenance: dict) -> dict:
    findings_note = (
        "sha_convention: bytes on disk as-is (binary read, no line-ending "
        "normalization) -- matches receipt_check.py's own documented "
        "convention; present because this receipt's provenance section may "
        "carry a sha256 field."
    )
    d = {
        "ticket": TICKET,
        "ts": ts_str,
        "invariant_sha256": receipt_check.INVARIANT_SHA256,
        "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
        "refs": ISSUE_REFS,
        "live": bool(live),
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "scale": "434M c03 (frozen contract native scale)",
        "run_config": run_config,
        "provenance": provenance,
        "realized_split": realized_split,
        "measurand_1_commit_footprint": {
            "commit_delta_gib": commit_delta_gib,
            "byte_arithmetic_check": byte_check,
        },
        "measurand_2_copies_opt_other": {
            "arm_fp32": copies_opt_other_a,
            "arm_bf16": copies_opt_other_b,
            "momentum_buffer_bytes_sidecar": {
                "arm_fp32": momentum_bytes_a,
                "arm_bf16": momentum_bytes_b,
            },
        },
        "measurand_3_loss_band": band,
        "measurand_4_momentum_cosine_diagnostic": momentum_cosine,
        "verdict": verdict["verdict"],
        "verdict_reason": verdict["reason"],
        "kills": REFUSAL_TEXT,
        "not_claimed": [
            "any 2.2B step-time number (needs the branch-B receipt)",
            "any transplant-fidelity statement (A3 clause)",
            "any master-precision statement (A2)",
            "any bf16-Muon-momentum-safety claim outside the QAT-on "
            "configuration (AMENDMENT-1 finding 5)",
        ],
        "note": findings_note,
    }
    return d


# ---------------------------------------------------------------------------
# --selftest -- pure-CPU coverage, no model/GPU/live dispatch.
# ---------------------------------------------------------------------------

def _selftest() -> int:
    """CPU-only coverage: bf16 memmap round-trip, byte-arithmetic check
    branches, noise-band + verdict-evaluation branches (KILL/INCONCLUSIVE/
    PROMOTE/INVALID), the SIGN and ORCHESTRATION cure-round fixtures
    (falsifier findings against head f81728f3), the PROVENANCE binding
    fixture (#801 convention), and the required negative fixture (delegated
    to tests/test_screen792_bf16_momentum.py so the fixture lives in
    exactly one place)."""
    import tempfile
    import torch

    ok = True

    # 1. bf16 memmap round-trip.
    # ignore_cleanup_errors=True (first-execution finding, #792 cure round,
    # unrelated to the falsifier's three findings): np.memmap keeps the
    # backing file mapped on Windows, so a TemporaryDirectory holding an
    # OPEN memmap cannot rmtree itself at __exit__ (WinError 32) until the
    # OS releases the handle -- non-deterministic without an explicit
    # del+gc.collect() the mapped tensors don't otherwise need. Standard
    # stdlib escape hatch (Python 3.10+) for exactly this class; the test's
    # own assertions all run and pass before this cleanup step, so nothing
    # about correctness depends on it.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        p = Path(d) / "probe.momentum.bf16proxy.i16"
        t = bf16_view_memmap(p, (4, 4))
        if t.dtype != torch.bfloat16:
            print(f"FAIL bf16_view_memmap: dtype={t.dtype}, expected bfloat16")
            ok = False
        if not torch.equal(t, torch.zeros(4, 4, dtype=torch.bfloat16)):
            print("FAIL bf16_view_memmap: not zero-initialized")
            ok = False
        t.copy_(torch.full((4, 4), 1.5, dtype=torch.bfloat16))
        # Reopen the same file fresh to prove the write is real (file-
        # backed, not just an in-process tensor mutation).
        import numpy as np
        reopened = np.memmap(str(p), dtype=np.int16, mode="r", shape=(4, 4))
        reopened_t = torch.from_numpy(reopened).view(torch.bfloat16)
        if not torch.equal(reopened_t, torch.full((4, 4), 1.5, dtype=torch.bfloat16)):
            print("FAIL bf16_view_memmap: reopened file does not show the write")
            ok = False

    # 2. byte-arithmetic check branches.
    c_ok = check_byte_arithmetic(commit_delta_gib=0.5, realized_p_matrix=268_435_456)
    # expected = 268435456*2/1024**3 = 0.5 GiB exactly -> within band.
    if not c_ok["within_band"]:
        print(f"FAIL check_byte_arithmetic: expected within-band, got {c_ok}")
        ok = False
    c_bad = check_byte_arithmetic(commit_delta_gib=5.0, realized_p_matrix=268_435_456)
    if c_bad["within_band"]:
        print(f"FAIL check_byte_arithmetic: expected out-of-band, got {c_bad}")
        ok = False

    # 3. noise band + verdict branches.
    band = build_noise_band([1.0, 1.0, 1.0], [1.02, 0.99, 1.01])  # band=0.02
    v_kill = evaluate_verdict(losses_arm_b=[1.5, 1.0, 1.0], losses_arm_a=[1.0, 1.0, 1.0],
                              band=band, commit_check=c_ok)
    if v_kill["verdict"] != "KILL":
        print(f"FAIL evaluate_verdict: expected KILL, got {v_kill}")
        ok = False
    v_promote = evaluate_verdict(losses_arm_b=[1.001, 1.0, 1.0], losses_arm_a=[1.0, 1.0, 1.0],
                                 band=band, commit_check=c_ok)
    if v_promote["verdict"] != "PROMOTE":
        print(f"FAIL evaluate_verdict: expected PROMOTE, got {v_promote}")
        ok = False
    v_inconclusive = evaluate_verdict(losses_arm_b=[1.015, 1.0, 1.0], losses_arm_a=[1.0, 1.0, 1.0],
                                      band=band, commit_check=c_ok)
    if v_inconclusive["verdict"] != "INCONCLUSIVE":
        print(f"FAIL evaluate_verdict: expected INCONCLUSIVE, got {v_inconclusive}")
        ok = False
    v_invalid = evaluate_verdict(losses_arm_b=[1.0], losses_arm_a=[1.0], band=band,
                                 commit_check=c_bad)
    if v_invalid["verdict"] != "INVALID":
        print(f"FAIL evaluate_verdict: expected INVALID, got {v_invalid}")
        ok = False

    # 4. steady-state gate refuses on construction_complete=False.
    try:
        commit_steady_state_gib(construction_complete=False)
        print("FAIL commit_steady_state_gib: did not raise on construction_complete=False")
        ok = False
    except RuntimeError:
        pass

    # 5. momentum_buffer_bytes_sidecar's disclosed-inapplicable branch.
    side_empty = momentum_buffer_bytes_sidecar({})
    if side_empty.get("applicable") is not False:
        print(f"FAIL momentum_buffer_bytes_sidecar: expected applicable=False for no-muon dict, got {side_empty}")
        ok = False

    # 6. SIGN fixture (falsifier finding, #792 cure round): bf16 arm using
    #    LESS committed memory than fp32 arm must yield a POSITIVE delta.
    delta_correct = compute_commit_delta_gib(
        arm_a_commit={"applicable": True, "used_gib": 10.5},
        arm_b_commit={"applicable": True, "used_gib": 10.0})
    if abs(delta_correct - 0.5) > 1e-9:
        print(f"FAIL compute_commit_delta_gib: expected +0.5 (fp32 - bf16), got {delta_correct!r}")
        ok = False
    check_on_correct = check_byte_arithmetic(commit_delta_gib=delta_correct, realized_p_matrix=268_435_456)
    if check_on_correct["verdict"] != "OK":
        print(f"FAIL compute_commit_delta_gib downstream: expected OK verdict on correct-sign delta, got {check_on_correct}")
        ok = False
    # Falsifier's exact repro (the INVERTED-sign shape this cure fixes) must
    # still correctly flag INVALID -- proves check_byte_arithmetic itself
    # was never the bug, only the caller's sign convention.
    check_on_falsifier_repro = check_byte_arithmetic(commit_delta_gib=-0.5, realized_p_matrix=268_435_456)
    if (check_on_falsifier_repro["verdict"] != "INVALID_INSTRUMENT_DEFECT"
            or check_on_falsifier_repro["relative_error"] != 2.0):
        print(f"FAIL falsifier sign repro: expected INVALID_INSTRUMENT_DEFECT rel_err=2.0, got {check_on_falsifier_repro}")
        ok = False

    # 7. ORCHESTRATION fixture (falsifier finding, #792 cure round): the
    #    isolated-arm-lifetime invariant must raise while a slot is alive
    #    and pass clean once it is cleared -- proves the structural cure's
    #    own mechanism, not just its intent.
    _ALIVE_ARM_SLOTS.add("fixture_probe")
    try:
        _assert_no_arm_alive("selftest probe")
        print("FAIL _assert_no_arm_alive: did not raise with a slot alive")
        ok = False
    except RuntimeError:
        pass
    finally:
        _ALIVE_ARM_SLOTS.discard("fixture_probe")
    try:
        _assert_no_arm_alive("selftest probe, slots clear")
    except RuntimeError as e:
        print(f"FAIL _assert_no_arm_alive: raised with slots clear: {e!r}")
        ok = False

    # 8. PROVENANCE fixture (#801 convention): compute_provenance runs for
    #    real (proving the code path), refuse_on_missing_provenance must
    #    pass through live=False unconditionally and must raise for
    #    live=True when shard_dir is given but unresolvable.
    prov = compute_provenance(shard_dir=None)
    if "executing_git_sha" not in prov or "source_sha256" not in prov:
        print(f"FAIL compute_provenance: missing required keys, got {prov.keys()}")
        ok = False
    if not prov.get("source_sha256", {}).get("screen792_bf16_momentum.py"):
        print("FAIL compute_provenance: this runner's own source_sha256 entry is missing")
        ok = False
    try:
        refuse_on_missing_provenance(prov, live=False)
    except RuntimeError as e:
        print(f"FAIL refuse_on_missing_provenance: raised for live=False, got {e!r}")
        ok = False
    prov_bad_shard = dict(prov)
    prov_bad_shard["shard_dir"] = "/does/not/exist/fixture-only"
    prov_bad_shard["shard_manifest_sha256"] = None
    prov_bad_shard["shard_manifest_error"] = "fixture: not resolved"
    try:
        refuse_on_missing_provenance(prov_bad_shard, live=True)
        print("FAIL refuse_on_missing_provenance: did not raise for live=True with an unresolved shard_dir")
        ok = False
    except RuntimeError:
        pass

    # 9. required negative fixture -- delegated to the test module (single
    #    source of truth for the fixture itself).
    tests_dir = Path(__file__).resolve().parent / "tests"
    sys.path.insert(0, str(tests_dir))
    try:
        import test_screen792_bf16_momentum as fixture_mod  # noqa: E402
        fixture_ok = fixture_mod.run_negative_fixture()
        if not fixture_ok:
            print("FAIL required negative fixture (test_screen792_bf16_momentum.run_negative_fixture)")
            ok = False
    except Exception as e:
        print(f"FAIL required negative fixture raised: {e!r}")
        ok = False

    if ok:
        print("SCREEN792_SELFTEST_PASS")
        return 0
    return 1


# ---------------------------------------------------------------------------
# --schema-probe -- launch-time schema probe (gate-discipline-rules.md: "A
# receipt-write path that has never executed is an unvalidated instrument").
# Calls receipt_check.validate_receipt DIRECTLY, never receipt_write.
# checked_write, so a schema finding can never trigger a destructive
# delete-on-finding against a real file during this probe.
# ---------------------------------------------------------------------------

def _schema_probe() -> int:
    ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dummy = build_receipt(
        ts_str=ts_str,
        live=False,
        realized_split={"realized_matrix_params": 0, "realized_nonmatrix_params": 0,
                        "realized_total_params": 0},
        commit_delta_gib=0.0,
        byte_check=check_byte_arithmetic(commit_delta_gib=0.0, realized_p_matrix=1),
        copies_opt_other_a={"copies_wall_s": 0.0, "copies_bytes": 0,
                            "opt_other_wall_s": 0.0, "n_steps": 0},
        copies_opt_other_b={"copies_wall_s": 0.0, "copies_bytes": 0,
                            "opt_other_wall_s": 0.0, "n_steps": 0},
        momentum_bytes_a={"applicable": False, "reason": "schema-probe dummy"},
        momentum_bytes_b={"applicable": False, "reason": "schema-probe dummy"},
        momentum_cosine={"applicable": False, "reason": "schema-probe dummy"},
        band=build_noise_band([0.0], [0.0]),
        verdict={"verdict": "INVALID", "reason": "schema-probe dummy run, not a real verdict"},
        run_config={"schema_probe": True},
        provenance=compute_provenance(shard_dir=None),
    )
    findings = receipt_check.validate_receipt(dummy)
    if findings:
        print("SCREEN792_SCHEMA_PROBE_FAIL")
        for f in findings:
            print(f"  {f}")
        return 1
    print("SCREEN792_SCHEMA_PROBE_PASS")
    return 0


# ---------------------------------------------------------------------------
# Live two-arm screen orchestration. NO EXECUTION until the coordinator's
# window-release GO -- gated the same way as every other live-dispatch
# entrypoint in this tree.
# ---------------------------------------------------------------------------

def run_screen(*, cfg: dict, shard_dir: str, run_dir: str, device: str,
               n_warmup: int, n_active: int, batch_size: int,
               ce_chunk_tokens: int, seed_a: int, seed_a2: int) -> dict:
    """Three sequential builds, matched seed/data-order/steps per arm:
      1. Arm A, seed_a  (fp32 momentum, production) -> losses_a
      2. Arm A, seed_a2 (fp32 momentum, production, DIFFERENT seed) ->
         losses_a2 -- sets the noise band BEFORE arm B ever runs.
      3. Arm B, seed_a  (bf16 momentum, A1-fixed) -> losses_b, profiled
         with the #702 attribution instrument for measurand (2); commit
         governor read at steady state for measurand (1).
    Each build is independent (no fork/restore -- this screen compares TWO
    DIFFERENT optimizer implementations, not profiling overhead of one, so
    the #702 runner's AB/BA counterbalancing design does not apply here;
    #702's own primitives -- SubphaseCollector, attach/detach, the model/
    optimizer build functions -- are reused, its AB/BA orchestration is
    not).

    ISOLATED ARM LIFETIMES (falsifier finding, #792 cure round,
    ORCHESTRATION): each arm is built, measured, and TORN DOWN before the
    next arm is built (_teardown_arm + the _assert_no_arm_alive invariant),
    so arm A's and arm B's commit_steady_state_gib readings each reflect
    exactly one arm's resident state, never the union of retained prior
    arms. Cross-arm diagnostics that used to need both arms' live optimizer
    objects simultaneously (momentum_cosine_diagnostic) now work off small
    on-disk file manifests captured before each arm's teardown instead."""
    import torch

    total_steps = n_warmup + n_active
    mtp_enabled = bool(cfg.get("objective", {}).get("mtp_aux_heads", {}).get("enabled", False))
    mtp_weight = cfg.get("objective", {}).get("mtp_aux_heads", {}).get("weight", 0.0)

    def _one_arm(*, arm: str, seed: int, optstate_subdir: str, collector=None):
        _assert_no_arm_alive(f"about to build arm={arm!r} seed={seed}")
        _ALIVE_ARM_SLOTS.add(optstate_subdir)
        try:
            torch.manual_seed(seed)
            import random
            random.seed(seed)
            optstate_dir = Path(run_dir) / "optstate" / optstate_subdir
            model, vocab, hidden, n_mtp = ts.build_v0_model(cfg, live=True, device=device)
            optimizers, base_lrs, routing = build_arm_optimizers(
                model, cfg, arm=arm, optstate_dir=optstate_dir)
            ce_impl, ce_fn = ts.resolve_ce_impl(prefer_liger=True)
            loader = ts.PackedShardLoader(shard_dir, cfg["model"]["seq"], n_mtp)

            # Warmup (unprofiled) -- construction write-pass already happened
            # inside build_arm_optimizers (_memmap_zeros' full write pass at
            # optimizer-init time); warmup steps are what AMENDMENT-1's
            # steady-state gate is timed relative to.
            run_arm_block(
                model=model, loader=loader, optimizers=optimizers, base_lrs=base_lrs,
                cfg=cfg, ce_fn=ce_fn, mtp_enabled=mtp_enabled, mtp_weight=mtp_weight,
                ce_chunk_tokens=ce_chunk_tokens, n_steps=n_warmup, global_step_start=0,
                total_steps=total_steps, device=device, batch_size=batch_size, collector=None)

            if collector is not None:
                attrib.install_span_collector(optimizers, collector, device=device)
            try:
                active = run_arm_block(
                    model=model, loader=loader, optimizers=optimizers, base_lrs=base_lrs,
                    cfg=cfg, ce_fn=ce_fn, mtp_enabled=mtp_enabled, mtp_weight=mtp_weight,
                    ce_chunk_tokens=ce_chunk_tokens, n_steps=n_active,
                    global_step_start=n_warmup, total_steps=total_steps, device=device,
                    batch_size=batch_size, collector=collector)
            finally:
                if collector is not None:
                    attrib.uninstall_span_collector(optimizers)

            # Everything below MUST be captured while the arm is still alive
            # -- _teardown_arm frees model + optimizers immediately after.
            commit = commit_steady_state_gib(construction_complete=True)
            realized_split = realized_matrix_split(model, routing)
            momentum_bytes = momentum_buffer_bytes_sidecar(optimizers)
            momentum_manifest = momentum_file_manifest(
                optimizers, arm=arm, optstate_dir=optstate_dir)
            result = {"routing": routing, "losses": active["losses"], "commit": commit,
                     "realized_split": realized_split, "momentum_bytes": momentum_bytes,
                     "momentum_manifest": momentum_manifest}
            _teardown_arm(model, optimizers, device)
            return result
        finally:
            _ALIVE_ARM_SLOTS.discard(optstate_subdir)

    # --- Arm A, seed_a (fp32) ---
    collector_a = attrib.SubphaseCollector()
    arm_a = _one_arm(arm="fp32", seed=seed_a, optstate_subdir="fp32", collector=collector_a)

    # --- Arm A, seed_a2 (fp32, extra seed -- sets the band before arm B) ---
    arm_a2 = _one_arm(arm="fp32", seed=seed_a2, optstate_subdir="fp32_seed2", collector=None)
    band = build_noise_band(arm_a["losses"], arm_a2["losses"])

    # --- Arm B, seed_a (bf16 -- SAME seed as arm A, matched data order) ---
    collector_b = attrib.SubphaseCollector()
    arm_b = _one_arm(arm="bf16", seed=seed_a, optstate_subdir="bf16", collector=collector_b)

    realized_split = arm_a["realized_split"]
    # SIGN + ISOLATION fix (falsifier finding, #792 cure round): fp32_used -
    # bf16_used (never the reverse -- see compute_commit_delta_gib), and
    # each side of the subtraction was measured with ONLY that one arm
    # resident (arm_a2 and arm_b did not exist yet when arm_a's commit was
    # read; arm_a and arm_a2 were already torn down when arm_b's was).
    commit_delta_gib = compute_commit_delta_gib(
        arm_a_commit=arm_a["commit"], arm_b_commit=arm_b["commit"])
    byte_check = check_byte_arithmetic(
        commit_delta_gib=commit_delta_gib,
        realized_p_matrix=realized_split["realized_matrix_params"])
    copies_a = copies_opt_other_totals(collector_a)
    copies_b = copies_opt_other_totals(collector_b)
    # Measured-bytes sidecar (team-lead review, #792): the existing
    # attribution instrument's copies_bytes has zero coverage of momentum
    # traffic (see copies_opt_other_totals docstring) -- captured per-arm,
    # while each arm was still alive, in _one_arm above.
    momentum_bytes_a = arm_a["momentum_bytes"]
    momentum_bytes_b = arm_b["momentum_bytes"]
    # Reopens each arm's momentum-buffer files fresh from disk -- both arms
    # are already torn down at this point (see momentum_cosine_diagnostic's
    # section docstring for why that's safe / zero-commit-charge).
    cosine = momentum_cosine_diagnostic(arm_a["momentum_manifest"], arm_b["momentum_manifest"])
    verdict = evaluate_verdict(losses_arm_b=arm_b["losses"], losses_arm_a=arm_a["losses"],
                               band=band, commit_check=byte_check)

    provenance = compute_provenance(shard_dir=shard_dir)
    refuse_on_missing_provenance(provenance, live=True)

    ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    receipt = build_receipt(
        ts_str=ts_str, live=True, realized_split=realized_split,
        commit_delta_gib=commit_delta_gib, byte_check=byte_check,
        copies_opt_other_a=copies_a, copies_opt_other_b=copies_b,
        momentum_bytes_a=momentum_bytes_a, momentum_bytes_b=momentum_bytes_b,
        momentum_cosine=cosine, band=band, verdict=verdict,
        run_config={"n_warmup": n_warmup, "n_active": n_active,
                   "batch_size": batch_size, "seed_a": seed_a, "seed_a2": seed_a2,
                   "shard_dir": shard_dir},
        provenance=provenance)
    return receipt


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--selftest", action="store_true",
                    help="CPU-only coverage; no model/GPU/live dispatch.")
    ap.add_argument("--schema-probe", action="store_true",
                    help="Launch-time schema probe: validates the receipt "
                         "schema against a dummy dict built through the "
                         "SAME code path as a real run. Never writes a file.")
    ap.add_argument("--live", action="store_true",
                    help="Real GPU dispatch. Requires EMBER_GATE_AUTHORIZED=1 "
                         "and --shard-dir. BLOCKED on this host until the "
                         "coordinator's explicit window-release GO.")
    ap.add_argument("--shard-dir", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--receipt-dir", default=str(_REPO / "receipts"))
    ap.add_argument("--n-warmup", type=int, default=2)
    ap.add_argument("--n-active", type=int, default=10)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--ce-chunk-tokens", type=int, default=256)
    ap.add_argument("--seed-a", type=int, default=42)
    ap.add_argument("--seed-a2", type=int, default=43)
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.schema_probe:
        return _schema_probe()

    if not args.live:
        ap.print_help()
        print("\nNothing to do without --selftest, --schema-probe, or --live.")
        return 0

    # HARD TIMING RAIL (builder spawn spec, issue #792): no execution on the
    # authoring host until the coordinator's explicit window-release GO.
    if os.environ.get("EMBER_GATE_AUTHORIZED") != "1":
        print("REFUSAL: EMBER_GATE_AUTHORIZED != 1 -- --live requires the "
              "same interlock convention as every other live-dispatch "
              "entrypoint in this tree, AND the coordinator's explicit "
              "window-release GO per issue #792's HARD TIMING RAIL.")
        print(REFUSAL_TEXT)
        return 1
    if not args.shard_dir:
        print("REFUSAL: --live requires a real --shard-dir (real packed "
              "uint16 corpus shard dir).")
        return 1

    cfg = ts.load_contract()
    out_dir = args.out_dir or str(_REPO / "scratch" / "screen792")
    os.makedirs(out_dir, exist_ok=True)
    receipt = run_screen(
        cfg=cfg, shard_dir=args.shard_dir, run_dir=out_dir, device=args.device,
        n_warmup=args.n_warmup, n_active=args.n_active, batch_size=args.batch_size,
        ce_chunk_tokens=args.ce_chunk_tokens, seed_a=args.seed_a, seed_a2=args.seed_a2)
    ts_str = receipt["ts"].replace(":", "").replace("-", "")
    out_path = os.path.join(args.receipt_dir, f"screen792-bf16-momentum-{ts_str}.json")
    receipt_write.checked_write(out_path, receipt)
    print(f"Wrote {out_path}")
    print(f"VERDICT: {receipt['verdict']} -- {receipt['verdict_reason']}")
    return 0 if receipt["verdict"] in ("PROMOTE", "KILL") else 1


if __name__ == "__main__":
    sys.exit(main())
