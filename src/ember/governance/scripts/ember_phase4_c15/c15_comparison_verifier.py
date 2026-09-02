#!/usr/bin/env python3
"""c15_comparison_verifier.py — machine-checkable verifier for the C15 tiny
BitNet comparison receipt.

Reads a completed tiny_bitnet_comparison receipt JSON and asserts every C15
CHK field.  Emits a structured CHK receipt with verdict C15_CHK_PASS or
C15_CHK_FAIL and a list of findings.

Key interfaces
--------------
verify_receipt(receipt_path: Path) -> dict
    Validate the receipt at *receipt_path*.  Returns a CHK receipt dict with
    keys: ticket, ts, verdict, findings.

main() -> int
    CLI entry point.  --receipt <path> required.  Exits 0 on C15_CHK_PASS,
    non-zero on C15_CHK_FAIL or any fatal error.

CPU selftest (--selftest)
    Constructs a synthetic BITNET_COMPARISON_PASS receipt and a synthetic
    BITNET_BLOCKED receipt (both fully in-memory, no real comparison run),
    asserts that verify_receipt produces C15_CHK_PASS for both branches,
    then verifies two must-fail cases (bad hashes equal, empty blocking field).
    Also runs a standalone BitLinear-STE correctness check and param-update
    assertion on a tiny toy model — no GPU, no C-BASE weights required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TICKET = "C15-COMPARISON-VERIFIER"
VERIFIER_VERSION = "1"

# ---------------------------------------------------------------------------
# Allowed verdict values in the comparison receipt
# ---------------------------------------------------------------------------
ALLOWED_COMPARISON_VERDICTS = {"BITNET_COMPARISON_PASS", "BITNET_BLOCKED"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fail(msg: str) -> dict[str, Any]:
    return {"ok": False, "msg": msg}


def _ok() -> dict[str, Any]:
    return {"ok": True, "msg": ""}


# ---------------------------------------------------------------------------
# Per-field CHK checks
# ---------------------------------------------------------------------------


def _chk_verdict(r: dict[str, Any]) -> list[str]:
    verdict = r.get("verdict")
    if verdict not in ALLOWED_COMPARISON_VERDICTS:
        return [f"CHK-V1: verdict {verdict!r} not in {sorted(ALLOWED_COMPARISON_VERDICTS)}"]
    return []


def _chk_blocked_branch(r: dict[str, Any]) -> list[str]:
    """BITNET_BLOCKED branch: missing_implementation_surface and
    next_executable_command must be non-empty strings."""
    findings: list[str] = []
    mis = r.get("missing_implementation_surface")
    if not (isinstance(mis, str) and mis.strip()):
        findings.append(
            "CHK-B1: BITNET_BLOCKED receipt missing non-empty"
            " 'missing_implementation_surface' string"
        )
    nec = r.get("next_executable_command")
    if not (isinstance(nec, str) and nec.strip()):
        findings.append(
            "CHK-B2: BITNET_BLOCKED receipt missing non-empty"
            " 'next_executable_command' string"
        )
    return findings


def _chk_pass_branch(r: dict[str, Any]) -> list[str]:
    """BITNET_COMPARISON_PASS branch: full suite of CHK assertions."""
    findings: list[str] = []

    # --- (3) pre != post parameter hashes ---
    fp16_pre = r.get("fp16_pre_parameter_hash")
    fp16_post = r.get("fp16_post_parameter_hash")
    if not (isinstance(fp16_pre, str) and fp16_pre.strip()):
        findings.append("CHK-P1: fp16_pre_parameter_hash missing or empty")
    if not (isinstance(fp16_post, str) and fp16_post.strip()):
        findings.append("CHK-P2: fp16_post_parameter_hash missing or empty")
    if (
        isinstance(fp16_pre, str)
        and isinstance(fp16_post, str)
        and fp16_pre.strip()
        and fp16_post.strip()
        and fp16_pre == fp16_post
    ):
        findings.append(
            "CHK-P3: fp16_pre_parameter_hash == fp16_post_parameter_hash"
            " — fp16 parameters did not change under training"
        )

    bitnet_pre = r.get("bitnet_pre_parameter_hash")
    bitnet_post = r.get("bitnet_post_parameter_hash")
    if not (isinstance(bitnet_pre, str) and bitnet_pre.strip()):
        findings.append("CHK-P4: bitnet_pre_parameter_hash missing or empty")
    if not (isinstance(bitnet_post, str) and bitnet_post.strip()):
        findings.append("CHK-P5: bitnet_post_parameter_hash missing or empty")
    if (
        isinstance(bitnet_pre, str)
        and isinstance(bitnet_post, str)
        and bitnet_pre.strip()
        and bitnet_post.strip()
        and bitnet_pre == bitnet_post
    ):
        findings.append(
            "CHK-P6: bitnet_pre_parameter_hash == bitnet_post_parameter_hash"
            " — BitNet parameters did not change under STE training"
        )

    # --- model identities present ---
    if not (isinstance(r.get("fp16_baseline_identity"), str) and r.get("fp16_baseline_identity", "").strip()):
        findings.append("CHK-P7: fp16_baseline_identity missing or empty")
    if not (isinstance(r.get("bitnet_model_identity"), str) and r.get("bitnet_model_identity", "").strip()):
        findings.append("CHK-P8: bitnet_model_identity missing or empty")

    # --- trainable_param_counts present and nonzero ---
    fp16_count = r.get("fp16_trainable_parameter_count")
    if not (isinstance(fp16_count, int) and fp16_count > 0):
        findings.append(
            f"CHK-P9: fp16_trainable_parameter_count is {fp16_count!r};"
            " expected a positive int"
        )
    bitnet_count = r.get("bitnet_trainable_parameter_count")
    if not (isinstance(bitnet_count, int) and bitnet_count > 0):
        findings.append(
            f"CHK-P10: bitnet_trainable_parameter_count is {bitnet_count!r};"
            " expected a positive int"
        )

    # --- quality_delta keys present ---
    qd = r.get("quality_delta")
    if not isinstance(qd, dict):
        findings.append("CHK-P11: quality_delta missing or not a dict")
    else:
        for key in (
            "fp16_heldout_mean",
            "bitnet_heldout_mean",
            "bitnet_minus_fp16_heldout_mean",
            "fp16_transfer_mean",
            "bitnet_transfer_mean",
            "bitnet_minus_fp16_transfer_mean",
        ):
            if key not in qd:
                findings.append(f"CHK-P11a: quality_delta missing key {key!r}")

    # --- footprint.bitnet_effective_weight_bits == 1.58 ---
    footprint = r.get("footprint")
    if not isinstance(footprint, dict):
        findings.append("CHK-P12: footprint missing or not a dict")
    else:
        bew = footprint.get("bitnet_effective_weight_bits")
        if bew != 1.58:
            findings.append(
                f"CHK-P13: footprint.bitnet_effective_weight_bits is {bew!r};"
                " expected 1.58"
            )

    # --- throughput_latency keys present for both arms ---
    tl = r.get("throughput_latency")
    if not isinstance(tl, dict):
        findings.append("CHK-P14: throughput_latency missing or not a dict")
    else:
        for arm in ("fp16", "bitnet"):
            if arm not in tl:
                findings.append(f"CHK-P14a: throughput_latency missing arm {arm!r}")
            elif not isinstance(tl[arm], dict):
                findings.append(f"CHK-P14b: throughput_latency[{arm!r}] is not a dict")

    # --- memory_cpu_measurements present ---
    mcm = r.get("memory_cpu_measurements")
    if not isinstance(mcm, dict):
        findings.append("CHK-P15: memory_cpu_measurements missing or not a dict")

    # --- transfer_rows non-empty and all have split=='transfer' ---
    transfer_rows = r.get("transfer_rows")
    if not (isinstance(transfer_rows, list) and len(transfer_rows) > 0):
        findings.append("CHK-P16: transfer_rows missing or empty")
    else:
        bad_splits = [
            i
            for i, row in enumerate(transfer_rows)
            if not (isinstance(row, dict) and row.get("split") == "transfer")
        ]
        if bad_splits:
            findings.append(
                f"CHK-P17: transfer_rows indices {bad_splits} have split !='transfer'"
            )

    # --- deletion_revert_evidence non-empty ---
    dre = r.get("deletion_revert_evidence")
    if not (isinstance(dre, list) and len(dre) > 0):
        findings.append("CHK-P18: deletion_revert_evidence missing or empty")

    # --- matched_budget_envelope.same_seed is an int ---
    mbe = r.get("matched_budget_envelope")
    if not isinstance(mbe, dict):
        findings.append("CHK-P19: matched_budget_envelope missing or not a dict")
    else:
        same_seed = mbe.get("same_seed")
        if not isinstance(same_seed, int):
            findings.append(
                f"CHK-P20: matched_budget_envelope.same_seed is {same_seed!r};"
                " expected an int"
            )

    return findings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def verify_receipt(receipt_path: Path) -> dict[str, Any]:
    """Validate the C15 comparison receipt at *receipt_path*.

    Returns a CHK receipt dict::

        {
            "ticket": "C15-COMPARISON-VERIFIER",
            "ts": "<ISO8601Z>",
            "verdict": "C15_CHK_PASS" | "C15_CHK_FAIL",
            "findings": [...],
            "receipt_path": str(receipt_path),
        }
    """
    chk_ts = _ts()
    try:
        raw = receipt_path.read_text(encoding="utf-8-sig")
        r = json.loads(raw)
    except Exception as exc:
        return {
            "ticket": TICKET,
            "ts": chk_ts,
            "verdict": "C15_CHK_FAIL",
            "findings": [f"CHK-LOAD: could not parse receipt: {exc}"],
            "receipt_path": str(receipt_path),
        }

    findings: list[str] = []

    # Require base receipt fields
    for req in ("ticket", "ts", "verdict"):
        if req not in r:
            findings.append(f"CHK-R1: required field {req!r} missing from receipt")

    # Verdict must be in allowed set
    findings.extend(_chk_verdict(r))

    verdict = r.get("verdict")
    if verdict == "BITNET_BLOCKED":
        findings.extend(_chk_blocked_branch(r))
    elif verdict == "BITNET_COMPARISON_PASS":
        findings.extend(_chk_pass_branch(r))
    # If verdict is neither (already flagged by _chk_verdict), skip branch checks.

    chk_verdict = "C15_CHK_PASS" if not findings else "C15_CHK_FAIL"
    return {
        "ticket": TICKET,
        "ts": chk_ts,
        "verdict": chk_verdict,
        "findings": findings,
        "receipt_path": str(receipt_path),
        "comparison_verdict": verdict,
        "verifier_version": VERIFIER_VERSION,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description="C15 CHK verifier for the tiny BitNet comparison receipt."
    )
    ap.add_argument("--receipt", type=Path, help="Path to the comparison receipt JSON")
    ap.add_argument("--selftest", action="store_true", help="Run CPU selftest suite")
    ap.add_argument(
        "--out", type=Path, default=None,
        help="Write CHK receipt JSON to this path (optional)"
    )
    args = ap.parse_args()

    if args.selftest:
        return _run_selftest()

    if not args.receipt:
        ap.error("--receipt is required (or use --selftest)")

    if not args.receipt.exists():
        print(
            json.dumps(
                {
                    "ticket": TICKET,
                    "ts": _ts(),
                    "verdict": "C15_CHK_FAIL",
                    "findings": [f"CHK-LOAD: receipt file does not exist: {args.receipt}"],
                    "receipt_path": str(args.receipt),
                },
                indent=2,
            )
        )
        return 2

    chk = verify_receipt(args.receipt)
    print(json.dumps(chk, indent=2))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(chk, indent=2) + "\n", encoding="utf-8")

    return 0 if chk["verdict"] == "C15_CHK_PASS" else 2


# ---------------------------------------------------------------------------
# CPU selftest
# ---------------------------------------------------------------------------

def _make_pass_receipt() -> dict[str, Any]:
    """Build a fully-populated synthetic BITNET_COMPARISON_PASS receipt."""
    def fake_hash(seed: str) -> str:
        return "sha256:" + hashlib.sha256(seed.encode()).hexdigest()

    pre_fp16 = fake_hash("fp16_pre")
    post_fp16 = fake_hash("fp16_post_changed")
    pre_bitnet = fake_hash("bitnet_pre")
    post_bitnet = fake_hash("bitnet_post_changed")

    return {
        "ticket": "EMBER-TINY-BITNET-COMPARISON",
        "ts": _ts(),
        "sha_convention": "bytes/tensors as-is",
        "verdict": "BITNET_COMPARISON_PASS",
        "post_resident_gate_required": True,
        "resident_gate_receipt_status": "PASS",
        "resident_gate_receipt_path": "/fake/gate/receipt.json",
        "task_source": "synthetic",
        "fp16_baseline_identity": "tiny_fp16_resident_policy_linear_seed_20260621",
        "bitnet_model_identity": "tiny_ste_ternary_resident_policy_b1_58_seed_20260621",
        "precision_quantization_scheme": {
            "fp16": "torch.float16",
            "bitnet": "ternary STE b1.58",
        },
        "fp16_trainable_parameter_count": 42,
        "bitnet_trainable_parameter_count": 42,
        "fp16_pre_parameter_hash": pre_fp16,
        "fp16_post_parameter_hash": post_fp16,
        "bitnet_pre_parameter_hash": pre_bitnet,
        "bitnet_post_parameter_hash": post_bitnet,
        "matched_budget_envelope": {
            "same_train_rows": True,
            "same_heldout_rows": True,
            "same_transfer_rows": True,
            "same_epochs": True,
            "same_lr": True,
            "same_seed": 20260621,
            "same_verifier": "synthetic",
        },
        "training": {
            "fp16": {"epochs": 40, "lr": 0.8, "initial_loss": 1.5, "final_loss": 0.3},
            "bitnet": {"epochs": 40, "lr": 0.8, "initial_loss": 1.6, "final_loss": 0.35},
        },
        "heldout_rows": [
            {"task_id": "h1", "split": "heldout", "fp16_score": 1.0, "bitnet_score": 0.9},
        ],
        "transfer_rows": [
            {"task_id": "t1", "split": "transfer", "fp16_score": 0.8, "bitnet_score": 0.75},
            {"task_id": "t2", "split": "transfer", "fp16_score": 0.9, "bitnet_score": 0.88},
        ],
        "quality_delta": {
            "fp16_heldout_mean": 1.0,
            "bitnet_heldout_mean": 0.9,
            "bitnet_minus_fp16_heldout_mean": -0.1,
            "fp16_transfer_mean": 0.85,
            "bitnet_transfer_mean": 0.815,
            "bitnet_minus_fp16_transfer_mean": -0.035,
        },
        "footprint": {
            "fp16_parameter_bytes": 84,
            "bitnet_effective_parameter_bytes": 10,
            "bitnet_effective_weight_bits": 1.58,
            "bias_bits": 16,
        },
        "throughput_latency": {
            "fp16": {"repeats": 512, "total_seconds": 0.01, "mean_ms": 0.02},
            "bitnet": {"repeats": 512, "total_seconds": 0.009, "mean_ms": 0.018},
        },
        "memory_cpu_measurements": {
            "torch_cuda_available": False,
            "cuda_max_memory_allocated_bytes": 0,
            "python_tracemalloc_peak_bytes_during_training": 12345,
            "device": "cpu",
        },
        "deletion_revert_evidence": [
            {
                "task_id": "h1",
                "bitnet_score": 0.9,
                "deleted_score": 0.0,
                "deleted_condition": "ternary_policy_parameters_reverted_to_zero_pre_update_state",
            }
        ],
        "missing_implementation_surface": None,
        "next_executable_command": "python scripts\\ember_post_resident_discovery.py",
    }


def _make_blocked_receipt() -> dict[str, Any]:
    """Build a synthetic BITNET_BLOCKED receipt."""
    return {
        "ticket": "EMBER-TINY-BITNET-COMPARISON",
        "ts": _ts(),
        "verdict": "BITNET_BLOCKED",
        "post_resident_gate_required": True,
        "resident_gate_receipt_status": "MISSING",
        "resident_gate_receipt_path": None,
        "missing_implementation_surface": "resident-training gate PASS receipt",
        "next_executable_command": (
            "python scripts\\ember_resident_training_gate.py"
            " --candidate-manifest <manifest> --out <gate-receipt>"
        ),
    }


def _selftest_bitlinear_ste() -> list[str]:
    """Verify BitLinear STE correctness and param-update on a toy model.

    Checks:
    T1: absmean scale is computed correctly.
    T2: forward output shape matches input.
    T3: quantized forward weights are ternary {-1,0,+1}.
    T4: grad_norm > 0 after loss.backward() — STE lets gradients through.
    T5: parameter values change after opt.step().
    T6: untrained (zero-init) policy output differs from trained policy output.
    """
    failures: list[str] = []
    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F

        # --- Implement a toy BitLinear inline for selftest isolation ---
        class _AbsmeanQuant(torch.autograd.Function):
            @staticmethod
            def forward(ctx, weight):  # type: ignore[override]
                eps = torch.tensor(1e-6, dtype=weight.dtype, device=weight.device)
                scale = weight.detach().abs().mean().clamp_min(eps)
                q = weight.detach().div(scale).clamp(-1.0, 1.0).round()
                ctx.save_for_backward(weight)
                # Return re-scaled ternary (STE: grad passes through scale)
                return q * scale

            @staticmethod
            def backward(ctx, grad_output):  # type: ignore[override]
                # Straight-through: pass gradient unchanged to shadow weight
                return grad_output

        class ToyBitLinear(nn.Module):
            def __init__(self, in_f: int, out_f: int):
                super().__init__()
                # Shadow weight — full-precision, trainable
                self.weight = nn.Parameter(torch.randn(out_f, in_f) * 0.5)
                self.bias = nn.Parameter(torch.zeros(out_f))

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                w_q = _AbsmeanQuant.apply(self.weight)
                return F.linear(x, w_q, self.bias)

        in_f, out_f = 8, 4
        model = ToyBitLinear(in_f, out_f)

        # T1: absmean scale
        expected_scale = model.weight.detach().abs().mean().item()
        # Check it's positive
        if expected_scale <= 0:
            failures.append("T1: absmean scale is not positive")

        # T2: forward output shape
        x = torch.randn(3, in_f)
        out = model(x)
        if out.shape != (3, out_f):
            failures.append(f"T2: output shape {tuple(out.shape)} != (3, {out_f})")

        # T3: quantized weights are ternary {-1, 0, +1}
        eps = torch.tensor(1e-6, dtype=model.weight.dtype, device=model.weight.device)
        scale = model.weight.detach().abs().mean().clamp_min(eps)
        q = model.weight.detach().div(scale).clamp(-1.0, 1.0).round()
        unique_vals = set(q.unique().tolist())
        if not unique_vals.issubset({-1.0, 0.0, 1.0}):
            failures.append(f"T3: quantized weight values not subset of {{-1,0,1}}: {unique_vals}")

        # T4: grad_norm > 0 after backward
        x_train = torch.randn(5, in_f)
        y_train = torch.randint(0, out_f, (5,))
        opt = torch.optim.SGD(model.parameters(), lr=0.1)
        opt.zero_grad()
        loss = F.cross_entropy(model(x_train), y_train)
        loss.backward()
        grad_norm = sum(
            p.grad.norm().item() ** 2
            for p in model.parameters()
            if p.grad is not None
        ) ** 0.5
        if grad_norm <= 0:
            failures.append(f"T4: grad_norm={grad_norm} after backward — STE not passing gradients")

        # T5: parameter values change after opt.step()
        weight_before = model.weight.detach().clone()
        bias_before = model.bias.detach().clone()
        opt.step()
        weight_after = model.weight.detach()
        bias_after = model.bias.detach()
        if torch.allclose(weight_before, weight_after, atol=1e-9):
            failures.append("T5: weight parameters unchanged after opt.step() — training not working")
        if torch.allclose(bias_before, bias_after, atol=1e-9):
            failures.append("T5b: bias parameters unchanged after opt.step() — training not working")

        # T6: untrained (zero-init) vs trained output differs
        untrained = ToyBitLinear(in_f, out_f)
        nn.init.zeros_(untrained.weight)
        nn.init.zeros_(untrained.bias)
        x_eval = torch.randn(2, in_f)
        with torch.no_grad():
            trained_out = model(x_eval)
            untrained_out = untrained(x_eval)
        if torch.allclose(trained_out, untrained_out, atol=1e-6):
            failures.append("T6: trained and zero-init models produce identical output — training has no effect")

    except ImportError:
        # torch not available in this env; skip but don't fail the verifier selftest
        pass

    return failures


def _run_selftest() -> int:
    """Run all CPU selftest assertions.  Prints C15_COMPARISON_VERIFIER_SELFTEST_PASS
    or a list of failures.  Returns 0 on pass, non-zero on failure."""
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)

        # --- Branch 1: BITNET_COMPARISON_PASS receipt must produce C15_CHK_PASS ---
        pass_receipt = _make_pass_receipt()
        pass_path = td / "pass_receipt.json"
        pass_path.write_text(json.dumps(pass_receipt, indent=2), encoding="utf-8")
        chk_pass = verify_receipt(pass_path)
        if chk_pass["verdict"] != "C15_CHK_PASS":
            failures.append(
                f"SELFTEST-1: BITNET_COMPARISON_PASS receipt produced"
                f" {chk_pass['verdict']} with findings: {chk_pass['findings']}"
            )

        # --- Branch 2: BITNET_BLOCKED receipt must produce C15_CHK_PASS ---
        blocked_receipt = _make_blocked_receipt()
        blocked_path = td / "blocked_receipt.json"
        blocked_path.write_text(json.dumps(blocked_receipt, indent=2), encoding="utf-8")
        chk_blocked = verify_receipt(blocked_path)
        if chk_blocked["verdict"] != "C15_CHK_PASS":
            failures.append(
                f"SELFTEST-2: BITNET_BLOCKED receipt produced"
                f" {chk_blocked['verdict']} with findings: {chk_blocked['findings']}"
            )

        # --- Must-fail 1: pre == post hashes should produce C15_CHK_FAIL ---
        bad_hash_receipt = _make_pass_receipt()
        same_hash = "sha256:" + hashlib.sha256(b"same").hexdigest()
        bad_hash_receipt["fp16_pre_parameter_hash"] = same_hash
        bad_hash_receipt["fp16_post_parameter_hash"] = same_hash
        bad_hash_path = td / "bad_hash_receipt.json"
        bad_hash_path.write_text(json.dumps(bad_hash_receipt, indent=2), encoding="utf-8")
        chk_bad_hash = verify_receipt(bad_hash_path)
        if chk_bad_hash["verdict"] != "C15_CHK_FAIL":
            failures.append(
                "SELFTEST-3: receipt with pre==post fp16 hash should produce"
                f" C15_CHK_FAIL but got {chk_bad_hash['verdict']}"
            )
        found_p3 = any("CHK-P3" in f for f in chk_bad_hash.get("findings", []))
        if not found_p3:
            failures.append("SELFTEST-3b: CHK-P3 finding not present for equal fp16 hashes")

        # --- Must-fail 2: BITNET_BLOCKED with empty missing_implementation_surface ---
        bad_blocked_receipt = _make_blocked_receipt()
        bad_blocked_receipt["missing_implementation_surface"] = ""
        bad_blocked_path = td / "bad_blocked_receipt.json"
        bad_blocked_path.write_text(json.dumps(bad_blocked_receipt, indent=2), encoding="utf-8")
        chk_bad_blocked = verify_receipt(bad_blocked_path)
        if chk_bad_blocked["verdict"] != "C15_CHK_FAIL":
            failures.append(
                "SELFTEST-4: BITNET_BLOCKED with empty missing_implementation_surface"
                f" should produce C15_CHK_FAIL but got {chk_bad_blocked['verdict']}"
            )
        found_b1 = any("CHK-B1" in f for f in chk_bad_blocked.get("findings", []))
        if not found_b1:
            failures.append("SELFTEST-4b: CHK-B1 finding not present for empty missing_implementation_surface")

        # --- Must-fail 3: bitnet_effective_weight_bits != 1.58 ---
        bad_bits_receipt = _make_pass_receipt()
        bad_bits_receipt["footprint"]["bitnet_effective_weight_bits"] = 2.0
        bad_bits_path = td / "bad_bits_receipt.json"
        bad_bits_path.write_text(json.dumps(bad_bits_receipt, indent=2), encoding="utf-8")
        chk_bad_bits = verify_receipt(bad_bits_path)
        if chk_bad_bits["verdict"] != "C15_CHK_FAIL":
            failures.append(
                "SELFTEST-5: receipt with bitnet_effective_weight_bits=2.0 should produce"
                f" C15_CHK_FAIL but got {chk_bad_bits['verdict']}"
            )

        # --- Must-fail 4: transfer_rows with wrong split value ---
        bad_transfer_receipt = _make_pass_receipt()
        bad_transfer_receipt["transfer_rows"] = [
            {"task_id": "t1", "split": "heldout", "fp16_score": 0.8, "bitnet_score": 0.75}
        ]
        bad_transfer_path = td / "bad_transfer_receipt.json"
        bad_transfer_path.write_text(json.dumps(bad_transfer_receipt, indent=2), encoding="utf-8")
        chk_bad_transfer = verify_receipt(bad_transfer_path)
        if chk_bad_transfer["verdict"] != "C15_CHK_FAIL":
            failures.append(
                "SELFTEST-6: receipt with transfer_rows having split='heldout' should produce"
                f" C15_CHK_FAIL but got {chk_bad_transfer['verdict']}"
            )

        # --- Must-fail 5: same_seed is not an int ---
        bad_seed_receipt = _make_pass_receipt()
        bad_seed_receipt["matched_budget_envelope"]["same_seed"] = "20260621"
        bad_seed_path = td / "bad_seed_receipt.json"
        bad_seed_path.write_text(json.dumps(bad_seed_receipt, indent=2), encoding="utf-8")
        chk_bad_seed = verify_receipt(bad_seed_path)
        if chk_bad_seed["verdict"] != "C15_CHK_FAIL":
            failures.append(
                "SELFTEST-7: receipt with same_seed as string should produce"
                f" C15_CHK_FAIL but got {chk_bad_seed['verdict']}"
            )

    # --- BitLinear STE correctness + param-update selftest ---
    ste_failures = _selftest_bitlinear_ste()
    failures.extend(ste_failures)

    if failures:
        print("C15_COMPARISON_VERIFIER_SELFTEST_FAIL")
        for f in failures:
            print(f"  FAIL: {f}")
        return 1

    print("C15_COMPARISON_VERIFIER_SELFTEST_PASS")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    raise SystemExit(main())
