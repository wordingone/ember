#!/usr/bin/env python3
"""spectral_nonequivalence_check.py -- audit-requested follow-up (team-lead,
2026-07-10), blocking item 1: SPECTRAL NON-EQUIVALENCE.

The vacuity check (outcome b) and the earlier precheck only established that
the real-null twin's gate_proj is (a) not a row-permutation of the anchor and
(b) has a genuinely random per-row direction relative to the anchor's rows.
Neither of those facts rules out the FULL singular-value-invariance group:
singular values are preserved by ANY left-multiplication by an orthogonal
matrix (Q^T Q = I), not just by permutation matrices (permutations are one
special case of orthogonal transforms). "Outside the permutation group" is
therefore NOT the same claim as "outside the singular-value-invariance
group" -- this script closes that gap directly, by computing the actual
singular-value (equivalently Gram-eigenvalue) spectra of BOTH matrices and
receipting their difference.

Method: for W [ff, d] with ff >> d (here 32768 x 1024), computing eigenvalues
of the Gram matrix W^T W [d, d] is algebraically equivalent to computing
squared singular values of W, and is far cheaper (1024x1024 eigendecomp vs a
32768x1024 SVD). Both are computed here and cross-checked against each other
(sqrt of Gram eigenvalues vs svdvals(W), sorted descending) for the top-K
values as an internal consistency check.

Pre-named outcomes (mirroring the vacuity check's outcome letters, since this
is testing the same underlying question at a broader invariance-group level):
  - spectra match to float32 tolerance => the twin is STILL inside the (full)
    SV-invariance group; the leg is VACUOUS-(b) again, regardless of the
    non-permutation construction; R_spectral's near-sqrt(2) reading carries
    no information about NS5/gradient behavior specifically -- it would be
    expected from ANY SV-preserving perturbation.
  - spectra differ materially (order(s) of magnitude above float32
    tolerance) => the raw weight matrix's spectral content DID change
    materially, yet the NS5-processed R_spectral barely moved (0.0208%
    measured) -- consistent with (not proof of) an NS5-plateau-saturation
    interpretation: the instrument may be insensitive to real spectral
    differences at this shape, not that no real difference exists to detect.

This script makes NO verdict call -- it returns the measured spectral-
difference numbers only. Adjudication is the coordinator's per team-lead's
standing instruction.

Refs: #123 #591
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import torch

REAL_REPO = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REAL_REPO / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
from cbase_grow_rung2_event import _gate_up_down_keys  # noqa: E402
from cbase_grow_rung2_real_nullmodel_precheck import build_real_nullmodel_gate_variant, RANDOM_DIRECTION_SEED  # noqa: E402

WORKTREE = REAL_REPO / ".claude" / "worktrees" / "remeasure-466"
CACHE_DIR = WORKTREE / "receipts" / ".rung2-event-cache"
GROWN_CACHE_PATH = CACHE_DIR / "grown-eps-58e8e98916823941-sigma0.05-seed0.pt"
OUT_DIR = REAL_REPO / "receipts"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def main():
    t0 = time.time()
    if not GROWN_CACHE_PATH.exists():
        print(json.dumps({"status": "MISSING_INPUT", "missing": str(GROWN_CACHE_PATH)}))
        return 1

    gate_key, up_key, down_key = _gate_up_down_keys(0)
    grown = torch.load(GROWN_CACHE_PATH, map_location="cpu", weights_only=True)
    anchor_gate = grown[gate_key].detach().clone().to(torch.float32)
    twin_gate, provenance, ga, gb, gb_random, original_row_norms = build_real_nullmodel_gate_variant(grown, gate_key)
    twin_gate_f32 = twin_gate.to(torch.float32)

    # --- Gram-eigenvalue spectrum (cheap: d x d eigendecomp) ---
    gram_anchor = anchor_gate.T @ anchor_gate
    gram_twin = twin_gate_f32.T @ twin_gate_f32
    eig_anchor = torch.linalg.eigvalsh(gram_anchor)  # ascending
    eig_twin = torch.linalg.eigvalsh(gram_twin)
    eig_anchor_desc = torch.flip(eig_anchor, dims=[0]).clamp_min(0.0)
    eig_twin_desc = torch.flip(eig_twin, dims=[0]).clamp_min(0.0)
    sv_from_gram_anchor = eig_anchor_desc.sqrt()
    sv_from_gram_twin = eig_twin_desc.sqrt()

    # --- Direct SVD (top-K cross-check against the Gram-derived spectrum) ---
    K = 10
    svdvals_anchor = torch.linalg.svdvals(anchor_gate)
    svdvals_twin = torch.linalg.svdvals(twin_gate_f32)

    cross_check_anchor_max_abs_diff = float((svdvals_anchor - sv_from_gram_anchor).abs().max().item())
    cross_check_twin_max_abs_diff = float((svdvals_twin - sv_from_gram_twin).abs().max().item())

    # --- Full-spectrum comparison: anchor vs twin (the load-bearing measurement) ---
    diff = (sv_from_gram_anchor - sv_from_gram_twin)
    abs_diff = diff.abs()
    rel_diff = abs_diff / sv_from_gram_anchor.clamp_min(1e-12)

    max_abs_diff = float(abs_diff.max().item())
    mean_abs_diff = float(abs_diff.mean().item())
    max_rel_diff = float(rel_diff.max().item())
    mean_rel_diff = float(rel_diff.mean().item())

    top_sv_anchor = float(sv_from_gram_anchor[0].item())
    top_sv_twin = float(sv_from_gram_twin[0].item())
    top_sv_rel_diff = float(abs(top_sv_anchor - top_sv_twin) / top_sv_anchor)

    # Float32-tolerance threshold: same convention as the vacuity check's
    # row-permutation-equivalence test (which found max_rel_diff ~2.27e-6 for
    # a TRUE row-permutation). Use a generous 1e-3 relative-difference floor
    # as the "float32 tolerance" cutoff, consistent with vacuity_check.py's
    # row_permutation_equal threshold, to classify this measurement on the
    # SAME numeric scale as that already-adjudicated check.
    FLOAT32_TOLERANCE_REL = 1e-3
    spectra_match_to_float32_tolerance = bool(max_rel_diff < FLOAT32_TOLERANCE_REL)

    result = {
        "ticket": "CBASE-GROW-RUNG2-SPECTRAL-NONEQUIVALENCE-CHECK",
        "issue": 123,
        "refs": [591],
        "coordinator_instruction": "team-lead resume message 2026-07-10, item 1 (blocking)",
        "grown_weights_sha256": _sha256_file(GROWN_CACHE_PATH),
        "construction_provenance": provenance,
        "method": "Gram-eigenvalue spectrum (W^T W, d=1024 eigendecomp) as the primary "
                  "cheap route to squared singular values; direct svdvals(W) computed "
                  "for both matrices as an independent cross-check on the top values.",
        "cross_check_gram_vs_svd": {
            "anchor_max_abs_diff": cross_check_anchor_max_abs_diff,
            "twin_max_abs_diff": cross_check_twin_max_abs_diff,
            "note": "internal consistency check only -- confirms the Gram-eigenvalue route "
                    "reproduces direct SVD to numerical precision on BOTH matrices "
                    "independently; not itself the anchor-vs-twin comparison.",
        },
        "top_10_singular_values_anchor": [float(x) for x in sv_from_gram_anchor[:K]],
        "top_10_singular_values_twin": [float(x) for x in sv_from_gram_twin[:K]],
        "full_spectrum_comparison": {
            "n_singular_values": int(sv_from_gram_anchor.shape[0]),
            "max_abs_diff": max_abs_diff,
            "mean_abs_diff": mean_abs_diff,
            "max_rel_diff": max_rel_diff,
            "mean_rel_diff": mean_rel_diff,
            "top_singular_value_anchor": top_sv_anchor,
            "top_singular_value_twin": top_sv_twin,
            "top_singular_value_rel_diff": top_sv_rel_diff,
        },
        "float32_tolerance_rel_threshold": FLOAT32_TOLERANCE_REL,
        "float32_tolerance_reference": "vacuity_check.py's row-permutation-equal test measured "
                                        "max_rel_diff=2.27e-6 for a CONFIRMED true row-permutation "
                                        "of this same matrix -- that is the empirical float32-noise "
                                        "floor this threshold is set well above.",
        "spectra_match_to_float32_tolerance": spectra_match_to_float32_tolerance,
        "outcome": ("VACUOUS_STILL_INSIDE_SV_INVARIANCE_GROUP" if spectra_match_to_float32_tolerance
                    else "SPECTRA_DIFFER_MATERIALLY_R_SPECTRAL_READING_IS_A_REAL_MEASUREMENT"),
        "note_no_adjudication": "This script returns measured numbers only. Whether this outcome "
                                 "changes the standing R_spectral verdict (KILL_NS5_PLATEAU_ARTIFACT, "
                                 "deviation 0.0208%, receipt cbase-grow-rung2-real-nullmodel-"
                                 "20260710T004908Z.json) is the coordinator's ruling, not this script's.",
        "wall_seconds": time.time() - t0,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"cbase-grow-rung2-spectral-nonequivalence-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"WROTE {out_path}", flush=True)
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
