#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cbase_grow_rung2_real_nullmodel_precheck.py -- frozen follow-up spec on issue #123
(coordinator comment 4930377425), leg 2: CPU-only construction + precheck for
the "REAL NULL MODEL" -- a gate_proj twin that perturbs W_grown OUTSIDE the
spectral (row-permutation) invariance group, at matched scale.

Construction (frozen text, verbatim): "replace each duplicated-row pair's
second member with a random direction at the SAME per-row norm (overall
Frobenius norm matched)."

This script does NOT run on GPU. It only constructs the variant, verifies it
is sound (per-row norm match, Frobenius match, genuinely non-permutation
content, no accidental row collisions), and prints a precheck receipt. The
matching GPU run script (rider_a2_real_nullmodel_run.py, same shape as
rider_a_run.py) is authored alongside but NOT executed -- GPU use is gated on
team-lead adding the corresponding #591 row.

Prediction registered NOW, before any GPU run (frozen, verbatim):
  - if the sqrt(2) signature tracks row-duplication STRUCTURE:
      R_spectral departs sqrt(2) by >= 1% on the random-direction twin
  - if it stays inside +/-0.1%:
      sqrt(2) is an NS5-plateau artifact at these shapes; the
      flagship-demotion argument loses this instrument (Q1 then ruled from
      the alignment-sensitive side only -- rms_ratio / min-per-row-cosine).

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

# Distinct from rider_a_run.py's PERMUTATION_SEED (20260709) -- this seed
# drives a DIFFERENT construction (random direction, not a permutation) and
# is deliberately dated to this follow-up leg for provenance clarity.
RANDOM_DIRECTION_SEED = 20260710


def _tensor_to_raw_bytes(t: torch.Tensor) -> bytes:
    """numpy has no native bfloat16 dtype -- .numpy() on a bf16 tensor raises
    TypeError. Reinterpret via a uint8 view to get the exact bit pattern."""
    return t.contiguous().view(torch.uint8).numpy().tobytes()


def build_real_nullmodel_gate_variant(grown: dict, gate_key: str) -> tuple[torch.Tensor, dict]:
    gate = grown[gate_key].detach().clone()
    grown_dtype = gate.dtype
    gate_f32 = gate.to(torch.float32)
    ff = int(gate_f32.shape[0])
    d = int(gate_f32.shape[1])
    half = ff // 2
    ga = gate_f32[:half]
    gb = gate_f32[half:]

    # Precondition (reconfirm): second half is an exact row-duplicate of the
    # first half BEFORE this construction touches it.
    row_dup_exact = bool(torch.equal(ga, gb))

    gen = torch.Generator().manual_seed(RANDOM_DIRECTION_SEED)
    # Random direction per row: iid standard normal, then normalized to a
    # unit vector, then scaled to the ORIGINAL row's own L2 norm -- this is
    # what "same per-row norm, random direction" means concretely.
    raw_directions = torch.randn((half, d), generator=gen, dtype=torch.float32)
    unit_directions = raw_directions / raw_directions.norm(dim=1, keepdim=True)
    original_row_norms = gb.norm(dim=1, keepdim=True)  # == ga's row norms, by row_dup_exact
    gb_random = unit_directions * original_row_norms

    new_gate_f32 = torch.cat([ga, gb_random], dim=0)
    new_gate = new_gate_f32.to(grown_dtype)

    provenance = {
        "random_direction_seed": RANDOM_DIRECTION_SEED,
        "half": half,
        "ff": ff,
        "d": d,
        "row_dup_exact_pre_construction": row_dup_exact,
        "construction_sha256": hashlib.sha256(_tensor_to_raw_bytes(new_gate)).hexdigest(),
    }
    return new_gate, provenance, ga, gb, gb_random, original_row_norms


def main():
    gate_key, up_key, down_key = _gate_up_down_keys(0)
    if not GROWN_CACHE_PATH.exists():
        print(json.dumps({"status": "MISSING_INPUT", "missing": str(GROWN_CACHE_PATH)}))
        return 1

    grown = torch.load(GROWN_CACHE_PATH, map_location="cpu", weights_only=True)
    anchor_gate = grown[gate_key].detach().clone()
    new_gate, provenance, ga, gb, gb_random, original_row_norms = build_real_nullmodel_gate_variant(grown, gate_key)

    anchor_f32 = anchor_gate.to(torch.float32)
    new_f32 = new_gate.to(torch.float32)

    # --- Check 1: per-row norm preserved on the replaced half ---
    new_row_norms = gb_random.norm(dim=1, keepdim=True)
    per_row_norm_max_abs_diff = float((new_row_norms - original_row_norms).abs().max().item())
    per_row_norm_max_rel_diff = float(((new_row_norms - original_row_norms).abs() / original_row_norms.clamp_min(1e-12)).max().item())

    # --- Check 2: overall Frobenius norm preserved (first half untouched, second half norm-matched row-wise) ---
    frob_anchor = float(anchor_f32.norm().item())
    frob_new = float(new_f32.norm().item())
    frob_abs_diff = abs(frob_anchor - frob_new)
    frob_rel_diff = frob_abs_diff / frob_anchor

    # --- Check 3: construction genuinely lies OUTSIDE the permutation group ---
    # (a) per-row cosine between each new row and its original paired row (gb) --
    #     should NOT cluster near +/-1 (that would mean "random" collapsed onto
    #     something structured/aligned by chance).
    cos_new_vs_original = torch.nn.functional.cosine_similarity(gb_random, gb, dim=1)
    cos_min = float(cos_new_vs_original.min().item())
    cos_max = float(cos_new_vs_original.max().item())
    cos_mean = float(cos_new_vs_original.mean().item())

    # (b) no accidental row collision: min L2 distance from each new row to
    #     EVERY row of the anchor's full matrix (first half ga + second half gb)
    #     should be bounded away from 0 -- i.e. the random row did not, by
    #     freak chance, land on an existing row (would break the "genuinely
    #     different content" premise). Computed as nearest-neighbour distance
    #     from each new row to the anchor's 32768 rows.
    anchor_rows_f32 = anchor_f32  # [ff, d]
    # chunked to bound memory: half x ff distance matrix (16384 x 32768) is
    # ~2GB in float32 -- do it in chunks of 512 rows.
    min_nn_dist = float("inf")
    chunk = 512
    for start in range(0, gb_random.shape[0], chunk):
        block = gb_random[start:start + chunk]  # [c, d]
        dists = torch.cdist(block, anchor_rows_f32)  # [c, ff]
        block_min = float(dists.min().item())
        if block_min < min_nn_dist:
            min_nn_dist = block_min

    # (c) direct byte-identity check: the new full matrix must not equal the
    #     anchor's full matrix (sanity; obviously true given norm-preserving
    #     random replacement of half the rows, but checked for discipline).
    byte_identical_to_anchor = bool(_tensor_to_raw_bytes(new_gate) == _tensor_to_raw_bytes(anchor_gate))

    outside_invariance_group = (not byte_identical_to_anchor) and (min_nn_dist > 1e-3) and (abs(cos_mean) < 0.9)

    result = {
        "ticket": "CBASE-GROW-RUNG2-REAL-NULLMODEL-PRECHECK",
        "issue": 123,
        "refs": [449, 591],
        "coordinator_comment": 4930377425,
        "grown_weights_sha256": hashlib.sha256(open(GROWN_CACHE_PATH, "rb").read()).hexdigest(),
        "provenance": provenance,
        "checks": {
            "per_row_norm_max_abs_diff": per_row_norm_max_abs_diff,
            "per_row_norm_max_rel_diff": per_row_norm_max_rel_diff,
            "frobenius_norm_anchor": frob_anchor,
            "frobenius_norm_new": frob_new,
            "frobenius_abs_diff": frob_abs_diff,
            "frobenius_rel_diff": frob_rel_diff,
            "cosine_new_vs_original_row_min": cos_min,
            "cosine_new_vs_original_row_max": cos_max,
            "cosine_new_vs_original_row_mean": cos_mean,
            "min_nearest_neighbour_l2_dist_to_any_anchor_row": min_nn_dist,
            "byte_identical_to_anchor": byte_identical_to_anchor,
        },
        "outside_spectral_invariance_group": outside_invariance_group,
        "precheck_verdict": "PASS" if (per_row_norm_max_rel_diff < 1e-3 and frob_rel_diff < 1e-3 and outside_invariance_group) else "FAIL",
        "prediction_registered_pre_run": {
            "if_signature_tracks_row_duplication_structure": ">=1% R_spectral departure from sqrt(2)",
            "if_NS5_plateau_artifact": "within +/-0.1% of sqrt(2); Q1 then ruled from alignment-sensitive side only (rms_ratio / min-per-row-cosine)",
        },
        "gpu_run_gate": "NOT EXECUTED -- gated on team-lead adding the corresponding #591 row (frozen spec, no adjustment)",
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"cbase-grow-rung2-real-nullmodel-precheck-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"WROTE {out_path}", flush=True)
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["precheck_verdict"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
