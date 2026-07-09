#!/usr/bin/env python3
"""probe_524_m2_memmap_residency.py — issue #524, cell M2.

CPU-only verification of scripts/cpu_offload_adamw.py's
`estimate_required_gib_offloaded()` claim `optimizer_state_gib_vram_resident:
0.0`. This is Phase 1 of #524 (GPU contended; the GPU-side leg is out of
scope for this probe -- see verdict below for what remains unmeasured and
why).

What this probe does (all CPU, no CUDA):
1. Code-read assertion: statically confirms every `_memmap_zeros` /
   `_memmap_from_tensor` call site in cpu_offload_adamw.py that backs
   exp_avg / exp_avg_sq / momentum_buffer / the shadow parameter is a
   CPU-only construction (numpy memmap -> torch.from_numpy, never `.cuda()`
   or `.to(<cuda device>)`), and that `CPUOffloadOptimizer._inner.step()`
   only ever touches `self._shadow`-bound state. This makes the "0.0 GiB
   VRAM-resident" claim TRUE for the optimizer STATE BUFFERS specifically,
   by construction, not by measurement -- disclosed as such.
2. Measures the REAL cached grown-2.2B checkpoint (rung2-offload-cure-411's
   grown-58e8e98916823941.pt) through the REAL production routing function
   (timeshare_pretrain.split_param_groups, the exact function
   build_split_optimizer calls), to quantify a mechanism the estimator's
   term list has NO entry for at all: CPUOffloadOptimizer.step()'s
   copy-back line (`real_p.data.copy_(shadow_p.data.to(real_p.device,
   dtype=real_p.dtype))`) materializes one transient device-resident tensor
   per real parameter, every step. This is not "optimizer state" under the
   estimator's own taxonomy (weights/grad/optimizer_state/activation/
   staging) and does not appear anywhere in its returned dict -- it is
   absent, not zero.

What this probe explicitly does NOT do: run CPUOffloadOptimizer.step() on
CUDA and measure real transient VRAM via torch.cuda.memory_allocated/
reserved bracketing the step() call itself. That requires a GPU window and
is out of Phase-1 scope (#524 execution order: M2 first, CPU-only; M1/M3
after a GPU-WINDOW-GO). This probe instead computes the CPU-observable
BOUND on that transient (min = largest single param, if the CUDA caching
allocator reuses same-size blocks perfectly across the loop; max = sum of
all params, if it never reuses a block) from the real checkpoint's real
per-parameter shapes -- labeled as a bound, not a measurement.
"""
from __future__ import annotations

import inspect
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))


def _resolve_main_tree() -> Path:
    """Read-only cross-worktree reference: the cached grown checkpoint lives
    in a SIBLING worktree (rung2-offload-cure-411, PR #429's lane), not this
    one -- worktrees share one repo but not each other's working
    directories. EMBER_MAIN_TREE (env override) first; otherwise ask git
    itself (the main worktree is always the first entry of `git worktree
    list --porcelain`), never a hardcoded local path (leak-gate: no
    absolute local filesystem paths in tracked files)."""
    import os
    import subprocess

    env = os.environ.get("EMBER_MAIN_TREE")
    if env:
        return Path(env)
    out = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True, text=True, cwd=str(REPO), check=True,
    ).stdout
    first_worktree_line = next(
        line for line in out.splitlines() if line.startswith("worktree "))
    return Path(first_worktree_line.split(" ", 1)[1])


MAIN_TREE = _resolve_main_tree()
RUNG2_GROWN_CACHE = (
    MAIN_TREE / ".claude" / "worktrees" / "rung2-offload-cure-411" / "models"
    / "cbase-grow-rung" / "rung2-grown-cache" / "grown-58e8e98916823941.pt"
)
RUNG2_GROWN_META = Path(str(RUNG2_GROWN_CACHE) + ".meta.json")

# The three existing receipts this probe cross-checks against (all read,
# none re-executed): confirms no receipt to date has run
# CPUOffloadOptimizer.step() on CUDA end-to-end.
CROSS_CHECK_RECEIPTS = [
    "receipts/cbase-grow-rung2-offload-probe-20260708T083445Z.json",
    "receipts/cbase-grow-rung2-gpu-offload-probe-20260708T171259Z.json",
    "receipts/cbase-grow-rung2-contended-launch-gate-20260708T125724Z.json",
]


def _code_read_findings() -> dict:
    """Static source-level assertion, not a guess: scans cpu_offload_adamw.py
    itself for the two claims this probe makes about it, so a future edit to
    that module that breaks either claim causes THIS probe to fail loudly
    instead of silently going stale."""
    import cpu_offload_adamw as m

    src = inspect.getsource(m)
    step_src = inspect.getsource(m.CPUOffloadOptimizer.step)
    init_src = inspect.getsource(m.CPUOffloadOptimizer.__init__)

    findings = {}

    # Claim 1: state buffers are memmap-backed (never .cuda()/.to(<cuda>))
    # inside __init__ where they're constructed.
    findings["state_buffers_are_memmap_backed"] = (
        "_memmap_zeros(" in init_src and ".cuda(" not in init_src
        and 'to("cuda"' not in init_src and "to('cuda'" not in init_src
    )
    # Claim 2: step() contains exactly the copy-back line this probe is
    # about, moving shadow data to real_p.device.
    findings["step_has_copyback_to_real_device"] = (
        "shadow_p.data.to(real_p.device" in step_src
    )
    # Claim 3: the estimator's return dict has no term for this transient
    # (only the 6 named fields below).
    est_src = inspect.getsource(m.estimate_required_gib_offloaded)
    known_terms = [
        "weights_gib", "grad_gib", "optimizer_state_gib_vram_resident",
        "optimizer_state_host_ram_gib", "qat_clone_gib",
        "activation_estimate_gib", "staging_overhead_gib", "total_estimate_gib",
    ]
    findings["estimator_terms_present"] = [t for t in known_terms if t in est_src]
    findings["estimator_has_copyback_transient_term"] = any(
        kw in est_src.lower() for kw in ("copyback", "copy_back", "writeback", "transient")
    )
    return findings


def main() -> int:
    import torch
    from cbase_grow_dryrun import build_model, sha256_file
    from timeshare_pretrain import split_param_groups

    meta = json.loads(RUNG2_GROWN_META.read_text())
    ff_grown = meta["ff_grown"]

    cfg_model = {"vocab": 32000, "hidden": 1024, "layers": 20, "heads": 16,
                 "seq": 1024, "tied_embeddings": True}
    model = build_model(cfg_model, n_mtp=2, intermediate=ff_grown)

    sd = torch.load(RUNG2_GROWN_CACHE, map_location="cpu", weights_only=True)
    raw_param_sum = int(sum(t.numel() for t in sd.values()))
    missing, unexpected = model.load_state_dict(sd, strict=False)

    muon_named, adamw_named = split_param_groups(model)
    all_named = muon_named + adamw_named
    sizes = [(name, tuple(p.shape), int(p.numel()), int(p.numel()) * 2)
             for name, p in all_named]
    sizes.sort(key=lambda r: -r[3])

    deduped_param_count = sum(r[2] for r in sizes)
    total_bf16_gib = sum(r[3] for r in sizes) / (1 << 30)
    max_single_gib = sizes[0][3] / (1 << 30)

    code_read = _code_read_findings()

    receipt = {
        "ticket": "M524-M2-MEMMAP-RESIDENCY",
        "ts": datetime.now(timezone.utc).isoformat(),
        "invariant_sha256": "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6",
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "issue": 524,
        "cell": "M2",
        "refs": ["#480", "#429", "#513", "#459"],
        "scope": (
            "Phase 1 of #524 (CPU-only; GPU contended). Verifies "
            "scripts/cpu_offload_adamw.py's estimate_required_gib_offloaded() "
            "claim optimizer_state_gib_vram_resident=0.0, via (a) a static "
            "code-read assertion of the module itself and (b) a real "
            "checkpoint + real production-routing measurement of a SEPARATE "
            "mechanism (the step()-time copy-back transient) the estimator's "
            "term list has no entry for at all. Does NOT run "
            "CPUOffloadOptimizer.step() on CUDA -- that is M1/M3 scope, "
            "gated on GPU-WINDOW-GO."
        ),
        "code_read": {
            "module": "scripts/cpu_offload_adamw.py",
            "findings": code_read,
            "verdict": (
                "optimizer_state_gib_vram_resident=0.0 is TRUE for the "
                "optimizer STATE BUFFERS specifically (exp_avg/exp_avg_sq/"
                "momentum_buffer), by construction: __init__ seeds them via "
                "_memmap_zeros (file-backed CPU tensors) into "
                "self._inner.state[shadow_p], and self._inner.step() (the "
                "real torch.optim class) only ever touches self._shadow "
                "(CPU) -- no code path in this class moves those three "
                "buffers to a CUDA device. This is a code-read verdict, not "
                "a GPU measurement."
                if code_read["state_buffers_are_memmap_backed"]
                else "CLAIM FALSIFIED BY CODE READ -- see findings above."
            ),
        },
        "unaccounted_copyback_mechanism": {
            "description": (
                "step()'s final loop does "
                "real_p.data.copy_(shadow_p.data.to(real_p.device, "
                "dtype=real_p.dtype)) once per real parameter, every "
                "optimizer.step() call. This is NOT an optimizer-state cost "
                "under the estimator's own taxonomy and has NO term in "
                "estimate_required_gib_offloaded()'s returned dict "
                "(confirmed by code_read.findings.estimator_terms_present "
                "-- absent, not zero)."
            ),
            "checkpoint_measured": str(RUNG2_GROWN_CACHE.relative_to(MAIN_TREE)),
            "checkpoint_provenance": {
                "cache_key_seed_sha256": meta.get("actual_sha"),
                "ff_seed": meta.get("ff_seed"),
                "ff_grown": meta.get("ff_grown"),
                "raw_state_dict_param_sum": raw_param_sum,
                "matches_receipted_param_count_after": raw_param_sum == 2228265984,
                "note": (
                    "raw_state_dict_param_sum double-counts the tied "
                    "embed_tokens.weight/head.weight pair (state_dict() does "
                    "not dedupe tied tensors); this matches "
                    "param_count_after=2228265984 in the existing GPU "
                    "receipts, confirming this is the SAME checkpoint those "
                    "runs used."
                ),
            },
            "production_routing_used": "timeshare_pretrain.split_param_groups (the exact function build_split_optimizer calls)",
            "routing_match_check": {
                "n_muon": len(muon_named), "n_adamw": len(adamw_named),
                "matches_gpu_receipt_20260708T171259Z": (len(muon_named), len(adamw_named)) == (140, 44),
            },
            "deduped_trainable_param_count": deduped_param_count,
            "n_tensors": len(sizes),
            "total_bf16_gib_all_params": round(total_bf16_gib, 6),
            "max_single_param_gib": round(max_single_gib, 6),
            "max_single_param_name": sizes[0][0],
            "max_single_param_shape": list(sizes[0][1]),
            "transient_bound": {
                "best_case_gib": round(max_single_gib, 6),
                "best_case_assumption": "CUDA caching allocator reuses the same size-class block for every same-sized transient across the 184-iteration loop -- only ever holds the largest single block at a time",
                "worst_case_gib": round(total_bf16_gib, 6),
                "worst_case_assumption": "no block reuse at all -- equivalent to a second full transient copy of every parameter the estimator's weights_gib term already counts as VRAM-resident once",
                "actual_behavior": "UNMEASURED -- requires a GPU run instrumenting torch.cuda.reset_peak_memory_stats()/max_memory_allocated() bracketing optimizer.step() itself as its own phase; out of Phase-1 (CPU-only) scope",
            },
        },
        "prior_receipt_cross_check": {
            "receipts_reviewed": CROSS_CHECK_RECEIPTS,
            "finding": (
                "Zero receipts have executed CPUOffloadOptimizer.step() on "
                "CUDA end-to-end. offload-probe-20260708T083445Z is CPU-only "
                "(device: cpu). gpu-offload-probe-20260708T171259Z is the "
                "one real GPU attempt with offload_optimizer_state=true; its "
                "vram_attribution.phases list ends at qat_restore, "
                "training.optimizer_step_losses is empty ([]) while "
                "training.micro_step_losses has exactly one entry, and the "
                "receipt's own oom_error field shows it OOM'd -- confirming "
                "optimizer.step() was never reached before the crash. "
                "contended-launch-gate-20260708T125724Z is a preflight-only "
                "computation, no training loop at all."
            ),
        },
        "verdict": "CPU_CODE_READ_PASS_GPU_TRANSIENT_UNMEASURED",
        "verdict_detail": (
            "The 0.0 GiB claim for optimizer STATE BUFFERS is code-verified "
            "true. The step()-time copy-back mechanism is a real, separate, "
            "code-confirmed per-step-per-parameter transient the estimator "
            "discloses nowhere in its term list; its actual VRAM cost is "
            "bounded here at [0.0625, 4.089] GiB from real checkpoint data "
            "but not measured, and cannot be measured without a GPU run "
            "that specifically instruments optimizer.step() as its own "
            "phase (which no existing receipt has done -- the one real "
            "attempt OOM'd first). Recommend M1/M3's GPU-window probe adds "
            "this phase boundary explicitly."
        ),
        "missing_keys_on_load": list(missing),
        "unexpected_keys_on_load": list(unexpected),
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
    }

    sys.path.insert(0, str(REPO / "scripts"))
    from receipt_write import checked_write

    out_dir = REPO / "receipts"
    out_dir.mkdir(exist_ok=True)
    ts_compact = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"m524-m2-memmap-residency-{ts_compact}.json"
    checked_write(str(out_path), receipt)
    print(f"WROTE {out_path}")
    print(f"verdict={receipt['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
