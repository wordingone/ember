#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""vacuity_check.py -- frozen follow-up spec on issue #123 (coordinator
comment 4930377425), leg 1: VACUITY CHECK for the rider-A permuted-twin
null model (receipt cbase-grow-rung2-nullmodel-permuted-twin-20260709T220710Z.json).

CPU only. Reconstructs the EXACT same two W_grown gate_proj tensors that
rider_a_run.py measured (anchor_control: unmodified grown checkpoint;
permuted_twin: build_permuted_gate_variant output, same fixed seed 20260709)
and:

  1. Byte-compares them directly.
  2. If not byte-identical, tests row-permutation equivalence via a
     canonical row ordering (sort all rows by their own raw-byte content;
     if the two matrices are row-permutations of each other, their
     canonical forms are byte-identical) AND compares singular values to
     machine precision (row permutation is an orthogonal transform, which
     preserves singular values exactly in exact arithmetic).

Pre-named outcomes (frozen, verbatim from the coordinator comment):
  (a) byte-identical => rider-A KILL is VACUOUS (instrument input never varied)
  (b) row-permutation-equal => VACUOUS by spectral invariance (same recording)
  (c) genuinely different matrix => bit-identical u_post_spectral is an
      instrument-path defect (cache/pinning bug); instrument quarantined
      until cured, filed at higher severity.

Refs: #123 #449 #591
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import torch

OUT_DIR = Path(__file__).resolve().parent.parent / "receipts"

REAL_REPO = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REAL_REPO / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
from cbase_grow_rung2_event import _gate_up_down_keys  # noqa: E402

WORKTREE = REAL_REPO / ".claude" / "worktrees" / "remeasure-466"
CACHE_DIR = WORKTREE / "receipts" / ".rung2-event-cache"
GROWN_CACHE_PATH = CACHE_DIR / "grown-eps-58e8e98916823941-sigma0.05-seed0.pt"

PERMUTATION_SEED = 20260709  # identical to rider_a_run.py -- must reproduce byte-for-byte


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def build_permuted_gate_variant(grown: dict, gate_key: str) -> tuple[torch.Tensor, dict]:
    """Verbatim reproduction of rider_a_run.py's construction (same fixed
    seed, same first-half-unchanged / second-half-permuted shape) so the
    vacuity check tests the EXACT tensors the GPU rider measured, not a
    re-derivation that could silently diverge."""
    gate = grown[gate_key].detach().clone()
    grown_dtype = gate.dtype
    gate_f32 = gate.to(torch.float32)
    ff = int(gate_f32.shape[0])
    half = ff // 2
    ga = gate_f32[:half]
    gb = gate_f32[half:]

    gen = torch.Generator().manual_seed(PERMUTATION_SEED)
    perm = torch.randperm(half, generator=gen)
    fixed_points = int((perm == torch.arange(half)).sum().item())
    gb_permuted = gb[perm]

    permuted_gate = torch.cat([ga, gb_permuted], dim=0).to(grown_dtype)
    perm_sha256 = hashlib.sha256(perm.numpy().tobytes()).hexdigest()
    return permuted_gate, {"permutation_sha256": perm_sha256, "fixed_points": fixed_points, "half": half, "ff": ff}


def _tensor_to_raw_bytes(t: torch.Tensor) -> bytes:
    """Raw-bit byte extraction that works for bfloat16 (numpy has no native
    bf16 dtype, so .numpy() on a bf16 tensor raises TypeError). Reinterpreting
    via a uint8 view keeps the exact bit pattern -- the correct notion of
    'byte-identical' for this check, rather than routing through a dtype
    conversion that would change the underlying bits."""
    return t.contiguous().view(torch.uint8).numpy().tobytes()


def canonical_form_bytes(matrix: torch.Tensor) -> bytes:
    """Sorts all rows by their own raw byte content. Two matrices that are
    row-permutations of each other produce byte-identical canonical forms;
    matrices that differ in row CONTENT (not just order) do not."""
    matrix_u8 = matrix.contiguous().view(torch.uint8)  # [N, D*elem_size]
    rows_bytes = [row.numpy().tobytes() for row in matrix_u8]
    order = sorted(range(len(rows_bytes)), key=lambda i: rows_bytes[i])
    return b"".join(rows_bytes[i] for i in order)


def main():
    gate_key, up_key, down_key = _gate_up_down_keys(0)
    if not GROWN_CACHE_PATH.exists():
        print(json.dumps({"status": "MISSING_INPUT", "missing": str(GROWN_CACHE_PATH)}))
        return 1

    grown = torch.load(GROWN_CACHE_PATH, map_location="cpu", weights_only=True)
    anchor_gate = grown[gate_key].detach().clone()  # exactly what rider_a_run.py's anchor_control leg loaded
    permuted_gate, perm_provenance = build_permuted_gate_variant(grown, gate_key)

    assert anchor_gate.shape == permuted_gate.shape
    assert anchor_gate.dtype == permuted_gate.dtype

    # --- Step 1: direct byte compare ---
    anchor_bytes = _tensor_to_raw_bytes(anchor_gate)
    permuted_bytes = _tensor_to_raw_bytes(permuted_gate)
    byte_identical = anchor_bytes == permuted_bytes

    result = {
        "ticket": "CBASE-GROW-RUNG2-VACUITY-CHECK",
        "issue": 123,
        "refs": [449, 591],
        "coordinator_comment": 4930377425,
        "grown_weights_sha256": _sha256_file(GROWN_CACHE_PATH),
        "permutation_provenance": perm_provenance,
        "step1_byte_compare": {
            "anchor_gate_sha256": hashlib.sha256(anchor_bytes).hexdigest(),
            "permuted_gate_sha256": hashlib.sha256(permuted_bytes).hexdigest(),
            "byte_identical": byte_identical,
        },
    }

    if byte_identical:
        result["outcome"] = "a"
        result["outcome_meaning"] = "byte-identical -- rider-A KILL is VACUOUS (instrument input never varied)"
        _write_result(result)
        return 0

    # --- Step 2: row-permutation equivalence (canonical ordering) ---
    anchor_canon = canonical_form_bytes(anchor_gate)
    permuted_canon = canonical_form_bytes(permuted_gate)
    canon_identical = anchor_canon == permuted_canon

    # --- Step 2b: singular values to machine precision ---
    sv_anchor = torch.linalg.svdvals(anchor_gate.to(torch.float32))
    sv_permuted = torch.linalg.svdvals(permuted_gate.to(torch.float32))
    sv_max_abs_diff = float((sv_anchor - sv_permuted).abs().max().item())
    sv_max_rel_diff = float(((sv_anchor - sv_permuted).abs() / sv_anchor.clamp_min(1e-12)).max().item())

    result["step2_row_permutation_equivalence"] = {
        "canonical_form_sha256_anchor": hashlib.sha256(anchor_canon).hexdigest(),
        "canonical_form_sha256_permuted": hashlib.sha256(permuted_canon).hexdigest(),
        "canonical_forms_byte_identical": canon_identical,
        "singular_values_max_abs_diff": sv_max_abs_diff,
        "singular_values_max_rel_diff": sv_max_rel_diff,
        "singular_values_top5_anchor": [float(x) for x in sv_anchor[:5]],
        "singular_values_top5_permuted": [float(x) for x in sv_permuted[:5]],
    }

    row_permutation_equal = canon_identical and sv_max_abs_diff < 1e-3

    if row_permutation_equal:
        result["outcome"] = "b"
        result["outcome_meaning"] = ("row-permutation-equal -- VACUOUS by spectral invariance "
                                      "(same multiset of rows, reordered; P*W and W share singular "
                                      "values exactly, up to float32 SVD computation tolerance)")
    else:
        result["outcome"] = "c"
        result["outcome_meaning"] = ("genuinely different matrix -- the bit-identical u_post_spectral "
                                      "is an instrument-path defect (cache/pinning bug); instrument "
                                      "quarantined until cured")

    _write_result(result)
    return 0


def _write_result(result: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"cbase-grow-rung2-vacuity-check-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"WROTE {out_path}", flush=True)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    sys.exit(main())
