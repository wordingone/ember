#!/usr/bin/env python3
"""rider_a2_real_nullmodel_run.py -- issue #123 follow-up (coordinator comment
4930377425), leg 2 measurement: the REAL null model for the gate-class
R_spectral = sqrt(2) constant.

EXECUTION RULING (team-lead, 2026-07-10T00:3xZ): CPU, NOT GPU. llama-server is
resident at ~22.97/24.5 GiB VRAM -- the contended-launch gate would refuse any
GPU tenant at that margin. This forward+backward + Muon/NS5 + SVD pipeline is
CPU-tractable (device="cpu" is an explicitly supported real-architecture path
in ts.build_v0_model, used elsewhere for smoke checks); the model is ~2.23B
params so this will be slower than the GPU legs but not prohibitive. This
script touches NEITHER the GPU NOR the resident llama-server process at all --
no torch.cuda.* calls anywhere in this file.

IMPORTANT device-path fix: ts.resolve_ce_impl(prefer_liger=True) (the prior
GPU riders' default) would try to import and call Liger's fused-linear-CE
kernel, which is Triton/CUDA-only -- calling it on CPU tensors would crash at
the forward() call (the import itself succeeds, so the try/except in
resolve_ce_impl does NOT catch a device mismatch at call time). This script
forces prefer_liger=False to get the portable chunked_cross_entropy fallback,
which is pure PyTorch (matmul + log_softmax + gather) and CPU-safe.

Same base pipeline as rider_a_run.py (#123 permuted-twin rider), differing
ONLY in twin construction: instead of permuting the row PAIRING (which stays
inside the spectral/row-permutation invariance group -- confirmed VACUOUS by
the vacuity check, outcome (b)), this rider replaces each duplicated-row
pair's SECOND member with a genuinely random direction at the SAME per-row
norm (Frobenius norm matched) -- a perturbation that lies OUTSIDE the
invariance group (confirmed by cbase_grow_rung2_real_nullmodel_precheck.py, PASS).

Per team-lead's explicit instruction: run the twin measurement ONCE (no
repeat anchor_control GPU leg -- that leg is already executed and banked in
receipts/cbase-grow-rung2-nullmodel-permuted-twin-20260709T220710Z.json).
The anchor bands for the two PROMOTED alignment-sensitive instruments
(rms_ratio, min-per-row-cosine) are PINNED from that executed receipt and
from the CPU-only precheck receipt (min-per-row-cosine needs no GPU -- it is
a pure property of the constructed tensor, already measured). R_spectral's
band is the ORIGINAL frozen absolute-deviation-from-sqrt(2) band; it is
computed fresh here since it is the instrument under direct test.

Prediction registered BEFORE this run (frozen, verbatim, no adjustment):
  - if sqrt(2) tracks row-duplication STRUCTURE: R_spectral departs sqrt(2)
    by >=1% on this twin
  - if it stays within +/-0.1%: sqrt(2) is an NS5-plateau artifact at these
    shapes; Q1 is then ruled from the alignment-sensitive side only.

Refs: #123 #482 #466 #513 #591
"""
from __future__ import annotations

import gc
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import torch

REAL_REPO = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REAL_REPO / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
from receipt_write import checked_write  # noqa: E402
import timeshare_pretrain as ts  # noqa: E402
from p5_ratio_audit.run_p5_audit import _muon_step_in_copy, rms  # noqa: E402
from cbase_grow_rung2_event import _gate_up_down_keys, _build_pinned_batch  # noqa: E402
from cbase_grow_rung2_real_nullmodel_precheck import build_real_nullmodel_gate_variant, RANDOM_DIRECTION_SEED  # noqa: E402

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"

RUN_ID = "grow-rung2-20260709-remeasure"
WORKTREE = REAL_REPO / ".claude" / "worktrees" / "remeasure-466"
CACHE_DIR = WORKTREE / "receipts" / ".rung2-event-cache"
RECEIPT_DIR = REAL_REPO / "receipts"
SCRATCH_RECEIPT_DIR = REAL_REPO / "receipts"
B1M_RECEIPT = RECEIPT_DIR / f"cbase-grow-rung2-event-{RUN_ID}-b1m.json"
GROWN_CACHE_PATH = CACHE_DIR / "grown-eps-58e8e98916823941-sigma0.05-seed0.pt"

MICRO_BATCH = 1
GRAD_ACCUM_STEPS = 8
DEVICE = "cpu"  # team-lead execution ruling: do not touch the GPU or the server

BATCH_PIN_SHA_EXPECTED = "2e56e349ebbd680668902a2f6edeb32439528074fe656ec65543b2f3eb4f1f7e"
SQRT2 = 2.0 ** 0.5

# --- PINNED anchor bands for the two PROMOTED alignment-sensitive instruments,
# cited from the already-EXECUTED anchor legs -- NOT recomputed here (team-lead
# instruction: run the twin ONCE, no repeat anchor GPU leg). ---
PINNED_ANCHOR = {
    "rms_ratio_post_over_pre": {
        "value": 1.0145176101002584,
        "source": "receipts/cbase-grow-rung2-nullmodel-permuted-twin-20260709T220710Z.json"
                   " :: variants.anchor_control.rms_ratio_post_over_pre (executed anchor leg, unmodified checkpoint)",
    },
    "min_per_row_cosine": {
        "value": 1.0,
        "measured_value": 0.9999998211860657,
        "source": "scratch/riders591 rider_a_precheck.py :: min_cos_before_permutation "
                   "(row_dup_exact_pre_permutation=true was confirmed via torch.equal; "
                   "1.0 is the exact theoretical anchor for an unperturbed duplicate pair, "
                   "0.9999998... is the as-measured float value carried for full disclosure)",
    },
}

PREREGISTERED = (
    "If the sqrt(2) signature tracks row-duplication STRUCTURE, R_spectral departs "
    "sqrt(2) by >=1% on the random-direction twin (which lies outside the spectral/"
    "row-permutation invariance group, per cbase_grow_rung2_real_nullmodel_precheck.py PASS). "
    "If it stays within +/-0.1% of sqrt(2), the constant is an NS5-plateau artifact at "
    "these shapes and the flagship-demotion argument loses this instrument; Q1 is then "
    "ruled from the alignment-sensitive side only (rms_ratio, min-per-row-cosine, both "
    "pinned here from already-executed anchor legs). Between 0.1% and 1%: "
    "INCONCLUSIVE_BY_RULE, no interpretation attempted."
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


def capture_grad_post_gate_for_variant(state_dict: dict, gate_key: str, ff_grown: int, device: str) -> dict:
    """Faithful reproduction of rider_a_run.py's function of the same name
    (itself reproducing cbase_grow_rung2_gradpost_capture.py's
    capture_grad_post_gate exactly) -- unmodified, so this rider's methodology
    is byte-for-byte identical to the already-executed permuted-twin rider,
    differing only in which state_dict variant is passed in."""
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
            f"CBASE-GROW-RUNG2-REAL-NULLMODEL: variant checkpoint load mismatch: "
            f"missing={real_missing} unexpected={unexpected}")

    seq = cfg["model"]["seq"]
    n_mtp = cfg["objective"]["mtp_aux_heads"]["n_heads"]
    qat_enabled = bool(cfg.get("precision", {}).get("qat", {}).get("enabled", False))

    batch = _build_pinned_batch(CACHE_DIR, RUN_ID, cfg, n_mtp, vocab, seq,
                                 MICRO_BATCH, GRAD_ACCUM_STEPS, device)
    batch_pin_match = bool(batch["overall_sha256"] == b1m["batch"]["overall_sha256"])
    if not batch_pin_match:
        raise SystemExit(
            "CBASE-GROW-RUNG2-REAL-NULLMODEL: pinned-batch sha mismatch vs B1m -- "
            f"refusing to proceed (B1m={b1m['batch']['overall_sha256']} "
            f"recomputed={batch['overall_sha256']})")

    # prefer_liger=False (device="cpu" ruling): Liger FLCE is Triton/CUDA-only
    # and would crash calling into it with CPU tensors; the portable
    # chunked_cross_entropy fallback is pure PyTorch and CPU-safe.
    ce_impl, ce_fn = ts.resolve_ce_impl(prefer_liger=False)
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
    t_start = time.time()
    if not GROWN_CACHE_PATH.exists():
        print(json.dumps({"status": "MISSING_INPUT", "missing": str(GROWN_CACHE_PATH)}))
        return 1

    assert DEVICE == "cpu", "execution ruling: CPU only, do not touch the GPU or the server"

    gate_key, up_key, down_key = _gate_up_down_keys(0)
    grown = torch.load(GROWN_CACHE_PATH, map_location="cpu", weights_only=True)
    ff_grown = int(grown[gate_key].shape[0])
    grown_weights_sha256 = _sha256_file(GROWN_CACHE_PATH)

    new_gate, construction_provenance, ga, gb, gb_random, original_row_norms = build_real_nullmodel_gate_variant(grown, gate_key)

    variant_state_dict = {**dict(grown), gate_key: new_gate}
    variant_construction = ("gate_proj second-half rows replaced with a random direction at the SAME "
                             "per-row L2 norm (seed=%d); first half + up_proj/down_proj unchanged; "
                             "construction lies OUTSIDE the spectral/row-permutation invariance group "
                             "(precheck-confirmed: outside_spectral_invariance_group=true)" % RANDOM_DIRECTION_SEED)

    # u_pre leg -- identical convention to rider_a_run.py (cached pre-grow
    # tensors, RESET arm, lr=0.015); shared across variants, not construction-dependent.
    theta_gate_pre = torch.load(CACHE_DIR / f"{RUN_ID}-theta-gate-pre.pt",
                                 map_location="cpu", weights_only=True).float()
    grad_pre_gate = torch.load(CACHE_DIR / f"{RUN_ID}-grad-pre-gate.pt",
                                map_location="cpu", weights_only=True).float()
    zero_pre = torch.zeros_like(theta_gate_pre)
    assert float(zero_pre.abs().sum()) == 0.0, "RESET-arm pre-momentum must be exactly zero"
    pre_reset_015 = _norms(theta_gate_pre, grad_pre_gate, zero_pre, lr=0.015)

    capture = capture_grad_post_gate_for_variant(variant_state_dict, gate_key, ff_grown, DEVICE)
    theta_gate_post = capture["theta_gate_post"]
    grad_post_gate = capture["grad_post_gate"]
    zero_post = torch.zeros_like(theta_gate_post)
    assert float(zero_post.abs().sum()) == 0.0, "RESET-arm post-momentum must be exactly zero"
    post_reset_015 = _norms(theta_gate_post, grad_post_gate, zero_post, lr=0.015)

    rms_ratio = post_reset_015["rms"] / pre_reset_015["rms"]
    R_spectral = post_reset_015["spectral"] / pre_reset_015["spectral"]

    deviation_from_sqrt2 = R_spectral - SQRT2
    deviation_pct = abs(deviation_from_sqrt2) / SQRT2 * 100
    if deviation_pct <= 0.1:
        band_verdict = "KILL_NS5_PLATEAU_ARTIFACT"
    elif deviation_pct > 1.0:
        band_verdict = "PROMOTE_STRUCTURE_TRACKING_CONFIRMED"
    else:
        band_verdict = "INCONCLUSIVE_BY_RULE"

    rms_ratio_vs_anchor_pct = abs(rms_ratio - PINNED_ANCHOR["rms_ratio_post_over_pre"]["value"]) / PINNED_ANCHOR["rms_ratio_post_over_pre"]["value"] * 100
    # min-per-row-cosine for the twin needs no GPU -- pure property of the
    # constructed tensor, already measured in the CPU-only precheck.
    min_per_row_cosine_twin = float(torch.nn.functional.cosine_similarity(gb_random, gb, dim=1).min().item())

    receipt = {
        "ticket": "CBASE-GROW-RUNG2-REAL-NULLMODEL",
        "ts": _timestamp_iso(),
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "issue": 123,
        "refs": [449, 482, 466, 513, 591],
        "run_id": RUN_ID,
        "preregistered": PREREGISTERED,
        "scope": "REAL null-model rider for the sqrt(2) gate-class R_spectral constant, "
                 "constructed OUTSIDE the spectral/row-permutation invariance group "
                 "(random-direction replacement at matched per-row norm), per the "
                 "vacuity-check follow-up on the permuted-twin KILL (outcome b, "
                 "VACUOUS by spectral invariance). One CPU leg only (the twin); the "
                 "anchor bands for the two promoted alignment-sensitive instruments "
                 "are PINNED from already-executed receipts, not recomputed.",
        "execution_ruling": "CPU, not GPU (team-lead, 2026-07-10) -- llama-server resident at "
                             "~22.97/24.5 GiB VRAM, contended-launch gate would refuse any GPU "
                             "tenant at that margin; this pipeline is CPU-tractable. No "
                             "torch.cuda.* calls anywhere in this script.",
        "construction_provenance": construction_provenance,
        "grown_weights_sha256": grown_weights_sha256,
        "variant_construction": variant_construction,
        "u_pre_reset_lr015": {
            "lr": 0.015, "momentum": "zero buffer (RESET arm)",
            "spectral": pre_reset_015["spectral"], "rms": pre_reset_015["rms"],
        },
        "real_nullmodel_twin": {
            "u_post_rms": post_reset_015["rms"],
            "u_post_spectral": post_reset_015["spectral"],
            "rms_ratio_post_over_pre": rms_ratio,
            "R_spectral_ratio_post_over_pre": R_spectral,
            "min_per_row_cosine": min_per_row_cosine_twin,
            "batch_pin_check": capture["batch_pin_check"],
            "compute_seconds_cpu": capture["gpu_seconds"],
        },
        "pinned_anchor_bands": PINNED_ANCHOR,
        "instrument_assessment": {
            "R_spectral": {
                "sqrt2": SQRT2,
                "twin_value": R_spectral,
                "deviation_from_sqrt2": deviation_from_sqrt2,
                "deviation_pct": deviation_pct,
                "kill_band": "deviation_pct <= 0.1 (NS5-plateau artifact)",
                "promote_band": "deviation_pct > 1.0 (structure-tracking confirmed)",
                "inconclusive_band": "0.1 < deviation_pct <= 1.0",
                "band_verdict": band_verdict,
            },
            "rms_ratio": {
                "anchor_value": PINNED_ANCHOR["rms_ratio_post_over_pre"]["value"],
                "twin_value": rms_ratio,
                "abs_pct_diff_vs_anchor": rms_ratio_vs_anchor_pct,
            },
            "min_per_row_cosine": {
                "anchor_value": PINNED_ANCHOR["min_per_row_cosine"]["value"],
                "twin_value": min_per_row_cosine_twin,
            },
        },
        "compute_seconds_cpu": capture["gpu_seconds"],
        "wall_seconds": time.time() - t_start,
        "device": DEVICE,
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
        "verdict": "MEASUREMENT_COMPLETE_NO_MECHANISM_ADJUDICATION",
    }
    ts_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = SCRATCH_RECEIPT_DIR / f"cbase-grow-rung2-real-nullmodel-{ts_tag}.json"
    SCRATCH_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
    print(f"CBASE_GROW_RUNG2_REAL_NULLMODEL receipt={out_path}", flush=True)
    print(json.dumps({
        "R_spectral_twin": R_spectral,
        "deviation_pct": deviation_pct,
        "band_verdict": band_verdict,
        "rms_ratio_twin": rms_ratio,
        "rms_ratio_anchor": PINNED_ANCHOR["rms_ratio_post_over_pre"]["value"],
        "min_per_row_cosine_twin": min_per_row_cosine_twin,
        "min_per_row_cosine_anchor": PINNED_ANCHOR["min_per_row_cosine"]["value"],
        "compute_seconds_cpu": capture["gpu_seconds"],
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
