#!/usr/bin/env python3
"""cbase_grow_rung2_attribution_702.py -- barrier axis-3 (memory traffic)
step-time attribution + PCIe throughput profiling runner, issue #702.

Authoritative spec: the #702 comment thread (wordingone/ember), not this
docstring. Where this file and the thread ever disagree, the thread wins.
The prereg (amendment comment id 4938595840, frozen, plus pre-run amendments
4939491354 tied-tensor erratum and 4939674864 executable verdict-grammar
predicates) is summarized below; the FULL summary of those four items lived
in this file's prior revision (PR #721) and is unchanged here -- see that
revision's history for the verbatim recap. This revision implements the
POST-#721 BLOCK comment (disposition BLOCK_721_PRODUCTION_ATTRIBUTION /
CLEAR_PREDICATE_TABLE_ONLY): the #721-merged runner's predicate table and
fail-closed gates stood, but its ATTRIBUTION MECHANISM did not, on three
counts, each repaired here:

  (a) Consumer-identity defect (was: L226-273 installed `_instrumented_step`,
      a hand-copied reimplementation of CPUOffloadOptimizer.step monkey-
      patched onto the CLASS -- production's real step() never executed
      under profiling, and there was no equivalence receipt). REPAIRED by
      moving instrumentation INSIDE the original method: cpu_offload_adamw.
      CPUOffloadOptimizer now exposes attach_span_collector()/
      detach_span_collector(), a per-INSTANCE (never class-level), default-
      OFF hook set checked at exactly the four named subphase boundaries
      inside the real step() body. Unattached, step()'s arithmetic, control
      flow, and every side effect (grad_lazy_creates counting, memmap
      creation, param writeback order) are byte-identical to the pristine
      method -- there is no second implementation to diverge from the real
      one. This is repair option (a) from the block comment ("instrumentation
      lives INSIDE the original step ... record_function/span hooks,
      default-off"), not option (b) (equivalence receipts) -- (a) removes the
      defect by construction rather than by proof-after-the-fact, so no
      separate equivalence-receipt machinery is built here.
  (b) Unmatched overhead gate (was: profiled and unprofiled blocks ran in
      FIXED sequential order on different batches/global-steps/optimizer
      state -- temporal drift could mask a real overhead cost or fabricate a
      violation with zero instrumentation). REPAIRED by a counterbalanced
      AB/BA design: after warmup, the full training state (model params,
      each CPUOffloadOptimizer's shadow params + inner optimizer state, and
      the CPU/CUDA/python RNG streams) is snapshotted once (`_snapshot_fork`).
      Arm A runs profiled-then-unprofiled from that fork; the fork is then
      RESTORED byte-for-byte (`_restore_fork_`) and Arm B runs unprofiled-
      then-profiled from the identical restored state. PackedShardLoader.
      batch(step, batch_size) is a pure function of step (see timeshare_
      pretrain.py's own docstring: "resume re-derives the identical data
      stream"), so "same loader state" reduces to reusing the same starting
      global_step for both arms -- which this design does: both arms
      traverse the SAME absolute step range, just with profiled/unprofiled
      swapped between the first and second half. Every step-slot in that
      range is therefore measured BOTH profiled and unprofiled, from
      matching state, at both temporal positions -- profiled/unprofiled
      trade first/second position 1:1, cancelling any position-order
      confound (thermal drift, page-cache warmth) the #721 design could not
      distinguish from real instrumentation cost. The overhead and closure
      gates, and the verdict-grammar bootstrap, all consume the POOLED
      (arm A + arm B) samples -- 2x the statistical power of a single
      sequential block at no extra wall-clock cost per sample.
  (c) No integration fixture reached gates_all_passed=true (only predicate-
      table unit fixtures existed). REPAIRED by
      `_selftest_integration_all_gates_pass()`: runs the REAL attribution_run
      pipeline end-to-end on a tiny CPU fixture -- real fork/restore, real
      AB/BA blocks, real per-instance instrumented step() calls, real gate
      evaluation, real verdict classification -- with ONLY the fundamentally
      CUDA-only pinned/pageable calibration function stubbed to a disclosed
      synthetic dict (a real PCIe H2D/D2H number has no CPU-only meaning).
      Every other gate (step_count, overhead, closure, exact_bytes) passes or
      fails on its own real CPU-measured merits. The original `_selftest()`
      is unchanged and must still see gates_all_passed=False on an UNSTUBBED
      run -- proving the stub is disclosed and isolated to one fixture, not a
      silent lowering of the real gate.

This revision ALSO repairs the scale-substitution erratum (comment
4942686121) both live runs hit: `main()` never threaded --intermediate-
override through to attribution_run(), so build_v0_model silently built the
c03 FF4096 model (433,890,304 numel) instead of the frozen rung-2 FF32768
arch (2,195,497,984 numel) -- a 5.06x scale substitution the exact_bytes
gate's own disclosed cross-check flagged (`matches_this_run: false`) but the
prior gate comment explained away rather than refusing on. Two repairs:
  (d) --intermediate-override is now threaded from main() through to
      attribution_run() (was accepted by the function, silently dropped by
      the CLI).
  (e) A new --resume-continuation mode (builder-spec skeleton comment
      4942704748, six numbered clauses; data-identity addendum 4942713685)
      implements TRUE checkpoint continuation identity, not just scale
      repair: model/optimizer/RNG load through the PRODUCTION
      load_checkpoint/load_optimizers_state/restore_rng paths (the same
      three functions run_v0_segment's own resume block calls); total_steps
      binds to the checkpoint manifest's own original schedule denominator
      (449651 at the frozen pins), never the measurement-window length
      n_warmup+2*n_active=42 the erratum's wrong-scale runs silently
      substituted; the loader binds to the pinned shard/mmap source by
      content hash (never the misleading "shards-v1" filename); and a
      fail-closed identity-refusal gate derives architecture identity
      (dedup numel + FF width) DIRECTLY FROM THE CHECKPOINT BYTES and
      refuses (structured receipt, before any compute) on any mismatch --
      caller-supplied config alone is never accepted. See the
      RUNG2_EXPECTED_* constants and the _verify_rung2_* gate functions
      above attribution_run() for the frozen pins and each gate's contract.

Reuse discipline (unchanged from #721, restated): this script does NOT
reimplement Muon/AdamW/CE/WSD math. It builds the model/optimizer/loader via
the SAME production functions run_v0_segment calls (build_v0_model,
build_split_optimizer, split_param_groups, resolve_ce_impl, mtp_total_loss,
apply_wsd, PackedShardLoader, write_packed_shard, load_contract) against the
same frozen contract cfg. The outer step loop is necessarily its own
(run_v0_segment exposes no per-subphase timing hooks and none should be added
to the production training path just to profile it once). The ONE change
this revision makes to a production file is cpu_offload_adamw.py's step() --
adding default-off instrumentation hooks INSIDE the real method is exactly
what block-comment repair item (a) specifies; it is not a reimplementation
and every existing caller of CPUOffloadOptimizer.step() (tests/
test_stabilize_v9_cure.py included) sees byte-identical behavior when
unattached (the default).

No git commits from this module. No founder/user names. api_spend_usd=0,
paid_api_surface_used=false. This module launches NO GPU run by default;
--live requires EMBER_GATE_AUTHORIZED=1 (same interlock convention as every
other live-dispatch entrypoint in this tree) and a real --shard-dir.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import timeshare_pretrain as ts                                       # noqa: E402
import cpu_offload_adamw as _coa                                      # noqa: E402
from cpu_offload_adamw import nvidia_smi_vram, vram_preflight          # noqa: E402

_REPO = Path(__file__).resolve().parent.parent

# ---- subphase names (exact order = the frozen decomposition) --------------
# ember #702 ADDENDUM-5: the per-step body (fwd/loss/bwd) now lives in the
# SHARED ts._run_production_step (timeshare_pretrain.py), but that function
# exposes an OPTIONAL phase_cb/sync_cb observer (falsifier round 2) that
# _run_block wires to this SAME collector -- fwd/loss/bwd stay separately
# and DIRECTLY measured, byte-identical bucket names/boundaries to
# pre-ADDENDUM-5, never a derived/subtracted quantity.
FWD_LOSS_BWD_PHASES = ("fwd", "loss", "bwd")
OPTIMIZER_SUBPHASES = (
    "grad_to_cpu_fp32", "grad_heap_to_memmap", "inner_optimizer_step",
    "updated_param_to_gpu",
)
ALL_PHASES = FWD_LOSS_BWD_PHASES + OPTIMIZER_SUBPHASES

# ---- validity-gate thresholds (frozen spec's own numbers) -----------------
MIN_WARMUP_STEPS = 2
MIN_ACTIVE_STEPS = 10
OVERHEAD_BOUND_FRAC = 0.10          # matched unprofiled block, median step wall
CLOSURE_BOUND_FRAC = 0.05           # subphase-sum vs measured step wall

# ---- pre-run amendment reference point (disclosed cross-check only; the
# gate itself binds to the LIVE realized numel, never this constant) -------
REFERENCE_REALIZED_N_PARAMS = 2_195_497_984
REFERENCE_N_TENSORS = 184
REFERENCE_N_MUON = 140
REFERENCE_N_ADAMW = 44

# ---- verdict-grammar decision procedure (second pre-run amendment, comment
# id 4939674864 -- EXECUTABLE numeric predicates, frozen; every number below
# is the thread's own, not a runner-authored formalization) ----------------
SESOI_DIRECT = 0.10                 # T_stage/T_step lower-CI95 floor (D)
SESOI_FACTOR = 0.10                 # T_inner/T_step lower-CI95 floor (F)
GPU_COMPUTE_BOUND_GPU_LOWER_CI_FLOOR = 0.50    # T_gpu/T_step lower-CI95 floor
GPU_COMPUTE_BOUND_HOST_UPPER_CI_CEIL = 0.15    # (T_stage+T_host_unavoidable)/T_step upper-CI95 ceiling
N_BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 0                  # fixed seed -- verdicts are reproducible, not resample-noise-dependent
VERDICT_GRAMMAR = (
    "DIRECT_COPY_FIRST", "FACTOR1_FIRST", "BOTH_COMPOSE",
    "GPU_COMPUTE_BOUND", "INCONCLUSIVE",
)

# ---- #702 2.2B rung-2 continuation-identity pins (frozen spec: comment
# 4942686121 scope erratum, 4942704748 six-clause builder-spec skeleton,
# 4942713685 data-identity addendum, and the step866-identity-pins final
# addendum -- verbatim from the thread, never a runner-authored
# derivation). Used ONLY by the --resume-continuation path added in this
# revision; every pre-existing path (tiny CPU fixture, plain --live c03) is
# unchanged. These are DEFAULTS for the identity-gate functions below, never
# the gates' only check -- each gate also derives its own value from the
# live checkpoint/config and refuses on a mismatch (the "hardcode as
# cross-check, never hardcoded-only" convention REFERENCE_REALIZED_N_PARAMS
# above already uses, extended to this second, independent identity plane).
RUNG2_EXPECTED_DEDUP_NUMEL = 2_195_497_984
RUNG2_EXPECTED_INTERMEDIATE_SIZE = 32768

# Clause 2: the ORIGINAL stabilize schedule denominator (never the
# measurement-window length n_warmup+2*n_active=42 the erratum's wrong-scale
# runs silently substituted).
RUNG2_EXPECTED_TOTAL_STEPS = 449651

# Clause 3 data-identity pins (verbatim, comment 4942713685): the custody
# mmap_cache manifest FILE's own byte-hash, and the CONTENT-derived combined
# source-shard-set lineage hash _build_or_open_memmap_cache (timeshare_
# pretrain.py) already writes/reads as "combined_manifest_sha256". Binding
# is to CONTENT, never the misleading "shards-v1" filename (the thread's own
# words).
RUNG2_EXPECTED_MANIFEST_FILE_SHA256 = (
    "8d8cc751bbcde2409d7e24b6ecf2f87a8b83078e71eaaf5ed48999819a188d05")
RUNG2_EXPECTED_COMBINED_SOURCE_MANIFEST_SHA256 = (
    "aa48f6ee5e74a40b533f3565ccb4025f9b6c5ad28d7926abc6bd0272ae92d88a")

# Clause 5 (receipt emissions) / step866-final-addendum: the source
# checkpoint's own 4-hash set, independently rehashed + torch-loaded by the
# falsifier. ts.load_checkpoint() already verifies model.pt/optimizer.pt/
# rng.pt against the checkpoint's OWN manifest (internal self-consistency);
# this second cross-check proves it is THE PINNED checkpoint, not merely an
# internally-consistent one at some other step.
RUNG2_REFERENCE_CHECKPOINT_HASHES = {
    "manifest.json": "6ef47596e05f04c98b6681481a8bbeca17baf5fe189297dd8dd2979d9559c6f9",
    "model.pt": "757bdfbf7bc64e8047e3c5809c86fa73514348870460c3aaea0853066bf72821",
    "optimizer.pt": "b0758a9921dfd31c18e059136a08d165c927959951d3bd9da4b5c56783bf182d",
    "rng.pt": "2e30b6c87ed2e1edb9d4077e569da2115c2377d952bf256071ad93e990c8e6c7",
}

# Addendum-2 blocker (b): the pinned checkpoint's own on-disk file sizes,
# hardcoded as a CROSS-CHECK only (same convention as every RUNG2_EXPECTED_*
# constant above) -- _preflight_checkpoint_load_commit below always prices
# the pre-load commit gate against the REAL os.path.getsize() of the files
# actually present at grow_checkpoint_dir (a stat call, zero bytes read,
# zero commit charged), never against these pins alone; a checkpoint whose
# real sizes disagree with these pins is still priced correctly (and the
# mismatch is disclosed in the preflight receipt), never silently
# under/over-priced by trusting a stale pin. model.pt+optimizer.pt sum to
# the addendum's own cited "12.6347 GiB" eager-load figure (rng.pt is a few
# KB and priced from its own real size, never pinned).
RUNG2_EXPECTED_CHECKPOINT_MODEL_PT_BYTES = 4_391_063_423
RUNG2_EXPECTED_CHECKPOINT_OPTIMIZER_PT_BYTES = 9_175_455_079

# External-adjudication gate (2): the pinned checkpoint's AdamW inner
# optimizer carries a POST-GROWTH-LIFETIME step count of 136 -- NOT the
# 866 resume/global_step (that trap is exactly what this pin exists to
# catch: _verify_rung2_optimizer_identity below refuses if the restored
# AdamW step-set is anything other than this pin, INCLUDING 866). Hardcoded
# as a cross-check only (same convention as every RUNG2_EXPECTED_* constant
# above) -- the selftest monkeypatches this to its own fixture's genuine
# value, never bypassing the gate.
RUNG2_EXPECTED_ADAMW_INTERNAL_STEP = 136


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Subphase collector
# ---------------------------------------------------------------------------

class SubphaseCollector:
    """Per-step subphase wall-time + byte accumulator. `begin_step()` /
    `end_step(step_wall)` bracket one optimizer step; `add(phase, dt)` and
    `add_bytes(phase, n)` are called from inside the profiled fwd/loss/bwd
    block and from the ATTACHED (real, in-place-instrumented) CPUOffload
    Optimizer.step() while a step is open. One collector instance is used
    for exactly one profiled block (a fresh instance per block keeps blocks
    from ever mixing samples); `_merge_collectors` combines multiple blocks'
    finished records (used to pool the AB/BA arms)."""

    def __init__(self) -> None:
        self.step_records: list[dict] = []
        self._cur: dict | None = None
        self.realized_numel_total = 0

    def begin_step(self) -> None:
        self._cur = {p: 0.0 for p in ALL_PHASES}
        self._cur["_bytes"] = {p: 0 for p in OPTIMIZER_SUBPHASES}
        self._cur["_realized_numel"] = 0

    def add(self, phase: str, dt: float) -> None:
        assert self._cur is not None, "add() called outside begin_step/end_step"
        self._cur[phase] += dt

    def add_bytes(self, phase: str, n: int) -> None:
        assert self._cur is not None, "add_bytes() called outside begin_step/end_step"
        self._cur["_bytes"][phase] += n

    def add_realized_numel(self, n: int) -> None:
        assert self._cur is not None, "add_realized_numel() called outside begin_step/end_step"
        self._cur["_realized_numel"] += n
        self.realized_numel_total += n

    def end_step(self, step_wall: float) -> None:
        assert self._cur is not None, "end_step() called without a matching begin_step()"
        self._cur["_wall"] = step_wall
        self.step_records.append(self._cur)
        self._cur = None

    # ---- aggregate views -----------------------------------------------

    def phase_totals(self) -> dict:
        totals = {p: 0.0 for p in ALL_PHASES}
        for rec in self.step_records:
            for p in ALL_PHASES:
                totals[p] += rec[p]
        return totals

    def byte_totals(self) -> dict:
        totals = {p: 0 for p in OPTIMIZER_SUBPHASES}
        for rec in self.step_records:
            for p in OPTIMIZER_SUBPHASES:
                totals[p] += rec["_bytes"][p]
        return totals

    def step_walls(self) -> list:
        return [rec["_wall"] for rec in self.step_records]


def _merge_collectors(collectors: list) -> SubphaseCollector:
    """Combines finished step_records from multiple SubphaseCollector
    instances (the AB/BA design's two profiled sub-blocks) into one, for
    gate evaluation and verdict classification over the POOLED sample."""
    merged = SubphaseCollector()
    for c in collectors:
        merged.step_records.extend(c.step_records)
        merged.realized_numel_total += c.realized_numel_total
    return merged


# ---------------------------------------------------------------------------
# Per-instance span-collector attach/detach -- ember #702
# BLOCK_721_PRODUCTION_ATTRIBUTION repair item (a). Attaches directly to the
# REAL CPUOffloadOptimizer instances (never a class-level monkeypatch, never
# a reimplementation of step()) -- see cpu_offload_adamw.py's own
# attach_span_collector()/detach_span_collector() for the instrumented sites.
# ---------------------------------------------------------------------------

def install_span_collector(optimizers: dict, collector: SubphaseCollector, *, device: str):
    import torch
    sync = (torch.cuda.synchronize if device == "cuda" and torch.cuda.is_available()
            else (lambda: None))
    for opt in optimizers.values():
        if isinstance(opt, _coa.CPUOffloadOptimizer):
            opt.attach_span_collector(
                add=collector.add, add_bytes=collector.add_bytes,
                add_numel=collector.add_realized_numel, sync=sync)


def uninstall_span_collector(optimizers: dict) -> None:
    for opt in optimizers.values():
        if isinstance(opt, _coa.CPUOffloadOptimizer):
            opt.detach_span_collector()


# ---------------------------------------------------------------------------
# AB/BA fork snapshot/restore -- ember #702 BLOCK_721_PRODUCTION_ATTRIBUTION
# repair item (b), DISK-BACKED per the mid-build capacity repair (auditor
# prelaunch review, coordinator disposition BLOCK_702_REPAIR_LIVE_AS_WRITTEN
# item 1). The first revision of this section held an IN-MEMORY .clone() of
# the entire fork (model weights + shadow params + optimizer state)
# concurrently with the live run for the whole of Arm A's execution -- on a
# full 2.2B live dispatch that adds ~4.09GiB extra VRAM (model weights, on
# top of a measured ~20GiB peak on a 24GiB card) and ~16.36GiB extra host
# commit (shadow + optimizer state), which the auditor's arithmetic showed
# pushes both resources over their limits. This revision writes the fork to
# DISK instead -- chosen over independently-reconstructed-fork-by-replay
# (the block comment's alternative (b)): this repo's own file-backed-memmap
# convention for CPUOffloadOptimizer state is already exactly "disk instead
# of a second in-memory copy" (cpu_offload_adamw.py's own module docstring),
# so a disk-backed fork snapshot is the SAME established pattern applied one
# level up, not a new one.
#
# model.state_dict() and a CPUOffloadOptimizer's _shadow/_inner.state are
# REFERENCES to the live tensors, not copies -- torch.save serializes their
# CURRENT bytes directly to a file with zero extra concurrent allocation at
# snapshot-write time. Restore loads each component (model, then each
# optimizer's shadow, then its inner state) SEQUENTIALLY, never concurrently,
# in-place copy_()s into the existing live tensors, and drops the loaded
# reference immediately -- bounding peak transient extra memory to the
# single LARGEST component, not the sum of all of them. mmap=True reads
# tensor bytes lazily (page-mapped from the file rather than eagerly
# materialized) -- the same "file-backed, zero pagefile-commit-charge" trick
# cpu_offload_adamw.py's own memmap tensors already rely on. In-place copy_()
# restore (never optimizer.load_state_dict, which reallocates NEW state
# tensors and would silently swap the file-backed memmap tensors this whole
# offload strategy exists to keep -- exactly the memory strategy under
# profiling) so both arms genuinely run against the identical,
# non-reallocated tensor objects the live run uses.
# ---------------------------------------------------------------------------

def _snapshot_rng(device: str) -> dict:
    import random
    import torch
    state = {"torch_cpu": torch.get_rng_state().clone(), "python_random": random.getstate()}
    if device == "cuda" and torch.cuda.is_available():
        state["torch_cuda"] = [t.clone() for t in torch.cuda.get_rng_state_all()]
    return state


def _restore_rng_(state: dict, *, device: str) -> None:
    import random
    import torch
    torch.set_rng_state(state["torch_cpu"])
    random.setstate(state["python_random"])
    if device == "cuda" and torch.cuda.is_available() and "torch_cuda" in state:
        torch.cuda.set_rng_state_all(state["torch_cuda"])


def _snapshot_fork(*, model, optimizers: dict, device: str, global_step: int,
                   fork_dir: Path) -> dict:
    """Writes the fork to fork_dir -- never held in memory as a whole. RNG
    state (a few KB) is the one piece kept in-memory in the returned dict;
    it is not a capacity concern at any scale."""
    import torch
    fork_dir.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), str(fork_dir / "model_state.pt"))

    opt_meta: dict = {}
    for name, opt in optimizers.items():
        if isinstance(opt, _coa.CPUOffloadOptimizer):
            shadow_path = fork_dir / f"{name}.shadow.pt"
            state_path = fork_dir / f"{name}.inner_state.pt"
            torch.save(list(opt._shadow), str(shadow_path))
            # Positionally keyed (index i <-> opt._shadow[i]) -- the SAME
            # index-alignment convention timeshare_pretrain.py's
            # load_optimizers_state already documents for this optimizer
            # family ("same param order... state indices align").
            state_list = [dict(opt._inner.state.get(sp, {})) for sp in opt._shadow]
            torch.save(state_list, str(state_path))
            opt_meta[name] = {"kind": "coa", "shadow_path": str(shadow_path),
                              "state_path": str(state_path)}
        else:
            import copy
            path = fork_dir / f"{name}.plain_state.pt"
            torch.save(copy.deepcopy(opt.state_dict()), str(path))
            opt_meta[name] = {"kind": "plain", "path": str(path)}

    return {
        "fork_dir": str(fork_dir),
        "model_path": str(fork_dir / "model_state.pt"),
        "optimizers": opt_meta,
        "rng": _snapshot_rng(device),
        "global_step": global_step,
    }


def _restore_fork_(snapshot: dict, *, model, optimizers: dict, device: str) -> int:
    """Sequential, never-concurrent per-component load: model, then each
    optimizer's shadow, then its inner state -- each loaded, copy_()'d
    in-place into the live tensors, then dropped before the next component
    loads. weights_only=False: this repo's own trusted, same-run data (never
    externally sourced), and the inner-state dicts mix tensors with plain
    step counters -- weights_only=True would reject that structure."""
    import torch

    loaded_model_sd = torch.load(snapshot["model_path"], map_location="cpu",
                                 mmap=True, weights_only=False)
    with torch.no_grad():
        for k, v in model.state_dict().items():
            v.copy_(loaded_model_sd[k])
    del loaded_model_sd

    for name, opt in optimizers.items():
        meta = snapshot["optimizers"][name]
        if meta["kind"] == "coa":
            loaded_shadow = torch.load(meta["shadow_path"], map_location="cpu",
                                       mmap=True, weights_only=False)
            with torch.no_grad():
                for s, saved in zip(opt._shadow, loaded_shadow):
                    s.copy_(saved)
            del loaded_shadow

            loaded_state = torch.load(meta["state_path"], map_location="cpu",
                                      mmap=True, weights_only=False)
            with torch.no_grad():
                for shadow_p, saved_entry in zip(opt._shadow, loaded_state):
                    live_entry = opt._inner.state.get(shadow_p, {})
                    for k, v in saved_entry.items():
                        if isinstance(v, torch.Tensor):
                            if k in live_entry and isinstance(live_entry[k], torch.Tensor):
                                live_entry[k].copy_(v)
                            else:
                                live_entry[k] = v.clone()
                        else:
                            live_entry[k] = v
                    opt._inner.state[shadow_p] = live_entry
            del loaded_state
        else:
            loaded = torch.load(meta["path"], map_location="cpu", weights_only=False)
            opt.load_state_dict(loaded)

    _restore_rng_(snapshot["rng"], device=device)
    return snapshot["global_step"]


# ---------------------------------------------------------------------------
# In-place checkpoint optimizer-state restore -- ember #702 addendum-2
# blocker (a). ts.load_optimizers_state (timeshare_pretrain.py) forwards to
# torch.optim.Optimizer.load_state_dict, which REPLACES self.state[param]
# with tensors freshly materialized from the loaded bundle -- for a
# CPUOffloadOptimizer this REBINDS the per-parameter state off the
# pre-seeded file-backed memmap tensors onto heap (~8.545GiB charge at the
# pinned checkpoint), defeating the entire CPU-offload strategy DEV-002 and
# cpu_offload_adamw.py exist for. Mirrors the SAME in-place copy_() pattern
# _restore_fork_ above already uses for AB/BA fork restoration -- applied to
# the positionally-indexed torch.optim.Optimizer.state_dict() shape
# ts.save_optimizers_state/load_optimizers_state use (state keyed by
# integer index into the flattened, single-group param list, which for a
# CPUOffloadOptimizer is exactly opt._shadow's own construction order --
# confirmed by reading build_split_optimizer/CPUOffloadOptimizer.__init__,
# not assumed), instead of _snapshot_fork's own custom shadow-order list.
# ---------------------------------------------------------------------------

def _restore_checkpoint_optimizer_state_in_place(
        optimizers: dict, bundle: dict, *, run_dir: str) -> dict:
    """Restores each optimizer's state from a ts.load_checkpoint() bundle
    (standard {"state": {idx: {...}}, "param_groups": [...]} shape) by
    copy_()-ing values IN PLACE into the already-allocated shadow/inner-state
    tensors every CPUOffloadOptimizer pre-seeds at construction (AdamW's
    step/exp_avg/exp_avg_sq[/max_exp_avg_sq] and this repo's own Muon's
    momentum_buffer alike -- generic over both schemas via saved_entry's own
    keys, no per-schema special-casing). NEVER calls opt.load_state_dict().

    Group hyperparams (lr/weight_decay/betas/eps -- everything in a saved
    param_group except "params") are also copied onto the live optimizer's
    param_groups, matching the addendum-2 requirement; lr is immediately
    overridden by the caller's own apply_wsd() at the correct new absolute
    step before the first restored step, so this is a completeness measure,
    never load-bearing for correctness on its own.

    external-adjudication BLOCKER 5 hardening (this function was previously
    fail-OPEN on four axes: a missing saved key left the pre-seeded ZERO
    tensor in place silently; an unexpected saved key got heap-cloned
    (disclosed in reallocated_keys, but never refused); a param_groups
    count mismatch was tolerated via a silent `break`; the report
    unconditionally claimed storage_identity_preserved=True regardless of
    any of the above). Every axis is now a hard, pre-mutation refusal:

    1. Exact param_groups COUNT equality both directions (never a partial
       apply that silently drops trailing groups).
    2. A validation-ONLY pre-pass (zero mutation) asserts, per param index,
       that the live and saved state dicts carry the EXACT SAME key set
       (a saved-only key would require a clone; a live-only key would
       silently keep its pre-seeded zero -- BOTH refuse now, before any
       copy_() runs, so a refusal never leaves live state partially
       restored) and that every shared tensor key has matching shape/dtype.
       Zero clones are possible after this pre-pass passes.
    2. Post-copy VALUE PARITY: every restored tensor is compared
       element-wise (torch.equal, exact -- this is a byte copy_(), never a
       computed value) against the saved source, not just data_ptr()
       identity -- proves the bytes actually match, not merely that the
       object wasn't reallocated.
    3. Post-copy BACKING-FILE byte-mutation proof: for every key backed by
       a CPUOffloadOptimizer memmap file (exp_avg/exp_avg_sq/
       max_exp_avg_sq/momentum_buffer -- "step" is a plain scalar tensor,
       never file-backed, and is explicitly excluded with a disclosed
       reason rather than silently skipped), the file is REOPENED fresh
       (a brand-new np.memmap handle, independent of the in-process torch
       view) and its on-disk values compared against the saved source --
       proving the write reached the file-backed page the CPU-offload
       strategy depends on, not merely an in-process tensor view.

    Fail-closed (SystemExit, written receipt) on: a missing bundle key, a
    param-count/group-count/key-set/shape/dtype mismatch (checkpoint/live
    split_param_groups() disagreement), any state tensor whose data_ptr()
    changed across the restore or whose value/backing-file bytes do not
    match the checkpoint source, or a non-singleton AdamW internal step-set
    after restore (a genuine checkpoint's optimizer steps every param
    together each call; a real, specific step VALUE like 136 is NEVER
    hardcoded here -- ember #702's explicit "do not require/rewrite internal
    optimizer step" clause -- only INTERNAL CONSISTENCY is asserted, derived
    from the loaded checkpoint itself).

    Returns a per-optimizer receipt dict (n_params, reallocated_keys --
    always [] now that clones are refused rather than tolerated,
    storage_identity_preserved, value_parity_verified,
    backing_files_verified/backing_files_skipped_no_file, the observed
    singleton adamw_internal_step where applicable). storage_identity_
    preserved is now an HONEST field: the function raises before returning
    on any violation, so a normal return means every check above genuinely
    passed for every param -- never an unconditional True."""
    import torch
    import numpy as np

    report: dict = {}
    for name, opt in optimizers.items():
        if name not in bundle:
            _write_rung2_refusal_receipt(
                {"gate": "optimizer_restore_bundle_key",
                 "missing_key": name, "have_keys": sorted(bundle)},
                run_dir=run_dir, ticket="EMBER-702-CONTINUATION-OPTIMIZER-BUNDLE-REFUSAL")
            raise SystemExit(
                f"ATTRIBUTION_702_OPTIMIZER_BUNDLE_MISSING_KEY: {name!r} not in "
                f"checkpoint optimizer bundle (have {sorted(bundle)}) -- "
                "checkpoint/runner optimizer mismatch")
        if not isinstance(opt, _coa.CPUOffloadOptimizer):
            raise SystemExit(
                f"ATTRIBUTION_702_OPTIMIZER_NOT_OFFLOADED: {name!r} is "
                f"{type(opt).__name__}, not CPUOffloadOptimizer -- in-place "
                "restore requires offload_optimizer_state=True at "
                "build_split_optimizer time")

        saved = bundle[name]
        saved_state = saved.get("state", {})
        saved_groups = saved.get("param_groups", [])
        n_shadow = len(opt._shadow)
        live_groups = opt._inner.param_groups

        # ---- BLOCKER 5 (1): exact param_groups COUNT equality both
        # directions -- previously a silent `break` tolerated any
        # mismatch. ----
        if len(saved_groups) != len(live_groups):
            receipt_path = _write_rung2_refusal_receipt(
                {"gate": "optimizer_restore_group_count", "optimizer": name,
                 "n_saved_groups": len(saved_groups), "n_live_groups": len(live_groups)},
                run_dir=run_dir, ticket="EMBER-702-CONTINUATION-OPTIMIZER-GROUP-COUNT-REFUSAL")
            raise SystemExit(
                f"ATTRIBUTION_702_OPTIMIZER_GROUP_COUNT_MISMATCH: optimizer "
                f"{name!r} has {len(live_groups)} live param_groups but the "
                f"checkpoint bundle carries {len(saved_groups)} -- refuse, "
                f"never partial-apply (receipt={receipt_path})")

        if len(saved_state) != n_shadow:
            _write_rung2_refusal_receipt(
                {"gate": "optimizer_restore_param_count",
                 "optimizer": name, "n_shadow": n_shadow,
                 "n_saved_state_entries": len(saved_state)},
                run_dir=run_dir, ticket="EMBER-702-CONTINUATION-OPTIMIZER-PARAM-COUNT-REFUSAL")
            raise SystemExit(
                f"ATTRIBUTION_702_OPTIMIZER_PARAM_COUNT_MISMATCH: optimizer "
                f"{name!r} has {n_shadow} live shadow params but the "
                f"checkpoint bundle carries {len(saved_state)} state entries "
                "-- checkpoint/live split_param_groups() disagreement")

        # ---- BLOCKER 5 (2): validation-only pre-pass, ZERO mutation.
        # Exact key-set equality BOTH directions + shape/dtype equality on
        # every shared key, for every index -- collected in full (never
        # fail-fast on the first) so one refusal discloses every violation
        # at once. ----
        mismatches: list[str] = []
        for i in range(n_shadow):
            if i not in saved_state:
                mismatches.append(f"{name}[{i}]: missing from checkpoint state "
                                   f"(have indices {sorted(saved_state)[:5]}...)")
                continue
            shadow_p = opt._shadow[i]
            live_entry = opt._inner.state.get(shadow_p, {})
            saved_entry = saved_state[i]
            live_keys = set(live_entry.keys())
            saved_keys = set(saved_entry.keys())
            extra_in_saved = saved_keys - live_keys
            missing_from_saved = live_keys - saved_keys
            if extra_in_saved:
                mismatches.append(
                    f"{name}[{i}]: checkpoint carries key(s) {sorted(extra_in_saved)} "
                    "with no pre-seeded live destination -- would require a "
                    "clone, refused (zero clones permitted)")
            if missing_from_saved:
                mismatches.append(
                    f"{name}[{i}]: checkpoint is MISSING key(s) "
                    f"{sorted(missing_from_saved)} -- the live tensor would "
                    "silently keep its pre-seeded ZERO value, refused")
            for k in sorted(live_keys & saved_keys):
                lv, sv = live_entry[k], saved_entry[k]
                if isinstance(lv, torch.Tensor) != isinstance(sv, torch.Tensor):
                    mismatches.append(
                        f"{name}[{i}].{k}: tensor-ness mismatch "
                        f"(live={type(lv).__name__}, saved={type(sv).__name__})")
                elif isinstance(lv, torch.Tensor):
                    if tuple(lv.shape) != tuple(sv.shape):
                        mismatches.append(
                            f"{name}[{i}].{k}: shape {tuple(lv.shape)} != "
                            f"checkpoint {tuple(sv.shape)}")
                    elif lv.dtype != sv.dtype:
                        mismatches.append(
                            f"{name}[{i}].{k}: dtype {lv.dtype} != checkpoint {sv.dtype}")
        if mismatches:
            receipt_path = _write_rung2_refusal_receipt(
                {"gate": "optimizer_restore_key_shape_dtype_parity",
                 "optimizer": name, "mismatches": mismatches[:20],
                 "n_mismatches": len(mismatches)},
                run_dir=run_dir,
                ticket="EMBER-702-CONTINUATION-OPTIMIZER-KEY-PARITY-REFUSAL")
            raise SystemExit(
                f"ATTRIBUTION_702_OPTIMIZER_KEY_SHAPE_DTYPE_MISMATCH: "
                f"optimizer {name!r}: {mismatches[:10]} -- exact key-set/"
                "shape/dtype parity required BOTH directions before any "
                f"copy_() runs, zero clones ever (receipt={receipt_path})")

        # ---- Mutation pass -- the pre-pass above guarantees every index's
        # key set matches exactly, so this loop only ever copy_()s into a
        # pre-existing, correctly-shaped/dtyped destination. No clone
        # branch exists anymore (removed -- was the fail-open hole). ----
        pre_ptrs: list[dict[str, int]] = []
        for i in range(n_shadow):
            live_entry = opt._inner.state.get(opt._shadow[i], {})
            pre_ptrs.append({k: v.data_ptr() for k, v in live_entry.items()
                             if isinstance(v, torch.Tensor)})

        with torch.no_grad():
            for i in range(n_shadow):
                shadow_p = opt._shadow[i]
                live_entry = opt._inner.state.get(shadow_p, {})
                saved_entry = saved_state[i]
                for k, v in saved_entry.items():
                    if isinstance(v, torch.Tensor):
                        live_entry[k].copy_(v)
                    else:
                        live_entry[k] = v
                opt._inner.state[shadow_p] = live_entry

            for gi, sg in enumerate(saved_groups):
                for k, v in sg.items():
                    if k == "params":
                        continue
                    live_groups[gi][k] = v

        # ---- BLOCKER 5 (3a): storage-identity proof (data_ptr() unchanged
        # -- now a sanity CONFIRMATION, since the pre-pass already forbids
        # the clone path that used to cause breaks). ----
        post_ptrs: list[dict[str, int]] = []
        step_values: set[float] = set()
        for i in range(n_shadow):
            live_entry = opt._inner.state.get(opt._shadow[i], {})
            post_ptrs.append({k: v.data_ptr() for k, v in live_entry.items()
                              if isinstance(v, torch.Tensor)})
            if "step" in live_entry:
                step_t = live_entry["step"]
                step_values.add(
                    float(step_t.item()) if isinstance(step_t, torch.Tensor) else float(step_t))

        identity_breaks: list[str] = []
        for i in range(n_shadow):
            for k, ptr in pre_ptrs[i].items():
                if post_ptrs[i].get(k) != ptr:
                    identity_breaks.append(f"{name}[{i}].{k}")
        if identity_breaks:
            receipt_path = _write_rung2_refusal_receipt(
                {"gate": "optimizer_restore_storage_identity",
                 "optimizer": name, "identity_breaks": identity_breaks[:20],
                 "n_identity_breaks": len(identity_breaks)},
                run_dir=run_dir,
                ticket="EMBER-702-CONTINUATION-OPTIMIZER-STORAGE-REBOUND-REFUSAL")
            raise SystemExit(
                f"ATTRIBUTION_702_OPTIMIZER_STORAGE_REBOUND: optimizer "
                f"{name!r} tensors {identity_breaks[:10]} changed data_ptr() "
                "across restore -- in-place copy_() invariant violated "
                f"(defeats the file-backed CPU-offload strategy) "
                f"(receipt={receipt_path})")

        # ---- BLOCKER 5 (3b): VALUE parity -- data_ptr() unchanged proves
        # object identity, never that the BYTES actually match the
        # checkpoint. Exact element-wise equality (torch.equal): this is a
        # byte copy_(), never a computed/lossy value. ----
        value_mismatches: list[str] = []
        for i in range(n_shadow):
            shadow_p = opt._shadow[i]
            live_entry = opt._inner.state.get(shadow_p, {})
            saved_entry = saved_state[i]
            for k, sv in saved_entry.items():
                if not isinstance(sv, torch.Tensor):
                    continue
                lv = live_entry[k]
                if not torch.equal(lv.detach().cpu(), sv.detach().cpu()):
                    value_mismatches.append(f"{name}[{i}].{k}")
        if value_mismatches:
            receipt_path = _write_rung2_refusal_receipt(
                {"gate": "optimizer_restore_value_parity", "optimizer": name,
                 "value_mismatches": value_mismatches[:20],
                 "n_value_mismatches": len(value_mismatches)},
                run_dir=run_dir,
                ticket="EMBER-702-CONTINUATION-OPTIMIZER-VALUE-PARITY-REFUSAL")
            raise SystemExit(
                f"ATTRIBUTION_702_OPTIMIZER_VALUE_PARITY_FAILED: optimizer "
                f"{name!r} tensors {value_mismatches[:10]} do not byte-match "
                f"the checkpoint source after copy_() (receipt={receipt_path})")

        # ---- BLOCKER 5 (3c): backing-FILE byte-mutation proof. Every
        # memmap-backed key (never "step", a plain scalar with no file) is
        # re-read from a BRAND-NEW np.memmap handle on its own file --
        # independent of the in-process torch view -- and compared against
        # the checkpoint source, proving the write reached the file-backed
        # page the CPU-offload strategy's whole memory model depends on. ----
        key_to_suffix = {"exp_avg": ".exp_avg.f32", "exp_avg_sq": ".exp_avg_sq.f32",
                         "max_exp_avg_sq": ".max_exp_avg_sq.f32",
                         "momentum_buffer": ".momentum.f32"}
        backing_files_verified: list[str] = []
        backing_files_skipped_no_file: list[str] = []
        backing_mismatches: list[str] = []
        for i in range(n_shadow):
            saved_entry = saved_state[i]
            stem = opt._optstate_dir / _coa._sanitize_name(opt._names[i])
            for k, sv in saved_entry.items():
                if not isinstance(sv, torch.Tensor):
                    continue
                if k not in key_to_suffix:
                    backing_files_skipped_no_file.append(f"{name}[{i}].{k}")
                    continue
                fpath = Path(str(stem) + key_to_suffix[k])
                if not fpath.is_file():
                    backing_mismatches.append(f"{name}[{i}].{k}: backing file {fpath} does not exist")
                    continue
                fresh = np.memmap(str(fpath), dtype=np.float32, mode="r",
                                  shape=tuple(sv.shape))
                if not np.array_equal(fresh, sv.detach().cpu().numpy()):
                    backing_mismatches.append(f"{name}[{i}].{k}: on-disk bytes "
                                              f"({fpath}) do not match checkpoint source")
                else:
                    backing_files_verified.append(f"{name}[{i}].{k}")
                del fresh
        if backing_mismatches:
            receipt_path = _write_rung2_refusal_receipt(
                {"gate": "optimizer_restore_backing_file_parity", "optimizer": name,
                 "backing_mismatches": backing_mismatches[:20],
                 "n_backing_mismatches": len(backing_mismatches)},
                run_dir=run_dir,
                ticket="EMBER-702-CONTINUATION-OPTIMIZER-BACKING-FILE-REFUSAL")
            raise SystemExit(
                f"ATTRIBUTION_702_OPTIMIZER_BACKING_FILE_MISMATCH: optimizer "
                f"{name!r} {backing_mismatches[:10]} -- the offload strategy's "
                f"file-backed page did not receive the restored value "
                f"(receipt={receipt_path})")

        if len(step_values) > 1:
            _write_rung2_refusal_receipt(
                {"gate": "optimizer_restore_step_set_consistency",
                 "optimizer": name, "distinct_step_values": sorted(step_values)},
                run_dir=run_dir,
                ticket="EMBER-702-CONTINUATION-OPTIMIZER-STEP-SET-REFUSAL")
            raise SystemExit(
                f"ATTRIBUTION_702_OPTIMIZER_STEP_SET_INCONSISTENT: optimizer "
                f"{name!r} post-restore step values are not a singleton set: "
                f"{sorted(step_values)} -- a genuine checkpoint's optimizer "
                "steps every param together each call; a non-singleton set "
                "means checkpoint/param-order corruption, never proceed "
                "(this function never hardcodes or requires any specific "
                "step VALUE -- only internal consistency)")

        report[name] = {
            "n_params": n_shadow,
            "reallocated_keys": [],
            "storage_identity_preserved": True,
            "value_parity_verified": True,
            "backing_files_verified": backing_files_verified,
            "backing_files_skipped_no_file": backing_files_skipped_no_file,
            "adamw_internal_step": (sorted(step_values)[0] if step_values else None),
        }
    return report


# ---------------------------------------------------------------------------
# Fail-closed fork-capacity preflight -- ember #702 mid-build repair item 3.
# abort-not-degrade, same discipline as cpu_offload_adamw.vram_preflight and
# this tree's other Windows-commit governors (cbase_grow_rung2_stabilize.py's
# _commit_margin_assert / _read_commit_gb): hold, report numbers, refuse,
# never proceed into the wall, never widen the floor to make a measurement
# pass. _read_commit_gib below duplicates (rather than imports) that
# module's ctypes read: cbase_grow_rung2_stabilize.py applies PROCESS-WIDE
# monkeypatches at IMPORT TIME (torch.nn.Module.load_state_dict,
# CPUOffloadOptimizer.load_state_dict) that this runner must not silently
# inherit just to reuse a 15-line memory read.
# ---------------------------------------------------------------------------

COMMIT_MARGIN_FLOOR_GIB = 6.0   # same floor value as this tree's other commit governors
VRAM_MARGIN_FLOOR_GIB = 2.0     # same floor as cpu_offload_adamw.vram_preflight's own default
DISK_MARGIN_FLOOR_GIB = 4.0     # spare disk headroom required beyond the snapshot's own bytes

# Bounded, fixed (never model/snapshot-size-scaled) allowances for the
# restore path's genuinely transient overhead -- ember #702 mid-build repair
# round 2 (independent falsifier re-test of the round-1 preflight): the
# round-1 preflight priced model_bytes against free VRAM and the FULL
# model+shadow+state snapshot sum against free host commit, as if the
# restore path materialized all of that a second time. It does not: model/
# shadow/state all restore via mmap=True sequential per-component loads,
# copy_()'d IN-PLACE into already-allocated destination tensors (model
# params on GPU; shadow/state on CPU), never reallocated -- so the true
# added VRAM and added (pagefile-backed) commit from restore are both ~0.
# At the measured real envelope (~19.98-20.04GiB peak VRAM used on a 24GiB
# card, ~4GiB free) the round-1 math required free_vram >= model_bytes
# (~4.09GiB) + 2GiB margin = ~6.09GiB -- a bound the real workload can NEVER
# clear, so the gate was safe-fail but undeliverable, not merely
# conservative. These two constants are the bounded staging-buffer
# allowance kept IN PLACE of the phantom charge, sized to cover the small
# non-mmap .clone() calls in _restore_fork_'s coa inner-state merge and
# Windows' del/GC commit-release lag -- not to price the snapshot itself.
VRAM_STAGING_BUFFER_GIB = 0.5
COMMIT_STAGING_BUFFER_GIB = 1.0


def _read_commit_gib() -> dict | None:
    """Ground-truth Windows commit via ONE in-process GlobalMemoryStatusEx
    call (ullAvailPageFile). Never raises -- returns None on any read
    failure (non-Windows interpreter, API failure), the same
    never-raises-on-read-failure contract every other commit-read helper in
    this tree uses; a failed read is disclosed, never treated as a
    violation."""
    import ctypes

    class _MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]
    try:
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        if not ok:
            return None
        gib = 1024.0 ** 3
        return {
            "committed_gib": round((stat.ullTotalPageFile - stat.ullAvailPageFile) / gib, 3),
            "limit_gib": round(stat.ullTotalPageFile / gib, 3),
            "free_gib": round(stat.ullAvailPageFile / gib, 3),
        }
    except Exception:
        return None


def _read_disk_free_gib(path: str) -> dict | None:
    """Ground-truth free disk space for the volume holding `path` (run_dir --
    already created by the time this fires, see attribution_run's
    os.makedirs). Never raises -- returns None on any read failure
    (nonexistent path, permissions), same never-raises-on-read-failure
    contract as _read_commit_gib; a failed read is disclosed, never treated
    as a violation."""
    import shutil
    try:
        usage = shutil.disk_usage(path)
        gib = 1024.0 ** 3
        return {
            "total_gib": round(usage.total / gib, 3),
            "used_gib": round(usage.used / gib, 3),
            "free_gib": round(usage.free / gib, 3),
        }
    except Exception:
        return None


def _tensor_bytes_in(obj) -> int:
    """Recursively sums .numel()*.element_size() over any torch.Tensor found
    inside obj (dict/list/tuple nesting, the shape torch optimizer
    state_dict()s use). Non-tensor leaves (step counters, etc.) contribute 0.
    Sizes exactly what a PLAIN (non-CPUOffloadOptimizer) optimizer's
    state_dict() would serialize -- mirrors _snapshot_fork's
    copy.deepcopy(opt.state_dict()) write path for that branch."""
    import torch
    if isinstance(obj, torch.Tensor):
        return obj.numel() * obj.element_size()
    if isinstance(obj, dict):
        return sum(_tensor_bytes_in(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return sum(_tensor_bytes_in(v) for v in obj)
    return 0


def _realized_fork_bytes(*, model, optimizers: dict) -> dict:
    """Sizes the fork snapshot from REALIZED tensor bytes actually present
    in THIS run (never a config-derived estimate) -- the exact numbers the
    torch.save calls in _snapshot_fork are about to write. model_bytes/
    shadow_bytes/state_bytes/plain_bytes together are the DISK-write sizing
    input (every one of these is written to a file under fork_dir). Only
    plain_bytes matters for the COMMIT preflight (see _preflight_fork_
    capacity): model/shadow/state all restore via mmap=True (file-backed,
    same zero-commit-charge convention this codebase's own CPUOffload
    Optimizer memmap tensors already rely on -- see _restore_fork_), so they
    add ~zero real host commit; a PLAIN optimizer's state_dict() restores via
    an ordinary (non-mmap) torch.load + load_state_dict, which DOES
    materialize real heap bytes -- currently size-0 in this runner's actual
    invocation path (build_split_optimizer is always called with
    offload_optimizer_state=True, so every entry in `optimizers` is a
    CPUOffloadOptimizer), kept as a real measured input rather than an
    assumption so a future caller adding a non-offloaded leg is priced
    correctly instead of silently under-priced."""
    import torch
    model_bytes = sum(v.numel() * v.element_size() for v in model.state_dict().values())
    shadow_bytes = 0
    state_bytes = 0
    plain_bytes = 0
    for opt in optimizers.values():
        if isinstance(opt, _coa.CPUOffloadOptimizer):
            shadow_bytes += sum(s.numel() * s.element_size() for s in opt._shadow)
            for shadow_p in opt._shadow:
                for v in opt._inner.state.get(shadow_p, {}).values():
                    if isinstance(v, torch.Tensor):
                        state_bytes += v.numel() * v.element_size()
        else:
            plain_bytes += _tensor_bytes_in(opt.state_dict())
    return {"model_bytes": model_bytes, "shadow_bytes": shadow_bytes,
            "state_bytes": state_bytes, "plain_bytes": plain_bytes}


def _write_capacity_refusal_receipt(result: dict, *, run_dir: str) -> str:
    import json
    import os
    receipt = {
        "ticket": "EMBER-702-ATTRIBUTION-FORK-CAPACITY-REFUSAL",
        "ts": _ts(),
        "issue": "wordingone/ember#702",
        "verdict": "GOVERNOR_CAPACITY_FAIL",
        **result,
        "api_spend_usd": 0, "paid_api_surface_used": False,
    }
    path = os.path.join(run_dir, f"attribution-702-fork-capacity-refusal-{receipt['ts']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, default=str)
    return path


def _preflight_fork_capacity(*, model, optimizers: dict, device: str, run_dir: str,
                             nvsmi: dict | None = None, commit: dict | None = None,
                             disk: dict | None = None) -> dict:
    """Fail-closed capacity assert BEFORE any fork-snapshot write. Sized from
    REALIZED tensor bytes (_realized_fork_bytes), not config, and from the
    ACTUAL restore path's exposure, not the snapshot's own size:

    - VRAM (device=='cuda' only): restore's real added VRAM is ~0 -- the
      model-state load is map_location=cpu, mmap=True, then copy_()'d
      IN-PLACE into model.state_dict()'s ALREADY-ALLOCATED GPU tensors
      (never reallocated). Priced against a bounded, fixed staging-buffer
      allowance (VRAM_STAGING_BUFFER_GIB), never model_bytes -- charging
      model_bytes here was a phantom cost the real restore path never
      incurs, and at the measured real envelope (~4GiB free on a 24GiB
      card at peak) made the gate permanently unclearable (mid-build repair
      round 2, independent falsifier re-test).
    - Host commit: model/shadow/state all restore via mmap=True (file-
      backed -- the SAME zero-commit-charge convention this codebase's own
      CPUOffloadOptimizer memmap tensors already rely on), so only a PLAIN
      (non-CPUOffloadOptimizer) optimizer's state -- which restores via an
      ordinary non-mmap torch.load -- is real, measured, materializing
      commit; this is currently always 0 bytes in this runner's actual
      invocation path (see _realized_fork_bytes). Priced as plain_gib plus
      a bounded staging-buffer allowance (COMMIT_STAGING_BUFFER_GIB) for
      _restore_fork_'s small non-mmap .clone() calls and Windows' del/GC
      commit-release lag -- never the full model+shadow+state snapshot sum
      (that sum is real DISK bytes, not simultaneous commit; charging it as
      commit was the second phantom cost).
    - Disk (new in this repair round): the fork snapshot's files (model +
      shadow + state + any plain state) ARE written to fork_dir as real,
      simultaneous bytes on disk before any restore happens -- sized
      against the FULL realized-bytes sum, never bounded to one component,
      because unlike restore the write is not sequential-with-drop.

    `nvsmi`/`commit`/`disk` are optional INJECTED measurement dicts (same
    pure-function-of-a-measured-dict pattern as cpu_offload_adamw.
    vram_preflight's own `nvsmi` parameter) -- when omitted each is measured
    for real; production call sites (attribution_run's live path) always
    omit all three. Only _selftest_fork_capacity_preflight() injects
    synthetic envelopes, to prove the PRICING LOGIC against known VRAM/
    disk states rather than depending on today's actual idle GPU/disk on
    whatever box runs the selftest.

    FAIL-CLOSED on an UNAVAILABLE required measurement -- ember #702
    mid-build repair round 3 (post-merge falsifier finding on the round-2
    head): the round-2 version treated a commit-read failure, a disk-read
    failure, or a VRAM-read exception as "disclosed, never a violation" and
    left result["sufficient"]=True -- fail-OPEN on exactly the inputs this
    gate exists to assert. "Disclosed skip" is legitimate ONLY for an
    INAPPLICABLE leg (VRAM when device != 'cuda' -- there is no GPU-side
    restore exposure to measure for a CPU run at all); every leg that IS
    applicable (commit and disk always; VRAM whenever device=='cuda') is
    REQUIRED, and an unmeasured required resource refuses, exactly like an
    insufficient one -- a capacity gate that cannot see a resource has not
    cleared it. Raises SystemExit with a written refusal receipt on
    insufficiency OR unavailability -- abort-not-degrade, no fix-forward,
    no widened floor."""
    sizes = _realized_fork_bytes(model=model, optimizers=optimizers)
    gib = 1024.0 ** 3
    total_write_gib = round(sum(sizes.values()) / gib, 3)
    plain_gib = round(sizes["plain_bytes"] / gib, 3)
    result = {"sizes_bytes": sizes, "total_write_gib": total_write_gib,
             "plain_gib": plain_gib, "vram": None, "commit": None, "disk": None,
             "sufficient": True, "refusal_reasons": []}

    def _refuse(reason: str) -> None:
        result["sufficient"] = False
        result["refusal_reasons"].append(reason)

    if device == "cuda":
        try:
            import torch
            if torch.cuda.is_available():
                vram_check = vram_preflight(VRAM_STAGING_BUFFER_GIB,
                                            margin_gib_floor=VRAM_MARGIN_FLOOR_GIB,
                                            nvsmi=nvsmi)
                result["vram"] = vram_check
                if not vram_check["sufficient"]:
                    _refuse(
                        f"VRAM margin insufficient for the restore path's "
                        f"bounded staging buffer: {vram_check}")
            else:
                # device=='cuda' makes VRAM an APPLICABLE, REQUIRED leg -- no
                # visible CUDA runtime means that required measurement is
                # UNAVAILABLE, not inapplicable.
                result["vram"] = {"error": "torch.cuda.is_available() is "
                                            "False for a device='cuda' preflight"}
                _refuse(
                    "VRAM measurement unavailable: device='cuda' but no CUDA "
                    "runtime visible in this process -- a required, "
                    "applicable measurement that could not be taken is a "
                    "refusal, never a silent pass")
        except Exception as e:
            result["vram"] = {"error": str(e)}
            _refuse(
                f"VRAM measurement raised an exception for a device='cuda' "
                f"preflight -- a required, applicable measurement that "
                f"could not be taken is a refusal, never a silent pass: {e}")
    # device != 'cuda': VRAM is INAPPLICABLE (no GPU-side restore exposure
    # exists to measure on a CPU run) -- result["vram"] stays None, a
    # legitimate disclosed skip, never a violation.

    commit_stat = commit if commit is not None else _read_commit_gib()
    result["commit"] = commit_stat
    if commit_stat is not None:
        commit_required_gib = round(plain_gib + COMMIT_STAGING_BUFFER_GIB, 3)
        commit_margin_gib = round(commit_stat["free_gib"] - commit_required_gib, 3)
        result["commit_required_gib"] = commit_required_gib
        result["commit_margin_gib"] = commit_margin_gib
        if commit_margin_gib < COMMIT_MARGIN_FLOOR_GIB:
            _refuse(
                f"host-commit margin insufficient for the restore path's plain-"
                f"optimizer bytes + staging buffer: free={commit_stat['free_gib']}"
                f"GiB, required={commit_required_gib}GiB, margin="
                f"{commit_margin_gib}GiB < floor={COMMIT_MARGIN_FLOOR_GIB}GiB")
    else:
        # commit is an ALWAYS-APPLICABLE, REQUIRED measurement (every host
        # has a commit limit) -- a read failure is UNAVAILABLE, not
        # inapplicable.
        _refuse(
            "host-commit measurement unavailable (read failure) -- an "
            "unmeasured required resource is a refusal, never a pass")

    disk_stat = disk if disk is not None else _read_disk_free_gib(run_dir)
    result["disk"] = disk_stat
    if disk_stat is not None:
        disk_margin_gib = round(disk_stat["free_gib"] - total_write_gib, 3)
        result["disk_margin_gib"] = disk_margin_gib
        if disk_margin_gib < DISK_MARGIN_FLOOR_GIB:
            _refuse(
                f"free disk insufficient for the fork snapshot write: free="
                f"{disk_stat['free_gib']}GiB, required={total_write_gib}GiB, "
                f"margin={disk_margin_gib}GiB < floor={DISK_MARGIN_FLOOR_GIB}GiB")
    else:
        # disk is an ALWAYS-APPLICABLE, REQUIRED measurement -- a read
        # failure is UNAVAILABLE, not inapplicable.
        _refuse(
            "free-disk measurement unavailable (read failure) -- an "
            "unmeasured required resource is a refusal, never a pass")

    result["refusal"] = " | ".join(result["refusal_reasons"]) or None

    if not result["sufficient"]:
        receipt_path = _write_capacity_refusal_receipt(result, run_dir=run_dir)
        print(f"ATTRIBUTION_702_FORK_CAPACITY_REFUSED receipt={receipt_path} "
              f"refusal={result['refusal']}", flush=True)
        raise SystemExit(
            f"ATTRIBUTION_702_FORK_CAPACITY_REFUSED: {result['refusal']} -- "
            f"abort-not-degrade, no fix-forward, no widened floor (receipt={receipt_path})")
    return result


# ---------------------------------------------------------------------------
# Pre-load checkpoint commit preflight -- ember #702 addendum-2 blocker (b),
# repriced per external-adjudication gate (4)/live-commit measurement.
#
# This file no longer calls ts.load_checkpoint() for the continuation path
# (see _verify_checkpoint_internal_hash_consistency's docstring): the eager
# torch.load of the full model.pt+optimizer.pt bundle (~12.6347GiB at the
# pinned rung-2 checkpoint) is replaced by a SEQUENTIAL, mmap=True,
# per-component load, copy_()'d in place -- the SAME zero-real-commit
# mechanism _restore_fork_ already establishes for fork restoration
# (mmap'd tensors are file-backed/page-cached, never pagefile-committed;
# only the bounded staging/GC-lag overhead is real commit). The required
# commit is therefore priced against a small BOUNDED staging allowance
# (CHECKPOINT_LOAD_STAGING_BUFFER_GIB), never the raw file-size sum --
# pricing the full disk-byte total here was the exact "phantom cost" class
# _preflight_fork_capacity's own history already documents (charging a
# component's SIZE as if it were simultaneous COMMIT, when the real
# mmap-sequential restore path adds ~zero). Live measurement that forced
# this repricing (external adjudicator, same-night): committed 66.373/
# 82.699GiB, free 16.325GiB -- the OLD eager pricing (12.635+6=18.635GiB
# required) REFUSES on this box right now; the repriced staging-buffer
# pricing (~1+6=7GiB required) does not. total_load_gib (real disk bytes)
# stays in the receipt for disk-I/O-time disclosure, but is no longer the
# commit-charge basis.
# ---------------------------------------------------------------------------

CHECKPOINT_LOAD_STAGING_BUFFER_GIB = 1.0

def _write_checkpoint_load_capacity_refusal_receipt(result: dict, *, run_dir: str) -> str:
    import json
    import os
    receipt = {
        "ticket": "EMBER-702-ATTRIBUTION-CHECKPOINT-LOAD-CAPACITY-REFUSAL",
        "ts": _ts(),
        "issue": "wordingone/ember#702",
        "verdict": "GOVERNOR_CAPACITY_FAIL",
        **result,
        "api_spend_usd": 0, "paid_api_surface_used": False,
    }
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, f"attribution-702-checkpoint-load-capacity-refusal-{receipt['ts']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, default=str)
    return path


def _preflight_checkpoint_load_commit(
        ckpt_dir: str, *, run_dir: str,
        margin_gib_floor: float = COMMIT_MARGIN_FLOOR_GIB,
        staging_buffer_gib: float = CHECKPOINT_LOAD_STAGING_BUFFER_GIB,
        expected_model_pt_bytes: int = RUNG2_EXPECTED_CHECKPOINT_MODEL_PT_BYTES,
        expected_optimizer_pt_bytes: int = RUNG2_EXPECTED_CHECKPOINT_OPTIMIZER_PT_BYTES,
        commit: dict | None = None) -> dict:
    """Fail-closed BEFORE the sequential mmap checkpoint load. Sizes the
    load's REAL on-disk file bytes (model.pt + optimizer.pt + rng.pt,
    os.path.getsize -- never read, never priced from an assumption;
    disclosed as total_load_gib for I/O-time planning) and cross-checks
    model.pt/optimizer.pt against the pinned rung-2 sizes (disclosed, never
    gating on its own). The COMMIT charge priced against the margin floor
    is the small bounded staging_buffer_gib, NOT total_load_gib -- the
    sequential mmap=True + copy_() restore path this gate precedes adds
    ~zero real host commit (file-backed pages, same mechanism _restore_
    fork_ already establishes), so pricing the full disk-byte sum here
    would be the exact phantom-cost class this file's OTHER capacity gate
    (_preflight_fork_capacity) already documents and corrects for. Refuses
    (SystemExit, written receipt) on insufficient OR unmeasured commit --
    same fail-closed-on-unavailable discipline as _preflight_fork_capacity.
    `commit` is an optional injected measurement (same pure-function-of-a-
    measured-dict pattern as vram_preflight/_preflight_fork_capacity) --
    production call sites always omit it; only the selftest injects a
    synthetic envelope to prove the pricing logic against known states."""
    import os

    sizes_bytes: dict[str, int] = {}
    missing: list[str] = []
    for fname in ("model.pt", "optimizer.pt", "rng.pt"):
        fpath = os.path.join(ckpt_dir, fname)
        try:
            sizes_bytes[fname] = os.path.getsize(fpath)
        except OSError as e:
            missing.append(f"{fname}: {type(e).__name__}: {e}")

    gib = 1024.0 ** 3
    total_load_gib = round(sum(sizes_bytes.values()) / gib, 4)
    size_cross_check = {
        "model_pt_matches_pin": sizes_bytes.get("model.pt") == expected_model_pt_bytes,
        "optimizer_pt_matches_pin": sizes_bytes.get("optimizer.pt") == expected_optimizer_pt_bytes,
    }

    result = {
        "ckpt_dir": ckpt_dir,
        "sizes_bytes": sizes_bytes,
        "missing_files": missing,
        "total_load_gib": total_load_gib,
        "staging_buffer_gib": staging_buffer_gib,
        "size_cross_check": size_cross_check,
        "commit_before": None,
        "margin_gib_floor": margin_gib_floor,
        "sufficient": True,
        "refusal_reasons": [],
    }

    def _refuse(reason: str) -> None:
        result["sufficient"] = False
        result["refusal_reasons"].append(reason)

    if missing:
        _refuse(f"checkpoint file(s) unavailable for size measurement: {missing}")

    commit_stat = commit if commit is not None else _read_commit_gib()
    result["commit_before"] = commit_stat
    if commit_stat is not None:
        margin_gib = round(commit_stat["free_gib"] - staging_buffer_gib, 4)
        result["margin_gib"] = margin_gib
        if margin_gib < margin_gib_floor:
            _refuse(
                f"host-commit margin insufficient for the sequential mmap "
                f"checkpoint load's bounded staging buffer: "
                f"free={commit_stat['free_gib']}GiB, "
                f"required={staging_buffer_gib}GiB, margin={margin_gib}GiB < "
                f"floor={margin_gib_floor}GiB")
    else:
        # Commit is an ALWAYS-APPLICABLE, REQUIRED measurement -- a read
        # failure is UNAVAILABLE, not inapplicable (same rule as
        # _preflight_fork_capacity).
        _refuse(
            "host-commit measurement unavailable (read failure) -- an "
            "unmeasured required resource is a refusal, never a pass")

    result["refusal"] = " | ".join(result["refusal_reasons"]) or None

    if not result["sufficient"]:
        receipt_path = _write_checkpoint_load_capacity_refusal_receipt(result, run_dir=run_dir)
        print(f"ATTRIBUTION_702_CHECKPOINT_LOAD_CAPACITY_REFUSED receipt={receipt_path} "
              f"refusal={result['refusal']}", flush=True)
        raise SystemExit(
            f"ATTRIBUTION_702_CHECKPOINT_LOAD_CAPACITY_REFUSED: {result['refusal']} -- "
            f"abort-not-degrade, no fix-forward, no widened floor (receipt={receipt_path})")
    return result


# ---------------------------------------------------------------------------
# Pinned-vs-pageable D2H/H2D calibration
# ---------------------------------------------------------------------------

def calibrate_pinned_vs_pageable(*, device: str, n_elems: int = 1 << 22,
                                  n_trials: int = 5) -> dict:
    """H2D/D2H throughput for pinned vs pageable host buffers, at n_elems
    fp32 elements (16 MiB default -- large enough that kernel-launch fixed
    cost is a small fraction of transfer time, small enough for a fast
    calibration pass). CPU-only mode (no CUDA device) cannot measure a real
    PCIe number and reports that plainly (skipped=True) rather than
    fabricating one -- callers must fail the calibration gate closed on a
    skip, never treat a skip as a pass."""
    import torch
    if device != "cuda" or not torch.cuda.is_available():
        return {"skipped": True, "reason": f"device={device!r} / cuda_available="
                f"{torch.cuda.is_available()} -- pinned-vs-pageable calibration "
                "requires a real CUDA device"}

    n_bytes = n_elems * 4
    gpu_buf = torch.empty(n_elems, dtype=torch.float32, device="cuda")
    pageable = torch.empty(n_elems, dtype=torch.float32)
    pinned = torch.empty(n_elems, dtype=torch.float32).pin_memory()

    def _time_h2d(host_buf) -> float:
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(n_trials):
            gpu_buf.copy_(host_buf, non_blocking=host_buf.is_pinned())
        torch.cuda.synchronize()
        return (time.perf_counter() - t0) / n_trials

    def _time_d2h(host_buf) -> float:
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(n_trials):
            host_buf.copy_(gpu_buf, non_blocking=host_buf.is_pinned())
        torch.cuda.synchronize()
        return (time.perf_counter() - t0) / n_trials

    # warmup (excluded from timing) -- first-touch page fault / cuBLAS-style
    # lazy init should not bias the measured steady-state throughput.
    gpu_buf.copy_(pageable); gpu_buf.copy_(pinned)
    torch.cuda.synchronize()

    h2d_pageable_s = _time_h2d(pageable)
    h2d_pinned_s = _time_h2d(pinned)
    d2h_pageable_s = _time_d2h(pageable)
    d2h_pinned_s = _time_d2h(pinned)

    def _gbps(s: float) -> float:
        return round((n_bytes / s) / 1e9, 4) if s > 0 else None

    return {
        "skipped": False,
        "n_bytes_per_trial": n_bytes,
        "n_trials": n_trials,
        "h2d_pageable_gbps": _gbps(h2d_pageable_s),
        "h2d_pinned_gbps": _gbps(h2d_pinned_s),
        "d2h_pageable_gbps": _gbps(d2h_pageable_s),
        "d2h_pinned_gbps": _gbps(d2h_pinned_s),
        "pcie4_x16_peak_gbps": 31.508,
        "h2d_pinned_vs_pageable_speedup": (
            round(h2d_pageable_s / h2d_pinned_s, 3) if h2d_pinned_s > 0 else None),
        "d2h_pinned_vs_pageable_speedup": (
            round(d2h_pageable_s / d2h_pinned_s, 3) if d2h_pinned_s > 0 else None),
    }


# ---------------------------------------------------------------------------
# Profiled / unprofiled block loop -- reuses the production primitives,
# forks only the outer step loop (see module docstring for why).
# ---------------------------------------------------------------------------

def _run_block(*, model, loader, optimizers, base_lrs, cfg, ce_fn, mtp_enabled,
                mtp_weight, ce_chunk_tokens, n_steps: int, global_step_start: int,
                total_steps: int, device: str, batch_size: int,
                grad_accum_steps: int, qat_enabled: bool,
                profile: bool, collector: "SubphaseCollector | None") -> list:
    """Runs n_steps production macro-steps via the SHARED
    ts._run_production_step (ember #702 ADDENDUM-5, "ADDENDUM-3(F)
    operationalized") -- the SAME function run_v0_segment itself calls, so
    grad_accum_steps/QAT lifecycle/apply_wsd/loss composition are genuine
    production semantics here, never a sibling reimplementation (class rule
    F, satisfied by construction). profile=True passes `collector.add`/
    `sync` to _run_production_step's own OPTIONAL phase_cb/sync_cb
    parameters (ADDENDUM-5 falsifier round 2 -- an internal observer inside
    the shared step, not a subtraction derived from the outside), so "fwd"/
    "loss"/"bwd" are measured DIRECTLY and INDEPENDENTLY at the exact same
    boundaries this file measured pre-ADDENDUM-5 -- loader/H2D/QAT/
    apply_wsd/opt.step()/zero_grad() stay unmeasured, exactly as before,
    which is what keeps the closure gate a real residual (measured spans
    vs measured wall) rather than an identity that can never fail. AND
    expects the caller to have already install_span_collector()'d the SAME
    collector onto `optimizers` (the optimizer's own step()-internal
    subphases -- grad_to_cpu_fp32/grad_heap_to_memmap/inner_optimizer_step/
    updated_param_to_gpu -- are UNCHANGED, still instrumented at the
    CPUOffloadOptimizer level, called from inside _run_production_step's
    own opt.step() loop, strictly AFTER the fwd/loss/bwd spans close --
    disjoint, never overlapping; this function does not attach/detach the
    optimizer-level hooks itself, the caller brackets a whole profiled
    block with them). profile=False passes phase_cb=None/sync_cb=None,
    adding ZERO extra instrumentation, and expects the caller to have
    detached any span collector from `optimizers` first -- the matched-
    unprofiled-block baseline. Returns the list of measured step-wall
    times (perf_counter, device-synced)."""
    import torch
    sync = (torch.cuda.synchronize if device == "cuda" and torch.cuda.is_available()
            else (lambda: None))
    step_walls: list = []
    for local_step in range(n_steps):
        global_step = global_step_start + local_step
        if profile:
            collector.begin_step()
        sync(); t_step0 = time.perf_counter()

        ts._run_production_step(
            model=model, loader=loader, optimizers=optimizers, base_lrs=base_lrs,
            cfg=cfg, ce_fn=ce_fn, mtp_enabled=mtp_enabled, mtp_weight=mtp_weight,
            ce_chunk_tokens=ce_chunk_tokens, device=device, batch_size=batch_size,
            global_step=global_step, total_steps=total_steps,
            grad_accum_steps=grad_accum_steps, qat_enabled=qat_enabled,
            phase_cb=collector.add if profile else None,
            sync_cb=sync if profile else None)

        sync(); step_wall = time.perf_counter() - t_step0
        step_walls.append(step_wall)
        if profile:
            collector.end_step(step_wall)
    return step_walls


def _run_counterbalanced_ab_ba(*, model, loader, optimizers, base_lrs, cfg, ce_fn,
                                mtp_enabled, mtp_weight, ce_chunk_tokens, device,
                                batch_size, total_steps, n_active: int,
                                grad_accum_steps: int, qat_enabled: bool,
                                fork_global_step: int, run_dir: str) -> dict:
    """AB/BA counterbalanced overhead measurement -- ember #702
    BLOCK_721_PRODUCTION_ATTRIBUTION repair item (b). Both arms fork from the
    IDENTICAL post-warmup snapshot (model + every optimizer's mutable state +
    both RNG streams; loader state reduces to the shared starting global_step
    since PackedShardLoader.batch is a pure function of step). Arm A runs
    profiled-then-unprofiled; the fork is restored byte-for-byte; Arm B runs
    unprofiled-then-profiled from the identical restored state. Both arms
    therefore traverse the SAME absolute step range [fork_global_step,
    fork_global_step + 2*n_active) -- every step-slot in that range is
    measured once profiled and once unprofiled, at swapped temporal
    positions, cancelling any order confound (thermal drift, page-cache
    warmth) a single fixed-order design cannot distinguish from real
    instrumentation cost. Returns pooled wall-time lists, the merged
    subphase collector, and the per-arm breakdown (for receipt disclosure /
    falsifiability of the counterbalancing itself).

    A fail-closed capacity preflight (ember #702 mid-build repair item 3)
    runs BEFORE the fork snapshot is written -- refuses (named receipt under
    run_dir, SystemExit, no fix-forward) rather than writing a snapshot into
    insufficient VRAM/commit margin. The fork itself is DISK-BACKED under
    run_dir/fork_snapshot (mid-build repair item 1, see the section header
    above _snapshot_fork), never an in-memory clone held for the whole of
    Arm A's execution."""
    common = dict(model=model, loader=loader, optimizers=optimizers, base_lrs=base_lrs,
                 cfg=cfg, ce_fn=ce_fn, mtp_enabled=mtp_enabled, mtp_weight=mtp_weight,
                 ce_chunk_tokens=ce_chunk_tokens, device=device, batch_size=batch_size,
                 total_steps=total_steps, grad_accum_steps=grad_accum_steps,
                 qat_enabled=qat_enabled)

    # ember #702 mid-build repair round 3: the preflight's successful result
    # was previously discarded (call for its side effect only) -- carried
    # into the final receipt below so a claim-bearing output PRESERVES the
    # realized sizes, margins, and all three measurement dicts a downstream
    # reader could recheck, rather than only the fact that SOME preflight
    # ran and did not raise.
    preflight_result = _preflight_fork_capacity(
        model=model, optimizers=optimizers, device=device, run_dir=run_dir)
    fork_dir = Path(run_dir) / "fork_snapshot"
    fork0 = _snapshot_fork(model=model, optimizers=optimizers, device=device,
                           global_step=fork_global_step, fork_dir=fork_dir)

    # ---- Arm A: profiled, then unprofiled ----
    collector_a = SubphaseCollector()
    install_span_collector(optimizers, collector_a, device=device)
    try:
        profiled_walls_a = _run_block(global_step_start=fork_global_step, n_steps=n_active,
                                      profile=True, collector=collector_a, **common)
    finally:
        uninstall_span_collector(optimizers)
    unprofiled_walls_a = _run_block(global_step_start=fork_global_step + n_active,
                                    n_steps=n_active, profile=False, collector=None, **common)

    # ---- restore to the identical fork point ----
    restored_step = _restore_fork_(fork0, model=model, optimizers=optimizers, device=device)
    assert restored_step == fork_global_step, (restored_step, fork_global_step)

    # ---- Arm B: unprofiled, then profiled (from the SAME restored state) ----
    unprofiled_walls_b = _run_block(global_step_start=restored_step, n_steps=n_active,
                                    profile=False, collector=None, **common)
    collector_b = SubphaseCollector()
    install_span_collector(optimizers, collector_b, device=device)
    try:
        profiled_walls_b = _run_block(global_step_start=restored_step + n_active,
                                      n_steps=n_active, profile=True, collector=collector_b,
                                      **common)
    finally:
        uninstall_span_collector(optimizers)

    return {
        "profiled_walls": profiled_walls_a + profiled_walls_b,
        "unprofiled_walls": unprofiled_walls_a + unprofiled_walls_b,
        "collector": _merge_collectors([collector_a, collector_b]),
        "arm_a": {"order": "profiled_first", "profiled_walls_s": profiled_walls_a,
                  "unprofiled_walls_s": unprofiled_walls_a},
        "arm_b": {"order": "unprofiled_first", "profiled_walls_s": profiled_walls_b,
                  "unprofiled_walls_s": unprofiled_walls_b},
        "fork_global_step": fork_global_step,
        "post_run_global_step": fork_global_step + 2 * n_active,
        "preflight": preflight_result,
    }


# ---------------------------------------------------------------------------
# Validity gates + verdict grammar
# ---------------------------------------------------------------------------

def _evaluate_gates(*, n_warmup: int, n_active: int, profiled_walls: list,
                    unprofiled_walls: list, collector: SubphaseCollector,
                    expected_full_numel: int, calibration: dict) -> dict:
    gates: dict = {}

    gates["step_count"] = {
        "passed": n_warmup >= MIN_WARMUP_STEPS and n_active >= MIN_ACTIVE_STEPS,
        "n_warmup": n_warmup, "n_active": n_active,
        "n_active_pooled_ab_ba": len(profiled_walls),
        "floor_warmup": MIN_WARMUP_STEPS, "floor_active": MIN_ACTIVE_STEPS,
    }

    prof_med = statistics.median(profiled_walls) if profiled_walls else None
    unprof_med = statistics.median(unprofiled_walls) if unprofiled_walls else None
    overhead_frac = (abs(prof_med - unprof_med) / unprof_med
                     if prof_med is not None and unprof_med else None)
    gates["overhead"] = {
        "passed": overhead_frac is not None and overhead_frac <= OVERHEAD_BOUND_FRAC,
        "profiled_median_wall_s": prof_med, "unprofiled_median_wall_s": unprof_med,
        "overhead_frac": overhead_frac, "bound_frac": OVERHEAD_BOUND_FRAC,
        "design": "counterbalanced_ab_ba_pooled",
    }

    totals = collector.phase_totals()
    sum_subphases = sum(totals.values())
    sum_wall = sum(collector.step_walls())
    closure_frac = (abs(sum_subphases - sum_wall) / sum_wall) if sum_wall else None
    gates["closure"] = {
        "passed": closure_frac is not None and closure_frac <= CLOSURE_BOUND_FRAC,
        "sum_subphases_s": sum_subphases, "sum_measured_wall_s": sum_wall,
        "closure_frac": closure_frac, "bound_frac": CLOSURE_BOUND_FRAC,
    }

    byte_totals = collector.byte_totals()
    realized_numel_per_step = (collector.realized_numel_total / len(collector.step_records)
                               if collector.step_records else 0)
    bytes_self_consistent = (
        byte_totals["grad_to_cpu_fp32"] == byte_totals["grad_heap_to_memmap"] == (
            collector.realized_numel_total * 4))
    numel_matches_live_param_groups = (
        round(realized_numel_per_step) == expected_full_numel)
    gates["exact_bytes"] = {
        "passed": bytes_self_consistent and numel_matches_live_param_groups,
        "realized_numel_per_step": realized_numel_per_step,
        "expected_full_numel_from_split_param_groups": expected_full_numel,
        "byte_totals": byte_totals,
        "bytes_self_consistent": bytes_self_consistent,
        "numel_matches_live_param_groups": numel_matches_live_param_groups,
        "rule": ("bound to REALIZED non-null-grad numel measured at runtime "
                 "from the live param groups -- never a raw/theoretical "
                 "checkpoint param count (pre-run amendment)"),
    }

    gates["pinned_pageable_calibration"] = {
        "passed": bool(calibration.get("skipped") is False),
        "calibration": calibration,
    }

    return gates


def _bootstrap_ci95(values: list, *, n_resamples: int = N_BOOTSTRAP_RESAMPLES,
                    rng=None) -> dict:
    """Bootstrap 95% CI of the MEAN of `values` (percentile method,
    2.5/97.5 percentiles of the resampled-mean distribution). `rng` is a
    numpy Generator shared across calls in one verdict classification so
    every span's CI in a receipt derives from one seeded, reproducible
    resample stream (never per-call reseeded, which would make different
    spans' CIs independently noisy for no reason)."""
    import numpy as np
    rng = rng if rng is not None else np.random.default_rng(BOOTSTRAP_SEED)
    arr = np.asarray(values, dtype=np.float64)
    n = len(arr)
    if n == 0:
        return {"lower": None, "upper": None, "mean": None,
                "n_samples": 0, "n_resamples": n_resamples}
    idx = rng.integers(0, n, size=(n_resamples, n))
    resample_means = arr[idx].mean(axis=1)
    return {
        "lower": round(float(np.percentile(resample_means, 2.5)), 6),
        "upper": round(float(np.percentile(resample_means, 97.5)), 6),
        "mean": round(float(arr.mean()), 6),
        "n_samples": n, "n_resamples": n_resamples,
    }


def _per_step_ratios(collector: "SubphaseCollector") -> dict:
    """Per-step EXCLUSIVE, counterfactual-removable span ratios (second
    pre-run amendment, comment id 4939674864) -- one scalar per active
    profiled step, never an aggregate-first ratio (aggregating first would
    silently reweight steps of different wall time and break the per-step
    bootstrap the amendment specifies)."""
    stage, inner, gpu, host_unavoidable, stage_plus_host = [], [], [], [], []
    for rec in collector.step_records:
        w = rec["_wall"]
        t_stage = rec["grad_heap_to_memmap"]
        t_inner = rec["inner_optimizer_step"]
        t_host = rec["grad_to_cpu_fp32"] + rec["updated_param_to_gpu"]
        # ADDENDUM-5: FWD_LOSS_BWD_PHASES collapsed to a single "compute"
        # span once _run_block calls the opaque shared _run_production_step
        # (fwd/loss/bwd are no longer separately observable from outside
        # that call) -- generic over the phase tuple so this sums whatever
        # it currently contains, never hardcoding the pre-ADDENDUM-5 keys.
        t_gpu = sum(rec[p] for p in FWD_LOSS_BWD_PHASES)
        if w <= 0:
            stage.append(0.0); inner.append(0.0); gpu.append(0.0)
            host_unavoidable.append(0.0); stage_plus_host.append(0.0)
            continue
        stage.append(t_stage / w)
        inner.append(t_inner / w)
        gpu.append(t_gpu / w)
        host_unavoidable.append(t_host / w)
        stage_plus_host.append((t_stage + t_host) / w)
    return {
        "stage_ratio": stage, "inner_ratio": inner, "gpu_ratio": gpu,
        "host_unavoidable_ratio": host_unavoidable,
        "stage_plus_host_unavoidable_ratio": stage_plus_host,
    }


def _classify_verdict_predicates(ratios: dict, *, seed: int = BOOTSTRAP_SEED) -> dict:
    """The frozen, EXECUTABLE decision grammar (second pre-run amendment,
    comment id 4939674864). Every threshold is the thread's own number.
    Reached only when every validity gate has already passed (see
    attribution_run) -- this function has no fail-closed logic of its own,
    it classifies whatever ratios it is given."""
    import numpy as np
    rng = np.random.default_rng(seed)

    ci_stage = _bootstrap_ci95(ratios["stage_ratio"], rng=rng)
    ci_inner = _bootstrap_ci95(ratios["inner_ratio"], rng=rng)
    ci_gpu = _bootstrap_ci95(ratios["gpu_ratio"], rng=rng)
    ci_host_unavoidable = _bootstrap_ci95(ratios["host_unavoidable_ratio"], rng=rng)
    ci_stage_plus_host = _bootstrap_ci95(ratios["stage_plus_host_unavoidable_ratio"], rng=rng)

    D = ci_stage["lower"] is not None and ci_stage["lower"] >= SESOI_DIRECT
    F = ci_inner["lower"] is not None and ci_inner["lower"] >= SESOI_FACTOR

    if D and not F:
        verdict, reason = "DIRECT_COPY_FIRST", (
            f"D=True (lowerCI95(T_stage/T_step)={ci_stage['lower']} >= {SESOI_DIRECT}), "
            f"F=False (lowerCI95(T_inner/T_step)={ci_inner['lower']} < {SESOI_FACTOR})")
    elif F and not D:
        verdict, reason = "FACTOR1_FIRST", (
            f"F=True (lowerCI95(T_inner/T_step)={ci_inner['lower']} >= {SESOI_FACTOR}), "
            f"D=False (lowerCI95(T_stage/T_step)={ci_stage['lower']} < {SESOI_DIRECT})")
    elif D and F:
        verdict, reason = "BOTH_COMPOSE", (
            f"D=True and F=True (lowerCI95(T_stage/T_step)={ci_stage['lower']}, "
            f"lowerCI95(T_inner/T_step)={ci_inner['lower']}, both >= 0.10)")
    elif (ci_gpu["lower"] is not None and ci_gpu["lower"] >= GPU_COMPUTE_BOUND_GPU_LOWER_CI_FLOOR
          and ci_stage_plus_host["upper"] is not None
          and ci_stage_plus_host["upper"] <= GPU_COMPUTE_BOUND_HOST_UPPER_CI_CEIL):
        verdict, reason = "GPU_COMPUTE_BOUND", (
            f"D=False, F=False, lowerCI95(T_gpu/T_step)={ci_gpu['lower']} >= "
            f"{GPU_COMPUTE_BOUND_GPU_LOWER_CI_FLOOR} and "
            f"upperCI95((T_stage+T_host_unavoidable)/T_step)={ci_stage_plus_host['upper']} "
            f"<= {GPU_COMPUTE_BOUND_HOST_UPPER_CI_CEIL} (positive GPU-compute dominance, "
            "low host movement)")
    else:
        verdict, reason = "INCONCLUSIVE", (
            f"D=False, F=False, and the GPU_COMPUTE_BOUND predicate did not fire "
            f"(lowerCI95(T_gpu/T_step)={ci_gpu['lower']}, "
            f"upperCI95((T_stage+T_host_unavoidable)/T_step)={ci_stage_plus_host['upper']})")

    return {
        "verdict": verdict,
        "reason": reason,
        "predicates": {"D_direct_copy": D, "F_factor1": F},
        "sesoi": {
            "SESOI_direct": SESOI_DIRECT, "SESOI_factor": SESOI_FACTOR,
            "gpu_compute_bound_gpu_lower_ci_floor": GPU_COMPUTE_BOUND_GPU_LOWER_CI_FLOOR,
            "gpu_compute_bound_host_upper_ci_ceil": GPU_COMPUTE_BOUND_HOST_UPPER_CI_CEIL,
        },
        "ci95": {
            "T_stage_over_T_step": ci_stage,
            "T_inner_over_T_step": ci_inner,
            "T_gpu_over_T_step": ci_gpu,
            "T_host_unavoidable_over_T_step": ci_host_unavoidable,
            "T_stage_plus_T_host_unavoidable_over_T_step": ci_stage_plus_host,
        },
        "n_bootstrap_resamples": N_BOOTSTRAP_RESAMPLES,
        "bootstrap_seed": seed,
    }


# ---------------------------------------------------------------------------
# Continuation-identity gates -- ember #702 2.2B rerun (builder-spec
# skeleton comment 4942704748, clauses 4/5/6; data-identity addendum
# 4942713685). Each gate is FAIL-CLOSED (structured refusal receipt under
# run_dir, SystemExit, no fix-forward) and each expected value is an
# INJECTABLE parameter defaulting to the frozen RUNG2_EXPECTED_* constant --
# same pattern _preflight_fork_capacity's nvsmi/commit/disk params already
# use, so the selftests below can prove the REFUSAL LOGIC against small,
# fast, deterministic fixtures without needing the real 2.2B checkpoint on
# this CPU-only box; the wired production call sites in attribution_run()
# never pass these overrides, so they always bind to the frozen pins.
# ---------------------------------------------------------------------------

def _sha256_bytes_of_file(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_any(obj) -> str:
    """Recursive, deterministic sha256 over ANY nested structure of
    tensors/ndarrays/dicts/lists/tuples/scalars -- used by the one-step
    production-step parity fixture to compare model weights, optimizer
    state (exp_avg/exp_avg_sq/momentum_buffer/step, keyed by param index --
    a plain dict of dicts and ints), and RNG capture bundles (a
    heterogeneous dict of python-random tuples, a torch ByteTensor, and a
    numpy random-state tuple) bit-for-bit between two independently-built
    object graphs. dict keys are visited in SORTED str-key order (never
    insertion order, which python/numpy RNG state's own get-state tuples
    don't even guarantee across builds). Tensors/ndarrays are hashed via
    their RAW memory (a uint8 view for torch -- numpy has no native
    bfloat16 dtype, and the real_arch model's weights are bf16 -- and
    .tobytes() for numpy) with shape+dtype folded in, never a numeric cast
    that could mask a genuine mismatch. A type tag byte prefixes every
    node so a tensor and a same-bytes non-tensor can never collide."""
    import hashlib
    h = hashlib.sha256()

    def _walk(o) -> None:
        if hasattr(o, "detach") and hasattr(o, "cpu"):  # torch.Tensor
            import torch
            t = o.detach().cpu().contiguous()
            h.update(b"T")
            h.update(str(tuple(t.shape)).encode("utf-8"))
            h.update(str(t.dtype).encode("utf-8"))
            # 0-dim (scalar) tensors -- e.g. an AdamW "step" counter stored as
            # a 0-dim tensor in optimizer state -- cannot be dtype-reinterpret
            # viewed directly ("self.dim() cannot be 0 to view Float as Byte");
            # reshape to 1-D first. The original shape is already folded into
            # the hash above, so this is a pure byte-reinterpret convenience,
            # never a loss of shape information.
            h.update(t.reshape(-1).view(torch.uint8).numpy().tobytes())
        elif hasattr(o, "tobytes") and hasattr(o, "shape"):  # numpy.ndarray
            h.update(b"N")
            h.update(str(o.shape).encode("utf-8"))
            h.update(str(o.dtype).encode("utf-8"))
            h.update(o.tobytes())
        elif isinstance(o, dict):
            h.update(b"D")
            for k in sorted(o.keys(), key=str):
                h.update(str(k).encode("utf-8"))
                _walk(o[k])
        elif isinstance(o, (list, tuple)):
            h.update(b"L")
            for item in o:
                _walk(item)
        else:
            h.update(b"S")
            h.update(repr(o).encode("utf-8"))

    _walk(obj)
    return h.hexdigest()


def _write_rung2_refusal_receipt(result: dict, *, run_dir: str, ticket: str) -> str:
    import json
    import os
    receipt = {
        "ticket": ticket, "ts": _ts(), "issue": "wordingone/ember#702",
        "verdict": "CONTINUATION_IDENTITY_REFUSED",
        **result, "api_spend_usd": 0, "paid_api_surface_used": False,
    }
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(
        run_dir, f"{ticket.lower().replace('_', '-')}-{receipt['ts']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, default=str)
    return path


def _verify_checkpoint_internal_hash_consistency(
        ckpt_dir: str, manifest: dict, *, run_dir: str) -> dict:
    """External-adjudication gate (4): replicates ts.load_checkpoint's OWN
    internal sha256 self-consistency check (manifest['files'][fname] vs the
    file's ACTUAL current on-disk bytes) WITHOUT eagerly torch.loading any
    tensor. This file stops calling ts.load_checkpoint for the continuation
    path (its single eager torch.load of the full ~12.6GiB model.pt+
    optimizer.pt bundle is the live-commit blocker the external adjudicator
    measured: committed 66.373/82.699GiB, free 16.325GiB, eager path
    requires 12.635+6=18.635GiB and REFUSES on this box right now) --
    replaced below by a sequential, mmap=True, per-component load
    (_verify_rung2_arch_identity already runs on lazily-paged metadata
    before any copy_(), and _restore_checkpoint_optimizer_state_in_place
    already copy_()s from an mmap'd source). This function preserves the
    file-integrity self-check ts.load_checkpoint used to provide as a side
    effect, now this file's own explicit responsibility, never silently
    dropped when it stopped being ts.load_checkpoint's caller. Fail-closed
    (written receipt, SystemExit) on any mismatch."""
    import os
    mismatches = {}
    for fname, expected_sha in manifest.get("files", {}).items():
        actual = _sha256_bytes_of_file(os.path.join(ckpt_dir, fname))
        if actual != expected_sha:
            mismatches[fname] = {"manifest_claimed": expected_sha, "actual_on_disk": actual}
    result = {"ckpt_dir": ckpt_dir, "mismatches": mismatches, "ok": not mismatches}
    if mismatches:
        receipt_path = _write_rung2_refusal_receipt(
            {"gate": "checkpoint_internal_hash_consistency", **result}, run_dir=run_dir,
            ticket="EMBER-702-CONTINUATION-CHECKPOINT-INTERNAL-HASH-REFUSAL")
        raise SystemExit(
            f"ATTRIBUTION_702_CHECKPOINT_INTERNAL_HASH_REFUSED: {mismatches} -- "
            f"checkpoint files do not match their OWN manifest's claimed "
            f"hashes (corruption / partial write) (receipt={receipt_path})")
    return result


def _rung2_checkpoint_arch_identity(model_state: dict) -> dict:
    """Derives raw/dedup numel + FF (gate_proj) width DIRECTLY from the
    checkpoint's own tensor bytes -- final-addendum's own method (fresh
    torch.load, 185 state keys, dedup by storage). Dedup-by-data_ptr() is
    the SAME convention split_param_groups_from_state_dict already uses for
    tied-tensor dedup (a tied embed/head shares storage after torch.load).
    Never reads live-model config -- this is the checkpoint-intrinsic leg
    the final addendum requires because "caller-supplied config alone is
    never accepted"."""
    raw_numel = sum(t.numel() for t in model_state.values())
    seen_ptrs: set = set()
    dedup_numel = 0
    for t in model_state.values():
        ptr = t.data_ptr()
        if ptr in seen_ptrs:
            continue
        seen_ptrs.add(ptr)
        dedup_numel += t.numel()
    gate_proj_shapes = {
        name: tuple(t.shape) for name, t in model_state.items()
        if "gate_proj" in name.lower() and "weight" in name.lower()}
    intermediate_size = (next(iter(gate_proj_shapes.values()))[0]
                         if gate_proj_shapes else None)
    return {
        "raw_numel": raw_numel, "dedup_numel": dedup_numel,
        "intermediate_size": intermediate_size,
        "n_state_keys": len(model_state),
        "n_gate_proj_tensors": len(gate_proj_shapes),
    }


def _verify_rung2_arch_identity(
        model_state: dict, *, run_dir: str,
        expected_dedup_numel: int = RUNG2_EXPECTED_DEDUP_NUMEL,
        expected_intermediate_size: int = RUNG2_EXPECTED_INTERMEDIATE_SIZE) -> dict:
    """Clause 4: refuses (before any compute) unless the CHECKPOINT-derived
    dedup numel and FF width equal the expected values -- the exact c03/
    FF4096-vs-FF32768 breach class becomes structurally impossible past
    this gate."""
    identity = _rung2_checkpoint_arch_identity(model_state)
    ok = (identity["dedup_numel"] == expected_dedup_numel and
          identity["intermediate_size"] == expected_intermediate_size)
    identity["expected_dedup_numel"] = expected_dedup_numel
    identity["expected_intermediate_size"] = expected_intermediate_size
    identity["matches_frozen_rung2_identity"] = ok
    if not ok:
        receipt_path = _write_rung2_refusal_receipt(
            {"gate": "arch_identity", **identity}, run_dir=run_dir,
            ticket="EMBER-702-CONTINUATION-ARCH-IDENTITY-REFUSAL")
        raise SystemExit(
            f"ATTRIBUTION_702_ARCH_IDENTITY_REFUSED: checkpoint-derived "
            f"dedup_numel={identity['dedup_numel']} (expected "
            f"{expected_dedup_numel}), intermediate_size="
            f"{identity['intermediate_size']} (expected "
            f"{expected_intermediate_size}) -- caller-supplied config alone "
            f"is never accepted, this is the exact c03/FF4096 breach class "
            f"the erratum caught (receipt={receipt_path})")
    return identity


def _verify_rung2_checkpoint_hashes(
        ckpt_dir: str, manifest: dict, *, run_dir: str,
        expected_hashes: dict = RUNG2_REFERENCE_CHECKPOINT_HASHES) -> dict:
    """Clause 5 / step866-final-addendum: cross-checks the checkpoint's own
    per-file hashes (ts.load_checkpoint already verified these against the
    checkpoint's OWN manifest -- internal self-consistency) PLUS a freshly
    computed manifest.json FILE hash (excluded from that internal check by
    save_checkpoint's own self-hash-avoidance convention) against the
    expected pins -- proves this is the EXACT pinned checkpoint, not merely
    an internally-consistent one at some other step."""
    import os
    computed = dict(manifest.get("files", {}))
    computed["manifest.json"] = _sha256_bytes_of_file(
        os.path.join(ckpt_dir, "manifest.json"))
    mismatches = {
        name: {"expected": expected, "actual": computed.get(name)}
        for name, expected in expected_hashes.items()
        if computed.get(name) != expected}
    result = {"computed_hashes": computed, "expected_hashes": dict(expected_hashes),
             "mismatches": mismatches}
    if mismatches:
        receipt_path = _write_rung2_refusal_receipt(
            {"gate": "checkpoint_hash_identity", **result}, run_dir=run_dir,
            ticket="EMBER-702-CONTINUATION-CHECKPOINT-HASH-REFUSAL")
        raise SystemExit(
            f"ATTRIBUTION_702_CHECKPOINT_HASH_REFUSED: {mismatches} -- this "
            f"is not the pinned checkpoint (receipt={receipt_path})")
    return result


def _verify_rung2_shard_manifest_identity(
        mmap_manifest_path: str, *, run_dir: str,
        expected_manifest_file_sha256: str = RUNG2_EXPECTED_MANIFEST_FILE_SHA256,
        expected_combined_source_manifest_sha256: str =
            RUNG2_EXPECTED_COMBINED_SOURCE_MANIFEST_SHA256) -> dict:
    """Clause 3: the custody mmap_cache/shards-v1-stream.manifest.json
    FILE's own bytes must match the pinned manifest-file sha256, and its
    CONTENT's combined_manifest_sha256 field (the source-shard-set lineage
    hash _build_or_open_memmap_cache already writes/reads, see timeshare_
    pretrain.py) must match the pinned combined-source-manifest sha256. The
    filename is misleading (the thread's own words) -- this binds CONTENT,
    never the name. This runs BEFORE the loader is constructed; the loader
    itself performs a SECOND, independent check (PackedShardLoader's
    expected_manifest_sha256 param, verified against a FRESH recompute over
    the live shard_dir bytes) -- this gate instead verifies the custody
    manifest ARTIFACT itself is the pinned one."""
    import json
    file_sha = _sha256_bytes_of_file(mmap_manifest_path)
    with open(mmap_manifest_path, "r", encoding="utf-8") as f:
        content = json.load(f)
    combined_sha = content.get("combined_manifest_sha256")
    result = {
        "mmap_manifest_path": mmap_manifest_path,
        "manifest_file_sha256": file_sha,
        "expected_manifest_file_sha256": expected_manifest_file_sha256,
        "combined_source_manifest_sha256": combined_sha,
        "expected_combined_source_manifest_sha256":
            expected_combined_source_manifest_sha256,
    }
    ok = (file_sha == expected_manifest_file_sha256 and
          combined_sha == expected_combined_source_manifest_sha256)
    result["matches_frozen_pins"] = ok
    if not ok:
        receipt_path = _write_rung2_refusal_receipt(
            {"gate": "shard_manifest_identity", **result}, run_dir=run_dir,
            ticket="EMBER-702-CONTINUATION-SHARD-MANIFEST-REFUSAL")
        raise SystemExit(
            f"ATTRIBUTION_702_SHARD_MANIFEST_REFUSED: {result} -- never "
            f"trust the 'shards-v1' filename, bind content "
            f"(receipt={receipt_path})")
    return result


def _verify_rung2_schedule_identity(manifest: dict, *, start_step: int,
                                    total_steps: int) -> None:
    """Clause 2/6: total_steps MUST equal the original stabilize schedule
    denominator declared in the checkpoint's own manifest (never the
    measurement-window length n_warmup+2*n_active), and start_step MUST
    equal the manifest's own step -- refuses (SystemExit) otherwise. This is
    the exact refusal the spec's negative fixture requires: a step866
    checkpoint driven with start=0 or total_steps=42 must refuse before any
    compute. Called in the wired attribution_run() path with values already
    DERIVED from the manifest (so it is a standing invariant assert there,
    never reachable via the CLI); the selftest below calls it directly with
    deliberately wrong values to prove the refusal fires."""
    manifest_step = manifest.get("step")
    manifest_total_steps = (manifest.get("extra") or {}).get("total_steps")
    reasons = []
    if start_step != manifest_step:
        reasons.append(f"start_step={start_step} != manifest step={manifest_step}")
    if total_steps != manifest_total_steps:
        reasons.append(
            f"total_steps={total_steps} != manifest extra.total_steps="
            f"{manifest_total_steps}")
    if reasons:
        raise SystemExit(
            "ATTRIBUTION_702_SCHEDULE_IDENTITY_REFUSED: " + " | ".join(reasons) +
            " -- continuation resume must traverse the checkpoint's OWN "
            "absolute schedule, never a measurement-window substitute "
            "(fail-closed, no partial credit).")


def _verify_rung2_optimizer_identity(
        optimizers: dict, *, run_dir: str, phase: str,
        expected_adamw_step: int | None,
        expected_n_adamw: int = REFERENCE_N_ADAMW,
        expected_n_muon: int = REFERENCE_N_MUON) -> dict:
    """External-adjudication gate (2): asserts the LIVE, already-restored
    optimizers dict matches the frozen rung-2 identity on THREE independent
    planes, fail-closed (written receipt, SystemExit) on any mismatch:

    1. Exact pinned param counts (44 AdamW / 140 Muon at the frozen split --
       REFERENCE_N_ADAMW/REFERENCE_N_MUON, already pinned elsewhere in this
       file for the receipt's disclosed cross-check).
    2. AdamW internal step-set is a SINGLETON equal to `expected_adamw_step`
       for THIS call's phase -- never any other value, including 866 (the
       resume/global_step -- the exact trap this pin exists to catch).
       Called at phase='post_restore' with the checkpoint's own pinned
       lifetime step (RUNG2_EXPECTED_ADAMW_INTERNAL_STEP, 136 at the frozen
       checkpoint) and again at phase='post_warmup' with that pin +
       n_warmup (138 at n_warmup=2) -- proving the restore AND the warmup
       block both advance the checkpoint's own internal counter correctly,
       never re-basing it onto the absolute/global step.
    3. Muon's state schema carries NO scalar "step" key at all, for every
       param -- this repo's own CPUOffloadOptimizer.__init__ (cpu_offload_
       adamw.py) only ever pre-seeds "momentum_buffer" for a non-Adam inner
       optimizer; a "step" key appearing there would mean structural
       cross-contamination between the two optimizer schemas. Per-tensor
       exp_avg/exp_avg_sq/momentum_buffer element counts are also asserted
       against their own shadow param's numel (self-consistency)."""
    import torch
    result: dict = {"phase": phase, "expected_adamw_step": expected_adamw_step, "checks": {}}
    problems: list[str] = []

    if "adamw" in optimizers:
        opt = optimizers["adamw"]
        n_adamw = len(opt._shadow)
        step_values: set = set()
        elem_mismatches: list[str] = []
        for i, shadow_p in enumerate(opt._shadow):
            state = opt._inner.state.get(shadow_p, {})
            if "step" not in state:
                problems.append(f"adamw[{i}] missing 'step' key")
                continue
            step_t = state["step"]
            step_values.add(float(step_t.item()) if isinstance(step_t, torch.Tensor) else float(step_t))
            for key in ("exp_avg", "exp_avg_sq"):
                if key in state and state[key].numel() != shadow_p.numel():
                    elem_mismatches.append(
                        f"adamw[{i}].{key}: {state[key].numel()} != shadow {shadow_p.numel()}")
        step_ok = (len(step_values) == 1 and expected_adamw_step is not None
                  and sorted(step_values)[0] == expected_adamw_step)
        result["checks"]["adamw"] = {
            "n_params": n_adamw, "expected_n_params": expected_n_adamw,
            "n_params_ok": n_adamw == expected_n_adamw,
            "step_values": sorted(step_values), "step_matches_pin": step_ok,
            "elem_count_mismatches": elem_mismatches,
        }
        if n_adamw != expected_n_adamw:
            problems.append(f"adamw n_params={n_adamw} != expected {expected_n_adamw}")
        if len(step_values) != 1:
            problems.append(f"adamw step-set not a singleton: {sorted(step_values)}")
        elif expected_adamw_step is not None and sorted(step_values)[0] != expected_adamw_step:
            problems.append(
                f"adamw internal step={sorted(step_values)[0]} != expected "
                f"{expected_adamw_step} at phase={phase!r}")
        if elem_mismatches:
            problems.append(f"adamw element-count mismatches: {elem_mismatches}")

    if "muon" in optimizers:
        opt = optimizers["muon"]
        n_muon = len(opt._shadow)
        has_step: list[int] = []
        elem_mismatches = []
        for i, shadow_p in enumerate(opt._shadow):
            state = opt._inner.state.get(shadow_p, {})
            if "step" in state:
                has_step.append(i)
            if "momentum_buffer" in state and state["momentum_buffer"].numel() != shadow_p.numel():
                elem_mismatches.append(
                    f"muon[{i}].momentum_buffer: {state['momentum_buffer'].numel()} "
                    f"!= shadow {shadow_p.numel()}")
        result["checks"]["muon"] = {
            "n_params": n_muon, "expected_n_params": expected_n_muon,
            "n_params_ok": n_muon == expected_n_muon,
            "no_scalar_step_ok": len(has_step) == 0,
            "indices_with_step": has_step, "elem_count_mismatches": elem_mismatches,
        }
        if n_muon != expected_n_muon:
            problems.append(f"muon n_params={n_muon} != expected {expected_n_muon}")
        if has_step:
            problems.append(f"muon state carries a 'step' key at indices {has_step} (schema violation)")
        if elem_mismatches:
            problems.append(f"muon element-count mismatches: {elem_mismatches}")

    result["ok"] = not problems
    result["problems"] = problems
    if problems:
        receipt_path = _write_rung2_refusal_receipt(
            {"gate": f"optimizer_identity_{phase}", **result}, run_dir=run_dir,
            ticket="EMBER-702-CONTINUATION-OPTIMIZER-IDENTITY-REFUSAL")
        raise SystemExit(
            f"ATTRIBUTION_702_OPTIMIZER_IDENTITY_REFUSED (phase={phase}): "
            f"{problems} (receipt={receipt_path})")
    return result


# Mirrors cbase_grow_rung2_stabilize.py's own module-level MICRO_BATCH
# constant (that file, line 630) -- production always micro-batches at 1
# and accumulates via grad_accum_steps; this file never re-derives that
# number independently, it imports the same fixed value.
ATTRIB702_PROD_MICRO_BATCH = 1


def _production_grad_accum_steps(cfg: dict, *, micro_batch: int) -> int:
    """Mirrors cbase_grow_rung2_stabilize.py lines 1537-1538 EXACTLY -- the
    only place in this repo that computes the production grad_accum_steps
    from cfg["throughput"]["batch"]. This is the single formula both the
    parity gate below and any live continuation call site use; neither
    re-derives it independently."""
    prod_batch = cfg["throughput"]["batch"] if cfg["throughput"]["batch"] >= 16 else 16
    return prod_batch // micro_batch if prod_batch % micro_batch == 0 else prod_batch


def _verify_rung2_production_config_parity(
        cfg: dict, *, batch_size: int, grad_accum_steps: int, run_dir: str,
        expected_micro_batch: int = ATTRIB702_PROD_MICRO_BATCH) -> dict:
    """ember #702 ADDENDUM-3/ADDENDUM-5 gates (5)/(7): the continuation path
    must exercise IDENTICAL production config to cbase_grow_rung2_stabilize
    .py's own run_v0_segment call site (batch=1 x accum=16 at the frozen
    pins, QAT lifecycle executing per cfg["precision"]["qat"]["enabled"]) --
    never a smaller/unaccumulated substitute that would silently change the
    measured step's memory-traffic shape. `batch_size`/`grad_accum_steps`
    are the CALLER's actual, independently-settable runtime values (this
    runner's own --batch-size/--grad-accum-steps, never re-derived from
    this gate's own output) -- checked against the cfg-derived production
    expectation computed via _production_grad_accum_steps, the ONE formula
    cbase_grow_rung2_stabilize.py itself uses. Fail-closed: any mismatch on
    either field refuses (SystemExit, structured receipt) before any
    production step executes. Counter fixture (ADDENDUM-3D): batch_size=4,
    grad_accum_steps=1 (no accumulation) against a cfg with
    throughput.batch=16 REFUSES on both fields."""
    expected_grad_accum_steps = _production_grad_accum_steps(
        cfg, micro_batch=expected_micro_batch)
    qat_enabled = bool(((cfg.get("precision") or {}).get("qat") or {}).get("enabled", False))
    mismatches = []
    if batch_size != expected_micro_batch:
        mismatches.append({"field": "batch_size", "got": batch_size,
                            "expected": expected_micro_batch})
    if grad_accum_steps != expected_grad_accum_steps:
        mismatches.append({"field": "grad_accum_steps", "got": grad_accum_steps,
                            "expected": expected_grad_accum_steps})
    result = {"ok": not mismatches, "mismatches": mismatches,
              "batch_size": batch_size, "grad_accum_steps": grad_accum_steps,
              "expected_micro_batch": expected_micro_batch,
              "expected_grad_accum_steps": expected_grad_accum_steps,
              "qat_enabled": qat_enabled}
    if mismatches:
        receipt_path = _write_rung2_refusal_receipt(
            {"gate": "production_config_parity", **result}, run_dir=run_dir,
            ticket="EMBER-702-PRODUCTION-CONFIG-PARITY-REFUSAL")
        raise SystemExit(
            f"ATTRIBUTION_702_PRODUCTION_CONFIG_PARITY_REFUSED: {mismatches} "
            f"(receipt={receipt_path})")
    return result


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------

def attribution_run(*, live: bool, cfg: dict, shard_dir: str | None,
                    run_dir: str, device: str, tiny_dims: dict | None = None,
                    intermediate_override: int | None = None,
                    batch_size: int | None = None, n_warmup: int = MIN_WARMUP_STEPS,
                    n_active: int = MIN_ACTIVE_STEPS, ce_chunk_tokens: int = 256,
                    total_steps: int | None = None,
                    resume_continuation: bool = False,
                    grow_checkpoint_dir: str | None = None,
                    mmap_cache_dir: str | None = None,
                    mmap_manifest_path: str | None = None,
                    grad_accum_steps: int | None = None) -> dict:
    """Runs warmup -> counterbalanced AB/BA blocks (repair item (b)) ->
    pinned/pageable calibration, evaluates every validity gate FAIL-CLOSED
    over the POOLED AB/BA samples, and returns the receipt dict (not yet
    written to disk -- see main()).

    resume_continuation (ember #702 2.2B rerun, additive -- False preserves
    byte-identical existing behavior for every prior caller): loads model +
    optimizer + RNG through the PRODUCTION ts.load_checkpoint /
    ts.load_optimizers_state / ts.restore_rng paths -- the SAME three
    functions run_v0_segment's own "--- resume ---" block calls, never a
    reimplementation -- binds total_steps to the checkpoint manifest's own
    original schedule denominator (clause 2; never n_warmup+2*n_active),
    binds the loader to the pinned shard/mmap source (clause 3), and
    REFUSES (fail-closed, SystemExit, structured receipt, before any
    compute) on any of: checkpoint-derived architecture identity (clause 4),
    checkpoint hash identity (clause 5), shard manifest identity (clause 3),
    or schedule identity (clause 2/6). grow_checkpoint_dir/shard_dir/
    mmap_cache_dir/mmap_manifest_path are ALL REQUIRED when
    resume_continuation=True -- no synthetic continuation state exists.

    grad_accum_steps (ADDENDUM-5, additive -- None preserves byte-identical
    prior behavior for every non-continuation caller, defaulting to 1: a
    single micro-batch per macro-step, matching the pre-ADDENDUM-5 _run_
    block exactly since grad_accum_steps=1 makes _run_production_step's
    micro-batch loop execute exactly once). On the resume_continuation
    path, None resolves to the PRODUCTION value computed by
    _production_grad_accum_steps(cfg, ...) (mirrors cbase_grow_rung2_
    stabilize.py's own driver, never re-derived independently); an
    EXPLICIT value (e.g. a caller passing --grad-accum-steps=1 against a
    --batch-size=4 -- the ADDENDUM-3D counter fixture) is checked against
    that production expectation by _verify_rung2_production_config_parity
    and REFUSED on mismatch, before any production step executes."""
    import os
    import torch

    os.makedirs(run_dir, exist_ok=True)
    seq = cfg["model"]["seq"] if live else (tiny_dims or {}).get("seq", 16)
    batch_size = batch_size or (
        ATTRIB702_PROD_MICRO_BATCH if resume_continuation else
        (cfg["throughput"]["batch"] if live else 2))

    resume_manifest = None
    checkpoint_arch_identity = None
    checkpoint_hash_identity = None
    shard_manifest_identity = None
    checkpoint_load_preflight = None
    optimizer_restore_report = None
    commit_telemetry = None
    start_step = 0

    if resume_continuation:
        if not grow_checkpoint_dir:
            raise SystemExit(
                "ATTRIBUTION_702_CONTINUATION_REFUSED: --resume-continuation "
                "requires --grow-checkpoint-dir (no synthetic continuation "
                "state).")
        if not shard_dir:
            raise SystemExit(
                "ATTRIBUTION_702_CONTINUATION_REFUSED: --resume-continuation "
                "requires a real --shard-dir (no synthetic tokens on the "
                "continuation path).")
        if not mmap_cache_dir or not mmap_manifest_path:
            raise SystemExit(
                "ATTRIBUTION_702_CONTINUATION_REFUSED: --resume-continuation "
                "requires --mmap-cache-dir and --mmap-manifest-path (clause "
                "3 data-identity binding).")

        model, vocab, hidden, n_mtp = ts.build_v0_model(
            cfg, live=live, tiny_dims=tiny_dims,
            intermediate_override=intermediate_override, device=device)

        # ---- external-adjudication gate (4): pre-load commit gate BEFORE ----
        # ---- any checkpoint bytes are touched -- repriced for the ----
        # ---- sequential mmap load below (bounded staging buffer, never ----
        # ---- the raw file-size sum; see _preflight_checkpoint_load_commit's ----
        # ---- own docstring for the live-commit measurement that forced ----
        # ---- this repricing). ----
        commit_before_load = _read_commit_gib()
        checkpoint_load_preflight = _preflight_checkpoint_load_commit(
            grow_checkpoint_dir, run_dir=run_dir, commit=commit_before_load)

        # ---- manifest + internal hash self-consistency -- NO tensor load ----
        # ---- (never ts.load_checkpoint; see _verify_checkpoint_internal_ ----
        # ---- hash_consistency's docstring for why this file stopped ----
        # ---- calling it). ----
        manifest = ts.read_manifest(grow_checkpoint_dir)
        _verify_checkpoint_internal_hash_consistency(
            grow_checkpoint_dir, manifest, run_dir=run_dir)
        resume_manifest = manifest

        # ---- sequential mmap component 1/3: model.pt. mmap=True (file- ----
        # ---- backed, lazily paged -- the SAME zero-real-commit mechanism ----
        # ---- _restore_fork_ already establishes) so the arch-identity gate ----
        # ---- below runs on lazily-paged METADATA (numel/shape/data_ptr, no ----
        # ---- byte materialization) and refuses BEFORE any copy_() into the ----
        # ---- live model. Each gate's expected-* value is read from the ----
        # ---- MODULE GLOBAL at THIS call site, never left to the gate ----
        # ---- function's own default -- Python binds a keyword default ONCE ----
        # ---- at function-definition time, so a caller (e.g. a selftest) ----
        # ---- that monkeypatches the module-level RUNG2_EXPECTED_* constant ----
        # ---- to test the refusal logic against a small fixture would ----
        # ---- silently miss a gate that relied on its own frozen default. ----
        model_state = torch.load(
            os.path.join(grow_checkpoint_dir, "model.pt"), map_location="cpu",
            mmap=True, weights_only=True)
        checkpoint_arch_identity = _verify_rung2_arch_identity(
            model_state, run_dir=run_dir,
            expected_dedup_numel=RUNG2_EXPECTED_DEDUP_NUMEL,
            expected_intermediate_size=RUNG2_EXPECTED_INTERMEDIATE_SIZE)
        checkpoint_hash_identity = _verify_rung2_checkpoint_hashes(
            grow_checkpoint_dir, manifest, run_dir=run_dir,
            expected_hashes=RUNG2_REFERENCE_CHECKPOINT_HASHES)
        shard_manifest_identity = _verify_rung2_shard_manifest_identity(
            mmap_manifest_path, run_dir=run_dir,
            expected_manifest_file_sha256=RUNG2_EXPECTED_MANIFEST_FILE_SHA256,
            expected_combined_source_manifest_sha256=
                RUNG2_EXPECTED_COMBINED_SOURCE_MANIFEST_SHA256)

        start_step = manifest.get("step")
        manifest_total_steps = (manifest.get("extra") or {}).get("total_steps")
        _verify_rung2_schedule_identity(
            manifest, start_step=start_step, total_steps=manifest_total_steps)
        total_steps = manifest_total_steps

        with torch.no_grad():
            for k, v in model.state_dict().items():
                v.copy_(model_state[k])
        del model_state

        loader = ts.PackedShardLoader(
            shard_dir, seq, n_mtp, mmap_cache_dir=mmap_cache_dir,
            expected_manifest_sha256=RUNG2_EXPECTED_COMBINED_SOURCE_MANIFEST_SHA256)

        optimizers, base_lrs, routing = ts.build_split_optimizer(
            model, cfg, offload_optimizer_state=True,
            deviation_dir=os.path.join(run_dir, "deviations"),
            optstate_dir=os.path.join(run_dir, "optstate"))

        # ---- sequential mmap component 2/3: optimizer.pt. addendum-2 ----
        # ---- blocker (a): in-place restore, NEVER ts.load_optimizers_ ----
        # ---- state (reallocates NEW state tensors, silently rebinding ----
        # ---- CPUOffloadOptimizer's pre-seeded file-backed memmap state to ----
        # ---- heap -- the exact defect this function replaces, both AdamW ----
        # ---- and Muon schemas, generic over saved_entry's own keys). ----
        optimizer_state = torch.load(
            os.path.join(grow_checkpoint_dir, "optimizer.pt"), map_location="cpu",
            mmap=True, weights_only=True)
        optimizer_restore_report = _restore_checkpoint_optimizer_state_in_place(
            optimizers, optimizer_state, run_dir=run_dir)
        del optimizer_state

        # ---- external-adjudication gate (2): pinned param counts (44 ----
        # ---- AdamW / 140 Muon), AdamW internal step-set == the ----
        # ---- checkpoint's OWN post-growth-lifetime step (never 866, the ----
        # ---- resume/global_step), Muon carries no scalar step key. ----
        optimizer_identity_post_restore = _verify_rung2_optimizer_identity(
            optimizers, run_dir=run_dir, phase="post_restore",
            expected_adamw_step=RUNG2_EXPECTED_ADAMW_INTERNAL_STEP,
            expected_n_adamw=REFERENCE_N_ADAMW, expected_n_muon=REFERENCE_N_MUON)

        # ---- sequential mmap component 3/3: rng.pt (small, no mmap ----
        # ---- benefit at this size). ----
        rng_state = torch.load(
            os.path.join(grow_checkpoint_dir, "rng.pt"), map_location="cpu",
            weights_only=False)
        ts.restore_rng(rng_state)
        del rng_state

        # Every component above was loaded, restored in place, and deleted
        # SEQUENTIALLY -- never all three held simultaneously (that peak-
        # footprint elimination, not a post-hoc release, is the actual fix
        # for the live-commit blocker; see the preflight's own docstring).
        # gc.collect() + measured before/after-load/after-release commit so
        # the receipt discloses the ACTUAL numbers, never an assumption.
        import gc
        commit_after_load = _read_commit_gib()
        gc.collect()
        commit_after_release = _read_commit_gib()
        commit_telemetry = {
            "before_load_gib": commit_before_load,
            "after_load_gib": commit_after_load,
            "after_release_gib": commit_after_release,
            "recovered_gib": (
                round(commit_after_release["free_gib"] - commit_after_load["free_gib"], 4)
                if commit_after_release is not None and commit_after_load is not None
                else None),
        }

        fork_global_step = start_step + n_warmup
    else:
        model, vocab, hidden, n_mtp = ts.build_v0_model(
            cfg, live=live, tiny_dims=tiny_dims,
            intermediate_override=intermediate_override, device=device)

        if shard_dir is None:
            assert not live, "live dispatch must supply a real --shard-dir"
            import numpy as np
            shard_dir = os.path.join(run_dir, "shards")
            os.makedirs(shard_dir, exist_ok=True)
            rng = np.random.default_rng(0)
            n_probe_steps = n_warmup + 2 * n_active + 4
            need = n_probe_steps * batch_size * seq + seq + n_mtp + 8
            toks = rng.integers(1, vocab, size=int(need), dtype=np.int64)
            toks[:: max(1, seq * 3)] = 0
            ts.write_packed_shard(
                os.path.join(shard_dir, "synthetic-00000.bin"), toks.astype("uint16").tolist())
        loader = ts.PackedShardLoader(shard_dir, seq, n_mtp,
                                      mmap_cache_dir=os.path.join(run_dir, "mmap_cache"))

        optimizers, base_lrs, routing = ts.build_split_optimizer(
            model, cfg, offload_optimizer_state=True,
            deviation_dir=os.path.join(run_dir, "deviations"),
            optstate_dir=os.path.join(run_dir, "optstate"))

        fork_global_step = n_warmup

    # optstate_dir is ALWAYS a per-invocation-unique path derived from run_dir
    # (itself unique per call -- a fresh tempdir on every selftest/CLI
    # invocation), never omitted -- ember #702 mid-build isolation repair.
    # The shared global default (cpu_offload_adamw._DEFAULT_OPTSTATE_DIR) is
    # therefore unreachable from this runner: a selftest's tiny-model param
    # names (or a live run racing another live run) can never collide with
    # or truncate another invocation's file-backed shadow/state.
    muon_named, adamw_named = ts.split_param_groups(model)
    expected_full_numel = sum(p.numel() for _, p in muon_named) + \
        sum(p.numel() for _, p in adamw_named)

    if resume_continuation and expected_full_numel != RUNG2_EXPECTED_DEDUP_NUMEL:
        # Clause 4, SECOND independent leg: the checkpoint-derived gate above
        # already refused on a wrong-scale checkpoint; this refuses if the
        # LIVE model (built from cfg + intermediate_override) does NOT also
        # realize the pinned scale -- catching a caller who fixed the
        # checkpoint pin but forgot to also pass
        # --intermediate-override=32768 (the exact class of silent
        # substitution the erratum caught in main()).
        receipt_path = _write_rung2_refusal_receipt(
            {"gate": "live_model_arch_identity",
             "expected_full_numel_from_split_param_groups": expected_full_numel,
             "expected_dedup_numel": RUNG2_EXPECTED_DEDUP_NUMEL,
             "intermediate_override": intermediate_override},
            run_dir=run_dir, ticket="EMBER-702-CONTINUATION-LIVE-ARCH-REFUSAL")
        raise SystemExit(
            f"ATTRIBUTION_702_LIVE_ARCH_REFUSED: live model realizes "
            f"{expected_full_numel} params (expected "
            f"{RUNG2_EXPECTED_DEDUP_NUMEL}) -- intermediate_override="
            f"{intermediate_override} is likely wrong (receipt={receipt_path})")

    ce_impl, ce_fn = ts.resolve_ce_impl(prefer_liger=live)
    mtp_cfg = cfg["objective"]["mtp_aux_heads"]
    mtp_enabled = mtp_cfg["enabled"]
    mtp_weight = mtp_cfg["weight"]
    total_steps = total_steps or (n_warmup + 2 * n_active)

    # ---- external-adjudication gates (5)/(7): production config parity ----
    # (batch=1 x accum=16, QAT lifecycle) -- ONLY meaningful on the
    # continuation path (a non-continuation synthetic/tiny fixture cfg has
    # no real throughput.batch/precision.qat contract to parity-check
    # against, and every pre-existing non-continuation caller keeps its
    # byte-identical single-micro-batch, no-QAT behavior: grad_accum_steps
    # defaults to 1, qat_enabled to False). A caller-supplied
    # grad_accum_steps on the continuation path (e.g. the ADDENDUM-3D
    # counter fixture's --batch-size=4 --grad-accum-steps=1) is checked,
    # never silently accepted or silently overridden. ----
    if resume_continuation:
        resolved_grad_accum_steps = (
            grad_accum_steps if grad_accum_steps is not None
            else _production_grad_accum_steps(cfg, micro_batch=ATTRIB702_PROD_MICRO_BATCH))
        production_config_parity = _verify_rung2_production_config_parity(
            cfg, batch_size=batch_size, grad_accum_steps=resolved_grad_accum_steps,
            run_dir=run_dir, expected_micro_batch=ATTRIB702_PROD_MICRO_BATCH)
        grad_accum_steps = production_config_parity["grad_accum_steps"]
        qat_enabled = production_config_parity["qat_enabled"]
    else:
        production_config_parity = None
        grad_accum_steps = grad_accum_steps if grad_accum_steps is not None else 1
        qat_enabled = False

    common = dict(model=model, loader=loader, optimizers=optimizers, base_lrs=base_lrs,
                 cfg=cfg, ce_fn=ce_fn, mtp_enabled=mtp_enabled, mtp_weight=mtp_weight,
                 ce_chunk_tokens=ce_chunk_tokens, device=device, batch_size=batch_size,
                 total_steps=total_steps, grad_accum_steps=grad_accum_steps,
                 qat_enabled=qat_enabled)

    # ---- warmup (uninstrumented) -- absolute step range: start_step is 0
    # for every pre-existing (non-continuation) caller, byte-identical to
    # prior behavior; start_step is the manifest's own step (866 at the
    # frozen pins) for a continuation resume. ----
    _run_block(global_step_start=start_step, n_steps=n_warmup, profile=False,
              collector=None, **common)

    # external-adjudication gate (2), second checkpoint: same pinned identity
    # re-verified after n_warmup LIVE optimizer.step() calls have advanced
    # the AdamW internal step counter past the restored value -- catches a
    # restore that "looked" identity-preserving at post_restore but silently
    # rebound on the first real step() (e.g. a state dict that aliases a
    # tensor rather than sharing storage).
    optimizer_identity_post_warmup = (
        _verify_rung2_optimizer_identity(
            optimizers, run_dir=run_dir, phase="post_warmup",
            expected_adamw_step=RUNG2_EXPECTED_ADAMW_INTERNAL_STEP + n_warmup,
            expected_n_adamw=REFERENCE_N_ADAMW, expected_n_muon=REFERENCE_N_MUON)
        if resume_continuation else None)

    # ---- counterbalanced AB/BA blocks (repair item (b)) -- fork_global_step
    # is n_warmup for every pre-existing caller (byte-identical), and
    # start_step + n_warmup (868 at the frozen pins) for a continuation
    # resume, so both AB/BA arms traverse the SAME absolute continuation
    # steps the frozen spec requires. ----
    ab_ba = _run_counterbalanced_ab_ba(
        n_active=n_active, fork_global_step=fork_global_step, run_dir=run_dir, **common)
    collector = ab_ba["collector"]

    # addendum-2/step-136-trap sanity: read back the LIVE AdamW internal
    # step counter after the full warmup+AB/BA run (arm B's 2*n_active
    # physical steps land on the never-restored-away live state -- arm A's
    # steps are undone by the fork restore between arms, so this is exactly
    # pre_run_step + n_warmup + 2*n_active, general over whatever internal
    # step value the checkpoint actually carried; never hardcoded to any
    # specific number like 136). None on any non-continuation caller.
    post_run_adamw_internal_step = None
    if resume_continuation and "adamw" in optimizers:
        adamw_opt = optimizers["adamw"]
        if isinstance(adamw_opt, _coa.CPUOffloadOptimizer):
            steps_seen = {
                float(s["step"].item()) if hasattr(s.get("step"), "item") else s.get("step")
                for s in (adamw_opt._inner.state.get(sp, {}) for sp in adamw_opt._shadow)
                if "step" in s
            }
            post_run_adamw_internal_step = (
                sorted(steps_seen)[0] if len(steps_seen) == 1 else sorted(steps_seen))

    calibration = calibrate_pinned_vs_pageable(device=device)

    gates = _evaluate_gates(
        n_warmup=n_warmup, n_active=n_active,
        profiled_walls=ab_ba["profiled_walls"], unprofiled_walls=ab_ba["unprofiled_walls"],
        collector=collector, expected_full_numel=expected_full_numel, calibration=calibration)
    all_passed = all(g["passed"] for g in gates.values())
    failing = [name for name, g in gates.items() if not g["passed"]]

    totals = collector.phase_totals()
    ratios = _per_step_ratios(collector)
    if all_passed:
        verdict_result = _classify_verdict_predicates(ratios)
    else:
        verdict_result = {"verdict": "INVALID", "reason": "one or more validity "
                          f"gates failed (fail-closed, no partial credit): {failing}"}

    vram = None
    if device == "cuda" and torch.cuda.is_available():
        try:
            vram = nvidia_smi_vram()
        except Exception as e:
            vram = {"error": str(e)}

    receipt = {
        "ticket": "EMBER-702-ATTRIBUTION",
        "ts": _ts(),
        "issue": "wordingone/ember#702",
        "prereg": {
            "amendment_comment_id": 4938595840,
            "status": "PREREG_FROZEN",
            "pre_run_amendments": [
                "4939491354: tied-tensor erratum (realized-numel binding)",
                "4939674864: executable verdict-grammar predicates (SESOI, "
                "bootstrap CIs, D/F predicate table)",
            ],
            "block_comment_repair": {
                "disposition": "BLOCK_721_PRODUCTION_ATTRIBUTION",
                "item_a": "instrumentation moved INSIDE the original "
                          "CPUOffloadOptimizer.step() -- per-instance "
                          "attach_span_collector()/detach_span_collector(), "
                          "default-off; no reimplementation of step() exists "
                          "in this runner",
                "item_b": "overhead gate redesigned as counterbalanced AB/BA "
                          "from an identical forked snapshot (model + "
                          "optimizer state + RNG streams; loader state = "
                          "shared starting global_step, since batch() is a "
                          "pure function of step)",
                "item_c": "_selftest_integration_all_gates_pass() -- real "
                          "pipeline, real gates, gates_all_passed=True on a "
                          "CPU fixture with only the CUDA-only calibration "
                          "function stubbed",
            },
        },
        "mode": {
            "live": live, "device": device, "n_warmup": n_warmup, "n_active": n_active,
            # addendum-4 spec self-correction, round-3 accounting repair
            # (_run_counterbalanced_ab_ba's own docstring + code confirm this
            # against the actual step boundaries, not just asserted):
            # physical_step_executions counts every actual step() call --
            # EACH arm runs a profiled n_active sub-block AND an unprofiled
            # n_active sub-block (Arm A: profiled-then-unprofiled; Arm B,
            # from the SAME restored fork point: unprofiled-then-profiled),
            # so warmup runs once + 4*n_active physical step() calls total
            # (2 sub-blocks x 2 arms). unique_absolute_schedule_steps counts
            # distinct schedule POSITIONS touched -- both arms traverse the
            # IDENTICAL absolute range [fork_global_step, fork_global_step +
            # 2*n_active) (arm A's profiled+unprofiled sub-blocks cover it
            # once; arm B's unprofiled+profiled sub-blocks, from the same
            # restored fork point, cover the SAME range again in swapped
            # order), so warmup once + 2*n_active unique positions. Neither
            # is ever a valid total_steps denominator on the continuation
            # path -- _verify_rung2_schedule_identity binds total_steps to
            # the checkpoint manifest's own original schedule only.
            "physical_step_executions": n_warmup + 4 * n_active,
            "unique_absolute_schedule_steps": n_warmup + 2 * n_active,
        },
        # Clause 5 receipt emissions: source checkpoint 4-hash set, start/end
        # absolute steps, total_steps denominator, shard identity shas, full
        # checkpoint-derived arch identity, realized numel -- populated only
        # on the continuation-resume path (None-valued keys on every
        # pre-existing caller, byte-identical absence of this block's
        # content otherwise).
        "continuation": {
            "resume_continuation": resume_continuation,
            "grow_checkpoint_dir": grow_checkpoint_dir,
            "checkpoint_manifest": resume_manifest,
            "start_step": start_step if resume_continuation else None,
            "fork_global_step": fork_global_step if resume_continuation else None,
            "end_step": ab_ba["post_run_global_step"] if resume_continuation else None,
            "total_steps_denominator": total_steps if resume_continuation else None,
            "checkpoint_arch_identity": checkpoint_arch_identity,
            "checkpoint_hash_identity": checkpoint_hash_identity,
            "shard_manifest_identity": shard_manifest_identity,
            # addendum-2 additions: pre-load commit gate result, in-place
            # optimizer-restore report (both schemas, storage-identity +
            # AdamW step-set consistency proofs), and the full before/after-
            # load/after-release commit telemetry for the immediate del+gc
            # release of the heap-loaded source bundle.
            "checkpoint_load_preflight": checkpoint_load_preflight,
            "optimizer_restore_report": optimizer_restore_report,
            # external-adjudication gate (2): pinned param counts / AdamW
            # step-set / Muon no-scalar-step, checked twice -- immediately
            # after restore (before any compute) and again after n_warmup
            # live steps (catches a restore that only LOOKED correct at
            # rest).
            "optimizer_identity_post_restore": optimizer_identity_post_restore,
            "optimizer_identity_post_warmup": optimizer_identity_post_warmup,
            "post_run_adamw_internal_step": post_run_adamw_internal_step,
            "commit_telemetry": commit_telemetry,
            # ADDENDUM-5 gates (5)/(7): production config parity (batch=1 x
            # accum=16, QAT lifecycle) -- computed/verified BEFORE any
            # production step ran (see the gate call above common's
            # construction); disclosed here so a downstream reader can
            # recheck the exact batch_size/grad_accum_steps/qat_enabled
            # values every _run_production_step call in this run used.
            "production_config_parity": production_config_parity,
        } if resume_continuation else {"resume_continuation": False},
        "optimizer_routing": routing,
        "expected_full_numel_from_split_param_groups": expected_full_numel,
        "reference_pre_run_amendment": {
            "n_params": REFERENCE_REALIZED_N_PARAMS, "n_tensors": REFERENCE_N_TENSORS,
            "n_muon": REFERENCE_N_MUON, "n_adamw": REFERENCE_N_ADAMW,
            "matches_this_run": expected_full_numel == REFERENCE_REALIZED_N_PARAMS,
            "note": ("disclosed cross-check only -- the exact_bytes gate binds to "
                     "THIS run's live-measured realized numel, never this constant"),
        },
        "ab_ba_design": {
            "fork_global_step": ab_ba["fork_global_step"],
            "post_run_global_step": ab_ba["post_run_global_step"],
            "arm_a": {"order": ab_ba["arm_a"]["order"],
                      "profiled_walls_s": ab_ba["arm_a"]["profiled_walls_s"],
                      "unprofiled_walls_s": ab_ba["arm_a"]["unprofiled_walls_s"]},
            "arm_b": {"order": ab_ba["arm_b"]["order"],
                      "profiled_walls_s": ab_ba["arm_b"]["profiled_walls_s"],
                      "unprofiled_walls_s": ab_ba["arm_b"]["unprofiled_walls_s"]},
        },
        # ember #702 mid-build repair round 3: the successful fork-capacity
        # preflight's full record (realized sizes, margins, all three
        # measurement dicts) -- previously discarded once the preflight
        # passed. A claim-bearing receipt PRESERVES what was measured, not
        # just that a check ran.
        "fork_capacity_preflight": ab_ba["preflight"],
        "subphase_totals_s": totals,
        "subphase_byte_totals": collector.byte_totals(),
        "per_step_span_ratios": ratios,
        "profiled_step_walls_s": collector.step_walls(),
        "unprofiled_step_walls_s": ab_ba["unprofiled_walls"],
        "gates": gates,
        "gates_all_passed": all_passed,
        "failing_gates": failing,
        "verdict_grammar": list(VERDICT_GRAMMAR),
        "calibration_pinned_vs_pageable": calibration,
        "vram_at_end": vram,
        "ce_impl": ce_impl,
        # ember #702 FIX A (2026-07-11, attempt-2 receipt destroyed by
        # checked_write's R2 rule): this receipt embeds several sha256
        # fields (checkpoint 4-hash set, manifest_file_sha256,
        # combined_source_manifest_sha256) computed by _sha256_bytes_of_file
        # -- a plain binary whole-file read, no normalization -- so this is
        # the accurate, not a placeholder, convention string. Matches the
        # canonical wording used across cbase_grow_rung.py/cbase_grow_live.py
        # /cbase_grow_measured_flops.py verbatim.
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
        **verdict_result,
    }
    return receipt


# ---------------------------------------------------------------------------
# Verdict-predicate selftest -- one synthetic profile per verdict class.
# The real attribution_run() CPU selftest below can NEVER exercise
# _classify_verdict_predicates via the UNSTUBBED path (gates never all-pass
# without a CUDA device, so the verdict grammar is unreachable from that path
# on this box -- see _selftest() for why that must stay true). This is the
# second pre-run amendment's own requirement (comment id 4939674864: "the
# runner's selftest must include one synthetic profile per verdict class")
# -- tests the predicate table directly and independently of the gate
# pipeline.
# ---------------------------------------------------------------------------

def _synthetic_ratio_fixture(*, stage: float, inner: float, gpu: float,
                             host_unavoidable: float, n_steps: int = 10,
                             jitter: float = 0.01, seed: int = 0) -> dict:
    """n_steps per-step ratio samples, each target +/- a small seeded
    jitter (bootstrap CI must see real per-step variance, not a point
    mass). stage_plus_host is DERIVED per step from the jittered stage/host
    values, not independently jittered -- the real per-step data has the
    same relationship (see _per_step_ratios)."""
    import random
    rnd = random.Random(seed)

    def _jseries(target: float) -> list:
        return [max(0.0, target + rnd.uniform(-jitter, jitter)) for _ in range(n_steps)]

    stage_s, inner_s, gpu_s, host_s = (
        _jseries(stage), _jseries(inner), _jseries(gpu), _jseries(host_unavoidable))
    return {
        "stage_ratio": stage_s, "inner_ratio": inner_s, "gpu_ratio": gpu_s,
        "host_unavoidable_ratio": host_s,
        "stage_plus_host_unavoidable_ratio": [s + h for s, h in zip(stage_s, host_s)],
    }


# Targets are chosen with generous margin (>=0.07) from every threshold
# (0.10 SESOI, 0.50 GPU floor, 0.15 host ceiling) so +/-0.01 per-step
# jitter and bootstrap resample noise can never flip the classification --
# these fixtures test the PREDICATE LOGIC, not threshold-boundary
# sensitivity.
_VERDICT_FIXTURES = {
    "DIRECT_COPY_FIRST": dict(stage=0.30, inner=0.02, gpu=0.40, host_unavoidable=0.28),
    "FACTOR1_FIRST": dict(stage=0.02, inner=0.35, gpu=0.40, host_unavoidable=0.23),
    "BOTH_COMPOSE": dict(stage=0.20, inner=0.20, gpu=0.30, host_unavoidable=0.30),
    "GPU_COMPUTE_BOUND": dict(stage=0.03, inner=0.03, gpu=0.86, host_unavoidable=0.08),
    "INCONCLUSIVE": dict(stage=0.05, inner=0.05, gpu=0.40, host_unavoidable=0.50),
}


def _selftest_verdict_predicates() -> None:
    for i, (expected_verdict, targets) in enumerate(_VERDICT_FIXTURES.items()):
        ratios = _synthetic_ratio_fixture(seed=100 + i, **targets)
        result = _classify_verdict_predicates(ratios)
        assert result["verdict"] == expected_verdict, (
            f"predicate-table fixture {expected_verdict!r} classified as "
            f"{result['verdict']!r} instead -- reason: {result['reason']}")
        # every ratio + both CI bounds per span + SESOI constants + fired
        # predicate must be present (amendment's own receipt requirement).
        for span_key in ("T_stage_over_T_step", "T_inner_over_T_step",
                         "T_gpu_over_T_step", "T_host_unavoidable_over_T_step",
                         "T_stage_plus_T_host_unavoidable_over_T_step"):
            ci = result["ci95"][span_key]
            assert ci["lower"] is not None and ci["upper"] is not None, (expected_verdict, span_key)
        assert set(result["sesoi"]) == {
            "SESOI_direct", "SESOI_factor", "gpu_compute_bound_gpu_lower_ci_floor",
            "gpu_compute_bound_host_upper_ci_ceil"}
        assert "D_direct_copy" in result["predicates"] and "F_factor1" in result["predicates"]
    print("ATTRIBUTION_702_VERDICT_PREDICATES_SELFTEST_PASS "
          f"fixtures={list(_VERDICT_FIXTURES.keys())} "
          f"n_bootstrap_resamples={N_BOOTSTRAP_RESAMPLES}", flush=True)


# ---------------------------------------------------------------------------
# CPU-only selftest -- exercises the FULL instrumentation + gate + verdict
# path with tiny fixture dims, no GPU, no daemon, < 30s. UNSTUBBED: this is
# the honest, real-hardware-constrained path and must keep failing closed on
# the calibration gate.
# ---------------------------------------------------------------------------

def _selftest() -> int:
    import random
    import tempfile
    import torch

    torch.manual_seed(0)
    random.seed(0)

    cfg = {
        "model": {"seq": 16, "vocab": 64, "hidden": 32, "tied_embeddings": False},
        "objective": {"mtp_aux_heads": {"enabled": True, "n_heads": 2, "weight": 0.3}},
        "optimizer": {"lr_muon": 0.02, "lr_adamw": 3e-4, "weight_decay": 0.1},
        "schedule": {"warmup_frac": 0.1, "stable_until_frac": 0.8, "decay_to_lr_frac": 0.1},
        "throughput": {"batch": 2},
    }
    tiny_dims = {"vocab": 64, "hidden": 32, "depth": 2, "seq": 16}
    run_dir = tempfile.mkdtemp(prefix="attribution702_selftest_")

    receipt = attribution_run(
        live=False, cfg=cfg, shard_dir=None, run_dir=run_dir, device="cpu",
        tiny_dims=tiny_dims, batch_size=2, n_warmup=2, n_active=10, ce_chunk_tokens=32)

    # ---- assertions: the mechanism, not a fabricated production verdict ----
    gates = receipt["gates"]
    assert receipt["gates_all_passed"] is False, (
        "CPU selftest must NOT produce a gates-all-passed run: there is no CUDA "
        "device, so pinned_pageable_calibration is expected (and required) to "
        "fail closed. A CPU run reporting all gates passed is the failure mode "
        "this selftest exists to catch (silent, ungated verdict fabrication).")
    assert gates["pinned_pageable_calibration"]["passed"] is False, (
        "pinned_pageable_calibration must fail closed on CPU (no CUDA device)")
    assert receipt["verdict"] == "INVALID", (
        f"expected fail-closed INVALID verdict on CPU, got {receipt['verdict']!r}")
    assert "pinned_pageable_calibration" in receipt["failing_gates"]

    # step-count gate: 2 warmup + 10 active IS the floor, must independently pass.
    assert gates["step_count"]["passed"] is True, gates["step_count"]
    assert gates["step_count"]["n_active_pooled_ab_ba"] == 20, gates["step_count"]

    # subphase decomposition actually fired for all four optimizer sites plus
    # fwd/loss/bwd, with nonzero wall time and nonzero realized-numel bytes,
    # POOLED across both AB/BA profiled sub-blocks.
    totals = receipt["subphase_totals_s"]
    for phase in ALL_PHASES:
        assert phase in totals and totals[phase] >= 0.0, f"missing/negative phase: {phase}"
    assert sum(totals[p] for p in OPTIMIZER_SUBPHASES) > 0.0, (
        "optimizer subphase instrumentation never fired")
    assert sum(totals[p] for p in FWD_LOSS_BWD_PHASES) > 0.0, (
        "fwd/loss/bwd instrumentation never fired")
    byte_totals = receipt["subphase_byte_totals"]
    assert byte_totals["grad_to_cpu_fp32"] > 0, "zero bytes attributed to grad_to_cpu_fp32"
    assert byte_totals["updated_param_to_gpu"] > 0, "zero bytes attributed to updated_param_to_gpu"

    # exact_bytes self-consistency must hold even though the calibration gate
    # (a DIFFERENT, CUDA-only gate) fails -- gates are independent.
    assert gates["exact_bytes"]["bytes_self_consistent"] is True, gates["exact_bytes"]
    assert gates["exact_bytes"]["numel_matches_live_param_groups"] is True, gates["exact_bytes"]

    # AB/BA counterbalanced design: both arms present, orders swapped, each
    # arm contributed n_active profiled + n_active unprofiled samples.
    ab = receipt["ab_ba_design"]
    assert ab["arm_a"]["order"] == "profiled_first" and ab["arm_b"]["order"] == "unprofiled_first"
    assert len(ab["arm_a"]["profiled_walls_s"]) == 10 and len(ab["arm_b"]["profiled_walls_s"]) == 10
    assert len(ab["arm_a"]["unprofiled_walls_s"]) == 10 and len(ab["arm_b"]["unprofiled_walls_s"]) == 10
    assert len(receipt["unprofiled_step_walls_s"]) == 20
    assert len(receipt["profiled_step_walls_s"]) == 20

    # per_step_span_ratios is populated even on a gates-failed (INVALID) run
    # -- the amendment's ratios/CI machinery is independent of the gate
    # pipeline; only the LABEL (verdict) is gated.
    assert set(receipt["per_step_span_ratios"]) == {
        "stage_ratio", "inner_ratio", "gpu_ratio", "host_unavoidable_ratio",
        "stage_plus_host_unavoidable_ratio"}
    assert len(receipt["per_step_span_ratios"]["stage_ratio"]) == 20

    print("ATTRIBUTION_702_SELFTEST_PASS "
          f"verdict={receipt['verdict']} failing_gates={receipt['failing_gates']} "
          f"n_optimizer_subphase_s={sum(totals[p] for p in OPTIMIZER_SUBPHASES):.6f} "
          f"n_fwd_loss_bwd_s={sum(totals[p] for p in FWD_LOSS_BWD_PHASES):.6f} "
          f"realized_numel_per_step={gates['exact_bytes']['realized_numel_per_step']} "
          f"closure_frac={gates['closure']['closure_frac']}", flush=True)

    _selftest_verdict_predicates()
    _selftest_span_collector_attach_detach()
    _selftest_integration_all_gates_pass()
    _selftest_fork_capacity_preflight()
    _selftest_rung2_identity_gate_units()
    _selftest_continuation_schedule_bind()
    _selftest_optimizer_restore_refusals()
    _selftest_production_config_parity_refusal()
    _selftest_production_step_parity()
    _selftest_continuation_resume_wiring()
    return 0


def _selftest_span_collector_attach_detach() -> None:
    """Direct unit check of ember #702 repair item (a): attach/detach is
    per-INSTANCE (a second, unattached instance is never affected), step()
    is byte-identical whether attached or not (same tensor values after one
    step from identical starting state, attached vs unattached), and detach
    actually clears the hooks (no leak past the profiled block)."""
    import tempfile

    import torch

    def _make_opt(tag: str):
        p = torch.nn.Parameter(torch.randn(4, 4))
        p.grad = torch.randn(4, 4)
        d = tempfile.mkdtemp(prefix=f"coa_span_selftest_{tag}_")
        opt = _coa.CPUOffloadOptimizer(
            [("w", p)], lambda ps: torch.optim.AdamW(ps, lr=1e-2, weight_decay=0.0),
            optstate_dir=d)
        return p, opt

    # ---- byte-identical step() with vs without an attached collector ----
    torch.manual_seed(1)
    p1, opt1 = _make_opt("unattached")
    torch.manual_seed(1)
    p2, opt2 = _make_opt("attached")
    assert torch.equal(p1.data, p2.data), "fixture setup diverged before any step()"

    events: list = []
    opt2.attach_span_collector(
        add=lambda phase, dt: events.append(("add", phase)),
        add_bytes=lambda phase, n: events.append(("bytes", phase)),
        add_numel=lambda n: events.append(("numel", n)),
        sync=lambda: None)
    assert opt2._span_add is not None

    opt1.step()
    opt2.step()
    assert torch.equal(p1.data, p2.data), (
        "attach_span_collector changed step()'s numerical result -- "
        "instrumentation must be observation-only")
    assert any(name == "add" and phase in OPTIMIZER_SUBPHASES for name, phase in events), (
        "attached collector never received any span -- instrumentation did not fire")
    fired_phases = {phase for name, phase in events if name == "add"}
    assert fired_phases == set(OPTIMIZER_SUBPHASES), fired_phases

    opt2.detach_span_collector()
    assert opt2._span_add is None
    events.clear()
    opt1.step()
    opt2.step()
    assert torch.equal(p1.data, p2.data), "post-detach step() diverged"
    assert events == [], f"detached collector still received spans: {events}"

    print("ATTRIBUTION_702_SPAN_COLLECTOR_ATTACH_DETACH_SELFTEST_PASS", flush=True)


def _selftest_integration_all_gates_pass() -> None:
    """Integration fixture -- ember #702 BLOCK_721_PRODUCTION_ATTRIBUTION
    repair item (c). Runs the REAL attribution_run() pipeline end-to-end on
    CPU: real fork/restore, real AB/BA counterbalanced blocks, real per-
    instance instrumented CPUOffloadOptimizer.step() calls, real gate
    evaluation, real verdict classification. Asserts gates_all_passed=True
    with a genuine (non-INVALID) verdict from VERDICT_GRAMMAR.

    Every gate except pinned_pageable_calibration is measured for real on
    this tiny CPU fixture. That ONE gate is fundamentally CUDA-only (a real
    PCIe H2D/D2H throughput number has no CPU-only meaning) and is STUBBED
    here to a disclosed, structurally valid synthetic dict for the duration
    of this fixture only (module-global monkeypatch, restored in a finally
    block regardless of outcome) -- this is the ONLY thing this fixture
    fakes. It does not touch step_count, overhead, closure, or exact_bytes,
    which all pass or fail on their own real CPU-measured merits; if any of
    those is broken, this fixture fails honestly rather than masking it.

    The production _selftest() above is UNCHANGED and still asserts
    gates_all_passed=False on an unstubbed run -- proving this fixture's
    stub is disclosed and isolated to itself, not a silent lowering of the
    real gate."""
    import random
    import tempfile

    import torch

    torch.manual_seed(7)
    random.seed(7)

    # Dims larger than _selftest()'s (hidden=32/depth=2/seq=16), deliberately:
    # this fixture's overhead/closure gates are REAL timing measurements, and
    # on a too-tiny model the fixed Python-level cost of the instrumentation
    # calls themselves (perf_counter/sync/callback dispatch) is a large
    # enough fraction of each (otherwise near-instant) tensor op to blow the
    # 10%/5% bounds on pure measurement noise. Re-swept at these dims after
    # the fork snapshot/restore went disk-backed (mid-build capacity repair,
    # item 1): the one-time real disk I/O per AB/BA invocation (torch.save/
    # torch.load around the fork, sharing the same disk as
    # CPUOffloadOptimizer's own per-step memmap I/O) adds enough timing
    # jitter that the PRIOR fixture (hidden=256/seq=32/n_active=14, tuned
    # against the in-memory-clone fork) intermittently failed the overhead
    # gate (observed 15.6%/31.9% against the 10% bound, 2 of 10 real CLI
    # invocations) -- a genuine regression the deeper sweep below is chosen
    # to survive, not a fluke. 20 seeds at these dims: overhead 0.2-5.8%,
    # closure 1.3-1.5%, both comfortably inside bound with margin.
    cfg = {
        "model": {"seq": 64, "vocab": 64, "hidden": 384, "tied_embeddings": False},
        "objective": {"mtp_aux_heads": {"enabled": True, "n_heads": 2, "weight": 0.3}},
        "optimizer": {"lr_muon": 0.02, "lr_adamw": 3e-4, "weight_decay": 0.1},
        "schedule": {"warmup_frac": 0.1, "stable_until_frac": 0.8, "decay_to_lr_frac": 0.1},
        "throughput": {"batch": 2},
    }
    tiny_dims = {"vocab": 64, "hidden": 384, "depth": 3, "seq": 64}
    run_dir = tempfile.mkdtemp(prefix="attribution702_integration_")

    synthetic_calibration = {
        "skipped": False, "n_bytes_per_trial": 1 << 24, "n_trials": 5,
        "h2d_pageable_gbps": 8.0, "h2d_pinned_gbps": 14.0,
        "d2h_pageable_gbps": 7.5, "d2h_pinned_gbps": 13.0,
        "pcie4_x16_peak_gbps": 31.508,
        "h2d_pinned_vs_pageable_speedup": 1.75, "d2h_pinned_vs_pageable_speedup": 1.733,
        "note": ("SYNTHETIC -- integration-fixture stub, CPU has no real PCIe "
                 "H2D/D2H path to measure. Every other gate in this receipt is "
                 "computed for real from a live CPU run."),
    }

    module = sys.modules[__name__]
    _orig_calibrate = module.calibrate_pinned_vs_pageable

    def _stub_calibrate(*, device: str, **kwargs):
        return dict(synthetic_calibration)

    module.calibrate_pinned_vs_pageable = _stub_calibrate
    try:
        receipt = attribution_run(
            live=False, cfg=cfg, shard_dir=None, run_dir=run_dir, device="cpu",
            tiny_dims=tiny_dims, batch_size=2, n_warmup=2, n_active=24, ce_chunk_tokens=32)
    finally:
        module.calibrate_pinned_vs_pageable = _orig_calibrate

    gates = receipt["gates"]
    assert receipt["gates_all_passed"] is True, (
        "integration fixture must reach gates_all_passed=True with only the "
        f"CUDA-only calibration gate stubbed -- got gates={gates}")
    for gate_name in ("step_count", "overhead", "closure", "exact_bytes"):
        assert gates[gate_name]["passed"] is True, (gate_name, gates[gate_name])
    assert gates["pinned_pageable_calibration"]["calibration"]["note"].startswith("SYNTHETIC"), (
        "the stub must be disclosed IN the receipt, not silently swapped in")
    assert receipt["verdict"] in VERDICT_GRAMMAR, (
        f"integration fixture must classify a real, non-INVALID verdict, "
        f"got {receipt['verdict']!r}")
    assert receipt["failing_gates"] == []

    print("ATTRIBUTION_702_INTEGRATION_ALL_GATES_PASS_SELFTEST_PASS "
          f"verdict={receipt['verdict']} "
          f"gates_all_passed={receipt['gates_all_passed']}", flush=True)


def _selftest_fork_capacity_preflight() -> None:
    """ember #702 mid-build repair rounds 2+3: proves _preflight_fork_
    capacity prices the ACTUAL restore-path exposure (bounded staging
    buffers + any real plain-optimizer bytes), never the phantom full-
    model/full-snapshot charges round 1 used (round 2) -- AND fails CLOSED,
    never open, on an unavailable required measurement (round 3, a post-
    merge falsifier finding on the round-2 head: monkeypatched read
    failures returned sufficient=True). Five assertions:

    1. CLEARS at a simulated 20GiB-VRAM-used envelope (24GiB card, ~4GiB
       free) with ample disk -- the exact real-world peak this repo's own
       measurements put the live 2.2B dispatch at, which the round-1
       preflight (pricing model_bytes~=4.09GiB + 2GiB margin against ~4GiB
       free) could NEVER clear -- safe-fail but undeliverable, not merely
       conservative.
    2. REFUSES under genuinely low free disk -- proves the disk check
       actually fires, not just that it exists.
    3. REFUSES when the commit measurement is UNAVAILABLE (module-level
       _read_commit_gib monkeypatched to return None) -- round 1/2 treated
       this as "disclosed, never a violation" and left sufficient=True;
       commit is an ALWAYS-APPLICABLE, REQUIRED measurement, so an
       unavailable read is a refusal, not a skip.
    4. REFUSES when the disk measurement is UNAVAILABLE (module-level
       _read_disk_free_gib monkeypatched to return None) -- same class of
       fix as #3.
    5. REFUSES when the VRAM measurement RAISES (a malformed nvsmi dict
       missing "free_gib") -- round 1/2 recorded {"error": ...} without
       setting sufficient=False; device=='cuda' makes VRAM an APPLICABLE,
       REQUIRED leg, so an exception during its measurement is a refusal,
       not a silently-absorbed error.

    nvsmi/disk are INJECTED synthetic measurement dicts (same pure-function-
    of-a-measured-dict pattern as vram_preflight's own `nvsmi` param); the
    commit/disk UNAVAILABLE fixtures monkeypatch the module-level read
    functions themselves (the same try/finally-restored pattern
    _selftest_integration_all_gates_pass already uses for
    calibrate_pinned_vs_pageable) since `commit=None`/`disk=None` as
    KEYWORD ARGUMENTS mean "measure for real" by design, not "force a read
    failure" -- the monkeypatch is the only way to inject that state
    deterministically. This proves the PRICING AND FAIL-CLOSED LOGIC
    against known envelopes, not today's actual idle GPU/disk/commit state
    on whatever box happens to run this selftest. Skips (disclosed, never a
    silent pass) if this process has no CUDA device at all -- the VRAM leg
    of this gate is fundamentally CUDA-only, same disclosed-skip discipline
    as calibrate_pinned_vs_pageable."""
    import tempfile

    import torch
    import torch.nn as nn

    if not torch.cuda.is_available():
        print("ATTRIBUTION_702_FORK_CAPACITY_PREFLIGHT_SELFTEST_SKIP "
              "reason=cuda_unavailable_in_this_process -- disclosed skip, "
              "never a silent pass", flush=True)
        return

    # Empty optimizers dict: this selftest targets the PRICING ARITHMETIC
    # itself (already exercised end-to-end against a real CPUOffloadOptimizer
    # by _selftest_integration_all_gates_pass), so model_bytes is the only
    # realized size in play -- and, by design, no longer matters to the VRAM
    # check at all (that's exactly the bug being proven fixed).
    model = nn.Linear(64, 64)
    optimizers: dict = {}
    run_dir = tempfile.mkdtemp(prefix="attribution702_capacity_preflight_")

    simulated_nvsmi_20gib_used = {
        "total_mib": 24576, "used_mib": 20480, "free_mib": 4096,
        "total_gib": 24.0, "used_gib": 20.0, "free_gib": 4.0,
    }
    ample_disk = {"total_gib": 500.0, "used_gib": 100.0, "free_gib": 400.0}

    # ---- 1: CLEARS at the measured real envelope ----
    result_clear = _preflight_fork_capacity(
        model=model, optimizers=optimizers, device="cuda", run_dir=run_dir,
        nvsmi=simulated_nvsmi_20gib_used, disk=ample_disk)
    assert result_clear["sufficient"] is True, (
        "gate must CLEAR at the measured real envelope (~4GiB free VRAM on "
        f"a 24GiB card, ample disk) -- got {result_clear}")
    assert result_clear["vram"]["sufficient"] is True, result_clear["vram"]

    # ---- 2: REFUSES under genuinely low free disk ----
    low_disk = {"total_gib": 500.0, "used_gib": 499.99, "free_gib": 0.01}
    low_disk_refused = False
    try:
        _preflight_fork_capacity(
            model=model, optimizers=optimizers, device="cuda", run_dir=run_dir,
            nvsmi=simulated_nvsmi_20gib_used, disk=low_disk)
    except SystemExit:
        low_disk_refused = True
    assert low_disk_refused, (
        "gate must REFUSE (SystemExit) under genuinely low free disk")

    module = sys.modules[__name__]

    # ---- 3: REFUSES when commit measurement is UNAVAILABLE (read failure) ----
    _orig_read_commit_gib = module._read_commit_gib
    module._read_commit_gib = lambda: None
    commit_none_refused = False
    try:
        try:
            _preflight_fork_capacity(
                model=model, optimizers=optimizers, device="cuda", run_dir=run_dir,
                nvsmi=simulated_nvsmi_20gib_used, disk=ample_disk)
        except SystemExit:
            commit_none_refused = True
    finally:
        module._read_commit_gib = _orig_read_commit_gib
    assert commit_none_refused, (
        "gate must REFUSE when the commit measurement is UNAVAILABLE (read "
        "failure), not silently pass -- this is the exact fail-open the "
        "round-3 post-merge falsifier caught")

    # ---- 4: REFUSES when disk measurement is UNAVAILABLE (read failure) ----
    _orig_read_disk_free_gib = module._read_disk_free_gib
    module._read_disk_free_gib = lambda path: None
    disk_none_refused = False
    try:
        try:
            _preflight_fork_capacity(
                model=model, optimizers=optimizers, device="cuda", run_dir=run_dir,
                nvsmi=simulated_nvsmi_20gib_used)
        except SystemExit:
            disk_none_refused = True
    finally:
        module._read_disk_free_gib = _orig_read_disk_free_gib
    assert disk_none_refused, (
        "gate must REFUSE when the disk measurement is UNAVAILABLE (read "
        "failure), not silently pass")

    # ---- 5: REFUSES when VRAM measurement RAISES (malformed nvsmi) ----
    vram_error_refused = False
    try:
        _preflight_fork_capacity(
            model=model, optimizers=optimizers, device="cuda", run_dir=run_dir,
            nvsmi={"bogus": True}, disk=ample_disk)
    except SystemExit:
        vram_error_refused = True
    assert vram_error_refused, (
        "gate must REFUSE when the VRAM measurement raises an exception, "
        "not record {'error': ...} and silently pass")

    print("ATTRIBUTION_702_FORK_CAPACITY_PREFLIGHT_SELFTEST_PASS "
          f"clear_vram_margin_gib={result_clear['vram']['margin_gib']} "
          f"clear_sufficient={result_clear['sufficient']} "
          f"low_disk_refused={low_disk_refused} "
          f"commit_none_refused={commit_none_refused} "
          f"disk_none_refused={disk_none_refused} "
          f"vram_error_refused={vram_error_refused}", flush=True)


# ---------------------------------------------------------------------------
# #702 2.2B continuation-identity selftests -- clauses 1/2/3/4/5/6 of the
# builder-spec skeleton (comment 4942704748) + data-identity addendum
# (4942713685). Each _verify_rung2_* gate's expected-* value is an
# injectable parameter (same pattern _preflight_fork_capacity's nvsmi/
# commit/disk already use), so these selftests prove the REFUSAL LOGIC
# against small, fast, deterministic fixtures -- never the real 2.2B
# checkpoint, which this CPU-only box cannot build or hold.
# ---------------------------------------------------------------------------

def _selftest_rung2_identity_gate_units() -> None:
    """Unit-level proof of the continuation-identity gates (clauses 3/4/5),
    independent of the full attribution_run() pipeline: each gate is
    exercised on a matching fixture (must NOT raise) and a deliberately
    wrong one (must raise SystemExit) -- the wrong-scale-numel refusal
    shape the #702 erratum's negative fixture requires."""
    import json
    import os
    import tempfile

    import torch

    run_dir = tempfile.mkdtemp(prefix="attribution702_rung2_units_")

    # ---- arch identity: matching small fixture passes, wrong FF width refuses ----
    small_state = {
        "backbone_model.embed_tokens.weight": torch.zeros(16, 8),
        "backbone_model.layers.0.mlp.gate_proj.weight": torch.zeros(24, 8),
        "backbone_model.layers.0.mlp.up_proj.weight": torch.zeros(24, 8),
        "backbone_model.layers.0.mlp.down_proj.weight": torch.zeros(8, 24),
        "head.weight": torch.zeros(16, 8),
    }
    small_dedup = sum(t.numel() for t in small_state.values())  # no shared storage here
    identity_ok = _verify_rung2_arch_identity(
        small_state, run_dir=run_dir,
        expected_dedup_numel=small_dedup, expected_intermediate_size=24)
    assert identity_ok["matches_frozen_rung2_identity"] is True, identity_ok

    arch_refused = False
    try:
        _verify_rung2_arch_identity(
            small_state, run_dir=run_dir,
            expected_dedup_numel=RUNG2_EXPECTED_DEDUP_NUMEL,
            expected_intermediate_size=RUNG2_EXPECTED_INTERMEDIATE_SIZE)
    except SystemExit:
        arch_refused = True
    assert arch_refused, (
        "arch identity gate must REFUSE a wrong-scale checkpoint -- this is "
        "the exact c03/FF4096-vs-FF32768 breach class the erratum caught")

    # a second small fixture at a DIFFERENT FF width, cross-checked against
    # the FIRST fixture's own dedup/FF -- proves the refusal fires on a
    # genuine mismatch between two otherwise-plausible small checkpoints,
    # not only against the (at this CPU scale) unreachable real 2.2B pin.
    other_small_state = {
        "backbone_model.embed_tokens.weight": torch.zeros(16, 8),
        "backbone_model.layers.0.mlp.gate_proj.weight": torch.zeros(40, 8),
        "backbone_model.layers.0.mlp.up_proj.weight": torch.zeros(40, 8),
        "backbone_model.layers.0.mlp.down_proj.weight": torch.zeros(8, 40),
        "head.weight": torch.zeros(16, 8),
    }
    cross_refused = False
    try:
        _verify_rung2_arch_identity(
            other_small_state, run_dir=run_dir,
            expected_dedup_numel=small_dedup, expected_intermediate_size=24)
    except SystemExit:
        cross_refused = True
    assert cross_refused, "arch identity gate must refuse a genuine FF-width mismatch"

    # ---- checkpoint hash identity: matching sidecar passes, tampered pin refuses ----
    ckpt_dir = os.path.join(run_dir, "fake_ckpt")
    os.makedirs(ckpt_dir, exist_ok=True)
    for name, content in (("model.pt", b"MODEL"), ("optimizer.pt", b"OPT"), ("rng.pt", b"RNG")):
        with open(os.path.join(ckpt_dir, name), "wb") as f:
            f.write(content)
    file_hashes = {name: _sha256_bytes_of_file(os.path.join(ckpt_dir, name))
                   for name in ("model.pt", "optimizer.pt", "rng.pt")}
    manifest_path = os.path.join(ckpt_dir, "manifest.json")
    fake_manifest = {"step": 43, "files": file_hashes, "extra": {"total_steps": 5000}}
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(fake_manifest, f)
    expected_hashes = dict(file_hashes)
    expected_hashes["manifest.json"] = _sha256_bytes_of_file(manifest_path)

    hash_ok = _verify_rung2_checkpoint_hashes(
        ckpt_dir, fake_manifest, run_dir=run_dir, expected_hashes=expected_hashes)
    assert hash_ok["mismatches"] == {}, hash_ok

    tampered_expected = dict(expected_hashes)
    tampered_expected["model.pt"] = "0" * 64
    hash_refused = False
    try:
        _verify_rung2_checkpoint_hashes(
            ckpt_dir, fake_manifest, run_dir=run_dir, expected_hashes=tampered_expected)
    except SystemExit:
        hash_refused = True
    assert hash_refused, "checkpoint hash gate must refuse a pin mismatch"

    # ---- shard manifest identity: matching content passes, wrong pin refuses ----
    mmap_manifest_path = os.path.join(run_dir, "shards-v1-stream.manifest.json")
    sidecar = {"combined_manifest_sha256": "c" * 64, "n_tokens": 1000, "n_files": 1}
    with open(mmap_manifest_path, "w", encoding="utf-8") as f:
        json.dump(sidecar, f)
    mmap_file_sha = _sha256_bytes_of_file(mmap_manifest_path)

    shard_ok = _verify_rung2_shard_manifest_identity(
        mmap_manifest_path, run_dir=run_dir,
        expected_manifest_file_sha256=mmap_file_sha,
        expected_combined_source_manifest_sha256="c" * 64)
    assert shard_ok["matches_frozen_pins"] is True, shard_ok

    shard_refused = False
    try:
        _verify_rung2_shard_manifest_identity(
            mmap_manifest_path, run_dir=run_dir,
            expected_manifest_file_sha256=mmap_file_sha,
            expected_combined_source_manifest_sha256="d" * 64)
    except SystemExit:
        shard_refused = True
    assert shard_refused, "shard manifest gate must refuse a combined-sha pin mismatch"

    print("ATTRIB702_IDENTITY_REFUSAL_PASS "
          f"arch_refused={arch_refused} cross_ff_refused={cross_refused} "
          f"hash_refused={hash_refused} shard_manifest_refused={shard_refused}",
          flush=True)


def _selftest_optimizer_restore_refusals() -> None:
    """BLOCKER-5 negative fixtures: proves every NEW fail-closed refusal
    branch in _restore_checkpoint_optimizer_state_in_place actually FIRES
    on a genuinely corrupted bundle (never just that the positive path in
    _selftest_continuation_resume_wiring happens not to trigger them) --
    bundle-key, group-count, param-count, extra-key (clone-avoidance),
    missing-key (zero-value-avoidance), shape, dtype, and
    step-set-singleton, each on a fresh, real (non-tiny-shortcut)
    CPUOffloadOptimizer built the same way attribution_run's own
    continuation branch builds one. value_parity and backing_file byte-
    mutation proofs are validated ONLY by the positive-path selftest
    (proving they do not false-positive on a genuine restore) -- forcing
    either of those two specific refusals would require corrupting a
    tensor strictly BETWEEN copy_() and the check itself, not reachable
    without white-box interference on this function's own control flow;
    disclosed here rather than silently assumed covered."""
    import copy
    import os
    import tempfile

    import torch

    cfg = {
        "model": {"seq": 16, "vocab": 64, "hidden": 32, "layers": 2, "heads": 2,
                  "tied_embeddings": False, "grad_checkpointing": False},
        "objective": {"mtp_aux_heads": {"enabled": True, "n_heads": 2, "weight": 0.3}},
        "optimizer": {"lr_muon": 0.02, "lr_adamw": 3e-4, "weight_decay": 0.1},
        "schedule": {"type": "wsd", "warmup_frac": 0.1, "stable_until_frac": 0.8,
                    "decay_to_lr_frac": 0.1},
        "throughput": {"batch": 2},
    }
    small_intermediate = 48

    def _fresh_optimizers():
        run_dir = tempfile.mkdtemp(prefix="attribution702_restore_negfix_")
        model, _, _, _ = ts.build_v0_model(
            cfg, live=True, tiny_dims=None, intermediate_override=small_intermediate,
            device="cpu")
        optimizers, _, _ = ts.build_split_optimizer(
            model, cfg, offload_optimizer_state=True,
            deviation_dir=os.path.join(run_dir, "deviations"),
            optstate_dir=os.path.join(run_dir, "optstate"))
        return optimizers, run_dir

    def _good_bundle(optimizers):
        bundle = {}
        for name, opt in optimizers.items():
            state = {}
            for i in range(len(opt._shadow)):
                live_entry = opt._inner.state.get(opt._shadow[i], {})
                state[i] = {k: (v.clone() if isinstance(v, torch.Tensor) else v)
                           for k, v in live_entry.items()}
            bundle[name] = {"state": state,
                            "param_groups": copy.deepcopy(opt._inner.param_groups)}
        return bundle

    def _refuses(optimizers, bundle, run_dir) -> bool:
        try:
            _restore_checkpoint_optimizer_state_in_place(optimizers, bundle, run_dir=run_dir)
        except SystemExit:
            return True
        return False

    # ---- refusal: missing top-level optimizer key ----
    optimizers, run_dir = _fresh_optimizers()
    bundle = _good_bundle(optimizers)
    del bundle[next(iter(bundle))]
    bundle_key_refused = _refuses(optimizers, bundle, run_dir)
    assert bundle_key_refused, "must refuse a bundle missing a top-level optimizer key"

    # ---- refusal: param_groups COUNT mismatch ----
    optimizers, run_dir = _fresh_optimizers()
    bundle = _good_bundle(optimizers)
    fname = next(iter(bundle))
    bundle[fname]["param_groups"] = (
        bundle[fname]["param_groups"] + [dict(bundle[fname]["param_groups"][0])])
    group_count_refused = _refuses(optimizers, bundle, run_dir)
    assert group_count_refused, "must refuse a param_groups count mismatch"

    # ---- refusal: state-entry COUNT mismatch ----
    optimizers, run_dir = _fresh_optimizers()
    bundle = _good_bundle(optimizers)
    fname = next(iter(bundle))
    last_idx = max(bundle[fname]["state"])
    del bundle[fname]["state"][last_idx]
    param_count_refused = _refuses(optimizers, bundle, run_dir)
    assert param_count_refused, "must refuse a state-entry count mismatch"

    # ---- refusal: extra saved key with no pre-seeded live destination
    # (the clone-avoidance hole -- previously silently cloned+disclosed,
    # never refused). ----
    optimizers, run_dir = _fresh_optimizers()
    bundle = _good_bundle(optimizers)
    fname = next(iter(bundle))
    idx0 = next(iter(bundle[fname]["state"]))
    bundle[fname]["state"][idx0]["__bogus_extra_key__"] = torch.zeros(3)
    extra_key_refused = _refuses(optimizers, bundle, run_dir)
    assert extra_key_refused, "must refuse an unexpected saved key (would require a clone)"

    # ---- refusal: live key missing from the saved bundle (the
    # zero-value-avoidance hole -- previously left the pre-seeded ZERO
    # tensor in place silently). ----
    optimizers, run_dir = _fresh_optimizers()
    bundle = _good_bundle(optimizers)
    fname = next(iter(bundle))
    idx0 = next(iter(bundle[fname]["state"]))
    some_key = next(iter(bundle[fname]["state"][idx0]))
    del bundle[fname]["state"][idx0][some_key]
    missing_key_refused = _refuses(optimizers, bundle, run_dir)
    assert missing_key_refused, "must refuse a checkpoint missing a live-expected key"

    # ---- refusal: shape mismatch on a matching key ----
    optimizers, run_dir = _fresh_optimizers()
    bundle = _good_bundle(optimizers)
    fname = next(iter(bundle))
    idx0 = next(iter(bundle[fname]["state"]))
    tensor_key = next(k for k, v in bundle[fname]["state"][idx0].items()
                      if isinstance(v, torch.Tensor) and v.dim() > 0)
    bundle[fname]["state"][idx0][tensor_key] = bundle[fname]["state"][idx0][tensor_key][:-1]
    shape_refused = _refuses(optimizers, bundle, run_dir)
    assert shape_refused, "must refuse a shape mismatch"

    # ---- refusal: dtype mismatch on a matching key ----
    optimizers, run_dir = _fresh_optimizers()
    bundle = _good_bundle(optimizers)
    fname = next(iter(bundle))
    idx0 = next(iter(bundle[fname]["state"]))
    tensor_key = next(k for k, v in bundle[fname]["state"][idx0].items()
                      if isinstance(v, torch.Tensor))
    bundle[fname]["state"][idx0][tensor_key] = (
        bundle[fname]["state"][idx0][tensor_key].to(torch.float64))
    dtype_refused = _refuses(optimizers, bundle, run_dir)
    assert dtype_refused, "must refuse a dtype mismatch"

    # ---- refusal: non-singleton AdamW internal step-set ----
    step_set_refused = None
    optimizers, run_dir = _fresh_optimizers()
    bundle = _good_bundle(optimizers)
    if "adamw" in bundle and len(bundle["adamw"]["state"]) >= 2:
        indices = sorted(bundle["adamw"]["state"])
        bundle["adamw"]["state"][indices[0]]["step"] = torch.tensor(1.0)
        bundle["adamw"]["state"][indices[1]]["step"] = torch.tensor(2.0)
        step_set_refused = _refuses(optimizers, bundle, run_dir)
        assert step_set_refused, "must refuse a non-singleton AdamW step-set"

    print("ATTRIB702_OPTIMIZER_RESTORE_REFUSAL_SELFTEST_PASS "
          f"bundle_key_refused={bundle_key_refused} "
          f"group_count_refused={group_count_refused} "
          f"param_count_refused={param_count_refused} "
          f"extra_key_refused={extra_key_refused} "
          f"missing_key_refused={missing_key_refused} "
          f"shape_refused={shape_refused} dtype_refused={dtype_refused} "
          f"step_set_refused={step_set_refused}", flush=True)


def _selftest_continuation_schedule_bind() -> None:
    """Clause 2/6 in isolation, PLUS addendum-4's spec self-correction
    (round-3 accounting repair -- verified against
    _run_counterbalanced_ab_ba's own step boundaries, not just asserted):
    total_steps binds to the checkpoint manifest's OWN original schedule
    denominator, never either measurement-window-derived substitute. The
    frozen pins are 42 = PHYSICAL_STEP_EXECUTIONS (n_warmup + 4*n_active --
    EACH arm runs a profiled n_active sub-block AND an unprofiled n_active
    sub-block, 2 sub-blocks x 2 arms, plus the shared warmup once) and
    22 = UNIQUE_ABSOLUTE_SCHEDULE_STEPS (n_warmup + 2*n_active -- both arms
    traverse the IDENTICAL absolute range [fork_global_step,
    fork_global_step + 2*n_active), just in swapped sub-block order, so the
    distinct schedule POSITIONS touched is warmup+2*n_active). At this
    file's own MIN_WARMUP_STEPS=2/MIN_ACTIVE_STEPS=10 floor: 2+4*10=42 and
    2+2*10=22 exactly -- the frozen literals and the generalized formula
    are the SAME numbers, not two separate scenarios. These are two
    DIFFERENT quantities, not two names for one number -- BOTH must
    independently refuse against a manifest declaring a real, much larger
    schedule, and the receipt now discloses both under their own names
    (attribution_run's "mode" dict), never conflated into one."""
    step866_style_manifest = {
        "step": 43,                          # a small "step866" analog
        "extra": {"total_steps": 5000,       # a small "449651" analog --
                                              # much larger than any
                                              # measurement-window length
                  "segment_id": "selftest-rung2-continuation-fixture"},
    }

    # ---- correct bind: start_step/total_steps derived from the manifest passes ----
    _verify_rung2_schedule_identity(
        step866_style_manifest, start_step=43, total_steps=5000)

    # ---- refusal 1: start=0 (the exact literal negative fixture) ----
    start0_refused = False
    try:
        _verify_rung2_schedule_identity(
            step866_style_manifest, start_step=0, total_steps=5000)
    except SystemExit:
        start0_refused = True
    assert start0_refused, "schedule gate must refuse start_step=0 against a resumed manifest"

    # ---- refusal 2: total_steps=42 -- PHYSICAL_STEP_EXECUTIONS at this
    # file's own MIN_WARMUP_STEPS=2/MIN_ACTIVE_STEPS=10 (2 warmup + 4*10 --
    # each of arm A and arm B runs a profiled AND an unprofiled n_active
    # sub-block). This literal IS the frozen ADDENDUM-4 pin, not a separate
    # historical scenario -- see refusal 4 below, which re-derives the same
    # number from the general formula. ----
    assert MIN_WARMUP_STEPS + 4 * MIN_ACTIVE_STEPS == 42, (
        MIN_WARMUP_STEPS, MIN_ACTIVE_STEPS, "frozen ADDENDUM-4 pin drifted "
        "from this file's own floor constants")
    total42_refused = False
    try:
        _verify_rung2_schedule_identity(
            step866_style_manifest, start_step=43, total_steps=42)
    except SystemExit:
        total42_refused = True
    assert total42_refused, (
        "schedule gate must refuse total_steps=42 (physical_step_executions "
        "at this file's floor constants) against a manifest declaring the "
        "real 5000-step schedule -- this is the exact erratum substitution class")

    # ---- refusal 3: total_steps=22 -- UNIQUE_ABSOLUTE_SCHEDULE_STEPS at the
    # SAME floor constants (2 warmup + 2*10). addendum-4's own correction:
    # this is NOT the same quantity as total_steps=42 above -- both AB/BA
    # arms traverse the IDENTICAL absolute range [fork_global_step,
    # fork_global_step+2*n_active) in swapped sub-block order, so only
    # 2+2*10=22 distinct schedule positions are actually touched -- and
    # BOTH 22 and 42 must independently refuse. ----
    assert MIN_WARMUP_STEPS + 2 * MIN_ACTIVE_STEPS == 22, (
        MIN_WARMUP_STEPS, MIN_ACTIVE_STEPS, "frozen ADDENDUM-4 pin drifted "
        "from this file's own floor constants")
    total22_refused = False
    try:
        _verify_rung2_schedule_identity(
            step866_style_manifest, start_step=43, total_steps=22)
    except SystemExit:
        total22_refused = True
    assert total22_refused, (
        "schedule gate must refuse total_steps=22 "
        "(unique_absolute_schedule_steps at this file's floor constants) "
        "against a manifest declaring the real 5000-step schedule")

    # ---- refusal 4: THIS file's own general formulas at ITS OWN floor
    # constants (MIN_WARMUP_STEPS/MIN_ACTIVE_STEPS) -- proves the refusal
    # logic generalizes past the frozen 42/22 worked example, to whatever
    # n_active a given invocation actually used, for BOTH the physical and
    # the unique formula independently (numerically identical to refusals
    # 2/3 above at THIS file's current floor constants -- that identity is
    # itself the proof the frozen literals and the general formula agree). ----
    physical_at_floor = MIN_WARMUP_STEPS + 4 * MIN_ACTIVE_STEPS
    unique_at_floor = MIN_WARMUP_STEPS + 2 * MIN_ACTIVE_STEPS
    physical_floor_refused = False
    try:
        _verify_rung2_schedule_identity(
            step866_style_manifest, start_step=43, total_steps=physical_at_floor)
    except SystemExit:
        physical_floor_refused = True
    assert physical_floor_refused, (
        "schedule gate must refuse this file's own physical_step_executions "
        f"formula at its floor constants ({physical_at_floor})")

    unique_floor_refused = False
    try:
        _verify_rung2_schedule_identity(
            step866_style_manifest, start_step=43, total_steps=unique_at_floor)
    except SystemExit:
        unique_floor_refused = True
    assert unique_floor_refused, (
        "schedule gate must refuse this file's own "
        f"unique_absolute_schedule_steps formula at its floor constants "
        f"({unique_at_floor})")

    # ---- refusal 5: both wrong at once (start=0 AND total_steps=42) ----
    both_refused = False
    try:
        _verify_rung2_schedule_identity(
            step866_style_manifest, start_step=0, total_steps=42)
    except SystemExit:
        both_refused = True
    assert both_refused

    print("ATTRIB702_SCHEDULE_BIND_PASS "
          f"start0_refused={start0_refused} "
          f"total42_physical_refused={total42_refused} "
          f"total22_unique_refused={total22_refused} "
          f"physical_floor_refused={physical_floor_refused} "
          f"unique_floor_refused={unique_floor_refused} "
          f"both_refused={both_refused}", flush=True)


def _selftest_continuation_resume_wiring() -> None:
    """Full end-to-end proof of the --resume-continuation wiring (clause 1):
    absolute step math, fork step, production ts.load_checkpoint/
    ts.load_optimizers_state/ts.restore_rng call sites, schedule identity
    bound to the manifest's own denominator, and the receipt's continuation
    metadata -- against a genuine (tiny, real-arch) checkpoint written by
    the SAME production ts.run_v0_segment/save_checkpoint path a real
    rung-2 checkpoint is written by (never a hand-built fixture that could
    diverge from what load_checkpoint actually expects). The module-level
    RUNG2_EXPECTED_* pins are monkeypatched (restored in a finally block) to
    this fixture's own genuine small-scale values -- attribution_run()'s own
    identity-gate call sites read the CURRENT global at call time (see the
    comment at those call sites), so this exercises the real wired path,
    not a bypass of it. CPU-only calibration still fails closed (same
    reason as every other selftest in this file) -- this fixture asserts
    the CONTINUATION metadata, not gates_all_passed, which
    _selftest_integration_all_gates_pass() already covers independently."""
    import json
    import os
    import tempfile

    import torch

    cfg = {
        "model": {"seq": 16, "vocab": 64, "hidden": 32, "layers": 2, "heads": 2,
                  "tied_embeddings": False, "grad_checkpointing": False},
        "objective": {"mtp_aux_heads": {"enabled": True, "n_heads": 2, "weight": 0.3}},
        "optimizer": {"lr_muon": 0.02, "lr_adamw": 3e-4, "weight_decay": 0.1},
        "schedule": {"type": "wsd", "warmup_frac": 0.1, "stable_until_frac": 0.8,
                    "decay_to_lr_frac": 0.1},
        "throughput": {"batch": 2},
    }
    small_intermediate = 48
    fixture_total_steps = 5000
    fixture_start_step = 43

    build_dir = tempfile.mkdtemp(prefix="attribution702_rung2_ckptbuild_")
    # ember #702 external falsifier finding (PR #762 comment 4945898324): this
    # call offloads its optimizer state via run_v0_segment, which exposes no
    # optstate_dir parameter of its own -- build_split_optimizer's default
    # (cpu_offload_adamw._DEFAULT_OPTSTATE_DIR, a SHARED, non-unique scratch
    # dir keyed by sanitized param name only) is what it always falls back
    # to. Two concurrent/sequential callers reusing common param names
    # collide with a PermissionError on the shared shadow file -- a selftest
    # whose verdict depends on global mutable state. Exactly the SAME gap
    # _selftest_production_step_parity's Path A already patches around (see
    # that fixture's docstring); applying the identical pattern here:
    # monkeypatch the module global to a fresh per-invocation tempdir for
    # the duration of this call only, restored in finally -- never a change
    # to run_v0_segment's own signature/behavior.
    orig_default_optstate_dir = _coa._DEFAULT_OPTSTATE_DIR
    _coa._DEFAULT_OPTSTATE_DIR = Path(
        tempfile.mkdtemp(prefix="attribution702_rung2_ckptbuild_optstate_"))
    try:
        build_receipt = ts.run_v0_segment(
            build_dir, cfg, n_steps=fixture_start_step, total_steps=fixture_total_steps,
            live=False, real_arch=True, device="cpu",
            intermediate_override=small_intermediate, offload_optimizer_state=True,
            checkpoint_every=fixture_start_step,
            segment_id="rung2-continuation-selftest-fixture", batch_size=2)
    finally:
        _coa._DEFAULT_OPTSTATE_DIR = orig_default_optstate_dir
    ckpt_dir = build_receipt["last_checkpoint"]
    assert ckpt_dir is not None, "fixture checkpoint build must produce a checkpoint"
    manifest = ts.read_manifest(ckpt_dir)
    assert manifest["step"] == fixture_start_step, manifest
    assert manifest["extra"]["total_steps"] == fixture_total_steps, manifest

    shard_dir = os.path.join(build_dir, "shards")
    assert os.path.isdir(shard_dir), shard_dir

    mmap_cache_dir = os.path.join(build_dir, "mmap_cache_fixture")
    n_mtp = cfg["objective"]["mtp_aux_heads"]["n_heads"]
    # Build the mmap cache ONCE via the real production loader constructor
    # (never hand-computed) to get a genuine shards-v1-stream.manifest.json
    # with correct content, then read the two hashes clause 3 pins.
    ts.PackedShardLoader(shard_dir, cfg["model"]["seq"], n_mtp,
                         mmap_cache_dir=mmap_cache_dir)
    mmap_manifest_path = os.path.join(mmap_cache_dir, "shards-v1-stream.manifest.json")
    assert os.path.isfile(mmap_manifest_path), mmap_manifest_path
    with open(mmap_manifest_path, "r", encoding="utf-8") as f:
        mmap_sidecar = json.load(f)
    pinned_combined_sha = mmap_sidecar["combined_manifest_sha256"]
    pinned_manifest_file_sha = _sha256_bytes_of_file(mmap_manifest_path)

    # Checkpoint-hash pins, read fresh off the fixture checkpoint's own
    # (already internally sha-verified by ts.load_checkpoint) manifest --
    # same shape as the real step866-final-addendum pins, sized to this
    # small fixture.
    pinned_checkpoint_hashes = dict(manifest["files"])
    pinned_checkpoint_hashes["manifest.json"] = _sha256_bytes_of_file(
        os.path.join(ckpt_dir, "manifest.json"))

    # Checkpoint-derived arch identity pins, computed the SAME way
    # _rung2_checkpoint_arch_identity does, off the fixture's own model.pt.
    fixture_model_state = torch.load(
        os.path.join(ckpt_dir, "model.pt"), map_location="cpu", weights_only=True)
    fixture_identity = _rung2_checkpoint_arch_identity(fixture_model_state)
    assert fixture_identity["intermediate_size"] == small_intermediate, fixture_identity

    # external-adjudication gate (2) fixture pins: the fixture's OWN true
    # AdamW/Muon param counts (a tiny 2-layer model has nowhere near the
    # frozen 44/140 rung-2 counts) and its OWN checkpoint-internal AdamW
    # step (deterministically ==fixture_start_step -- one opt.step() per
    # macro-step at this cfg's default grad_accum=1, exactly n_steps=
    # fixture_start_step physical steps were taken during the build). Both
    # derived from a disposable probe optimizer built the SAME way
    # attribution_run's own continuation branch builds one -- never
    # hand-computed -- and discarded before the real run.
    probe_model, _, _, _ = ts.build_v0_model(
        cfg, live=True, tiny_dims=None, intermediate_override=small_intermediate,
        device="cpu")
    probe_optimizers, _, _ = ts.build_split_optimizer(
        probe_model, cfg, offload_optimizer_state=True,
        deviation_dir=tempfile.mkdtemp(prefix="attribution702_probe_dev_"),
        optstate_dir=tempfile.mkdtemp(prefix="attribution702_probe_opt_"))
    fixture_n_adamw = len(probe_optimizers["adamw"]._shadow) if "adamw" in probe_optimizers else 0
    fixture_n_muon = len(probe_optimizers["muon"]._shadow) if "muon" in probe_optimizers else 0
    del probe_model, probe_optimizers

    run_dir = tempfile.mkdtemp(prefix="attribution702_rung2_continuation_")

    module = sys.modules[__name__]
    _orig = {
        "RUNG2_EXPECTED_DEDUP_NUMEL": module.RUNG2_EXPECTED_DEDUP_NUMEL,
        "RUNG2_EXPECTED_INTERMEDIATE_SIZE": module.RUNG2_EXPECTED_INTERMEDIATE_SIZE,
        "RUNG2_EXPECTED_COMBINED_SOURCE_MANIFEST_SHA256":
            module.RUNG2_EXPECTED_COMBINED_SOURCE_MANIFEST_SHA256,
        "RUNG2_EXPECTED_MANIFEST_FILE_SHA256": module.RUNG2_EXPECTED_MANIFEST_FILE_SHA256,
        "RUNG2_REFERENCE_CHECKPOINT_HASHES": module.RUNG2_REFERENCE_CHECKPOINT_HASHES,
        "RUNG2_EXPECTED_ADAMW_INTERNAL_STEP": module.RUNG2_EXPECTED_ADAMW_INTERNAL_STEP,
        "REFERENCE_N_ADAMW": module.REFERENCE_N_ADAMW,
        "REFERENCE_N_MUON": module.REFERENCE_N_MUON,
        "_read_commit_gib": module._read_commit_gib,
        "_read_disk_free_gib": module._read_disk_free_gib,
    }
    module.RUNG2_EXPECTED_DEDUP_NUMEL = fixture_identity["dedup_numel"]
    module.RUNG2_EXPECTED_INTERMEDIATE_SIZE = fixture_identity["intermediate_size"]
    module.RUNG2_EXPECTED_COMBINED_SOURCE_MANIFEST_SHA256 = pinned_combined_sha
    module.RUNG2_EXPECTED_MANIFEST_FILE_SHA256 = pinned_manifest_file_sha
    module.RUNG2_REFERENCE_CHECKPOINT_HASHES = pinned_checkpoint_hashes
    module.RUNG2_EXPECTED_ADAMW_INTERNAL_STEP = fixture_start_step
    module.REFERENCE_N_ADAMW = fixture_n_adamw
    module.REFERENCE_N_MUON = fixture_n_muon
    # ADDENDUM-5(B): this positive fixture's verdict must never depend on
    # ambient host tenancy -- the falsifier's executed counterexample
    # (PR #762 comment 4943461501) flipped this same selftest fail<->pass
    # minutes apart because _preflight_checkpoint_load_commit reads the
    # REAL machine's free commit via _read_commit_gib, and an unrelated
    # 5.2GiB process transiently starved it below the gate's floor. Both
    # commit-reading helpers are plain top-level functions (established
    # "optional injected measurement" pattern already used by their own
    # unit tests) -- patched here to fixed, deterministic, SUFFICIENT
    # synthetic dicts for the duration of THIS fixture's attribution_run
    # call only (restored in finally below). A refusal fixture proving the
    # INSUFFICIENT branch still fires lives at _selftest_fork_capacity_
    # preflight (unit-level, injects an insufficient dict directly) --
    # this patch only removes ambient-machine-state as a variable from the
    # POSITIVE continuation path.
    module._read_commit_gib = lambda: {
        "committed_gib": 40.0, "limit_gib": 96.0, "free_gib": 56.0}
    module._read_disk_free_gib = lambda path: {
        "total_gib": 500.0, "used_gib": 100.0, "free_gib": 400.0}
    try:
        # ADDENDUM-5 gates (5)/(7): batch_size is now REQUIRED to equal
        # ATTRIB702_PROD_MICRO_BATCH (1) on the continuation path -- the
        # production-config-parity gate refuses batch_size=2 the way the
        # pre-ADDENDUM-5 fixture used it. grad_accum_steps is left None
        # (auto-derived from cfg["throughput"]["batch"]=2, clamped to the
        # 16-floor -> 16) to exercise the DEFAULT continuation wiring, not
        # an explicit override.
        receipt = attribution_run(
            live=True, cfg=cfg, shard_dir=shard_dir, run_dir=run_dir,
            device="cpu", tiny_dims=None,
            intermediate_override=small_intermediate,
            batch_size=ATTRIB702_PROD_MICRO_BATCH, n_warmup=MIN_WARMUP_STEPS,
            n_active=MIN_ACTIVE_STEPS, ce_chunk_tokens=32,
            resume_continuation=True, grow_checkpoint_dir=ckpt_dir,
            mmap_cache_dir=mmap_cache_dir, mmap_manifest_path=mmap_manifest_path)
    finally:
        for k, v in _orig.items():
            setattr(module, k, v)

    cont = receipt["continuation"]
    assert cont["resume_continuation"] is True
    assert cont["start_step"] == fixture_start_step, cont
    assert cont["fork_global_step"] == fixture_start_step + MIN_WARMUP_STEPS, cont
    assert cont["end_step"] == (
        fixture_start_step + MIN_WARMUP_STEPS + 2 * MIN_ACTIVE_STEPS), cont
    assert cont["total_steps_denominator"] == fixture_total_steps, cont
    assert cont["checkpoint_arch_identity"]["matches_frozen_rung2_identity"] is True, cont
    assert cont["checkpoint_hash_identity"]["mismatches"] == {}, cont
    assert cont["shard_manifest_identity"]["matches_frozen_pins"] is True, cont

    # addendum-2 blocker (b): pre-load commit gate ran and passed.
    assert cont["checkpoint_load_preflight"] is not None, cont
    assert cont["checkpoint_load_preflight"]["sufficient"] is True, cont["checkpoint_load_preflight"]
    assert cont["checkpoint_load_preflight"]["total_load_gib"] > 0, cont["checkpoint_load_preflight"]

    # addendum-2 blocker (a): in-place restore report, both schemas
    # generically -- storage identity preserved for every optimizer this
    # fixture actually built (adamw and/or muon).
    assert cont["optimizer_restore_report"] is not None, cont
    for opt_name, restore_info in cont["optimizer_restore_report"].items():
        assert restore_info["storage_identity_preserved"] is True, (opt_name, restore_info)
    assert "adamw" in cont["optimizer_restore_report"], cont["optimizer_restore_report"]
    adamw_restore = cont["optimizer_restore_report"]["adamw"]
    pre_run_adamw_step = adamw_restore["adamw_internal_step"]
    assert pre_run_adamw_step is not None, adamw_restore
    assert pre_run_adamw_step == fixture_start_step, (pre_run_adamw_step, fixture_start_step)

    # external-adjudication gate (2): both phases ran, both passed (a
    # SystemExit inside attribution_run would already have aborted this
    # selftest before reaching this line -- these assertions additionally
    # prove the receipt DISCLOSES the passing verdict, not just that it
    # didn't crash), and post_warmup's pinned step advanced by exactly
    # n_warmup over post_restore's -- the same never-re-based-onto-global-
    # step proof as the post_run_adamw_internal_step check below, one full
    # AB/BA run earlier.
    assert cont["optimizer_identity_post_restore"] is not None, cont
    assert cont["optimizer_identity_post_restore"]["ok"] is True, cont["optimizer_identity_post_restore"]
    assert cont["optimizer_identity_post_restore"]["expected_adamw_step"] == fixture_start_step, (
        cont["optimizer_identity_post_restore"])
    assert cont["optimizer_identity_post_warmup"] is not None, cont
    assert cont["optimizer_identity_post_warmup"]["ok"] is True, cont["optimizer_identity_post_warmup"]
    assert cont["optimizer_identity_post_warmup"]["expected_adamw_step"] == (
        fixture_start_step + MIN_WARMUP_STEPS), cont["optimizer_identity_post_warmup"]

    # ADDENDUM-5 gates (5)/(7): production-config-parity ran, passed, and
    # threaded the AUTO-DERIVED value (grad_accum_steps was left None at
    # the call site above) -- this cfg's throughput.batch=2 clamps to the
    # 16-floor, so 16 is the correct production expectation even at this
    # tiny scale, never a hand-picked test constant.
    pcp = cont["production_config_parity"]
    assert pcp is not None, cont
    assert pcp["ok"] is True, pcp
    assert pcp["batch_size"] == ATTRIB702_PROD_MICRO_BATCH, pcp
    assert pcp["grad_accum_steps"] == 16 == pcp["expected_grad_accum_steps"], pcp
    assert pcp["qat_enabled"] is False, pcp  # cfg carries no precision.qat block

    # addendum-2/step-136-trap sanity, generalized -- NEVER hardcoded to any
    # specific step VALUE like 136: the live AdamW internal step counter
    # must advance by EXACTLY n_warmup + 2*n_active physical opt.step()
    # calls across the full warmup+AB/BA run (arm A's steps are undone by
    # the fork restore between arms; only the warmup block and arm B's two
    # sequential sub-blocks land on the never-restored-away live state).
    # Proves the restore never silently re-bases the checkpoint's own
    # internal step onto the resume global_step (the 866-vs-136 trap) in
    # either direction -- whatever internal step the checkpoint carried is
    # read back verbatim and advances only by real physical step() calls.
    expected_post_run_step = pre_run_adamw_step + MIN_WARMUP_STEPS + 2 * MIN_ACTIVE_STEPS
    assert cont["post_run_adamw_internal_step"] == expected_post_run_step, (
        cont["post_run_adamw_internal_step"], expected_post_run_step, adamw_restore)

    # addendum-2 blocker (a): immediate del+gc release of the heap-loaded
    # source bundle, with measured before/after-load/after-release commit.
    assert cont["commit_telemetry"] is not None, cont
    assert "recovered_gib" in cont["commit_telemetry"], cont["commit_telemetry"]

    # addendum-4, round-3 accounting repair: physical_step_executions and
    # unique_absolute_schedule_steps are two DISTINCT, separately-named
    # receipt fields, never conflated. physical = warmup + 4*n_active (each
    # of arm A and arm B runs a profiled AND an unprofiled n_active
    # sub-block); unique = warmup + 2*n_active (both arms traverse the
    # IDENTICAL absolute range, swapped sub-block order). At this fixture's
    # MIN_WARMUP_STEPS=2/MIN_ACTIVE_STEPS=10: 42 and 22, the frozen
    # ADDENDUM-4 pins verbatim.
    assert receipt["mode"]["physical_step_executions"] == (
        MIN_WARMUP_STEPS + 4 * MIN_ACTIVE_STEPS) == 42, receipt["mode"]
    assert receipt["mode"]["unique_absolute_schedule_steps"] == (
        MIN_WARMUP_STEPS + 2 * MIN_ACTIVE_STEPS) == 22, receipt["mode"]

    # CPU has no real PCIe path -- pinned_pageable_calibration fails closed
    # here for the SAME reason it does in the base _selftest() (this
    # fixture is not stubbing it, unlike _selftest_integration_all_gates_
    # pass -- proving CONTINUATION metadata correctness is this fixture's
    # job; the overhead/closure/exact_bytes gates' own numerical robustness
    # at a clean-verdict scale is that OTHER fixture's job).
    assert receipt["gates"]["pinned_pageable_calibration"]["passed"] is False
    assert receipt["verdict"] == "INVALID"
    assert "pinned_pageable_calibration" in receipt["failing_gates"]

    # ember #702 FIX C (2026-07-11): this fixture already builds a full
    # receipt through the EXACT SAME construction path attribution_run()
    # uses for a real --live --resume-continuation launch (the checkpoint/
    # manifest sha256 fields included) -- so it is the natural home for the
    # launch-time schema probe. Two receipts were destroyed the same
    # morning by a field-schema violation (missing sha_convention alongside
    # sha256 fields, checked_write's R2 rule) that only surfaced AFTER a
    # 52-minute compute; this makes that class fail HERE, in seconds of
    # CPU, as a standing regression assertion -- not just a caught-after-
    # the-fact incident. --schema-probe (main(), below) runs this exact
    # fixture standalone as a preflight, so the same check gates any
    # --live launch before it starts.
    import receipt_check as _receipt_check_probe
    schema_findings = _receipt_check_probe.validate_receipt(receipt)
    assert schema_findings == [], (
        f"{len(schema_findings)} receipt_check schema finding(s) on a receipt "
        f"built via the real resume_continuation=True path: {schema_findings}"
    )

    print("ATTRIB702_CONTINUATION_RESUME_PASS "
          f"start_step={cont['start_step']} "
          f"fork_global_step={cont['fork_global_step']} "
          f"end_step={cont['end_step']} "
          f"total_steps_denominator={cont['total_steps_denominator']} "
          f"checkpoint_arch_identity_ok="
          f"{cont['checkpoint_arch_identity']['matches_frozen_rung2_identity']} "
          f"checkpoint_hash_identity_ok={cont['checkpoint_hash_identity']['mismatches'] == {}} "
          f"shard_manifest_identity_ok="
          f"{cont['shard_manifest_identity']['matches_frozen_pins']} "
          f"checkpoint_load_preflight_sufficient="
          f"{cont['checkpoint_load_preflight']['sufficient']} "
          f"pre_run_adamw_internal_step={pre_run_adamw_step} "
          f"post_run_adamw_internal_step={cont['post_run_adamw_internal_step']} "
          f"commit_recovered_gib={cont['commit_telemetry']['recovered_gib']} "
          f"physical_step_executions={receipt['mode']['physical_step_executions']} "
          f"unique_absolute_schedule_steps="
          f"{receipt['mode']['unique_absolute_schedule_steps']}", flush=True)


def _selftest_production_config_parity_refusal() -> None:
    """ember #702 ADDENDUM-3D counter fixture, standalone unit-level (no
    checkpoint/model build needed -- _verify_rung2_production_config_parity
    is a pure function of cfg + the caller's actual batch_size/
    grad_accum_steps): batch_size=4, grad_accum_steps=1 (no accumulation)
    against a cfg with throughput.batch=16 REFUSES on both mismatched
    fields. The matching POSITIVE call (batch_size=1, grad_accum_steps=16
    -- this cfg's own production value, computed via
    _production_grad_accum_steps, never hand-picked) PASSES. A third case
    proves the 16-floor clamp: cfg.throughput.batch=2 (< 16) still expects
    grad_accum_steps=16, not 2."""
    import tempfile

    cfg = {"throughput": {"batch": 16}, "precision": {"qat": {"enabled": True}}}
    run_dir = tempfile.mkdtemp(prefix="attribution702_config_parity_selftest_")

    refused = False
    try:
        _verify_rung2_production_config_parity(
            cfg, batch_size=4, grad_accum_steps=1, run_dir=run_dir,
            expected_micro_batch=ATTRIB702_PROD_MICRO_BATCH)
    except SystemExit:
        refused = True
    assert refused, "batch4/no-accum must REFUSE (ADDENDUM-3D counter fixture)"

    ok = _verify_rung2_production_config_parity(
        cfg, batch_size=1, grad_accum_steps=16, run_dir=run_dir,
        expected_micro_batch=ATTRIB702_PROD_MICRO_BATCH)
    assert ok["ok"] is True, ok
    assert ok["qat_enabled"] is True, ok
    assert ok["expected_grad_accum_steps"] == 16, ok

    cfg_small = {"throughput": {"batch": 2}}
    clamp_refused = False
    try:
        _verify_rung2_production_config_parity(
            cfg_small, batch_size=1, grad_accum_steps=2, run_dir=run_dir,
            expected_micro_batch=ATTRIB702_PROD_MICRO_BATCH)
    except SystemExit:
        clamp_refused = True
    assert clamp_refused, "grad_accum_steps=2 must REFUSE against the 16-floor clamp"

    ok_small = _verify_rung2_production_config_parity(
        cfg_small, batch_size=1, grad_accum_steps=16, run_dir=run_dir,
        expected_micro_batch=ATTRIB702_PROD_MICRO_BATCH)
    assert ok_small["ok"] is True, ok_small
    assert ok_small["qat_enabled"] is False, ok_small  # cfg carries no precision.qat block

    print("ATTRIB702_PRODUCTION_CONFIG_PARITY_REFUSAL_SELFTEST_PASS "
          f"batch4_no_accum_refused={refused} positive_pass={ok['ok']} "
          f"floor_clamp_refused={clamp_refused} floor_clamp_pass={ok_small['ok']}",
          flush=True)


def _selftest_production_step_parity() -> None:
    """ember #702 ADDENDUM-5 condition (2) -- the MANDATORY one-step parity
    fixture, and the extraction proof itself (ADDENDUM-5 condition (1)'s
    "pure extraction" claim is only PROVEN here, not merely asserted by the
    git diff being small): ts.run_v0_segment(n_steps=1) end-to-end vs a
    direct ts._run_production_step(...) call against an INDEPENDENTLY
    built model/optimizers/loader produce bit-identical first-step loss,
    model weights, OPTIMIZER STATE, and RNG state (falsifier round 2: a
    model/loss-only compare could pass while the optimizer's own
    exp_avg/exp_avg_sq/momentum_buffer/step diverged -- exactly what a
    resume/continuation actually depends on).

    A freshly-constructed CPUOffloadOptimizer's state is all-zero/step=0
    regardless of RNG (cpu_offload_adamw.py's _memmap_zeros -- no seed
    dependency there); the ONLY source of cross-build nondeterminism is
    the model's weight-init RNG stream, pinned identical via
    torch.manual_seed(SEED) immediately before each independent build.
    Both paths use real_arch=True (never the CPU stand-in _tiny_v0_model,
    whose forward signature differs from the real backbone) and the SAME
    synthetic shard tokens (built once by path A's own run_v0_segment
    call; path B's loader reopens that identical shard_dir). Exercises
    grad_accum_steps=3 (>1, so the micro-batch accumulation loop itself is
    covered, not just the grad_accum_steps=1 degenerate case) and
    qat_enabled=True (so the fake-quant/restore STE lifecycle is proven
    identical too, closing gates 5-7 together).

    Path A isolation (falsifier round 2): run_v0_segment does not expose
    an optstate_dir parameter -- build_split_optimizer's own default
    (cpu_offload_adamw._DEFAULT_OPTSTATE_DIR, a SHARED, non-unique scratch
    dir) is what it always uses. This fixture monkeypatches that module
    global to a fresh per-invocation tempdir for the duration of path A's
    call only (restored in finally) -- an in-process patch of a THIRD
    file's (cpu_offload_adamw.py) runtime default, never a change to
    run_v0_segment's own signature/behavior, so it stays outside the
    extraction-locked file entirely."""
    import os
    import tempfile
    from pathlib import Path as _Path

    import torch

    cfg = {
        "model": {"seq": 16, "vocab": 64, "hidden": 32, "layers": 2, "heads": 2,
                  "tied_embeddings": False, "grad_checkpointing": False},
        "objective": {"mtp_aux_heads": {"enabled": True, "n_heads": 2, "weight": 0.3}},
        "optimizer": {"lr_muon": 0.02, "lr_adamw": 3e-4, "weight_decay": 0.1},
        "schedule": {"type": "wsd", "warmup_frac": 0.1, "stable_until_frac": 0.8,
                    "decay_to_lr_frac": 0.1},
        "throughput": {"batch": 16},
        "precision": {"qat": {"enabled": True}},
    }
    small_intermediate = 48
    SEED = 987654321
    GRAD_ACCUM = 3
    BATCH = 1

    # ---- Path A: run_v0_segment(n_steps=1) end-to-end, ISOLATED optstate ----
    run_dir_a = tempfile.mkdtemp(prefix="attribution702_parity_a_")
    orig_default_optstate_dir = _coa._DEFAULT_OPTSTATE_DIR
    _coa._DEFAULT_OPTSTATE_DIR = _Path(
        tempfile.mkdtemp(prefix="attribution702_parity_optstate_a_"))
    try:
        torch.manual_seed(SEED)
        receipt_a = ts.run_v0_segment(
            run_dir_a, cfg, n_steps=1, total_steps=4, live=False, real_arch=True,
            device="cpu", intermediate_override=small_intermediate,
            offload_optimizer_state=True, checkpoint_every=1,
            segment_id="attrib702-parity-fixture-a", batch_size=BATCH,
            grad_accum_steps=GRAD_ACCUM)
    finally:
        _coa._DEFAULT_OPTSTATE_DIR = orig_default_optstate_dir
    loss_a = receipt_a["loss_first"]
    assert loss_a is not None, receipt_a
    assert receipt_a["components"]["qat"]["enabled"] is True, receipt_a
    ckpt_dir_a = receipt_a["last_checkpoint"]
    assert ckpt_dir_a is not None, receipt_a
    m_state_a, o_state_a, r_state_a, _ = ts.load_checkpoint(ckpt_dir_a)
    hash_a_model = _hash_any(m_state_a)
    hash_a_opt = _hash_any(o_state_a)
    hash_a_rng = _hash_any(r_state_a)

    shard_dir = os.path.join(run_dir_a, "shards")
    assert os.path.isdir(shard_dir), shard_dir

    # ---- Path B: direct _run_production_step call, independently built,
    # ALREADY isolated (explicit optstate_dir passed below) ----
    torch.manual_seed(SEED)
    model_b, vocab_b, hidden_b, n_mtp_b = ts.build_v0_model(
        cfg, live=True, tiny_dims=None, intermediate_override=small_intermediate,
        device="cpu")
    loader_b = ts.PackedShardLoader(
        shard_dir, cfg["model"]["seq"], n_mtp_b,
        mmap_cache_dir=os.path.join(run_dir_a, "mmap_cache_b"))
    optimizers_b, base_lrs_b, _ = ts.build_split_optimizer(
        model_b, cfg, offload_optimizer_state=True,
        deviation_dir=tempfile.mkdtemp(prefix="attribution702_parity_dev_b_"),
        optstate_dir=tempfile.mkdtemp(prefix="attribution702_parity_opt_b_"))
    ce_impl_b, ce_fn_b = ts.resolve_ce_impl(prefer_liger=False)
    mtp_cfg_b = cfg["objective"]["mtp_aux_heads"]

    step_result_b = ts._run_production_step(
        model=model_b, loader=loader_b, optimizers=optimizers_b, base_lrs=base_lrs_b,
        cfg=cfg, ce_fn=ce_fn_b, mtp_enabled=mtp_cfg_b["enabled"],
        mtp_weight=mtp_cfg_b["weight"], ce_chunk_tokens=32, device="cpu",
        batch_size=BATCH, global_step=0, total_steps=4,
        grad_accum_steps=GRAD_ACCUM, qat_enabled=True)
    loss_b = round(step_result_b["loss"], 6)
    hash_b_model = _hash_any(model_b.state_dict())
    hash_b_opt = _hash_any(ts.save_optimizers_state(optimizers_b))
    hash_b_rng = _hash_any(ts.capture_rng())

    assert loss_a == loss_b, (loss_a, loss_b)
    assert hash_a_model == hash_b_model, (
        "post-step MODEL WEIGHTS diverged between the two call paths")
    assert hash_a_opt == hash_b_opt, (
        "post-step OPTIMIZER STATE (exp_avg/exp_avg_sq/momentum_buffer/step) "
        "diverged between the two call paths")
    assert hash_a_rng == hash_b_rng, (
        "post-step RNG STATE diverged between the two call paths")

    print("ATTRIB702_PRODUCTION_STEP_PARITY_SELFTEST_PASS "
          f"loss_a={loss_a} loss_b={loss_b} "
          f"model_hash_match={hash_a_model == hash_b_model} "
          f"opt_hash_match={hash_a_opt == hash_b_opt} "
          f"rng_hash_match={hash_a_rng == hash_b_rng} "
          f"grad_accum_steps={GRAD_ACCUM} qat_enabled=True", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true",
                    help="Run the CPU-only selftest (tiny fixture dims, < 30s, no GPU)")
    ap.add_argument("--schema-probe", action="store_true",
                    help="ember #702 FIX C (2026-07-11): build a receipt "
                         "through the SAME construction path as a real "
                         "--live --resume-continuation launch (tiny "
                         "synthetic checkpoint, seconds of CPU, no GPU/"
                         "shard-dir/network needed), then validate it via "
                         "receipt_check.validate_receipt. Prints "
                         "ATTRIBUTION_702_SCHEMA_PROBE_PASS and exits 0 on "
                         "no findings; prints "
                         "ATTRIBUTION_702_SCHEMA_PROBE_REFUSED with the "
                         "findings and exits 3 otherwise. Run this before "
                         "every --live --resume-continuation launch -- it "
                         "is the preflight that would have caught the "
                         "missing-sha_convention class before a 52-minute "
                         "compute instead of after it.")
    ap.add_argument("--live", action="store_true",
                    help="Real 2.2B-arch CUDA dispatch. Requires EMBER_GATE_AUTHORIZED=1 "
                         "and --shard-dir. Refused otherwise.")
    ap.add_argument("--shard-dir", default=None, help="real packed uint16 corpus shard dir")
    ap.add_argument("--out-dir", default=None, help="run/scratch dir (defaults to a tempdir)")
    ap.add_argument("--receipt-dir", default=str(_REPO / "receipts"))
    ap.add_argument("--n-warmup", type=int, default=MIN_WARMUP_STEPS)
    ap.add_argument("--n-active", type=int, default=MIN_ACTIVE_STEPS)
    ap.add_argument("--device", default="cuda")
    # ember #702 2.2B rerun (erratum 4942686121 fix): --intermediate-override
    # was accepted by attribution_run() but NEVER threaded through from
    # main() -- every --live dispatch silently built the c03 FF4096 model
    # regardless of this flag. Now wired straight through.
    ap.add_argument("--intermediate-override", type=int, default=None,
                    help="FF width for the LlamaConfig (e.g. 32768 for the "
                         "frozen rung-2 arch). None preserves the c03 "
                         "FF4096 default -- the erratum's silent scale "
                         "substitution is only possible by OMITTING this "
                         "flag, never by passing it wrong at the frozen "
                         "value, since --resume-continuation's identity "
                         "gates refuse a mismatch either way.")
    ap.add_argument("--resume-continuation", action="store_true",
                    help="ember #702 2.2B rerun (clauses 1-6): load model/"
                         "optimizer/RNG from --grow-checkpoint-dir through "
                         "the production load_checkpoint/load_optimizers_"
                         "state/restore_rng paths, bind total_steps to the "
                         "checkpoint's own schedule denominator, bind the "
                         "loader to the pinned shard/mmap source, and "
                         "REFUSE before any compute on an architecture/"
                         "checkpoint-hash/shard-manifest/schedule identity "
                         "mismatch. Requires --grow-checkpoint-dir, "
                         "--shard-dir, --mmap-cache-dir, "
                         "--mmap-manifest-path.")
    ap.add_argument("--grow-checkpoint-dir", default=None,
                    help="rung-2 stabilize checkpoint dir to resume from "
                         "(e.g. .../block-10/checkpoints/step-00000866)")
    ap.add_argument("--mmap-cache-dir", default=None,
                    help="custody mmap_cache dir for the continuation's "
                         "shard stream (e.g. .../block-10/mmap_cache)")
    ap.add_argument("--mmap-manifest-path", default=None,
                    help="custody shards-v1-stream.manifest.json path "
                         "(clause 3 data-identity binding)")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    if args.schema_probe:
        # ember #702 FIX C: reuse _selftest_continuation_resume_wiring()
        # unchanged -- it already builds a receipt through the real
        # resume_continuation=True construction path and (as of this same
        # fix) already asserts receipt_check.validate_receipt(receipt) ==
        # [] internally. Running it standalone as a flag, not only inside
        # --selftest, is what makes it a wireable PREFLIGHT step: a launch
        # script can call `python cbase_grow_rung2_attribution_702.py
        # --schema-probe` and gate on the exit code before ever touching
        # --live.
        try:
            _selftest_continuation_resume_wiring()
        except AssertionError as e:
            print(f"ATTRIBUTION_702_SCHEMA_PROBE_REFUSED: {e}", flush=True)
            return 3
        except Exception as e:
            print(f"ATTRIBUTION_702_SCHEMA_PROBE_REFUSED (unexpected "
                  f"{type(e).__name__}): {e}", flush=True)
            return 3
        print("ATTRIBUTION_702_SCHEMA_PROBE_PASS", flush=True)
        return 0

    import os
    import tempfile
    if args.live:
        if os.environ.get("EMBER_GATE_AUTHORIZED") != "1":
            print("ATTRIBUTION_702_REFUSED: --live requires EMBER_GATE_AUTHORIZED=1 "
                  "(same interlock convention as every other live-dispatch entrypoint "
                  "in this tree). No GPU run launched.", flush=True)
            return 3
        if not args.shard_dir:
            print("ATTRIBUTION_702_REFUSED: --live requires --shard-dir "
                  "(no synthetic tokens on the live path).", flush=True)
            return 3
        if args.n_warmup < MIN_WARMUP_STEPS or args.n_active < MIN_ACTIVE_STEPS:
            print(f"ATTRIBUTION_702_REFUSED: --n-warmup>={MIN_WARMUP_STEPS} and "
                  f"--n-active>={MIN_ACTIVE_STEPS} are validity-gate floors, not "
                  "tunable below them.", flush=True)
            return 3
    if args.resume_continuation:
        missing = [name for name, val in (
            ("--grow-checkpoint-dir", args.grow_checkpoint_dir),
            ("--mmap-cache-dir", args.mmap_cache_dir),
            ("--mmap-manifest-path", args.mmap_manifest_path),
        ) if not val]
        if missing:
            print(f"ATTRIBUTION_702_REFUSED: --resume-continuation requires "
                  f"{', '.join(missing)}.", flush=True)
            return 3

    cfg = ts.load_contract()
    run_dir = args.out_dir or tempfile.mkdtemp(prefix="attribution702_")
    Path(args.receipt_dir).mkdir(parents=True, exist_ok=True)

    receipt = attribution_run(
        live=args.live, cfg=cfg, shard_dir=args.shard_dir, run_dir=run_dir,
        device=args.device if args.live else "cpu",
        tiny_dims=None if args.live else {"vocab": 64, "hidden": 32, "depth": 2, "seq": 16},
        intermediate_override=args.intermediate_override,
        n_warmup=args.n_warmup, n_active=args.n_active,
        resume_continuation=args.resume_continuation,
        grow_checkpoint_dir=args.grow_checkpoint_dir,
        mmap_cache_dir=args.mmap_cache_dir,
        mmap_manifest_path=args.mmap_manifest_path)

    from receipt_write import checked_write
    receipt_path = Path(args.receipt_dir) / f"attribution-702-{receipt['ts']}.json"
    checked_write(str(receipt_path), receipt)
    print(f"ATTRIBUTION_702_DONE receipt={receipt_path} verdict={receipt['verdict']} "
          f"gates_all_passed={receipt['gates_all_passed']} "
          f"failing_gates={receipt['failing_gates']}", flush=True)
    return 0 if receipt["gates_all_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
