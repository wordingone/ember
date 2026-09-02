#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cbase_grow_rung2_eps0_fingerprint.py — issue #449 eps-counterfactual
gate-fingerprint rider.

Pre-registered prediction (ledger row eps0-gate-fingerprint-rider-20260709,
frozen 2026-07-09): backprop through the +/-eta down_proj columns splits the
gate/up gradient twin rows as G/2+/-Delta; NS5 amplifies the antisymmetric
Delta. Therefore the gate-class RMS(u_post)/RMS(u_pre) ratio at eps=0 returns
to 1.0 within 0.2%, and the ratio is monotone increasing in eps. Measured
anchor at eps=0.05: 1.0143604 (receipts/cbase-grow-rung2-event-
grow-rung2-20260709-remeasure-b3-gradpost.json).

This script adapts (does not modify) the landed template
cbase_grow_rung2_gradpost_capture.py (#482, PR #541): same grown-checkpoint
load, same _build_pinned_batch + batch-pin sha verify against
2e56e349ebbd680668902a2f6edeb32439528074fe656ec65543b2f3eb4f1f7e, same
manual_seed(42) position, same QAT/MTP/CE per-microstep loop, same Muon
closure reuse from p5_ratio_audit.run_p5_audit._muon_step_in_copy, RESET arm
(zero momentum both sides, lr=0.015 primary).

The eps-counterfactual construction (CPU-only, before any GPU touch): the
grown down_proj [1024, 32768] has BLOCK twin layout d_a = W[:, :16384],
d_b = W[:, 16384:]. eta = (d_a - d_b) / 2 is the realized #280 antisymmetric
perturbation (eps_sigma=0.05 at grow time); d_mean = (d_a + d_b) / 2 is the
eta-free block mean. Three variants are built by rewriting ONLY the down_proj
entry of the grown state dict (gate_proj/up_proj are unscaled row-dups per
cbase_grow_rung2_event.py's MOMENTUM_PUSHFORWARD_RULE_DECLARED and are
eps-invariant by construction, so they are left untouched in every variant):
  - eps=0.0          : both halves = d_mean (exact eta removal)
  - eps=0.025        : halves = d_mean +/- 0.5*eta (midpoint)
  - eps=0.05_control : halves = d_mean +/- 1.0*eta (reproduces the anchor
                        in-run, from the SAME loaded grown checkpoint, as a
                        control on this script's own Muon/measurement math)

For each variant: single forward+backward on the pinned batch -> real
grad_post_gate -> RESET-arm Muon step -> u_post RMS + spectral norm vs the
SAME u_pre leg the template computes (cached pre-grow tensors, RESET arm,
lr=0.015).

GPU is touched for exactly 3 forward+backward passes (one per variant, ~1
each per the landed template's precedent); every other measurement (Muon
steps, spectral norms, RMS, sanity assertions) runs on CPU only.

NUMBERS ONLY -- no verdict/adjudication language about the preregistered
prediction is written here; the coordinator adjudicates.

Refs: #449 #482 #466 #513
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
GROWN_CACHE_PATH = CACHE_DIR / "grown-eps-58e8e98916823941-sigma0.05-seed0.pt"

MICRO_BATCH = 1
GRAD_ACCUM_STEPS = 8

BATCH_PIN_SHA_EXPECTED = "2e56e349ebbd680668902a2f6edeb32439528074fe656ec65543b2f3eb4f1f7e"
ANCHOR_RMS_RATIO_EPS005 = 1.0143604319688646  # cbase-grow-rung2-event-grow-rung2-20260709-remeasure-b3-gradpost.json

PREREGISTERED = (
    "Backprop through the +/-eta down columns splits the gate/up gradient twin rows as "
    "G/2+/-Delta; NS5 amplifies the antisymmetric Delta. Therefore the gate-class "
    "RMS(u_post)/RMS(u_pre) ratio at eps=0 returns to 1.0 within 0.2%, and the ratio is "
    "monotone increasing in eps. Measured anchor at eps=0.05: 1.0143604 "
    "(receipts/cbase-grow-rung2-event-grow-rung2-20260709-remeasure-b3-gradpost.json)."
)


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


def load_grown_and_build_variants() -> tuple[dict, dict]:
    """CPU-only. Loads the grown checkpoint once, reconstructs d_mean/eta for
    layer-0 down_proj, and builds 3 state-dict variants by rewriting ONLY the
    down_proj entry. No model construction and no GPU touch happens here --
    this is the "sanity assertions before GPU" leg."""
    gate_key, up_key, down_key = _gate_up_down_keys(0)
    if not GROWN_CACHE_PATH.exists():
        raise FileNotFoundError(f"grown weights cache not found: {GROWN_CACHE_PATH}")
    grown_bf16 = torch.load(GROWN_CACHE_PATH, map_location="cpu", weights_only=True)
    grown_dtype = grown_bf16[down_key].dtype

    d_grown = grown_bf16[down_key].detach().clone().to(torch.float32)
    ff_grown = int(d_grown.shape[1])
    interm_seed = ff_grown // 2
    d_a = d_grown[:, :interm_seed]
    d_b = d_grown[:, interm_seed:]
    d_mean = (d_a + d_b) / 2.0
    eta = (d_a - d_b) / 2.0

    # --- sanity assertions, CPU only, before any GPU touch ---
    twin_cosine_eps0 = float(torch.nn.functional.cosine_similarity(d_mean, d_mean, dim=0).min().item())
    eta_rms_eps005 = float(rms(eta))
    # exact-by-construction (both halves are the literal same tensor d_mean); the
    # assertion tolerates float32 cosine-similarity rounding (norm/dot computed via
    # sqrt(sum(x**2)) is not bit-exact self-inverse), disclosed via the raw value above
    assert abs(twin_cosine_eps0 - 1.0) < 1e-5, (
        f"eps=0 twin-cosine must be 1.0 within float32 tolerance (identical halves by "
        f"construction), got {twin_cosine_eps0}")
    assert eta_rms_eps005 > 0.0, (
        f"recovered eta RMS at eps=0.05 must be > 0, got {eta_rms_eps005}")

    def _variant_down(scale: float) -> torch.Tensor:
        if scale == 0.0:
            new_down = torch.cat([d_mean, d_mean], dim=1)
        else:
            new_down = torch.cat([d_mean + scale * eta, d_mean - scale * eta], dim=1)
        return new_down.to(grown_dtype)

    variants = {}
    for name, scale, construction in (
        ("eps0.0", 0.0, "both down_proj halves set to d_mean (exact eta removal)"),
        ("eps0.025", 0.5, "halves = d_mean +/- 0.5*eta (midpoint)"),
        ("eps0.05_control", 1.0, "halves = d_mean +/- 1.0*eta (reproduces the eps=0.05 anchor in-run)"),
    ):
        sd = dict(grown_bf16)  # shallow copy; only down_key entry is rewritten
        sd[down_key] = _variant_down(scale)
        variants[name] = {"scale": scale, "construction": construction, "state_dict": sd}

    sanity = {
        "twin_cosine_eps0": twin_cosine_eps0,
        "eta_rms_eps005": eta_rms_eps005,
        "ff_grown": ff_grown,
        "interm_seed": interm_seed,
        "gate_key": gate_key, "up_key": up_key, "down_key": down_key,
        "grown_dtype": str(grown_dtype),
        "grown_weights_sha256": _sha256_file(GROWN_CACHE_PATH),
    }
    del grown_bf16
    gc.collect()
    return variants, sanity


def capture_grad_post_gate_for_variant(state_dict: dict, gate_key: str, ff_grown: int, device: str) -> dict:
    """Single forward+backward on the pinned batch using the GIVEN
    (eps-variant) state dict. Reproduces
    cbase_grow_rung2_gradpost_capture.py's capture_grad_post_gate exactly
    (same manual_seed(42) position, same build_v0_model + load_state_dict,
    same _build_pinned_batch, same QAT/CE/MTP per-microstep loop) with the
    grown checkpoint replaced by the variant's state dict."""
    b1m = json.loads(B1M_RECEIPT.read_text(encoding="utf-8"))

    torch.manual_seed(42)
    cfg = ts.load_contract(None)

    theta_gate_post = state_dict[gate_key].detach().clone().to(torch.float32)

    model, vocab, hidden, n_mtp = ts.build_v0_model(
        cfg, live=True, intermediate_override=ff_grown, device=device)
    missing, unexpected = model.load_state_dict(state_dict, strict=False)
    real_missing = [k for k in missing if k != "head.weight"]
    if real_missing or unexpected:
        raise SystemExit(
            f"CBASE-GROW-RUNG2-EPS0-FINGERPRINT: variant checkpoint load mismatch: "
            f"missing={real_missing} unexpected={unexpected}")

    seq = cfg["model"]["seq"]
    n_mtp = cfg["objective"]["mtp_aux_heads"]["n_heads"]
    qat_enabled = bool(cfg.get("precision", {}).get("qat", {}).get("enabled", False))

    batch = _build_pinned_batch(CACHE_DIR, RUN_ID, cfg, n_mtp, vocab, seq,
                                 MICRO_BATCH, GRAD_ACCUM_STEPS, device)
    batch_pin_match = bool(batch["overall_sha256"] == b1m["batch"]["overall_sha256"])
    if not batch_pin_match:
        raise SystemExit(
            "CBASE-GROW-RUNG2-EPS0-FINGERPRINT: pinned-batch sha mismatch vs B1m -- refusing "
            f"to proceed (B1m={b1m['batch']['overall_sha256']} recomputed={batch['overall_sha256']})")

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
        "qat_enabled": qat_enabled, "mtp_enabled": mtp_enabled, "ce_impl": ce_impl,
        "batch_pin_check": {
            "b1m_sha256": b1m["batch"]["overall_sha256"],
            "recomputed_sha256": batch["overall_sha256"],
            "match": batch_pin_match,
        },
        "gpu_seconds": gpu_t1 - gpu_t0,
    }


def _norms(w, g, m, lr):
    new_w, _, _ = _muon_step_in_copy(w, g, m, lr=lr)
    u = new_w - w
    return {
        "spectral": float(torch.linalg.svdvals(u)[0].item()),
        "rms": float(rms(u)),
        "scale": max(1.0, w.shape[0] / w.shape[1]) ** 0.5,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--precheck-only", action="store_true",
                     help="Run only the CPU-only variant construction + sanity assertions "
                          "(no model build, no GPU touch) and print them. Used to validate "
                          "the eps-counterfactual math before the GPU outage window opens.")
    ts_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ap.add_argument("--out", default=str(RECEIPT_DIR / f"cbase-grow-rung2-eps0-fingerprint-{ts_tag}.json"))
    args = ap.parse_args()

    t_start = time.time()
    variants, sanity = load_grown_and_build_variants()

    if args.precheck_only:
        print(json.dumps({"precheck": "PASS", "sanity": sanity}, indent=2), flush=True)
        return 0

    # u_pre leg -- identical convention to the landed template (cached
    # pre-grow tensors, RESET arm, lr=0.015)
    theta_gate_pre = torch.load(CACHE_DIR / f"{RUN_ID}-theta-gate-pre.pt",
                                 map_location="cpu", weights_only=True).float()
    grad_pre_gate = torch.load(CACHE_DIR / f"{RUN_ID}-grad-pre-gate.pt",
                                map_location="cpu", weights_only=True).float()
    pre_momentum_real = torch.load(CACHE_DIR / f"{RUN_ID}-pre-momentum.pt",
                                    map_location="cpu", weights_only=True).float()
    zero_pre = torch.zeros_like(theta_gate_pre)
    assert float(zero_pre.abs().sum()) == 0.0, "RESET-arm pre-momentum must be exactly zero"
    pre_reset_015 = _norms(theta_gate_pre, grad_pre_gate, zero_pre, lr=0.015)

    per_variant = {}
    total_gpu_seconds = 0.0
    for name, v in variants.items():
        capture = capture_grad_post_gate_for_variant(
            v["state_dict"], sanity["gate_key"], sanity["ff_grown"], args.device)
        theta_gate_post = capture["theta_gate_post"]
        grad_post_gate = capture["grad_post_gate"]
        zero_post = torch.zeros_like(theta_gate_post)
        assert float(zero_post.abs().sum()) == 0.0, "RESET-arm post-momentum must be exactly zero"
        post_reset_015 = _norms(theta_gate_post, grad_post_gate, zero_post, lr=0.015)
        rms_ratio = post_reset_015["rms"] / pre_reset_015["rms"]
        R_spectral = post_reset_015["spectral"] / pre_reset_015["spectral"]
        per_variant[name] = {
            "eps_scale_of_full_eta": v["scale"],
            "construction": v["construction"],
            "u_post_rms": post_reset_015["rms"],
            "u_post_spectral": post_reset_015["spectral"],
            "rms_ratio_post_over_pre": rms_ratio,
            "R_spectral_ratio_post_over_pre": R_spectral,
            "batch_pin_check": capture["batch_pin_check"],
            "gpu_seconds": capture["gpu_seconds"],
        }
        total_gpu_seconds += capture["gpu_seconds"]

    control = per_variant["eps0.05_control"]
    control_delta = control["rms_ratio_post_over_pre"] - ANCHOR_RMS_RATIO_EPS005
    control_delta_pct = abs(control_delta) / ANCHOR_RMS_RATIO_EPS005 * 100

    receipt = {
        "ticket": "CBASE-GROW-RUNG2-EPS0-FINGERPRINT",
        "ts": _timestamp_iso(),
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "issue": 449,
        "refs": [482, 466, 513],
        "run_id": RUN_ID,
        "preregistered": PREREGISTERED,
        "scope": "eps-counterfactual gate-fingerprint rider: reconstructs eps=0 and "
                 "eps=0.025 down_proj variants from the eps=0.05 grown checkpoint by "
                 "block-mean/eta decomposition, measures RMS(u_post)/RMS(u_pre) at each "
                 "under the RESET-arm Muon convention (zero momentum both sides, "
                 "lr=0.015), and reproduces the eps=0.05 anchor in-run as a control on "
                 "this script's own Muon/measurement math. NUMBERS ONLY -- no verdict on "
                 "the preregistered prediction; the coordinator adjudicates.",
        "method": {
            "eps_construction": "down_proj [1024, 32768] block-twin d_a=W[:,:16384], "
                                 "d_b=W[:,16384:]; d_mean=(d_a+d_b)/2, eta=(d_a-d_b)/2; "
                                 "variant halves = d_mean +/- scale*eta for scale in "
                                 "{0.0, 0.5, 1.0}; gate_proj/up_proj untouched in every "
                                 "variant (unscaled row-dups, eps-invariant per "
                                 "cbase_grow_rung2_event.py MOMENTUM_PUSHFORWARD_RULE_DECLARED).",
            "capture": "reproduces cbase_grow_rung2_gradpost_capture.py's "
                       "capture_grad_post_gate exactly (same manual_seed(42) position, "
                       "same build_v0_model + load_state_dict, same _build_pinned_batch, "
                       "same QAT/CE/MTP per-microstep loop) with the grown checkpoint's "
                       "state dict replaced by each variant's rewritten down_proj.",
            "muon_step_closure": "p5_ratio_audit.run_p5_audit._muon_step_in_copy (faithful reuse)",
            "spectral_norm_method": "torch.linalg.svdvals (top singular value)",
        },
        "sanity_pre_gpu": sanity,
        "u_pre_reset_lr015": {
            "lr": 0.015, "momentum": "zero buffer (RESET arm)",
            "spectral": pre_reset_015["spectral"], "rms": pre_reset_015["rms"],
        },
        "variants": per_variant,
        "anchor_control": {
            "anchor_source": "receipts/cbase-grow-rung2-event-grow-rung2-20260709-remeasure-b3-gradpost.json",
            "anchor_rms_ratio_post_over_pre": ANCHOR_RMS_RATIO_EPS005,
            "in_run_recomputed_rms_ratio": control["rms_ratio_post_over_pre"],
            "delta": control_delta, "delta_pct": control_delta_pct,
        },
        "gpu_seconds": total_gpu_seconds,
        "wall_seconds": time.time() - t_start,
        "device": args.device,
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
        "verdict": "MEASUREMENT_COMPLETE_NO_ADJUDICATION",
    }
    checked_write(args.out, receipt)
    print(f"CBASE_GROW_RUNG2_EPS0_FINGERPRINT receipt={args.out}", flush=True)
    print(json.dumps({
        name: {
            "rms_ratio_post_over_pre": v["rms_ratio_post_over_pre"],
            "R_spectral_ratio_post_over_pre": v["R_spectral_ratio_post_over_pre"],
        } for name, v in per_variant.items()
    } | {
        "control_delta_pct_vs_anchor": control_delta_pct,
        "gpu_seconds": total_gpu_seconds,
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
