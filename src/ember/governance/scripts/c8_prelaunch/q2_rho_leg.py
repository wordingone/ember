#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""q2_rho_leg.py — Q2 loss-gap bridge CPU leg (issue #662).

Frozen spec: issue #449 comment 4932624437 ("Q2 loss-gap bridge — derivation
+ pre-registration"), section 4 ("CPU leg — zero-GPU, cached-tensor,
builder-dispatchable"), referenced verbatim by issue #662. Reduces the
geometry->loss bridge question to ONE new measurable,

    rho := cos_F(G_post, U_T - U_R)

computed CPU-side from the b513-b4rerun cached tensors (grad_post_gate +
the pre-grow momentum needed to reconstruct both arms' updates), with an
EMPIRICAL spectrum-preserving rotation null (the analytic 1/sqrt(mn) null
is void for structured low-rank tensors -- refuter-fatal, accepted per the
prereg) and a scale/rotation decomposition that isolates the effective-LR
confound (a pure between-arm step-magnitude difference, zero geometry
content) from genuine orthogonal (new-information) alignment.

Execution order (L0-L3, binding per the prereg; each stage emits receipt
fields under its own label):

  L0  cache integrity (fail-closed). Load the b513-b4rerun cache family
      from the durable RESCUE location `receipts/.rung2-event-cache/
      b513-b4rerun/` ONLY (the flat `receipts/.rung2-event-cache/b513-
      b4rerun-*.pt` paths recorded in the live b3 event receipt's
      `cache_paths` field do NOT resolve to this family -- disclosed defect,
      #449 sec.4 -- the rescue copy at the nested path is the only trusted
      source). Verify every tensor's sha256 against the rescue manifest
      BEFORE any math; mismatch/absence => FAILED-ENGAGEMENT receipt, exit
      nonzero. Shapes are read from the files, never assumed (`m`, `n`, `mn`
      pinned into the receipt from the actual loaded tensors).

  L1  dimensional audit. Reconstruct the RESET-arm and TRANSPLANT-arm
      per-step updates from the cached momentum via explicit NS5 (Newton-
      Schulz quintic zeropower iteration, coefficients (3.4445, -4.7750,
      2.0315), 5 steps -- byte-identical reuse of
      src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py::_muon_step_in_copy, the SAME
      function the live B3 event phase used to produce
      receipts/cbase-grow-rung2-event-b513-b4rerun-b3.json's arms.*
      .d_comm_fields; no math is re-derived here). Adjudicates eta-inclusive
      vs eta-exclusive by RECOMPUTING step_rms_post for both arms from the
      cache and comparing against that live receipt's own step_rms_post
      fields (empirical falsification, not an assumption): if the bare
      config lr_muon reproduces the live numbers, eta_convention is
      "eta-exclusive" (no WSD schedule fraction folded into the per-step
      LR); otherwise an implied eta multiplier is solved for and disclosed.

  L2  rho with an empirical rotation null, two-phase in ONE run. Phase A
      computes the null ensemble cos_F(G_post, Q1.(U_T-U_R).Q2^T) for
      N=200 Haar-orthogonal (Q1, Q2) draws (seed recorded) and writes the
      99.7th-percentile |cos| threshold BEFORE phase B unblinds the
      observed rho_raw (both program order and receipt timestamps prove
      this). Q1 acts on the m=32768-dim row space -- an EXPLICIT m x m
      Haar matrix would need ~4.3GB and an O(m^3) QR per draw, violating
      the RAM<4GB / reasonable-runtime floor; see
      `sample_rotated_candidate` for the exact (not approximate)
      distributional reduction used instead, empirically cross-checked
      against the literal construction on a tiny matrix in --selftest.

  L3  scale/rotation decomposition. Splits U_T-U_R into the component
      parallel to the common update direction D = normalize((U_R+U_T)/2)
      and the orthogonal remainder; reports rho_perp = cos_F(G_post,
      (U_T-U_R)_perp) and the parallel fraction. Any orientation credit
      comes only from rho_perp (the effective-LR confound predicts the
      loss gap from the parallel part alone with zero geometry content);
      the decomposition itself is descriptive.

  Verdict (SUPERSEDED vocabulary -- claim-narrowing, tighten-only):
    The #449 sec.4 frozen table (BRIDGE-ALIVE / NULL-PRIMARY /
    EFFECTIVE-LR-ARTIFACT) is SUPERSEDED for this leg by an exact-head
    hostile review + the frozen Q2 successor contract
    (SHA 992463793324f75d90e0d80128efbe980a3cc7ee9171300132b59b536b468f33).
    This leg's inputs are CPU reconstructions from bf16 pre_momentum, not
    the actual decisive GPU U_T/U_R delta bytes (L1's own 0.1-0.2% rel_err
    tolerance is the receipt's evidence of that); there is no common batch
    and no paired L(W+v_T)-L(W+v_R) at this event -- so a non-null
    orientation cannot be called a loss bridge. Verdict vocabulary:

      SIBLING_NON_NULL_ORIENTATION   p_upper < alpha (= 0.003)
      INCONCLUSIVE                   p_upper >= alpha (failure to reject;
                                     NEVER a null/bridge-dead claim)

    where the CANONICAL test is the analytic two-sided Haar tail bound
    p_upper = min(1, 1/(mn * rho_perp^2)) (exact Var[cos_F] = 1/mn under
    the spectrum-preserving rotation null). The empirical N=200 ensemble
    is DEMOTED to descriptive corroboration: N=200 cannot express
    alpha=0.003 (minimum achievable corrected p = 1/201 = 0.004975; the
    99.7th-percentile order statistic is under-resolved). Actual-bridge
    verdicts await future-event capture (actual GPU delta bytes + common
    batch + paired losses) per the successor contract. The first-order gap
    e_T - e_R is additionally reported SIGNED (its direction is a caveat
    the sign-insensitive |rho_perp| statistic cannot carry).

Rails (binding, issue #662): worktree-first (this script and its receipts
never touch the repo's master checkout); no --no-verify / hook-skip; a
gate block is reported verbatim, never routed around; scratch stays in the
worktree; receipts carry no absolute paths (repo-relative only, #639
convention); close-keywords banned in commit messages; a blocked
(FAILED-ENGAGEMENT) report is success, invented output is the only
failure.

CLI:
  --selftest         Synthetic small-matrix run (L0 positive+negative sha
                      path, the Haar-null reduction cross-checked against
                      the literal Q1/Q2 construction, and both verdict
                      labels -- plus the parallel-absorbed descriptive
                      shape -- reproduced from planted rho). Exits nonzero
                      on any check failure. Prints Q2_RHO_LEG_SELFTEST_PASS
                      on success. No real cache touched.
  (no flags)          Real run against receipts/.rung2-event-cache/
                      b513-b4rerun/. Writes receipts/q2-rho-leg-
                      <UTCstamp>.json.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from receipt_write import checked_write                       # noqa: E402
from p5_ratio_audit.run_p5_audit import _muon_step_in_copy, rms  # noqa: E402

REPO = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"

CACHE_DIR_DEFAULT = REPO / "receipts" / ".rung2-event-cache" / "b513-b4rerun"
CROSSREF_RECEIPT_DEFAULT = REPO / "receipts" / "cbase-grow-rung2-event-b513-b4rerun-b3.json"
RECEIPT_DIR_DEFAULT = REPO / "receipts"

TENSOR_FILES = {
    "grad_post_gate": "b513-b4rerun-grad-post-gate.pt",
    "grad_pre_gate": "b513-b4rerun-grad-pre-gate.pt",
    "pre_momentum": "b513-b4rerun-pre-momentum.pt",
    "theta_gate_pre": "b513-b4rerun-theta-gate-pre.pt",
}
CONSUMED_BY_L1_L3 = ("grad_post_gate", "pre_momentum")

MUON_MOMENTUM = 0.95
NS5_STEPS = 5
NS5_COEFFS_A_B_C = (3.4445, -4.7750, 2.0315)  # pinned; must equal _muon_step_in_copy's own constants (asserted at import time below)
N_NULL_DRAWS_DEFAULT = 200
NULL_PERCENTILE = 99.7  # DESCRIPTIVE-ONLY after the merge-gate amendment (see ALPHA_CANONICAL)
ALPHA_CANONICAL = 0.003  # canonical significance level; test = analytic two-sided Haar tail bound
SUCCESSOR_CONTRACT_SHA256 = "992463793324f75d90e0d80128efbe980a3cc7ee9171300132b59b536b468f33"
EMPIRICAL_NULL_DEMOTION_REASON = (
    "N=200 cannot express alpha=0.003: minimum achievable corrected p = 1/(N+1) = "
    "1/201 = 0.004975 > alpha; the 99.7th-percentile order statistic is "
    "under-resolved at N=200. The ensemble is retained as descriptive "
    "corroboration only; the canonical test is the analytic two-sided Haar "
    "tail bound p_upper = min(1, 1/(mn * rho_perp^2)) with exact "
    "Var[cos_F] = 1/mn under the spectrum-preserving rotation null.")
ETA_MATCH_REL_TOL = 5e-3  # eta-exclusive accepted if both arms reproduce the live receipt within
                          # this relative error. Calibrated to the KNOWN precision floor of the
                          # reconstruction pipeline, not tuned for a desired outcome: pre_momentum
                          # is cached in bfloat16 (~8-bit mantissa, ~0.2-0.4% per-element rounding),
                          # which caps how closely a momentum-derived update can match the live
                          # fp32 run regardless of the LR convention used. A genuine WSD schedule
                          # fraction would show up as a much larger (>=several percent, typically
                          # 10-50%) deviation -- sub-0.5% is the bf16 floor, not an eta signal.


# ---------------------------------------------------------------------------
# small utilities
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _timestamp_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _repo_relative(path, root) -> str:
    """#639 convention: receipts carry repo-relative paths, never absolute.
    Paths outside root are kept absolute (inherently non-portable anyway,
    disclosed rather than silently truncated)."""
    path = Path(path).resolve()
    root = Path(root).resolve()
    try:
        rel = os.path.relpath(path, root)
        return rel.replace("\\", "/") if not rel.startswith("..") else str(path)
    except ValueError:
        return str(path)  # cross-drive on Windows


def _assert_ns5_constants():
    """Guards against silent drift between this script's pinned coefficients
    (frozen in the issue text) and the reused _muon_step_in_copy's own
    literal constants -- a source-diff check, not a re-derivation."""
    import inspect
    src = inspect.getsource(_muon_step_in_copy)
    assert "3.4445" in src and "4.7750" in src and "2.0315" in src, (
        "NS5 coefficient drift: _muon_step_in_copy's source no longer "
        "contains the frozen (3.4445, -4.7750, 2.0315) constants")


_assert_ns5_constants()


# ---------------------------------------------------------------------------
# L0 — cache integrity (fail-closed)
# ---------------------------------------------------------------------------

class EngagementFailure(Exception):
    pass


def load_and_verify_cache(cache_dir: Path) -> dict:
    """Loads the 4-tensor b513-b4rerun family from `cache_dir` (the durable
    RESCUE location only), verifying every file's sha256 against
    sha256-manifest.txt (or manifest.json's per-file sha256 field, same
    convention) BEFORE any tensor is touched by math. Raises
    EngagementFailure on any mismatch/absence (caller writes the
    FAILED-ENGAGEMENT receipt and exits nonzero)."""
    import torch

    cache_dir = Path(cache_dir)
    manifest_path = cache_dir / "sha256-manifest.txt"
    if not manifest_path.exists():
        raise EngagementFailure(f"rescue manifest missing: {manifest_path}")

    expected = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        sha, _, fname = line.partition(" *")
        if not fname:
            sha, _, fname = line.partition("  ")
        expected[fname.strip()] = sha.strip()

    verify_report = {}
    for role, fname in TENSOR_FILES.items():
        fpath = cache_dir / fname
        entry = {"file": fname, "expected_sha256": expected.get(fname)}
        if not fpath.exists():
            entry["present"] = False
            entry["sha256_match"] = False
            verify_report[role] = entry
            continue
        entry["present"] = True
        entry["bytes"] = fpath.stat().st_size
        actual = sha256_file(fpath)
        entry["actual_sha256"] = actual
        entry["sha256_match"] = bool(entry["expected_sha256"] is not None and actual == entry["expected_sha256"])
        verify_report[role] = entry

    all_present = all(v["present"] for v in verify_report.values())
    all_match = all(v["sha256_match"] for v in verify_report.values())
    if not (all_present and all_match):
        raise EngagementFailure(
            "cache integrity FAILED: " + json.dumps(
                {k: {kk: vv for kk, vv in v.items() if kk != "file"} for k, v in verify_report.items()}))

    tensors = {}
    shapes = {}
    for role, fname in TENSOR_FILES.items():
        t = torch.load(cache_dir / fname, map_location="cpu", weights_only=True)
        tensors[role] = t
        shapes[role] = {"shape": list(t.shape), "dtype": str(t.dtype), "numel": int(t.numel())}

    return {"tensors": tensors, "shapes": shapes, "verify_report": verify_report, "cache_dir": cache_dir}


def write_failed_engagement_receipt(receipt_dir: Path, reason: str, extra: dict | None = None) -> Path:
    receipt = {
        "ticket": "Q2-RHO-LEG-FAILED-ENGAGEMENT", "ts": _timestamp_iso(),
        "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
        "issue": 662, "refs": [449, 466],
        "reason": reason,
        "zombie_rule": "L0 cache-integrity is fail-closed: a mismatched or "
                       "absent tensor in the b513-b4rerun rescue family "
                       "means NO L1-L3 math runs and NO rho/verdict "
                       "artifact is written.",
        "api_spend_usd": 0, "paid_api_surface_used": False, "invalid_tokens_present": [],
        "verdict": "FAILED-ENGAGEMENT",
    }
    if extra:
        receipt.update(extra)
    receipt_dir = Path(receipt_dir)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    path = receipt_dir / f"q2-rho-leg-FAILED-ENGAGEMENT-{_ts()}.json"
    checked_write(str(path), receipt)
    print(f"Q2_RHO_LEG FAILED-ENGAGEMENT reason={reason!r} receipt={path}", flush=True)
    return path


# ---------------------------------------------------------------------------
# arm reconstruction (L1) — byte-identical reuse of _muon_step_in_copy
# ---------------------------------------------------------------------------

def build_arm_update(grad, momentum_buffer, lr: float, grown_shape):
    """One Muon step's UPDATE tensor (new_weight - weight), without needing
    the actual pre-update weight values: feeding weight=0 into
    _muon_step_in_copy makes new_weight == the update itself (the function
    only uses weight.shape, for the `scale = max(1, out/in)**0.5` factor,
    and weight.detach().clone() as the base it subtracts from -- 0 - X =
    -X = the update). Byte-identical to the live B3 event phase's own
    U_kplus1_reset / U_kplus1_transplant closures for identical inputs."""
    import torch
    zero_weight = torch.zeros(grown_shape, dtype=torch.float32)
    new_weight, new_buf, upd = _muon_step_in_copy(
        zero_weight, grad, momentum_buffer, lr=lr,
        momentum=MUON_MOMENTUM, nesterov=True, ns_steps=NS5_STEPS)
    return new_weight  # == the update U


def reconstruct_arms(grad_post_gate, pre_momentum, lr: float):
    import torch
    m, n = grad_post_gate.shape
    grad_post_gate = grad_post_gate.to(torch.float32)
    reset_momentum = torch.zeros_like(grad_post_gate)
    transplant_momentum = torch.cat([pre_momentum.to(torch.float32), pre_momentum.to(torch.float32)], dim=0)
    assert transplant_momentum.shape == grad_post_gate.shape, (
        f"row-duplication pushforward shape mismatch: transplant_momentum="
        f"{tuple(transplant_momentum.shape)} grad_post_gate={tuple(grad_post_gate.shape)}")
    U_R = build_arm_update(grad_post_gate, reset_momentum, lr, (m, n))
    U_T = build_arm_update(grad_post_gate, transplant_momentum, lr, (m, n))
    return U_R, U_T


def adjudicate_eta(grad_post_gate, pre_momentum, crossref_receipt_path: Path) -> dict:
    """L1: recompute step_rms_post for RESET/TRANSPLANT at the bare config
    lr_muon (the 'eta-exclusive' candidate) and compare against the live
    B3 event receipt's own arms.*.d_comm_fields.step_rms_post (ground
    truth from the SAME cached tensors, computed by the live pipeline
    before the rescue-copy path defect). A match within ETA_MATCH_REL_TOL
    for BOTH arms empirically CONFIRMS eta-exclusive (no WSD schedule
    fraction folded into the resolved per-step LR); otherwise the implied
    per-arm eta multiplier is solved for (step_rms_post scales linearly in
    lr) and disclosed as eta-inclusive."""
    crossref = json.loads(Path(crossref_receipt_path).read_text(encoding="utf-8"))
    lr_candidate = crossref["resolved_lr_muon"]
    truth_reset = crossref["arms"]["reset"]["d_comm_fields"]["step_rms_post"]
    truth_transplant = crossref["arms"]["transplant"]["d_comm_fields"]["step_rms_post"]

    U_R, U_T = reconstruct_arms(grad_post_gate, pre_momentum, lr_candidate)
    cand_reset = rms(U_R)
    cand_transplant = rms(U_T)

    rel_err_reset = abs(cand_reset - truth_reset) / truth_reset if truth_reset else float("nan")
    rel_err_transplant = abs(cand_transplant - truth_transplant) / truth_transplant if truth_transplant else float("nan")
    exclusive_matches = bool(rel_err_reset < ETA_MATCH_REL_TOL and rel_err_transplant < ETA_MATCH_REL_TOL)

    result = {
        "crossref_receipt": _repo_relative(crossref_receipt_path, REPO),
        "crossref_resolved_lr_muon": lr_candidate,
        "crossref_step_rms_post_reset": truth_reset,
        "crossref_step_rms_post_transplant": truth_transplant,
        "recomputed_step_rms_post_reset_at_lr_candidate": cand_reset,
        "recomputed_step_rms_post_transplant_at_lr_candidate": cand_transplant,
        "rel_err_reset": rel_err_reset,
        "rel_err_transplant": rel_err_transplant,
        "rel_tol": ETA_MATCH_REL_TOL,
        "precision_floor_note": "pre_momentum is cached in bfloat16 (see L0 shapes); any "
                                "residual mismatch below ~0.5% is attributable to that "
                                "rounding floor propagated through NS5, not to a WSD schedule "
                                "fraction -- disclosed, not treated as eta evidence below rel_tol.",
    }

    if exclusive_matches:
        result["eta_convention"] = "eta-exclusive"
        result["resolved_lr_per_step"] = lr_candidate
    else:
        implied_eta_reset = truth_reset / cand_reset if cand_reset else float("nan")
        implied_eta_transplant = truth_transplant / cand_transplant if cand_transplant else float("nan")
        implied_eta = (implied_eta_reset + implied_eta_transplant) / 2.0
        consistent = bool(
            abs(implied_eta_reset - implied_eta_transplant) / max(abs(implied_eta), 1e-12) < 0.05)
        result["implied_eta_reset"] = implied_eta_reset
        result["implied_eta_transplant"] = implied_eta_transplant
        result["implied_eta_consistent_across_arms"] = consistent
        result["eta_convention"] = "eta-inclusive" if consistent else "INDETERMINATE-fallback-eta-exclusive"
        result["resolved_lr_per_step"] = (
            lr_candidate * implied_eta if consistent else lr_candidate)

    return result


# ---------------------------------------------------------------------------
# L2 — empirical spectrum-preserving rotation null
# ---------------------------------------------------------------------------

def frobenius_cos(A, B) -> float:
    import torch
    a = A.to(torch.float32).flatten()
    b = B.to(torch.float32).flatten()
    na = torch.linalg.norm(a)
    nb = torch.linalg.norm(b)
    if na == 0 or nb == 0:
        return float("nan")
    return float(torch.dot(a, b) / (na * nb))


def _sample_semi_orthonormal(m: int, n: int, gen) -> "torch.Tensor":
    """Haar-uniform m x n matrix with orthonormal columns (a uniform random
    point on the Stiefel manifold V_n(R^m)): QR of an iid-Gaussian m x n
    draw with R's diagonal sign fixed (Mezzadri 2007, 'How to generate
    random matrices from the classical compact groups') -- LAPACK QR alone
    is NOT Haar-uniform without the sign fix."""
    import torch
    Z = torch.randn(m, n, generator=gen, dtype=torch.float32)
    Q, R = torch.linalg.qr(Z, mode="reduced")
    d = torch.sign(torch.diagonal(R))
    d = torch.where(d == 0, torch.ones_like(d), d)
    return Q * d.unsqueeze(0)


def _sample_haar_orthogonal(n: int, gen) -> "torch.Tensor":
    return _sample_semi_orthonormal(n, n, gen)


def sample_rotated_candidate(S_M, m: int, gen) -> "torch.Tensor":
    """One draw of (a matrix distributed identically to) Q1 @ M @ Q2^T for
    Q1 Haar-orthogonal on O(m), Q2 Haar-orthogonal on O(n), WITHOUT ever
    forming the dense m x m Q1 -- m=32768 here would need ~4.3GB and an
    O(m^3) QR per draw for Q1 alone, violating the RAM<4GB / CPU-only /
    reasonable-runtime acceptance bar (a computational wall the prereg's
    author did not size against; broken here rather than declared
    infeasible, per the standing break-the-wall floor).

    EXACT (not approximate) distributional reduction, from two standard
    Haar-measure invariances:
      (1) For Q1 Haar on O(m) and ANY fixed m x n semi-orthonormal U
          (n<=m), Q1 @ U is Haar-uniform on the Stiefel manifold V_n(R^m).
      (2) For Q2 Haar on O(n) and ANY fixed n x n orthogonal V, Q2 @ V is
          Haar-uniform on O(n) (right-invariance of Haar measure).
    Let M = U_M @ diag(S_M) @ V_M^T be M's thin SVD. Then
      Q1 @ M @ Q2^T = (Q1 @ U_M) @ diag(S_M) @ (Q2 @ V_M)^T
                    =d= W @ diag(S_M) @ (Q2')^T
    with W = Q1 @ U_M Stiefel-uniform (by 1) and Q2' = Q2 @ V_M Haar-
    uniform on O(n) (by 2), independent (Q1 perp Q2). Neither U_M nor V_M
    is needed at all -- only S_M (M's singular VALUES) and the shape (m,
    n) -- so this function only takes S_M and m as arguments. Cross-checked
    against the literal Q1/Q2 construction on a tiny matrix in --selftest
    (see selftest_null_reduction)."""
    n = S_M.shape[0]
    W = _sample_semi_orthonormal(m, n, gen)
    Q2p = _sample_haar_orthogonal(n, gen)
    return (W * S_M.unsqueeze(0)) @ Q2p.T


def empirical_rotation_null(G_post, M, n_draws: int, seed: int):
    """Phase A: N draws of cos_F(G_post, Q1.M.Q2^T) via the exact reduction
    above. Returns (draws, threshold, S_M) -- S_M is disclosed (M's
    Frobenius norm is recoverable from it: ||M||_F = ||S_M||_2, used as
    the out-of-invariance-group receipt the prereg requires: the ensemble
    itself demonstrates the null moves the instrument, dispersion>0)."""
    import torch
    m, n = M.shape
    S_M = torch.linalg.svdvals(M.to(torch.float32))
    gen = torch.Generator().manual_seed(seed)
    draws = []
    for i in range(n_draws):
        cand = sample_rotated_candidate(S_M, m, gen)
        draws.append(frobenius_cos(G_post, cand))
        del cand
        if (i + 1) % 25 == 0:
            gc.collect()
    draws_sorted = sorted(abs(x) for x in draws)
    k = min(len(draws_sorted) - 1, int(round((NULL_PERCENTILE / 100.0) * (len(draws_sorted) - 1))))
    threshold = draws_sorted[k]
    return draws, threshold, S_M


# ---------------------------------------------------------------------------
# L3 — scale/rotation decomposition
# ---------------------------------------------------------------------------

def decompose_parallel_orthogonal(M, U_R, U_T):
    import torch
    D = (U_R.to(torch.float32) + U_T.to(torch.float32)) / 2.0
    D_norm = torch.linalg.norm(D.flatten())
    if D_norm == 0:
        D_hat = torch.zeros_like(D)
    else:
        D_hat = D / D_norm
    M = M.to(torch.float32)
    coeff = torch.dot(M.flatten(), D_hat.flatten())
    M_parallel = coeff * D_hat
    M_perp = M - M_parallel
    M_norm = torch.linalg.norm(M.flatten())
    parallel_fraction = float(torch.linalg.norm(M_parallel.flatten()) / M_norm) if M_norm > 0 else float("nan")
    return M_parallel, M_perp, parallel_fraction, D_hat


# ---------------------------------------------------------------------------
# verdict (superseded vocabulary -- see module docstring; canonical test is
# the analytic two-sided Haar tail bound, alpha = ALPHA_CANONICAL)
# ---------------------------------------------------------------------------

def analytic_p_upper(rho: float, mn: int) -> float:
    """Canonical test statistic (successor contract): two-sided tail bound
    on |cos_F| under the spectrum-preserving Haar rotation null, from the
    exact null variance Var[cos_F] = 1/(mn) (mean 0) via Chebyshev:
    P(|cos| >= r) <= 1/(mn * r^2). Conservative (an upper bound on the true
    tail probability, hence 'p_upper'); sign-insensitive by construction
    (rho enters squared). NaN / zero rho / non-positive mn => 1.0 (never
    rejects)."""
    if mn <= 0 or rho != rho or rho == 0.0:
        return 1.0
    return min(1.0, 1.0 / (mn * rho * rho))


def verdict_from(p_upper: float, alpha: float = ALPHA_CANONICAL) -> str:
    """SIBLING_NON_NULL_ORIENTATION iff the canonical analytic bound
    rejects at alpha (strict <); otherwise INCONCLUSIVE -- a failure to
    reject, NEVER a null/bridge-dead claim. No loss-bridge verdict is
    mintable from this leg (CPU-reconstructed inputs, no common batch, no
    paired losses -- see module docstring / receipt claim_scope)."""
    return "SIBLING_NON_NULL_ORIENTATION" if p_upper < alpha else "INCONCLUSIVE"


# ---------------------------------------------------------------------------
# real run
# ---------------------------------------------------------------------------

def run_real(args) -> Path:
    import torch
    assert not torch.cuda.is_initialized(), "Q2-RHO-LEG is CPU-only; torch.cuda must never initialize"

    receipt_dir = Path(args.receipt_dir)
    cache_dir = Path(args.cache_dir)

    try:
        loaded = load_and_verify_cache(cache_dir)
    except EngagementFailure as e:
        write_failed_engagement_receipt(receipt_dir, str(e), {
            "cache_dir_checked": _repo_relative(cache_dir, REPO)})
        return None

    tensors = loaded["tensors"]
    grad_post_gate = tensors["grad_post_gate"].to(torch.float32)
    pre_momentum = tensors["pre_momentum"]
    m, n = grad_post_gate.shape
    mn = m * n

    l0_ts = _timestamp_iso()

    # L1: eta adjudication + final arm reconstruction at the resolved LR.
    eta = adjudicate_eta(grad_post_gate, pre_momentum, Path(args.crossref_receipt))
    resolved_lr = eta["resolved_lr_per_step"]
    U_R, U_T = reconstruct_arms(grad_post_gate, pre_momentum, resolved_lr)
    l1_ts = _timestamp_iso()

    M = (U_T - U_R).to(torch.float32)

    # L0 integrity_check (computed here since it needs U_R/U_T, but
    # labeled/disclosed as an L0-family cache/code consistency check per
    # the prereg -- "a linear function of the L2 quantities, not an
    # independent observable"): e_arm = <G_post, U_arm>_F (unnormalized);
    # e_T - e_R must equal <G_post, U_T-U_R>_F up to float roundoff.
    g_flat = grad_post_gate.flatten()
    e_reset = float(torch.dot(g_flat, U_R.flatten()))
    e_transplant = float(torch.dot(g_flat, U_T.flatten()))
    e_diff_direct = e_transplant - e_reset
    e_diff_independent = float(torch.dot(g_flat, M.flatten()))
    integrity_check = {
        "definition": "e_arm := <G_post, U_arm>_F (unnormalized Frobenius inner product; "
                       "the per-step train-loss-rate integrand each arm contributes, "
                       "s-prefactor omitted). e_T - e_R recomputed via a SEPARATE "
                       "codepath (dot with the already-materialized M=U_T-U_R tensor) "
                       "and checked against the per-arm-then-subtract path.",
        "e_reset": e_reset, "e_transplant": e_transplant,
        "e_diff_direct_path": e_diff_direct,
        "e_diff_independent_path": e_diff_independent,
        "abs_diff": abs(e_diff_direct - e_diff_independent),
        "consistent": bool(abs(e_diff_direct - e_diff_independent) < 1e-3 * max(abs(e_diff_direct), 1e-12)),
        "never_evidence": True,
        "note": "linear function of the L2 quantities by construction -- cache/code "
                "integrity check only, never an independent observable (prereg #449 sec.4).",
    }

    # L2, phase A: threshold BEFORE unblind (program order + timestamps).
    phase_a_ts = _timestamp_iso()
    draws, threshold, S_M = empirical_rotation_null(grad_post_gate, M, args.n_null, args.null_seed)
    phase_a_done_ts = _timestamp_iso()

    # L2, phase B: unblind.
    rho_raw = frobenius_cos(grad_post_gate, M)
    phase_b_ts = _timestamp_iso()
    assert phase_a_ts <= phase_a_done_ts <= phase_b_ts, "L2 phase ordering violated"

    # L3
    M_parallel, M_perp, parallel_fraction, D_hat = decompose_parallel_orthogonal(M, U_R, U_T)
    rho_perp = frobenius_cos(grad_post_gate, M_perp)

    # Canonical verdict: analytic two-sided Haar tail bound on rho_perp.
    p_upper = analytic_p_upper(rho_perp, mn)
    verdict = verdict_from(p_upper)

    receipt = {
        "ticket": "Q2-RHO-LEG", "ts": _timestamp_iso(),
        "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
        "issue": 662, "refs": [449, 466],
        "scope": "Q2 loss-gap bridge CPU leg: rho=cos_F(G_post,U_T-U_R) with an empirical "
                 "spectrum-preserving rotation null and a scale/rotation decomposition, "
                 "computed entirely from the b513-b4rerun cached tensors, zero GPU.",
        "L0_cache_integrity": {
            "cache_dir": _repo_relative(cache_dir, REPO),
            "ts": l0_ts,
            "verify_report": {k: {kk: vv for kk, vv in v.items() if kk != "file"}
                              for k, v in loaded["verify_report"].items()},
            "shapes": loaded["shapes"],
            "m": m, "n": n, "mn": mn,
            "integrity_check": integrity_check,
        },
        "L1_dimensional_audit": {"ts": l1_ts, **eta},
        "L2_null": {
            "canonical_analytic": {
                "test": "two-sided Haar tail bound: p_upper = min(1, 1/(mn * rho_perp^2)); "
                        "exact Var[cos_F] = 1/mn (mean 0) under the spectrum-preserving "
                        "rotation null; Chebyshev upper bound, conservative",
                "alpha": ALPHA_CANONICAL,
                "mn": mn,
                "rho_perp": rho_perp,
                "p_upper": p_upper,
                "reject_null": bool(p_upper < ALPHA_CANONICAL),
                "authority": "frozen Q2 successor contract (sha256 "
                             f"{SUCCESSOR_CONTRACT_SHA256}) + exact-head hostile review; "
                             "#449 prereg sec.4 as amended, tighten-only",
            },
            "empirical_descriptive": {
                "status": "DESCRIPTIVE-ONLY",
                "demotion_reason": EMPIRICAL_NULL_DEMOTION_REASON,
                "phase_a_threshold_ts": phase_a_ts,
                "phase_a_done_ts": phase_a_done_ts,
                "phase_b_unblind_ts": phase_b_ts,
                "phase_ordering_proven": bool(phase_a_ts <= phase_a_done_ts <= phase_b_ts),
                "n_draws": args.n_null, "seed": args.null_seed,
                "percentile": NULL_PERCENTILE,
                "threshold_abs_cos": threshold,
                "null_draws_dispersion": {
                    "min": min(draws), "max": max(draws),
                    "mean": sum(draws) / len(draws),
                },
                "M_singular_values_top5": [float(x) for x in S_M[:5].tolist()],
                "M_frobenius_norm": float(torch.linalg.norm(S_M)),
                "null_construction": "exact Stiefel/Haar reduction (see sample_rotated_candidate "
                                     "docstring), never a literal m x m Q1 (infeasible at m={}))".format(m),
            },
            "rho_raw": rho_raw,
        },
        "L3_scale_rotation_decomposition": {
            "status": "DESCRIPTIVE-ONLY (raw decomposition preserved; no verdict authority)",
            "common_direction": "D = normalize((U_R + U_T) / 2)",
            "parallel_fraction": parallel_fraction,
            "rho_perp": rho_perp,
        },
        "signed_first_order_gap": {
            "e_T_minus_e_R": e_diff_direct,
            "sign_convention": "U_arm is the ACTUAL parameter delta (build_arm_update returns "
                               "-lr*scale*NS5(...) measured from zero), so the first-order "
                               "loss change along an arm is <G_post, U_arm>_F with s=1 (the "
                               "lr is already inside U). POSITIVE e_T - e_R means the "
                               "TRANSPLANT arm's first-order integrand is less negative: "
                               "TRANSPLANT predicts HIGHER event-local train loss than RESET "
                               "at first order.",
            "caveat": "the |rho_perp| orientation statistic is sign-insensitive; any "
                      "directional bridge claim must carry this signed gap explicitly -- "
                      "its direction can contradict a naively assumed one. Reported as a "
                      "caveat/descriptive quantity, not independent evidence (the prereg "
                      "struck e_T - e_R from the evidence ledger as a linear function of "
                      "the L2 quantities; the merge-gate amendment binds reporting it "
                      "SIGNED because the sign qualifies the orientation claim).",
        },
        "claim_scope": {
            "verdict_vocabulary": ["SIBLING_NON_NULL_ORIENTATION", "INCONCLUSIVE",
                                    "FAILED-ENGAGEMENT"],
            "superseded_vocabulary": "BRIDGE-ALIVE / NULL-PRIMARY / EFFECTIVE-LR-ARTIFACT "
                                     "(#449 sec.4 frozen table) -- removed by tighten-only "
                                     "claim-narrowing supersession; this leg cannot mint a "
                                     "loss-bridge verdict.",
            "authority": "exact-head hostile review + frozen Q2 successor contract (sha256 "
                         f"{SUCCESSOR_CONTRACT_SHA256})",
            "rationale": [
                "the cached tensors are CPU reconstructions from bf16 pre_momentum, NOT the "
                "actual decisive GPU U_T/U_R delta bytes (this receipt's own L1 audit "
                "tolerates 0.1-0.2% reconstruction mismatch)",
                "no common batch and no paired L(W+v_T) - L(W+v_R) measurement exists at "
                "this event",
                "a non-null orientation of G_post against the reconstructed sibling "
                "difference therefore cannot be called a loss bridge",
                "actual-bridge verdicts await future-event capture (actual GPU delta bytes "
                "+ common batch + paired losses) per the successor contract",
            ],
        },
        "verdict_table": {
            "SIBLING_NON_NULL_ORIENTATION": "p_upper < alpha (0.003), where p_upper = "
                                            "min(1, 1/(mn * rho_perp^2))",
            "INCONCLUSIVE": "p_upper >= alpha -- failure to reject the Haar null; NEVER a "
                            "null/bridge-dead claim",
        },
        "api_spend_usd": 0, "paid_api_surface_used": False, "invalid_tokens_present": [],
        "verdict": verdict,
    }
    receipt_dir.mkdir(parents=True, exist_ok=True)
    path = receipt_dir / f"q2-rho-leg-{_ts()}.json"
    checked_write(str(path), receipt)
    print(f"Q2_RHO_LEG_DONE verdict={verdict} p_upper={p_upper:.6e} rho_raw={rho_raw:.6f} "
          f"rho_perp={rho_perp:.6f} e_T_minus_e_R={e_diff_direct:+.7f} receipt={path}", flush=True)
    return path


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------

def _write_synthetic_cache(tmp_dir: Path, m_pre: int, n: int, seed: int, corrupt: bool = False) -> Path:
    import torch
    cache_dir = tmp_dir / "b513-b4rerun"
    cache_dir.mkdir(parents=True, exist_ok=True)
    gen = torch.Generator().manual_seed(seed)
    grad_post_gate = torch.randn(2 * m_pre, n, generator=gen)
    grad_pre_gate = torch.randn(m_pre, n, generator=gen)
    pre_momentum = torch.randn(m_pre, n, generator=gen).to(torch.bfloat16)
    theta_gate_pre = torch.randn(m_pre, n, generator=gen)

    payload = {
        "b513-b4rerun-grad-post-gate.pt": grad_post_gate,
        "b513-b4rerun-grad-pre-gate.pt": grad_pre_gate,
        "b513-b4rerun-pre-momentum.pt": pre_momentum,
        "b513-b4rerun-theta-gate-pre.pt": theta_gate_pre,
    }
    lines = []
    for fname, t in payload.items():
        p = cache_dir / fname
        torch.save(t, p)
        lines.append(f"{sha256_file(p)} *{fname}")
    if corrupt:
        # flip a byte in one file AFTER the manifest was computed -- proves
        # the sha check, not just file-existence.
        target = cache_dir / "b513-b4rerun-grad-post-gate.pt"
        data = bytearray(target.read_bytes())
        data[-1] ^= 0xFF
        target.write_bytes(bytes(data))
    (cache_dir / "sha256-manifest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return cache_dir


def selftest_l0() -> None:
    import torch
    with tempfile.TemporaryDirectory(prefix="q2rho-selftest-l0-") as td:
        good_dir = _write_synthetic_cache(Path(td) / "good", m_pre=8, n=4, seed=1, corrupt=False)
        loaded = load_and_verify_cache(good_dir)
        assert all(v["sha256_match"] for v in loaded["verify_report"].values()), "L0 positive path failed"

        bad_dir = _write_synthetic_cache(Path(td) / "bad", m_pre=8, n=4, seed=2, corrupt=True)
        try:
            load_and_verify_cache(bad_dir)
            raise AssertionError("L0 negative path did not raise on a corrupted tensor")
        except EngagementFailure:
            pass
    print("selftest_l0: PASS", flush=True)


def selftest_null_reduction() -> None:
    """Cross-checks sample_rotated_candidate's exact-reduction distribution
    against the LITERAL Q1.M.Q2^T construction (feasible only for a tiny
    matrix) -- same seed family, many draws each, compare the empirical
    99.7th-percentile |cos| threshold. Not expected to be bit-identical
    (different sampling paths of the same distribution); asserts the two
    thresholds agree within finite-sample noise."""
    import torch
    m, n = 20, 6
    gen_fixed = torch.Generator().manual_seed(777)
    G_post = torch.randn(m, n, generator=gen_fixed)
    M = torch.randn(m, n, generator=gen_fixed)
    n_draws = 4000

    # literal construction
    gen_lit = torch.Generator().manual_seed(1001)
    literal_draws = []
    for _ in range(n_draws):
        Q1 = _sample_haar_orthogonal(m, gen_lit)
        Q2 = _sample_haar_orthogonal(n, gen_lit)
        cand = Q1 @ M @ Q2.T
        literal_draws.append(frobenius_cos(G_post, cand))

    # reduced construction
    reduced_draws, reduced_threshold, _S = empirical_rotation_null(G_post, M, n_draws, seed=2002)

    lit_sorted = sorted(abs(x) for x in literal_draws)
    k = int(round((NULL_PERCENTILE / 100.0) * (len(lit_sorted) - 1)))
    literal_threshold = lit_sorted[k]

    lit_mean = sum(abs(x) for x in literal_draws) / len(literal_draws)
    red_mean = sum(abs(x) for x in reduced_draws) / len(reduced_draws)

    rel_diff_threshold = abs(literal_threshold - reduced_threshold) / max(literal_threshold, 1e-9)
    rel_diff_mean = abs(lit_mean - red_mean) / max(lit_mean, 1e-9)
    assert rel_diff_threshold < 0.35, (
        f"null-reduction mismatch: literal_threshold={literal_threshold:.4f} "
        f"reduced_threshold={reduced_threshold:.4f} rel_diff={rel_diff_threshold:.3f}")
    assert rel_diff_mean < 0.25, (
        f"null-reduction mean mismatch: literal_mean={lit_mean:.4f} reduced_mean={red_mean:.4f} "
        f"rel_diff={rel_diff_mean:.3f}")
    print(f"selftest_null_reduction: PASS literal_threshold={literal_threshold:.4f} "
          f"reduced_threshold={reduced_threshold:.4f} literal_mean={lit_mean:.4f} "
          f"reduced_mean={red_mean:.4f}", flush=True)


def _planted_scenario(mn: int, c0: float, c1: float, c2: float, alpha: float, beta: float, seed: int):
    """Builds G_post (= b0, a fixed unit direction) and M = c0*b0+c1*b1+c2*b2
    (b1,b2 orthonormal, both ⟂ b0) directly (bypassing NS5 -- disclosed
    synthetic-mode construction for exercising L2/L3/verdict logic under
    controlled, exactly-known rho_raw/rho_perp), plus U_R/U_T reconstructed
    from a common direction D = alpha*b0 + beta*b1 (unit) so that
    (U_R+U_T)/2 = D and U_T-U_R = M exactly, matching L3's own contract."""
    import torch
    gen = torch.Generator().manual_seed(seed)
    v0 = torch.randn(mn, generator=gen)
    b0 = v0 / torch.linalg.norm(v0)
    v1 = torch.randn(mn, generator=gen)
    v1 = v1 - torch.dot(v1, b0) * b0
    b1 = v1 / torch.linalg.norm(v1)
    v2 = torch.randn(mn, generator=gen)
    v2 = v2 - torch.dot(v2, b0) * b0 - torch.dot(v2, b1) * b1
    b2 = v2 / torch.linalg.norm(v2)

    G_post = b0.clone()
    M = c0 * b0 + c1 * b1 + c2 * b2
    D = alpha * b0 + beta * b1
    assert abs(float(torch.linalg.norm(D)) - 1.0) < 1e-5, "D must be unit (alpha^2+beta^2=1)"
    U_R = D - M / 2.0
    U_T = D + M / 2.0
    return G_post, M, U_R, U_T


def selftest_verdicts() -> None:
    """Three scenarios at m=64, n=16 (mn=1024 -- large enough that the
    canonical analytic bound p_upper = 1/(mn*rho^2) CAN cross alpha=0.003
    at a plantable rho < 1; at tiny mn the bound never rejects, correctly),
    confirming the superseded-vocabulary verdict logic:

      - a strong orthogonal alignment mints SIBLING_NON_NULL_ORIENTATION;
      - a near-null alignment stays INCONCLUSIVE;
      - the parallel-absorbed shape (formerly the effective-LR-artifact
        class, now descriptive-only) stays INCONCLUSIVE even though
        rho_raw is large -- its descriptive markers (rho_raw > 0.9,
        parallel_fraction > 0.9, |rho_perp| ~ 0) are asserted so the
        decomposition's discriminating power is still exercised.

    The empirical null runs alongside at each scenario (descriptive-only,
    machinery-coverage) but the verdict assertion binds to the analytic p."""
    import torch
    m, n = 64, 16
    mn = m * n

    # Closed-form design (derived, not guessed -- see comments): with
    # G_post=b0, M=c0*b0+c1*b1+c2*b2, D=alpha*b0+beta*b1 (unit,
    # alpha^2+beta^2=1), the orthogonal-to-D numerator is exactly
    # <b0,M_perp> = beta*(c0*beta - c1*alpha). Setting alpha=0 (D=b1,
    # purely orthogonal to G_post) collapses this to c0*beta=c0, i.e.
    # rho_perp tracks rho_raw directly through c0 alone -- clean small-c0
    # (INCONCLUSIVE) / large-c0 (mint) scenarios. Setting
    # c1 = c0*beta/alpha (alpha != 0) makes the numerator EXACTLY zero
    # regardless of c2 -- rho_perp collapses to ~0 while rho_raw stays
    # controlled by c0/c2 alone: the parallel-absorbed shape (D absorbs
    # all of M's real G_post alignment; nothing survives orthogonal to it).
    alpha_absorbed = 0.995
    beta_absorbed = (1 - alpha_absorbed ** 2) ** 0.5
    c0_absorbed = 2.0
    c1_absorbed = c0_absorbed * beta_absorbed / alpha_absorbed  # exact rho_perp-nulling choice

    scenarios = {
        # rho_perp ~ 3/sqrt(9.01) ~ 0.9994 -> p ~ 1/(1024*0.9989) ~ 9.8e-4 < 0.003 -> mint
        "mint": dict(c0=3.0, c1=0.3, c2=0.1, alpha=0.0, beta=1.0, seed=11,
                     expect="SIBLING_NON_NULL_ORIENTATION"),
        # rho_perp ~ 0.01 -> p = min(1, 1/(1024*1e-4)) = 1 -> INCONCLUSIVE
        "near-null": dict(c0=0.01, c1=1.0, c2=1.0, alpha=0.0, beta=1.0, seed=22,
                          expect="INCONCLUSIVE"),
        # rho_perp exactly ~0 by construction, rho_raw ~ 0.99 -> INCONCLUSIVE
        # (formerly EFFECTIVE-LR-ARTIFACT; verdict authority removed)
        "parallel-absorbed": dict(c0=c0_absorbed, c1=c1_absorbed, c2=0.1,
                                  alpha=alpha_absorbed, beta=beta_absorbed, seed=33,
                                  expect="INCONCLUSIVE"),
    }

    for name, params in scenarios.items():
        seed = params.pop("seed")
        expected_verdict = params.pop("expect")
        G_post_flat, M_flat, U_R_flat, U_T_flat = _planted_scenario(mn, seed=seed, **params)
        G_post = G_post_flat.reshape(m, n)
        M = M_flat.reshape(m, n)
        U_R = U_R_flat.reshape(m, n)
        U_T = U_T_flat.reshape(m, n)

        rho_raw = frobenius_cos(G_post, M)
        # descriptive-only empirical ensemble, machinery coverage
        draws, threshold, _S = empirical_rotation_null(G_post, M, n_draws=200, seed=seed + 100000)
        M_parallel, M_perp, parallel_fraction, D_hat = decompose_parallel_orthogonal(M, U_R, U_T)
        rho_perp = frobenius_cos(G_post, M_perp)
        p_upper = analytic_p_upper(rho_perp, mn)
        got = verdict_from(p_upper)
        assert got == expected_verdict, (
            f"scenario {name}: got {got}, expected {expected_verdict} "
            f"(rho_raw={rho_raw:.4f} rho_perp={rho_perp:.4f} p_upper={p_upper:.6f} "
            f"parallel_fraction={parallel_fraction:.4f})")
        if name == "parallel-absorbed":
            assert abs(rho_raw) > 0.9, f"absorbed scenario lost its raw alignment (rho_raw={rho_raw:.4f})"
            assert parallel_fraction > 0.9, (
                f"absorbed scenario's parallel_fraction={parallel_fraction:.4f} not dominant")
            assert abs(rho_perp) < 1e-3, f"absorbed scenario's rho_perp={rho_perp:.6f} not nulled"
        print(f"selftest_verdicts: {name} -> {got} PASS rho_raw={rho_raw:.4f} "
              f"rho_perp={rho_perp:.4f} p_upper={p_upper:.6f} "
              f"empirical_threshold(descriptive)={threshold:.4f}", flush=True)


def selftest_arm_reconstruction() -> None:
    """Sanity check on build_arm_update's zero-weight trick: RESET arm
    (momentum=0) update direction must be independent of momentum-buffer
    content (pure function of grad), and TRANSPLANT arm (nonzero momentum)
    must differ from RESET whenever the momentum is nonzero and not
    perfectly co-linear with grad -- catches a silent zero-momentum
    fallback (the #513 defect class named in the reused module)."""
    import torch
    gen = torch.Generator().manual_seed(55)
    m, n = 12, 5
    grad = torch.randn(m, n, generator=gen)
    momentum = torch.randn(m, n, generator=gen)
    U_R, U_T = reconstruct_arms(grad, momentum[: m // 2, :], lr=0.02)
    assert U_R.shape == (m, n) and U_T.shape == (m, n)
    diff_rms = rms(U_T - U_R)
    assert diff_rms > 1e-8, "TRANSPLANT arm collapsed onto RESET arm (silent zero-momentum fallback?)"
    print(f"selftest_arm_reconstruction: PASS diff_rms={diff_rms:.6e}", flush=True)


def run_selftest(args) -> None:
    import torch
    assert not torch.cuda.is_initialized(), "Q2-RHO-LEG is CPU-only; torch.cuda must never initialize"
    selftest_l0()
    selftest_arm_reconstruction()
    selftest_null_reduction()
    selftest_verdicts()
    print("Q2_RHO_LEG_SELFTEST_PASS", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    ap.add_argument("--receipt-dir", default=str(RECEIPT_DIR_DEFAULT))
    ap.add_argument("--crossref-receipt", default=str(CROSSREF_RECEIPT_DEFAULT))
    ap.add_argument("--n-null", type=int, default=N_NULL_DRAWS_DEFAULT)
    ap.add_argument("--null-seed", type=int, default=449466)
    args = ap.parse_args()

    if args.selftest:
        run_selftest(args)
        return 0

    path = run_real(args)
    return 0 if path is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
