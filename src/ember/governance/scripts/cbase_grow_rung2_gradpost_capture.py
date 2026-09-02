#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cbase_grow_rung2_gradpost_capture.py — issue #482 grad_post_gate capture rider.

Completes the CBASE-GROW-RUNG2-SPECTRAL-B3S-PARTIAL receipt
(cbase-grow-rung2-event-grow-rung2-20260709-remeasure-b3s-partial.json):
that receipt banked u_pre_spectral (0.07214187 at lr=0.015) and explicitly
deferred u_post because cbase_grow_rung2_spectral_measurement.py's u_post
leg substitutes grad_pre_gate as an admitted PROXY for grad_post_gate
(see that script's lines ~170-175).

This script replaces the proxy with a REAL grad_post_gate: a single
forward+backward on the GROWN rung-2 checkpoint (b2 widen output,
run_id=grow-rung2-20260709-remeasure) over the run's pinned 8-microstep
batch, reproducing phase_b3's own capture leg
(cbase_grow_rung2_event.py:977-1058) verbatim -- same pinned-batch
construction, same QAT/MTP/CE conventions, same post-#513 gate_key
resolution. It does NOT re-run phase_b3 itself (that phase's fork_dir and
b3.json receipt already exist on disk; phase_b3 refuses to reuse an
existing fork dir), so this is a standalone reproduction of only the
capture sub-step, not a re-invocation of the phase-chained runner.

GPU is touched for exactly one forward+backward pass; every measurement
after that (both Muon steps, both spectral norms, all RMS values) runs on
CPU only. No verdict/adjudication language about the Zheng/Gupta fork is
written here -- issue #482's coordinator adjudicates against the frozen
predictions in the coordinator's own comment; this receipt reports
measured numbers only.

Refs: #482 #466 #449 #513
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import torch

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
from receipt_write import checked_write  # noqa: E402
from cbase_grow_dryrun import sha256_file  # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/timeshare_pretrain.py
import importlib.util as _ember_d9c5c82c124e1dc8_importlib
import sys as _ember_d9c5c82c124e1dc8_sys
from pathlib import Path as _ember_d9c5c82c124e1dc8_Path
_ember_d9c5c82c124e1dc8_path = _ember_d9c5c82c124e1dc8_Path(__file__).resolve().parent.joinpath('timeshare_pretrain.py')
if not _ember_d9c5c82c124e1dc8_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/timeshare_pretrain.py')
_ember_d9c5c82c124e1dc8_aliases = ('_ember_issue2015_d9c5c82c124e1dc8', 'src.ember.governance.scripts.timeshare_pretrain', 'timeshare_pretrain')
_ember_d9c5c82c124e1dc8_existing = []
for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
    _ember_d9c5c82c124e1dc8_candidate = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
    if _ember_d9c5c82c124e1dc8_candidate is not None and all(_ember_d9c5c82c124e1dc8_candidate is not item for item in _ember_d9c5c82c124e1dc8_existing):
        _ember_d9c5c82c124e1dc8_existing.append(_ember_d9c5c82c124e1dc8_candidate)
if len(_ember_d9c5c82c124e1dc8_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/timeshare_pretrain.py')
if _ember_d9c5c82c124e1dc8_existing:
    _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_existing[0]
    _ember_d9c5c82c124e1dc8_observed = getattr(_ember_d9c5c82c124e1dc8_module, '__file__', None)
    if _ember_d9c5c82c124e1dc8_observed is None or _ember_d9c5c82c124e1dc8_Path(_ember_d9c5c82c124e1dc8_observed).resolve() != _ember_d9c5c82c124e1dc8_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/timeshare_pretrain.py')
else:
    _ember_d9c5c82c124e1dc8_spec = _ember_d9c5c82c124e1dc8_importlib.spec_from_file_location('_ember_issue2015_d9c5c82c124e1dc8', _ember_d9c5c82c124e1dc8_path)
    if _ember_d9c5c82c124e1dc8_spec is None or _ember_d9c5c82c124e1dc8_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/timeshare_pretrain.py')
    _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_importlib.module_from_spec(_ember_d9c5c82c124e1dc8_spec)
    for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
        _ember_d9c5c82c124e1dc8_prior = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
        if _ember_d9c5c82c124e1dc8_prior is not None and _ember_d9c5c82c124e1dc8_prior is not _ember_d9c5c82c124e1dc8_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/timeshare_pretrain.py')
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
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/timeshare_pretrain.py')
    _ember_d9c5c82c124e1dc8_sys.modules[_ember_d9c5c82c124e1dc8_alias] = _ember_d9c5c82c124e1dc8_module
ts = _ember_d9c5c82c124e1dc8_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/timeshare_pretrain.py  # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py
import importlib.util as _ember_ba82af0721d80c9f_importlib
import sys as _ember_ba82af0721d80c9f_sys
from pathlib import Path as _ember_ba82af0721d80c9f_Path
_ember_ba82af0721d80c9f_path = _ember_ba82af0721d80c9f_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'p5_ratio_audit', 'run_p5_audit.py')
if not _ember_ba82af0721d80c9f_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
_ember_ba82af0721d80c9f_aliases = ('_ember_issue2015_ba82af0721d80c9f', 'p5_ratio_audit.run_p5_audit', 'run_p5_audit', 'scripts.p5_ratio_audit.run_p5_audit')
_ember_ba82af0721d80c9f_existing = []
for _ember_ba82af0721d80c9f_alias in _ember_ba82af0721d80c9f_aliases:
    _ember_ba82af0721d80c9f_candidate = _ember_ba82af0721d80c9f_sys.modules.get(_ember_ba82af0721d80c9f_alias)
    if _ember_ba82af0721d80c9f_candidate is not None and all(_ember_ba82af0721d80c9f_candidate is not item for item in _ember_ba82af0721d80c9f_existing):
        _ember_ba82af0721d80c9f_existing.append(_ember_ba82af0721d80c9f_candidate)
if len(_ember_ba82af0721d80c9f_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
if _ember_ba82af0721d80c9f_existing:
    _ember_ba82af0721d80c9f_module = _ember_ba82af0721d80c9f_existing[0]
    _ember_ba82af0721d80c9f_observed = getattr(_ember_ba82af0721d80c9f_module, '__file__', None)
    if _ember_ba82af0721d80c9f_observed is None or _ember_ba82af0721d80c9f_Path(_ember_ba82af0721d80c9f_observed).resolve() != _ember_ba82af0721d80c9f_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
else:
    _ember_ba82af0721d80c9f_spec = _ember_ba82af0721d80c9f_importlib.spec_from_file_location('_ember_issue2015_ba82af0721d80c9f', _ember_ba82af0721d80c9f_path)
    if _ember_ba82af0721d80c9f_spec is None or _ember_ba82af0721d80c9f_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
    _ember_ba82af0721d80c9f_module = _ember_ba82af0721d80c9f_importlib.module_from_spec(_ember_ba82af0721d80c9f_spec)
    for _ember_ba82af0721d80c9f_alias in _ember_ba82af0721d80c9f_aliases:
        _ember_ba82af0721d80c9f_prior = _ember_ba82af0721d80c9f_sys.modules.get(_ember_ba82af0721d80c9f_alias)
        if _ember_ba82af0721d80c9f_prior is not None and _ember_ba82af0721d80c9f_prior is not _ember_ba82af0721d80c9f_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
        _ember_ba82af0721d80c9f_sys.modules[_ember_ba82af0721d80c9f_alias] = _ember_ba82af0721d80c9f_module
    try:
        _ember_ba82af0721d80c9f_spec.loader.exec_module(_ember_ba82af0721d80c9f_module)
    except BaseException:
        for _ember_ba82af0721d80c9f_alias in _ember_ba82af0721d80c9f_aliases:
            if _ember_ba82af0721d80c9f_sys.modules.get(_ember_ba82af0721d80c9f_alias) is _ember_ba82af0721d80c9f_module:
                _ember_ba82af0721d80c9f_sys.modules.pop(_ember_ba82af0721d80c9f_alias, None)
        raise
for _ember_ba82af0721d80c9f_alias in _ember_ba82af0721d80c9f_aliases:
    _ember_ba82af0721d80c9f_prior = _ember_ba82af0721d80c9f_sys.modules.get(_ember_ba82af0721d80c9f_alias)
    if _ember_ba82af0721d80c9f_prior is not None and _ember_ba82af0721d80c9f_prior is not _ember_ba82af0721d80c9f_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
    _ember_ba82af0721d80c9f_sys.modules[_ember_ba82af0721d80c9f_alias] = _ember_ba82af0721d80c9f_module
_muon_step_in_copy = getattr(_ember_ba82af0721d80c9f_module, '_muon_step_in_copy')
rms = getattr(_ember_ba82af0721d80c9f_module, 'rms')
# issue2015 exact-local-import-end:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py  # noqa: E402
from cbase_grow_rung2_event import _gate_up_down_keys, _build_pinned_batch  # noqa: E402

REPO = Path(__file__).resolve().parents[4]
INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"

RUN_ID = "grow-rung2-20260709-remeasure"
WORKTREE = REPO / ".claude" / "worktrees" / "remeasure-466"
CACHE_DIR = WORKTREE / "receipts" / ".rung2-event-cache"
RECEIPT_DIR = REPO / "receipts"
B1M_RECEIPT = RECEIPT_DIR / f"cbase-grow-rung2-event-{RUN_ID}-b1m.json"

MICRO_BATCH = 1
GRAD_ACCUM_STEPS = 8


def _timestamp_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def capture_grad_post_gate(device: str) -> dict:
    """Reproduces cbase_grow_rung2_event.py phase_b3's capture leg
    (lines 977-1058) exactly: same manual_seed position (nothing between
    it and build_v0_model consumes RNG state), same grown-checkpoint load,
    same pinned-batch construction, same per-microstep QAT/CE/MTP loop.
    Returns dict with grad_post_gate (cpu float32 tensor) + provenance."""
    b1m = json.loads(B1M_RECEIPT.read_text(encoding="utf-8"))

    torch.manual_seed(42)
    cfg = ts.load_contract(None)
    gate_key, up_key, down_key = _gate_up_down_keys(0)

    grown_cache_path = CACHE_DIR / "grown-eps-58e8e98916823941-sigma0.05-seed0.pt"
    if not grown_cache_path.exists():
        raise FileNotFoundError(f"grown weights cache not found: {grown_cache_path}")
    grown_bf16 = torch.load(grown_cache_path, map_location="cpu", weights_only=True)
    ff_grown = int(grown_bf16[gate_key].shape[0])
    grown_gate_shape = list(grown_bf16[gate_key].shape)
    theta_gate_post = grown_bf16[gate_key].detach().clone().to(torch.float32)

    model, vocab, hidden, n_mtp = ts.build_v0_model(
        cfg, live=True, intermediate_override=ff_grown, device=device)
    missing, unexpected = model.load_state_dict(grown_bf16, strict=False)
    real_missing = [k for k in missing if k != "head.weight"]
    if real_missing or unexpected:
        raise SystemExit(
            f"CBASE-GROW-RUNG2-GRADPOST-CAPTURE: post-grow checkpoint load mismatch: "
            f"missing={real_missing} unexpected={unexpected}")
    del grown_bf16
    gc.collect()

    seq = cfg["model"]["seq"]
    n_mtp = cfg["objective"]["mtp_aux_heads"]["n_heads"]
    qat_enabled = bool(cfg.get("precision", {}).get("qat", {}).get("enabled", False))

    batch = _build_pinned_batch(CACHE_DIR, RUN_ID, cfg, n_mtp, vocab, seq,
                                 MICRO_BATCH, GRAD_ACCUM_STEPS, device)
    batch_pin_match = bool(batch["overall_sha256"] == b1m["batch"]["overall_sha256"])
    if not batch_pin_match:
        raise SystemExit(
            "CBASE-GROW-RUNG2-GRADPOST-CAPTURE: pinned-batch sha mismatch vs B1m -- "
            f"refusing to proceed (B1m={b1m['batch']['overall_sha256']} "
            f"recomputed={batch['overall_sha256']})")

    ce_impl, ce_fn = ts.resolve_ce_impl(prefer_liger=True)
    mtp_cfg = cfg["objective"]["mtp_aux_heads"]
    mtp_weight, mtp_enabled = mtp_cfg["weight"], mtp_cfg["enabled"]
    gate_param = model.get_parameter(gate_key)

    gpu_t0 = time.time()
    for microstep in batch["microsteps"]:
        qat_saved = ts._apply_fake_quant(model, "qat") if qat_enabled else []
        x = microstep["x"].to(device)
        y0 = microstep["y0"].to(device)
        y_mtp = [t.to(device) for t in microstep["y_mtp"]]
        hidden_out = model.backbone(x)
        h_flat = hidden_out.reshape(-1, hidden_out.shape[-1])
        primary_ce, _ = ce_fn(h_flat, model.head.weight, y0.reshape(-1), chunk_tokens=256)
        mtp_ces = []
        if mtp_enabled:
            for k, head in enumerate(model.mtp_heads):
                ce_k, _ = ce_fn(h_flat, head.weight, y_mtp[k].reshape(-1), chunk_tokens=256)
                mtp_ces.append(ce_k)
        loss = ts.mtp_total_loss(primary_ce, mtp_ces, mtp_weight)
        (loss / GRAD_ACCUM_STEPS).backward()
        if qat_enabled:
            ts._restore_weights(qat_saved)
    grad_post_gate = gate_param.grad.detach().clone().to(torch.float32).cpu()
    gpu_t1 = time.time()

    del model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    return {
        "grad_post_gate": grad_post_gate,
        "theta_gate_post": theta_gate_post,
        "gate_key": gate_key, "up_key": up_key, "down_key": down_key,
        "grown_gate_shape": grown_gate_shape,
        "ff_grown": ff_grown,
        "qat_enabled": qat_enabled, "mtp_enabled": mtp_enabled, "ce_impl": ce_impl,
        "batch_pin_check": {
            "b1m_sha256": b1m["batch"]["overall_sha256"],
            "recomputed_sha256": batch["overall_sha256"],
            "match": batch_pin_match,
        },
        "gpu_seconds": gpu_t1 - gpu_t0,
        "b1m_receipt": b1m,
    }


def measure(capture: dict, device: str) -> dict:
    """CPU-only spectral measurement. Loads cached pre-widen tensors +
    the freshly captured grad_post_gate, computes the Muon update (via
    the frozen _muon_step_in_copy closure -- never reimplemented) under
    three disclosed momentum/lr conventions:
      1. RESET (primary): zero momentum BOTH sides, lr=0.015 (scaffold's
         frozen convention, per cbase_grow_rung2_spectral_measurement.py).
      2. Reproducibility check: real non-zero pre_momentum, lr=0.015 --
         must reproduce the banked u_pre_spectral=0.07214187 (or disclose
         the delta) to prove this script's Muon math agrees with the
         already-landed b3s-partial measurement.
      3. Disclosed lr=0.02 variant (the resolved real event lr per the
         b1m receipt's u_pre.lr_used field) of the RESET-arm numbers,
         since 0.015 vs 0.02 are two different disclosed conventions in
         this issue's own receipt trail.
    """
    theta_gate_pre = torch.load(CACHE_DIR / f"{RUN_ID}-theta-gate-pre.pt",
                                 map_location="cpu", weights_only=True).float()
    grad_pre_gate = torch.load(CACHE_DIR / f"{RUN_ID}-grad-pre-gate.pt",
                                map_location="cpu", weights_only=True).float()
    pre_momentum_real = torch.load(CACHE_DIR / f"{RUN_ID}-pre-momentum.pt",
                                    map_location="cpu", weights_only=True).float()

    grown_cache_path = CACHE_DIR / "grown-eps-58e8e98916823941-sigma0.05-seed0.pt"
    theta_gate_post = capture["theta_gate_post"]

    grad_post_gate = capture["grad_post_gate"]

    zero_pre = torch.zeros_like(theta_gate_pre)
    zero_post = torch.zeros_like(theta_gate_post)
    assert float(zero_pre.abs().sum()) == 0.0 and float(zero_post.abs().sum()) == 0.0, \
        "RESET-arm momentum must be exactly zero on both sides (explicit assertion)"

    def _norms(w, g, m, lr):
        new_w, _, _ = _muon_step_in_copy(w, g, m, lr=lr)
        u = new_w - w
        return {
            "spectral": float(torch.linalg.svdvals(u)[0].item()),
            "rms": float(rms(u)),
            "scale": max(1.0, w.shape[0] / w.shape[1]) ** 0.5,
        }

    # 1) RESET primary, lr=0.015 (scaffold convention)
    pre_reset_015 = _norms(theta_gate_pre, grad_pre_gate, zero_pre, lr=0.015)
    post_reset_015 = _norms(theta_gate_post, grad_post_gate, zero_post, lr=0.015)

    # 2) Reproducibility check: real momentum, lr=0.015 (must match banked 0.07214187)
    pre_realmom_015 = _norms(theta_gate_pre, grad_pre_gate, pre_momentum_real, lr=0.015)

    # 3) Disclosed lr=0.02 (resolved real event lr) RESET variant
    pre_reset_02 = _norms(theta_gate_pre, grad_pre_gate, zero_pre, lr=0.02)
    post_reset_02 = _norms(theta_gate_post, grad_post_gate, zero_post, lr=0.02)

    grad_post_gate_path = CACHE_DIR / f"{RUN_ID}-grad-post-gate.pt"
    torch.save(grad_post_gate, grad_post_gate_path)
    grad_post_gate_sha256 = _sha256_file(grad_post_gate_path)

    cache_shas = {
        "theta_gate_pre": _sha256_file(CACHE_DIR / f"{RUN_ID}-theta-gate-pre.pt"),
        "grad_pre_gate": _sha256_file(CACHE_DIR / f"{RUN_ID}-grad-pre-gate.pt"),
        "pre_momentum": _sha256_file(CACHE_DIR / f"{RUN_ID}-pre-momentum.pt"),
        "grown_weights": _sha256_file(grown_cache_path),
        "grad_post_gate": grad_post_gate_sha256,
    }

    banked_u_pre_spectral_015 = 0.07214187
    R_reset_015 = post_reset_015["spectral"] / pre_reset_015["spectral"]
    R_reset_02 = post_reset_02["spectral"] / pre_reset_02["spectral"]

    receipt = {
        "ticket": "CBASE-GROW-RUNG2-GRADPOST-CAPTURE",
        "ts": _timestamp_iso(),
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "issue": 482,
        "refs": [466, 449, 513],
        "run_id": RUN_ID,
        "scope": "grad_post_gate REAL capture (single forward+backward on the grown "
                 "rung-2 checkpoint, pinned 8-microstep batch) replacing "
                 "cbase_grow_rung2_spectral_measurement.py's grad_pre_gate proxy, plus "
                 "the CPU-side spectral measurement it unblocks. Measurement only -- no "
                 "verdict on the Zheng/Gupta fork; issue #482's coordinator adjudicates.",
        "method": {
            "capture": "reproduces cbase_grow_rung2_event.py phase_b3's capture leg "
                       "(same manual_seed(42) position, same grown-checkpoint load via "
                       "ts.build_v0_model+load_state_dict, same _build_pinned_batch, same "
                       "QAT/CE/MTP per-microstep loop) without re-running phase_b3 itself "
                       "(its fork_dir + b3.json receipt already exist on disk).",
            "muon_step_closure": "p5_ratio_audit.run_p5_audit._muon_step_in_copy (faithful reuse)",
            "spectral_norm_method": "torch.linalg.svdvals (top singular value)",
        },
        "batch_pin_check": capture["batch_pin_check"],
        "capture_conventions": {
            "qat_enabled": capture["qat_enabled"], "mtp_enabled": capture["mtp_enabled"],
            "ce_impl": capture["ce_impl"], "ff_grown": capture["ff_grown"],
            "gate_key": capture["gate_key"],
        },
        "shapes": {
            "theta_gate_pre": list(theta_gate_pre.shape),
            "theta_gate_post": list(theta_gate_post.shape),
        },
        "grad_post_gate": {
            "rms": float(rms(grad_post_gate)),
            "sha256": grad_post_gate_sha256,
            "saved_path": str(grad_post_gate_path.relative_to(REPO)) if REPO in grad_post_gate_path.parents else str(grad_post_gate_path),
        },
        "measurement_reset_arm_lr015": {
            "lr": 0.015,
            "momentum": "zero buffer both sides (explicit RESET arm)",
            "u_pre_spectral": pre_reset_015["spectral"],
            "u_post_spectral": post_reset_015["spectral"],
            "u_pre_rms": pre_reset_015["rms"],
            "u_post_rms": post_reset_015["rms"],
            "rms_ratio_post_over_pre": post_reset_015["rms"] / pre_reset_015["rms"],
            "R_spectral_ratio_post_over_pre": R_reset_015,
            "pre_scale": pre_reset_015["scale"], "post_scale": post_reset_015["scale"],
            "pre_normalized_sigma_over_lr_scale": pre_reset_015["spectral"] / (0.015 * pre_reset_015["scale"]),
            "post_normalized_sigma_over_lr_scale": post_reset_015["spectral"] / (0.015 * post_reset_015["scale"]),
        },
        "measurement_reset_arm_lr02_disclosed_variant": {
            "lr": 0.02,
            "note": "0.02 is the resolved real event lr per b1m receipt's u_pre.lr_used "
                    "field (forensics panel 2026-07-09 tick-23); 0.015 above is the "
                    "scaffold's frozen convention. R is lr-invariant in principle "
                    "(both scale by the same factor); reported for full disclosure.",
            "momentum": "zero buffer both sides (explicit RESET arm)",
            "u_pre_spectral": pre_reset_02["spectral"],
            "u_post_spectral": post_reset_02["spectral"],
            "u_pre_rms": pre_reset_02["rms"],
            "u_post_rms": post_reset_02["rms"],
            "rms_ratio_post_over_pre": post_reset_02["rms"] / pre_reset_02["rms"],
            "R_spectral_ratio_post_over_pre": R_reset_02,
        },
        "reproducibility_check_real_momentum_lr015": {
            "note": "Reproduces cbase_grow_rung2_spectral_measurement.py's ORIGINAL "
                    "u_pre convention (real non-zero pre_momentum, not zero) to confirm "
                    "this script's Muon math agrees with the already-banked "
                    "b3s-partial receipt before trusting the RESET-arm numbers above.",
            "u_pre_spectral": pre_realmom_015["spectral"],
            "banked_u_pre_spectral": banked_u_pre_spectral_015,
            "delta": pre_realmom_015["spectral"] - banked_u_pre_spectral_015,
            "delta_pct": abs(pre_realmom_015["spectral"] - banked_u_pre_spectral_015) / banked_u_pre_spectral_015 * 100,
        },
        "cache_provenance": {k + "_sha256": v for k, v in cache_shas.items()},
        "gpu_seconds": capture["gpu_seconds"],
        "device": device,
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
        "verdict": "GRADPOST_CAPTURED_MEASUREMENT_COMPLETE",
    }
    return receipt


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--out", default=str(RECEIPT_DIR / f"cbase-grow-rung2-event-{RUN_ID}-b3-gradpost.json"))
    args = ap.parse_args()

    capture = capture_grad_post_gate(args.device)
    receipt = measure(capture, args.device)
    checked_write(args.out, receipt)
    print(f"CBASE_GROW_RUNG2_GRADPOST_CAPTURE verdict={receipt['verdict']} receipt={args.out}", flush=True)
    print(json.dumps({
        "R_reset_lr015": receipt["measurement_reset_arm_lr015"]["R_spectral_ratio_post_over_pre"],
        "R_reset_lr02": receipt["measurement_reset_arm_lr02_disclosed_variant"]["R_spectral_ratio_post_over_pre"],
        "pre_normalized": receipt["measurement_reset_arm_lr015"]["pre_normalized_sigma_over_lr_scale"],
        "post_normalized": receipt["measurement_reset_arm_lr015"]["post_normalized_sigma_over_lr_scale"],
        "gpu_seconds": receipt["gpu_seconds"],
        "reproducibility_delta_pct": receipt["reproducibility_check_real_momentum_lr015"]["delta_pct"],
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
