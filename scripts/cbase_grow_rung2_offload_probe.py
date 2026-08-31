#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cbase_grow_rung2_offload_probe.py — CPU-verifiable equivalence probes for
the DEV-002 cure (CPU-offloaded optimizer states + micro-batch/grad
accumulation). Companion to scripts/cbase_grow_rung2_dryrun.py; does NOT run
the measured production-scale dry-run itself (that needs the coordinated
serving-pause GPU window — explicitly out of THIS lane's scope per the cure
PR spec; the follow-up push adds those receipts before merge-gate).

Two probes, both CPU-only (no GPU touched, no nvidia-smi call):

  PROBE 1 — update-rule bitwise equivalence (spec build item 1).
    Reference: a real torch.optim.AdamW instance stepping directly on a CPU
    fp32 parameter (standing in for "the current in-VRAM optimizer code path
    executed on CPU tensors", since no GPU access is available in this lane —
    disclosed per the cure PR spec's own fallback instruction).
    Cure: cpu_offload_adamw.CPUOffloadOptimizer wrapping the SAME real
    torch.optim.AdamW class around a shadow copy of the same initial
    parameter, fed the SAME grad.
    Assert: max abs diff between the two post-step parameter tensors
    <= 1e-7 (fp32).

  PROBE 2 — grad-accumulation loss-equivalence (spec build item 2).
    A tiny REAL-architecture model (build_model from cbase_grow_dryrun.py,
    the harness's own CPU float32 twin of the c03 LlamaModel backbone — same
    module names, tiny dims for CPU tractability) is forward-passed on a
    FIXED, seeded 16-sample token batch two ways:
      monolithic  — one forward+backward on all 16 samples, CE loss
                    (reduction='mean').
      accumulated — 8 micro-batches of 2 samples each (the SAME 16 samples,
                    contiguous slices), each backward-scaled by 1/8; the
                    reported "accumulated loss" is the mean of the 8
                    per-micro-batch losses (mean-of-equal-size-chunk-means ==
                    overall mean for a reduction='mean' loss — the identity
                    DEV-002 candidate 2 relies on).
    Reports |loss_monolithic - loss_accumulated| (expected: fp-noise scale,
    not exactly 0.0 -- summation order differs between one CE over 16 rows
    and eight CEs over 2 rows each).
    Also reports (bonus, not required by the spec bullet but strengthens the
    same claim): max abs diff between the monolithic gradient and the SUM of
    the 8 scaled micro-batch gradients on the model's head weight — the
    accumulation identity at the gradient level, not just the scalar loss.

No git commits from this script. No founder/user names. api_spend_usd=0,
paid_api_surface_used=false (C(-1) lesson, same convention as
cbase_grow_rung2_dryrun.py).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cpu_offload_adamw import CPUOffloadOptimizer            # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/cbase_grow_dryrun.py
import importlib.util as _ember_e083c5df74f39043_importlib
import sys as _ember_e083c5df74f39043_sys
from pathlib import Path as _ember_e083c5df74f39043_Path
_ember_e083c5df74f39043_path = _ember_e083c5df74f39043_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'cbase_grow_dryrun.py')
if not _ember_e083c5df74f39043_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/cbase_grow_dryrun.py')
_ember_e083c5df74f39043_aliases = ('_ember_issue2015_e083c5df74f39043', 'cbase_grow_dryrun', 'scripts.cbase_grow_dryrun')
_ember_e083c5df74f39043_existing = []
for _ember_e083c5df74f39043_alias in _ember_e083c5df74f39043_aliases:
    _ember_e083c5df74f39043_candidate = _ember_e083c5df74f39043_sys.modules.get(_ember_e083c5df74f39043_alias)
    if _ember_e083c5df74f39043_candidate is not None and all(_ember_e083c5df74f39043_candidate is not item for item in _ember_e083c5df74f39043_existing):
        _ember_e083c5df74f39043_existing.append(_ember_e083c5df74f39043_candidate)
if len(_ember_e083c5df74f39043_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/cbase_grow_dryrun.py')
if _ember_e083c5df74f39043_existing:
    _ember_e083c5df74f39043_module = _ember_e083c5df74f39043_existing[0]
    _ember_e083c5df74f39043_observed = getattr(_ember_e083c5df74f39043_module, '__file__', None)
    if _ember_e083c5df74f39043_observed is None or _ember_e083c5df74f39043_Path(_ember_e083c5df74f39043_observed).resolve() != _ember_e083c5df74f39043_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/cbase_grow_dryrun.py')
else:
    _ember_e083c5df74f39043_spec = _ember_e083c5df74f39043_importlib.spec_from_file_location('_ember_issue2015_e083c5df74f39043', _ember_e083c5df74f39043_path)
    if _ember_e083c5df74f39043_spec is None or _ember_e083c5df74f39043_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/cbase_grow_dryrun.py')
    _ember_e083c5df74f39043_module = _ember_e083c5df74f39043_importlib.module_from_spec(_ember_e083c5df74f39043_spec)
    for _ember_e083c5df74f39043_alias in _ember_e083c5df74f39043_aliases:
        _ember_e083c5df74f39043_prior = _ember_e083c5df74f39043_sys.modules.get(_ember_e083c5df74f39043_alias)
        if _ember_e083c5df74f39043_prior is not None and _ember_e083c5df74f39043_prior is not _ember_e083c5df74f39043_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/cbase_grow_dryrun.py')
        _ember_e083c5df74f39043_sys.modules[_ember_e083c5df74f39043_alias] = _ember_e083c5df74f39043_module
    try:
        _ember_e083c5df74f39043_spec.loader.exec_module(_ember_e083c5df74f39043_module)
    except BaseException:
        for _ember_e083c5df74f39043_alias in _ember_e083c5df74f39043_aliases:
            if _ember_e083c5df74f39043_sys.modules.get(_ember_e083c5df74f39043_alias) is _ember_e083c5df74f39043_module:
                _ember_e083c5df74f39043_sys.modules.pop(_ember_e083c5df74f39043_alias, None)
        raise
for _ember_e083c5df74f39043_alias in _ember_e083c5df74f39043_aliases:
    _ember_e083c5df74f39043_prior = _ember_e083c5df74f39043_sys.modules.get(_ember_e083c5df74f39043_alias)
    if _ember_e083c5df74f39043_prior is not None and _ember_e083c5df74f39043_prior is not _ember_e083c5df74f39043_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/cbase_grow_dryrun.py')
    _ember_e083c5df74f39043_sys.modules[_ember_e083c5df74f39043_alias] = _ember_e083c5df74f39043_module
build_model = getattr(_ember_e083c5df74f39043_module, 'build_model')
# issue2015 exact-local-import-end:src/ember/governance/scripts/cbase_grow_dryrun.py                    # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
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
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py                       # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RECEIPT_DIR = REPO / "receipts"
INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"

LR_ADAMW = 3e-4          # configs/v0-pretrain-config.json optimizer.lr_adamw
WEIGHT_DECAY = 0.1       # configs/v0-pretrain-config.json optimizer.weight_decay
UPDATE_RULE_ATOL = 1e-7  # cure PR spec build item 1


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def probe_update_rule_equivalence() -> dict:
    """PROBE 1: bitwise update-rule equivalence, one step, a small param slice."""
    import torch

    torch.manual_seed(1234)
    p_init = torch.randn(8, 8, dtype=torch.float32)
    grad = torch.randn(8, 8, dtype=torch.float32)

    p_ref = p_init.clone().requires_grad_(True)
    opt_ref = torch.optim.AdamW([p_ref], lr=LR_ADAMW, weight_decay=WEIGHT_DECAY)
    p_ref.grad = grad.clone()
    opt_ref.step()

    p_cure = p_init.clone().requires_grad_(True)
    opt_cure = CPUOffloadOptimizer(
        [("probe_param", p_cure)],
        lambda ps: torch.optim.AdamW(ps, lr=LR_ADAMW, weight_decay=WEIGHT_DECAY),
        pin_memory=False,  # no CUDA context in this lane; plain CPU tensors
    )
    p_cure.grad = grad.clone()
    opt_cure.step()

    max_abs_diff = float((p_ref.detach() - p_cure.detach()).abs().max())
    passed = max_abs_diff <= UPDATE_RULE_ATOL
    return {
        "mechanism": ("reference = torch.optim.AdamW stepping directly on a CPU fp32 "
                      "parameter (standing in for the current in-VRAM optimizer code "
                      "path executed on CPU tensors, per the cure PR spec's disclosed "
                      "no-GPU-access fallback); cure = cpu_offload_adamw.CPUOffloadOptimizer "
                      "wrapping the SAME torch.optim.AdamW class around a shadow copy of "
                      "the identical initial parameter, fed the identical grad tensor -- "
                      "the wrapper never reimplements AdamW's math, it only relocates "
                      "where the real class's state lives and steps"),
        "param_shape": [8, 8],
        "lr_adamw": LR_ADAMW,
        "weight_decay": WEIGHT_DECAY,
        "seed": 1234,
        "max_abs_diff": max_abs_diff,
        "tolerance": UPDATE_RULE_ATOL,
        "gpu_side_disclosure": ("no GPU access available in this lane; the reference leg "
                                 "runs on CPU tensors per the cure PR spec's own fallback "
                                 "clause. The GPU-side leg (bf16 CUDA-resident param, real "
                                 "grad from a real forward/backward) runs as part of the "
                                 "MEASURED dry-run in a follow-up push, coordinated with the "
                                 "serving-pause window -- explicitly out of this lane's scope."),
        "passed": passed,
    }


def probe_accumulation_loss_equivalence() -> dict:
    """PROBE 2: grad-accumulation loss + gradient equivalence, tiny real-arch model."""
    import torch
    import torch.nn.functional as F

    cfg_model = {"vocab": 64, "hidden": 16, "layers": 2, "heads": 2, "seq": 32,
                 "tied_embeddings": False}
    n_mtp = 0
    intermediate = 32

    def _fresh_model_and_batch():
        torch.manual_seed(42)
        model = build_model(cfg_model, n_mtp, intermediate)
        model.train()
        gen = torch.Generator().manual_seed(42)
        ids = torch.randint(0, cfg_model["vocab"], (16, cfg_model["seq"]), generator=gen)
        targets = torch.randint(0, cfg_model["vocab"], (16, cfg_model["seq"]), generator=gen)
        return model, ids, targets

    def _forward_ce(model, ids, targets) -> "torch.Tensor":
        # Same forward shape run_v0_segment's training loop uses (backbone ->
        # head logits -> CE), but via F.cross_entropy directly since this
        # tiny probe has no MTP heads / chunked-CE path to exercise.
        h = model.backbone_model(input_ids=ids).last_hidden_state
        logits = model.head(h)
        return F.cross_entropy(logits.reshape(-1, logits.shape[-1]), targets.reshape(-1))

    # --- monolithic: one forward+backward over all 16 samples ---
    model_mono, ids, targets = _fresh_model_and_batch()
    loss_mono = _forward_ce(model_mono, ids, targets)
    loss_mono.backward()
    grad_mono_head = model_mono.head.weight.grad.detach().clone()
    loss_mono_value = float(loss_mono.detach())

    # --- accumulated: 8 micro-batches of 2, SAME 16 samples, contiguous slices ---
    model_accum, _, _ = _fresh_model_and_batch()  # identical seed -> identical init weights
    micro_batch = 2
    accum_steps = 8
    micro_losses = []
    for i in range(accum_steps):
        lo, hi = i * micro_batch, (i + 1) * micro_batch
        micro_loss = _forward_ce(model_accum, ids[lo:hi], targets[lo:hi])
        micro_losses.append(float(micro_loss.detach()))
        (micro_loss / accum_steps).backward()
    grad_accum_head = model_accum.head.weight.grad.detach().clone()
    loss_accum_value = sum(micro_losses) / len(micro_losses)

    delta_loss = abs(loss_mono_value - loss_accum_value)
    max_abs_grad_diff = float((grad_mono_head - grad_accum_head).abs().max())

    return {
        "mechanism": ("mean-of-equal-size-chunk-means == overall mean identity for a "
                      "reduction='mean' CE loss: 8 micro-batches of 2 (contiguous slices "
                      "of the SAME 16-sample fixed batch) averaged, vs one monolithic "
                      "forward+backward over all 16; gradients are compared on the model's "
                      "head weight (accumulated grad = sum of 8 micro-grads each scaled by "
                      "1/8, matching run_v0_segment's new grad_accum_steps wiring)"),
        "model_config": cfg_model,
        "intermediate": intermediate,
        "batch_monolithic": 16,
        "micro_batch": micro_batch,
        "accum_steps": accum_steps,
        "effective_batch": micro_batch * accum_steps,
        "seed": 42,
        "loss_monolithic": loss_mono_value,
        "loss_accumulated": loss_accum_value,
        "delta_loss": delta_loss,
        "max_abs_grad_diff_head_weight": max_abs_grad_diff,
        "note": ("delta_loss is expected at fp-noise scale, not exactly 0.0 -- summation "
                 "order differs between one CE reduction over 16 rows and eight CE "
                 "reductions over 2 rows each, then averaged"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--receipt-dir", default=str(RECEIPT_DIR))
    args = ap.parse_args()

    ts_stamp = _ts()
    print(f"[{ts_stamp}] PROBE 1: update-rule bitwise equivalence (CPU, small param slice)")
    probe1 = probe_update_rule_equivalence()
    print(f"  max_abs_diff={probe1['max_abs_diff']:.3e} tolerance={probe1['tolerance']} "
          f"passed={probe1['passed']}")

    print(f"\n[{ts_stamp}] PROBE 2: grad-accumulation loss-equivalence (CPU, tiny real-arch model)")
    probe2 = probe_accumulation_loss_equivalence()
    print(f"  loss_monolithic={probe2['loss_monolithic']:.6f} "
          f"loss_accumulated={probe2['loss_accumulated']:.6f} "
          f"delta_loss={probe2['delta_loss']:.3e}")
    print(f"  max_abs_grad_diff_head_weight={probe2['max_abs_grad_diff_head_weight']:.3e}")

    verdict_pass = bool(probe1["passed"])  # probe 2 is a measured-and-disclosed number,
    # not a pass/fail gate per the cure PR spec (which asks to "report the number", not
    # assert a threshold) -- the overall receipt verdict rides PROBE 1's explicit tolerance.

    receipt = {
        "ticket": "CBASE-GROW-RUNG2-OFFLOAD-PROBE",
        "ts": datetime.now(timezone.utc).isoformat(),
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "experiment": "C-BASE-clause-d-cure",
        "arm": "cpu-offload-probe",
        "spec_ref": "state/rung2-cure-pr-spec-20260708.md; docs/domains/governance/ledgers/deviations.md DEV-002",
        "scope": ("CPU-only equivalence probes for the DEV-002 cure (CPU-offloaded "
                  "optimizer states + micro-batch/grad accumulation). Does NOT run the "
                  "measured production-scale dry-run (real 2.2B, nvidia-smi sampling) -- "
                  "that needs the coordinated serving-pause GPU window and lands in a "
                  "follow-up push before merge-gate, per the cure PR spec."),
        "update_rule_equivalence": probe1,
        "accumulation_loss_equivalence": probe2,
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
        "device": "cpu",
        "measured_on_train_daemon": False,
        "script": "scripts/cbase_grow_rung2_offload_probe.py",
        "pass": verdict_pass,
        "verdict": "PASS" if verdict_pass else "FAIL",
        "kill_criterion": None if verdict_pass else "update_rule_tolerance_exceeded",
    }
    out_path = Path(args.receipt_dir) / f"cbase-grow-rung2-offload-probe-{ts_stamp}.json"
    checked_write(str(out_path), receipt)
    print(f"\n{'CBASE_GROW_RUNG2_OFFLOAD_PROBE_PASS' if verdict_pass else 'CBASE_GROW_RUNG2_OFFLOAD_PROBE_FAIL'} "
          f"receipt={out_path}")
    return 0 if verdict_pass else 2


if __name__ == "__main__":
    sys.exit(main())
