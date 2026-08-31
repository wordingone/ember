#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cbase_grow_live.py — REAL governed net2net warm-start growth run (C-GROW).

Produces the C-GROW receipt scripts/ember_totality/test_c_grow.py (in
the goal-forge working tree, read as the field/shape spec) demands: a net2net FF-
widening warm-start MEASURED on a real governed training run — before/after
PARAMETER COUNTS, LOSS CONTINUITY across the grow step, and the FLOP-SAVING
delta vs an equivalent from-scratch model, never an analytical argument.

Pipeline (both --smoke and --live run the SAME code path — see below):
  1. PRE-GROW: resume the seed checkpoint (or a fresh tiny model, --smoke) and
     train K continuation steps via timeshare_pretrain.run_v0_segment — the
     REAL v0 survivor-stack pretrain loop (Muon/AdamW split, WSD, chunked CE,
     MTP aux heads, packed-shard loader, governor, checkpoint/resume) the
     cbase-v0 seed was itself trained with. Per-step losses recorded.
  2. GROW: apply cbase_grow_dryrun.widen_state_dict (net2net FF-widening —
     gate_proj/up_proj row-duplicate, down_proj column-halve-duplicate) to the
     pre-grow segment's final checkpoint. Function-preservation is checked
     TWICE: (a) the deterministic same-batch forward-logit-diff check
     cbase_grow_dryrun.py itself uses (tight tolerance, low noise — the
     reliable proof), AND (b) the noisy training-loss continuity the C-GROW
     spec asks for (loss[grow] vs loss[grow-1] vs pre-grow step-to-step
     variance). Neither duplicates the other's math; (a) reuses
     cbase_grow_dryrun.widen_state_dict + its build_model forward-only twin,
     (b) reuses timeshare_pretrain's own per-step loss recording.
  3. POST-GROW: run_v0_segment again, same code path, resumed from the grown
     checkpoint at the grown FF width, K more steps. The pre-grow optimizer
     state cannot be replayed into the post-grow optimizer (FF-widening
     changes gate/up/down_proj param shapes) — reset_optimizer_on_resume=True
     skips that load; model weights still load normally.
  4. RECEIPT: param counts before/after, loss-continuity block (both checks),
     FLOP-saving vs an from-scratch-at-the-grown-width baseline. The from-
     scratch comparison is NOT run in this job (that would mean pretraining a
     368M+ model from init to convergence) — it is an honestly labeled
     ESTIMATE (never "measured"), method stated in the receipt.

Reuse discipline (no duplicated math):
  - timeshare_pretrain.run_v0_segment — the ACTUAL pretrain training loop the
    cbase-v0 seed was trained with (Muon/WSD/chunked-CE/MTP/governor/
    checkpoint-resume). Two small additive, backward-compatible parameters
    were added to timeshare_pretrain.py to make this runnable here without
    forking the loop: `intermediate_override` (thread a variable FF width
    into build_v0_model — its live branch hardcoded intermediate_size=4096)
    and `reset_optimizer_on_resume` (skip load_optimizers_state when the grow
    step changed param shapes), plus `real_arch`/`device` (build the REAL
    LlamaModel architecture on cpu — the plain live=False path builds an
    incompatible tiny stand-in with no mlp.{gate,up,down}_proj keys, which
    the net2net surgery cannot operate on). Existing callers pass none of
    these — every default preserves current behavior byte-for-byte
    (confirmed: `--selftest`, `--selftest-v0ext` both still pass unchanged).
  - cbase_grow_dryrun.widen_state_dict / .build_model / .sha256_file — the
    exact net2net surgery math and its forward-only verification twin,
    imported, never reimplemented.
  - receipt_write.checked_write — fail-closed receipt writer, imported.

Modes:
  --smoke   CPU, K=3, tiny real-architecture model (fast plumbing check —
            proves the wiring: pretrain-loop -> grow-surgery -> pretrain-
            loop-again -> receipt-fields; does NOT claim anything about the
            production cbase-v0 seed). No cuda, no shard-dir, no interlock.
  --live    Real governed cuda run against the real cbase-v0 step-610 seed.
            Requires EMBER_GATE_AUTHORIZED=1 (env) + --shard-dir (real packed
            uint16 shards) — enforced by run_v0_segment's own eng-33/eng-54
            interlock, not duplicated here. NOT launched by this script's
            author — the session fires --live.

Receipt: receipts/cbase-grow-live/cbase-grow-live-<smoke|live>-<ts>.json
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
# issue2015 exact-local-import:scripts/timeshare_pretrain.py
import importlib.util as _ember_d9c5c82c124e1dc8_importlib
import sys as _ember_d9c5c82c124e1dc8_sys
from pathlib import Path as _ember_d9c5c82c124e1dc8_Path
_ember_d9c5c82c124e1dc8_path = _ember_d9c5c82c124e1dc8_Path(__file__).resolve().parents[4].joinpath('scripts', 'timeshare_pretrain.py')
if not _ember_d9c5c82c124e1dc8_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/timeshare_pretrain.py')
_ember_d9c5c82c124e1dc8_aliases = ('_ember_issue2015_d9c5c82c124e1dc8', 'scripts.timeshare_pretrain', 'timeshare_pretrain')
_ember_d9c5c82c124e1dc8_existing = []
for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
    _ember_d9c5c82c124e1dc8_candidate = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
    if _ember_d9c5c82c124e1dc8_candidate is not None and all(_ember_d9c5c82c124e1dc8_candidate is not item for item in _ember_d9c5c82c124e1dc8_existing):
        _ember_d9c5c82c124e1dc8_existing.append(_ember_d9c5c82c124e1dc8_candidate)
if len(_ember_d9c5c82c124e1dc8_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/timeshare_pretrain.py')
if _ember_d9c5c82c124e1dc8_existing:
    _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_existing[0]
    _ember_d9c5c82c124e1dc8_observed = getattr(_ember_d9c5c82c124e1dc8_module, '__file__', None)
    if _ember_d9c5c82c124e1dc8_observed is None or _ember_d9c5c82c124e1dc8_Path(_ember_d9c5c82c124e1dc8_observed).resolve() != _ember_d9c5c82c124e1dc8_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/timeshare_pretrain.py')
else:
    _ember_d9c5c82c124e1dc8_spec = _ember_d9c5c82c124e1dc8_importlib.spec_from_file_location('_ember_issue2015_d9c5c82c124e1dc8', _ember_d9c5c82c124e1dc8_path)
    if _ember_d9c5c82c124e1dc8_spec is None or _ember_d9c5c82c124e1dc8_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/timeshare_pretrain.py')
    _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_importlib.module_from_spec(_ember_d9c5c82c124e1dc8_spec)
    for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
        _ember_d9c5c82c124e1dc8_prior = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
        if _ember_d9c5c82c124e1dc8_prior is not None and _ember_d9c5c82c124e1dc8_prior is not _ember_d9c5c82c124e1dc8_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/timeshare_pretrain.py')
        _ember_d9c5c82c124e1dc8_sys.modules[_ember_d9c5c82c124e1dc8_alias] = _ember_d9c5c82c124e1dc8_module
    try:
        _ember_d9c5c82c124e1dc8_spec.loader.exec_module(_ember_d9c5c82c124e1dc8_module)
    except BaseException:
        for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
            if _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias) is _ember_d9c5c82c124e1dc8_module:
                _ember_d9c5c82c124e1dc8_sys.modules.pop(_ember_d9c5c82c124e1dc8_alias, None)
        raise
for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
    _ember_d9c5c82c124e1dc8_prior = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
    if _ember_d9c5c82c124e1dc8_prior is not None and _ember_d9c5c82c124e1dc8_prior is not _ember_d9c5c82c124e1dc8_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/timeshare_pretrain.py')
    _ember_d9c5c82c124e1dc8_sys.modules[_ember_d9c5c82c124e1dc8_alias] = _ember_d9c5c82c124e1dc8_module
ts = _ember_d9c5c82c124e1dc8_module
# issue2015 exact-local-import-end:scripts/timeshare_pretrain.py                                    # noqa: E402
from cbase_grow_dryrun import (                                    # noqa: E402
    PASS_TOL, build_model as dryrun_build_model, sha256_file, widen_state_dict,
)
from receipt_write import checked_write                            # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SEED_CKPT_DEFAULT = REPO / "models" / "cbase-smoke-run" / "checkpoints" / "step-00000610"
K_LIVE_DEFAULT = 60
K_SMOKE = 3          # spec: "--smoke mode (CPU, K=3)"
SMOKE_FF_SEED = 8    # small FF width so the real LlamaModel arch trains in seconds on CPU


def _flops_per_step(param_count: int, batch: int, seq: int) -> float:
    """Standard dense-transformer FLOPs/step estimate: 6 * params * tokens
    (Kaplan et al. 2020 / Chinchilla convention: forward+backward ~= 6N FLOPs
    per token). Used for BOTH the measured grow-path total and the labeled
    from-scratch ESTIMATE below — same formula, so the comparison is
    apples-to-apples on the one axis (param count) that changes."""
    return 6.0 * param_count * batch * seq


def _backbone_param_estimate(hidden: int, layers: int, vocab: int, ff: int,
                              n_mtp: int = 0) -> int:
    """Dense-decoder param count at an explicit FF width — needed because the
    frozen v0 config's base_excluding_mtp pin (368354304) is only valid at
    the DEFAULT intermediate_size=4096; this grow run trains at ff_seed/
    ff_grown, both potentially != 4096. Per layer: 4*hidden^2 attention
    (q/k/v/o, no GQA reduction here) + 3*hidden*ff SwiGLU MLP (gate/up/
    down_proj) + 2*hidden (input + post-attn RMSNorm), plus one final RMSNorm
    (hidden) and the tied vocab embedding (vocab*hidden), plus n_mtp untied
    aux-head linears (n_mtp*hidden*vocab — FF-independent, and NOT counted in
    the base-excluding-MTP pin, so included here on top: conservative,
    never understates cost against the fixed G-budget micro-fit ceiling).
    Verified EXACT against the certified pin at hidden=1024/layers=20/
    vocab=32000/ff=4096/n_mtp=0 -> 368354304."""
    per_layer = 4 * hidden * hidden + 3 * hidden * ff + 2 * hidden
    return layers * per_layer + hidden + vocab * hidden + n_mtp * hidden * vocab


def _small_cfg(cfg: dict) -> dict:
    """Small-dims copy of the frozen v0 contract for --smoke: same optimizer/
    schedule/objective/precision/throughput structure (so the SAME code path
    exercises the same components), tiny model shape so the REAL LlamaModel
    architecture (required for the net2net surgery's key names — the
    non-live tiny stand-in lacks them) trains in seconds on CPU."""
    small = copy.deepcopy(cfg)
    small["model"] = dict(small["model"], hidden=32, layers=2, heads=2,
                           vocab=64, seq=16, params_estimate=None)
    small["throughput"] = dict(small["throughput"], batch=2)
    return small


def _loss_continuity_block(pre_losses: list[float], post_losses: list[float]) -> dict:
    """The C-GROW spec's noisy training-loss continuity check: loss[grow] vs
    loss[grow-1], plus max-jump / stdev stats over the pre-grow step-to-step
    losses as the tolerance envelope. Continuity is CLAIMED only if the
    grow-step delta falls within that envelope — computed honestly, not
    asserted."""
    loss_grow_minus_1 = pre_losses[-1]
    loss_grow = post_losses[0]
    grow_step_delta = abs(loss_grow - loss_grow_minus_1)
    pre_jumps = [abs(pre_losses[i + 1] - pre_losses[i]) for i in range(len(pre_losses) - 1)]
    if pre_jumps:
        max_pre_jump = max(pre_jumps)
        mean_pre_jump = sum(pre_jumps) / len(pre_jumps)
        var_pre_jump = sum((j - mean_pre_jump) ** 2 for j in pre_jumps) / len(pre_jumps)
        std_pre_jump = var_pre_jump ** 0.5
    else:
        max_pre_jump = mean_pre_jump = std_pre_jump = 0.0
    envelope = max(max_pre_jump, 1e-9)
    return {
        "loss_pre_grow_last_step": round(loss_grow_minus_1, 6),
        "loss_post_grow_first_step": round(loss_grow, 6),
        "grow_step_delta": round(grow_step_delta, 6),
        "pre_grow_step_to_step_jumps": {
            "n_jumps": len(pre_jumps), "max": round(max_pre_jump, 6),
            "mean": round(mean_pre_jump, 6), "stdev": round(std_pre_jump, 6),
        },
        "training_loss_continuity_within_pre_grow_variance_envelope":
            bool(grow_step_delta <= envelope),
        "note": ("noisy check — consecutive SGD steps train on DIFFERENT "
                 "minibatches, so this is a statistical continuity signal, "
                 "not a deterministic one; see function_preservation_check "
                 "for the deterministic same-batch forward-logit-diff proof"),
    }


def _function_preservation_check(cfg_model: dict, n_mtp: int, sd_pre_f32: dict,
                                  sd_post_f32: dict, ff_seed: int, ff_grown: int) -> dict:
    """The deterministic, low-noise proof cbase_grow_dryrun.py itself uses:
    same fixed recorded token batch, pre-grow model vs freshly-grown model
    (BEFORE any post-grow training step), max abs logit diff <= PASS_TOL.
    Reuses cbase_grow_dryrun.build_model (imported) — not reimplemented."""
    import torch
    torch.manual_seed(42)
    seq_probe = min(cfg_model["seq"], 128)
    ids = torch.randint(0, cfg_model["vocab"], (2, seq_probe),
                         generator=torch.Generator().manual_seed(42))
    batch_sha = __import__("hashlib").sha256(ids.numpy().tobytes()).hexdigest()

    pre_model = dryrun_build_model(cfg_model, n_mtp, ff_seed)
    missing, unexpected = pre_model.load_state_dict(sd_pre_f32, strict=False)
    real_missing = [k for k in missing if k != "head.weight"]
    if real_missing or unexpected:
        raise SystemExit(f"pre-grow probe load mismatch: missing={real_missing} unexpected={unexpected}")
    pre_model.eval()
    with torch.no_grad():
        logits_pre = pre_model.logits(ids).detach().clone()

    # #406: release the pre-grow model before building the post-grow model.
    # At rung-2 scale (~1.19B pre-grow + ~2.2B post-grow params) holding both
    # resident+uncollected here deterministically SIGSEGVs (exit 139). Bound
    # peak residency to one model at a time — logits_pre is already copied
    # out above, so pre_model is no longer needed past this point.
    import gc
    del pre_model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    post_model = dryrun_build_model(cfg_model, n_mtp, ff_grown)
    missing, unexpected = post_model.load_state_dict(sd_post_f32, strict=False)
    real_missing = [k for k in missing if k != "head.weight"]
    if real_missing or unexpected:
        raise SystemExit(f"post-grow probe load mismatch: missing={real_missing} unexpected={unexpected}")
    post_model.eval()
    logits_post = post_model.logits(ids)

    fp_diff = float((logits_post - logits_pre).abs().max())
    return {
        "mechanism": "same fixed recorded token batch through pre-grow vs "
                     "freshly-grown (pre-training) models; net2net FF-widening "
                     "is function-preserving by construction (duplicated "
                     "gate/up rows produce duplicated SwiGLU activations; the "
                     "halved, duplicated down columns sum them back to the "
                     "exact seed output)",
        "input_batch": {"batch": 2, "seqlen": seq_probe,
                         "token_ids_sha256": batch_sha, "generator_seed": 42},
        "logit_max_abs_diff": fp_diff,
        "pass_tolerance": PASS_TOL,
        "function_preserving": bool(fp_diff <= PASS_TOL),
    }


def _run(args, cfg: dict, ts_stamp: str, *, live: bool) -> int:
    k = K_SMOKE if not live else args.k_steps
    device = "cuda" if live else "cpu"
    n_mtp = cfg["objective"]["mtp_aux_heads"]["n_heads"]
    n_layers = cfg["model"]["layers"]
    batch = cfg["throughput"]["batch"]
    seq = cfg["model"]["seq"]

    out_root = Path(args.out_dir) / f"{'live' if live else 'smoke'}-{ts_stamp}"
    pre_dir = out_root / "pre"
    post_dir = out_root / "post"

    # --- resolve seed + ff_seed ------------------------------------------------
    if live:
        seed_ckpt = Path(args.seed_ckpt)
        manifest = json.loads((seed_ckpt / "manifest.json").read_text(encoding="utf-8"))
        model_pt = seed_ckpt / "model.pt"
        actual_sha = sha256_file(model_pt)
        claimed_sha = (manifest.get("files") or {}).get("model.pt")
        if not (isinstance(claimed_sha, str) and actual_sha == claimed_sha):
            raise SystemExit(f"seed checkpoint hash mismatch: manifest={claimed_sha} actual={actual_sha}")
        import torch
        sd_seed_bf16 = torch.load(model_pt, map_location="cpu", weights_only=True)
        ff_seed = int(sd_seed_bf16["backbone_model.layers.0.mlp.gate_proj.weight"].shape[0])
        resume_ckpt_dir = str(seed_ckpt)
        total_steps = args.total_steps or manifest.get("extra", {}).get("total_steps") \
            or (cfg["data"]["token_budget"]["compute_optimal"] // (batch * seq))
        seed_identity = {
            "checkpoint": str(seed_ckpt), "model_pt_sha256": actual_sha,
            "manifest_claim_verified": True, "step": manifest.get("step"),
            "segment_id": manifest.get("extra", {}).get("segment_id"),
        }
    else:
        ff_seed = SMOKE_FF_SEED
        resume_ckpt_dir = None
        total_steps = args.total_steps or (k * 4)
        seed_identity = {"checkpoint": None, "note": "smoke: fresh-init tiny model, no seed checkpoint (plumbing check only)"}

    ff_grown = ff_seed * 2

    # --- REQUESTED-RUN compute-fit descriptors (per-run-truthful G-budget) ---
    # This is a k-step micro-run, not the full v0 pretrain ladder — the launch
    # gate's G-budget row otherwise prices the FULL ladder's calendar/SHATTER
    # math regardless of what's actually being dispatched (see
    # v0_pretrain_launch_gate.g_budget). Passing an explicit requested_run
    # descriptor (this call's own k_steps + model dims, known here) lets
    # G-budget price THIS k-step segment instead. Only consumed on the live
    # path (run_v0_segment/_check_launch_interlock never fires off it).
    hidden = cfg["model"]["hidden"]
    vocab = cfg["model"]["vocab"]
    mtp_cost_heads = n_mtp if cfg["objective"]["mtp_aux_heads"]["enabled"] else 0
    params_pre = _backbone_param_estimate(hidden, n_layers, vocab, ff_seed, mtp_cost_heads)
    params_post = _backbone_param_estimate(hidden, n_layers, vocab, ff_grown, mtp_cost_heads)
    requested_run_pre = {
        "source": "cbase_grow_live:pre-grow",
        "total_steps": k,
        "flops_per_step": _flops_per_step(params_pre, batch, seq),
    }
    requested_run_post = {
        "source": "cbase_grow_live:post-grow",
        "total_steps": k,
        "flops_per_step": _flops_per_step(params_post, batch, seq),
    }

    # --- 1. PRE-GROW: K continuation steps via the REAL pretrain loop --------
    pre_receipt = ts.run_v0_segment(
        str(pre_dir), cfg, n_steps=k, total_steps=total_steps, live=live,
        real_arch=True, device=device, resume_ckpt_dir=resume_ckpt_dir,
        shard_dir=(args.shard_dir if live else None),
        checkpoint_every=k, segment_id="cbase-grow-live-pre",
        intermediate_override=ff_seed, ce_chunk_tokens=args.ce_chunk_tokens,
        requested_run=requested_run_pre,
    )
    assert pre_receipt["pass"] is True, "pre-grow segment did not complete"
    assert pre_receipt["last_checkpoint"], "pre-grow segment produced no checkpoint"

    # --- 2. GROW: net2net FF-widening on the pre-grow segment's checkpoint ---
    m_state, o_state, r_state, pre_ckpt_manifest = ts.load_checkpoint(pre_receipt["last_checkpoint"])
    sd_pre_f32 = {kk: v.float() for kk, v in m_state.items()}
    grown_sd_f32 = widen_state_dict(sd_pre_f32, n_layers)
    param_count_before = int(sum(v.numel() for v in sd_pre_f32.values()))
    param_count_after = int(sum(v.numel() for v in grown_sd_f32.values()))

    fp_check = _function_preservation_check(
        cfg["model"], n_mtp, sd_pre_f32, grown_sd_f32, ff_seed, ff_grown)
    assert fp_check["function_preserving"], (
        f"net2net grow surgery FAILED function preservation: "
        f"logit_max_abs_diff={fp_check['logit_max_abs_diff']} > tol={PASS_TOL}")

    grown_sd_bf16 = {kk: v.to(__import__("torch").bfloat16) for kk, v in grown_sd_f32.items()}
    grow_ckpt_dir = ts.save_checkpoint(
        str(post_dir), pre_ckpt_manifest["step"], grown_sd_bf16, o_state, r_state,
        extra={"segment_id": "cbase-grow-live-grown", "mechanism": "ff_widening_net2net",
               "grown_from_step": pre_ckpt_manifest["step"], "ff_seed": ff_seed,
               "ff_grown": ff_grown,
               "optimizer_state_carried_but_unused": True,
               "note": "optimizer.pt bytes carried from pre-grow verbatim (shapes stale "
                       "after FF-widening); post-grow resumes with reset_optimizer_on_resume=True "
                       "so this file is never loaded into a live optimizer"})

    # --- 3. POST-GROW: K more steps at the grown width, fresh optimizer ------
    post_receipt = ts.run_v0_segment(
        str(post_dir), cfg, n_steps=k, total_steps=total_steps, live=live,
        real_arch=True, device=device, resume_ckpt_dir=grow_ckpt_dir,
        shard_dir=(args.shard_dir if live else None),
        checkpoint_every=k, segment_id="cbase-grow-live-post",
        intermediate_override=ff_grown, reset_optimizer_on_resume=True,
        ce_chunk_tokens=args.ce_chunk_tokens,
        requested_run=requested_run_post,
    )
    assert post_receipt["pass"] is True, "post-grow segment did not complete"

    # --- 4. Receipt: params, loss continuity, FLOP saving --------------------
    loss_continuity = _loss_continuity_block(pre_receipt["losses"], post_receipt["losses"])

    total_steps_reached = post_receipt["global_step_end"]
    flops_pre_measured = _flops_per_step(param_count_before, batch, seq) * k
    flops_post_measured = _flops_per_step(param_count_after, batch, seq) * k
    flops_grow_path_measured_this_run = flops_pre_measured + flops_post_measured
    flops_sunk_pretrain = _flops_per_step(param_count_before, batch, seq) * pre_receipt["resume_step"]
    flops_grow_path_total_incl_sunk = flops_sunk_pretrain + flops_grow_path_measured_this_run
    flops_fromscratch_estimate_total = _flops_per_step(param_count_after, batch, seq) * total_steps_reached
    flop_saving_ratio = (flops_fromscratch_estimate_total / flops_grow_path_total_incl_sunk
                         if flops_grow_path_total_incl_sunk > 0 else None)

    flop_saving = {
        "estimate_method": (
            "FLOPs/step = 6 * param_count * batch * seq (Kaplan/Chinchilla dense-"
            "transformer forward+backward convention). flops_grow_path_measured_this_run "
            "= measured FLOPs actually spent in THIS run (k steps at the seed FF width + "
            "k steps at the grown FF width). flops_grow_path_total_incl_sunk additionally "
            "counts the seed's own pretrain steps (resume_step) at the seed FF width — "
            "sunk cost from the original pretrain segment, not re-measured here, but part "
            "of the full grow-path's real cost. flops_fromscratch_baseline_total = training "
            "the GROWN width from random init for the SAME total step count the warm-started "
            "path took to reach this point (total_steps_reached) — this is an ESTIMATE, not "
            "measured: it assumes a from-scratch wide model needs AT LEAST as many steps as "
            "the warm-started path to reach a comparable loss (a conservative floor; from-"
            "scratch convergence from random init is typically slower, so this likely "
            "UNDERSTATES the real saving)."
        ),
        "label": "estimate",
        "measured": False,
        "flops_grow_path_measured_this_run": flops_grow_path_measured_this_run,
        "flops_sunk_pretrain_not_measured_this_run": flops_sunk_pretrain,
        "flops_grow_path_total_incl_sunk": flops_grow_path_total_incl_sunk,
        "flops_fromscratch_baseline_total": flops_fromscratch_estimate_total,
        "flop_saving_ratio_fromscratch_over_growpath": (
            round(flop_saving_ratio, 4) if flop_saving_ratio is not None else None),
        "total_steps_reached": total_steps_reached,
    }

    verdict_pass = bool(fp_check["function_preserving"] and pre_receipt["pass"] and post_receipt["pass"])
    receipt: dict[str, Any] = {
        "ticket": "CBASE-GROW-LIVE",
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "scope": ("net2net FF-widening warm-start growth MEASURED on a real governed "
                  "run of the v0 survivor-stack pretrain loop (timeshare_pretrain."
                  "run_v0_segment) — before/after param counts, loss continuity across "
                  "the grow step (deterministic forward check + noisy training-loss "
                  "check), FLOP-saving vs an honestly-labeled from-scratch estimate"),
        "mode": "live" if live else "smoke",
        "grow_method": "net2net FF-widening (function-preserving, warm-start) — the "
                        "identical grow_operator surgery cbase_grow_dryrun.py proved on "
                        "the real cbase-v0 step-610 seed, applied here mid-training",
        "seed_identity": seed_identity,
        "k_steps_pre_grow": k,
        "k_steps_post_grow": k,
        "param_count_before": param_count_before,
        "param_count_after": param_count_after,
        "param_count_seed": param_count_before,
        "param_count_grown": param_count_after,
        "ff_seed": ff_seed,
        "ff_grown": ff_grown,
        "loss_continuity": loss_continuity,
        "function_preservation_check": fp_check,
        "flop_saving_vs_fromscratch": flop_saving,
        "pre_grow_segment": {
            "segment_id": pre_receipt["segment_id"], "resume_step": pre_receipt["resume_step"],
            "global_step_end": pre_receipt["global_step_end"], "steps": pre_receipt["steps"],
            "loss_first": pre_receipt["loss_first"], "loss_last": pre_receipt["loss_last"],
            "losses": pre_receipt["losses"], "wall_s": pre_receipt["wall_s"],
            "checkpoint": pre_receipt["last_checkpoint"], "governor": pre_receipt["governor"],
        },
        "grow_step": {
            "grown_from_step": pre_ckpt_manifest["step"], "checkpoint": grow_ckpt_dir,
            "mechanism": "ff_widening_net2net (grow_operator, imported from cbase_grow_dryrun.widen_state_dict)",
        },
        "post_grow_segment": {
            "segment_id": post_receipt["segment_id"], "resume_step": post_receipt["resume_step"],
            "global_step_end": post_receipt["global_step_end"], "steps": post_receipt["steps"],
            "loss_first": post_receipt["loss_first"], "loss_last": post_receipt["loss_last"],
            "losses": post_receipt["losses"], "wall_s": post_receipt["wall_s"],
            "checkpoint": post_receipt["last_checkpoint"], "governor": post_receipt["governor"],
            "optimizer_reset_on_resume": True,
        },
        "device": device,
        "measured_on_train_daemon": live,
        "script": "src/ember/governance/scripts/cbase_grow_live.py",
        "invalid_tokens_present": [],
        "pass": verdict_pass,
        "verdict": "GROW_LIVE_PASS" if (live and verdict_pass) else
                   "GROW_LIVE_FAIL" if live else
                   "GROW_LIVE_SMOKE_PASS" if verdict_pass else "GROW_LIVE_SMOKE_FAIL",
    }

    receipt_dir = Path(args.receipt_dir)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    out = receipt_dir / f"cbase-grow-live-{'live' if live else 'smoke'}-{ts_stamp}.json"
    checked_write(str(out), receipt)
    print(f"{receipt['verdict']} param_before={param_count_before} param_after={param_count_after} "
          f"fp_diff={fp_check['logit_max_abs_diff']:.3e} "
          f"grow_step_delta={loss_continuity['grow_step_delta']:.6f} "
          f"flop_saving_ratio={flop_saving['flop_saving_ratio_fromscratch_over_growpath']} "
          f"receipt={out}")
    return 0 if verdict_pass else 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--smoke", action="store_true",
                       help="CPU plumbing check, K=3, tiny real-architecture model, no cuda")
    mode.add_argument("--live", action="store_true",
                       help="Real governed cuda run against the real cbase-v0 seed "
                            "(requires EMBER_GATE_AUTHORIZED=1 + --shard-dir)")
    ap.add_argument("--seed-ckpt", default=str(SEED_CKPT_DEFAULT))
    ap.add_argument("--shard-dir", default=None,
                     help="Real packed uint16 shard dir (REQUIRED with --live)")
    ap.add_argument("--k-steps", type=int, default=K_LIVE_DEFAULT,
                     help="Continuation steps per phase for --live (default 60; --smoke always uses 3)")
    ap.add_argument("--total-steps", type=int, default=None,
                     help="WSD schedule denominator; default: seed manifest's recorded "
                          "total_steps for --live, k*4 for --smoke")
    ap.add_argument("--out-dir", default=str(REPO / "models" / "cbase-grow-live"))
    ap.add_argument("--receipt-dir", default=str(REPO / "receipts" / "cbase-grow-live"))
    ap.add_argument("--ce-chunk-tokens", type=int, default=256)
    args = ap.parse_args()

    if args.live and not args.shard_dir:
        raise SystemExit("cbase_grow_live --live requires --shard-dir (real packed uint16 shards; "
                          "eng-54 #194 refuses synthetic tokens on the live path)")

    cfg = ts.load_contract()
    if args.smoke:
        cfg = _small_cfg(cfg)

    ts_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _run(args, cfg, ts_stamp, live=bool(args.live))


if __name__ == "__main__":
    sys.exit(main())
