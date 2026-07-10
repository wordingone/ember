#!/usr/bin/env python3
"""Unit tests for scripts/c8_prelaunch/q2_rho_leg.py (issue #662; frozen
spec: issue #449 comment 4932624437 section 4).

Complements the module's own `--selftest` CLI mode (an integration smoke
test covering L0 positive/negative sha paths, the Haar-null exact-reduction
cross-check, and all three frozen verdicts end-to-end) with focused,
fast, direct-import unit tests on the individual L0-L3 primitives. One test
here (`test_cli_selftest_smoke`) also shells out to `--selftest` itself so
a CI failure in the integration path is caught even if every unit test
below passes.

CPU-only; every fixture here is synthetic and small (fixed seeds, tiny
matrices) -- no real cache tensors are touched.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import torch

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts" / "c8_prelaunch"))
sys.path.insert(0, str(_REPO / "scripts"))

import q2_rho_leg as qrl  # noqa: E402


def test_frobenius_cos_basic():
    a = torch.tensor([[1.0, 0.0], [0.0, 0.0]])
    b = torch.tensor([[1.0, 0.0], [0.0, 0.0]])
    assert qrl.frobenius_cos(a, b) == pytest.approx(1.0, abs=1e-6)

    c = torch.tensor([[0.0, 1.0], [0.0, 0.0]])
    assert qrl.frobenius_cos(a, c) == pytest.approx(0.0, abs=1e-6)

    d = torch.tensor([[-1.0, 0.0], [0.0, 0.0]])
    assert qrl.frobenius_cos(a, d) == pytest.approx(-1.0, abs=1e-6)

    zero = torch.zeros(2, 2)
    assert qrl.frobenius_cos(a, zero) != qrl.frobenius_cos(a, zero)  # NaN != NaN


def test_verdict_from_table():
    # BRIDGE-ALIVE: orthogonal component alone clears the threshold.
    assert qrl.verdict_from(rho_raw=0.5, rho_perp=0.9, threshold=0.3) == "BRIDGE-ALIVE"
    # EFFECTIVE-LR-ARTIFACT: raw clears, orthogonal remainder does not.
    assert qrl.verdict_from(rho_raw=0.5, rho_perp=0.1, threshold=0.3) == "EFFECTIVE-LR-ARTIFACT"
    # NULL-PRIMARY: neither clears.
    assert qrl.verdict_from(rho_raw=0.1, rho_perp=0.05, threshold=0.3) == "NULL-PRIMARY"
    # sign-insensitive (|.| per the frozen table).
    assert qrl.verdict_from(rho_raw=-0.5, rho_perp=-0.9, threshold=0.3) == "BRIDGE-ALIVE"
    # boundary: exactly-at-threshold does NOT count as exceeding it (strict >).
    assert qrl.verdict_from(rho_raw=0.0, rho_perp=0.3, threshold=0.3) == "NULL-PRIMARY"


def test_decompose_parallel_orthogonal_exact():
    """M constructed as a KNOWN sum of a component along D and a component
    orthogonal to D; the decomposition must recover both exactly (up to
    float tolerance) and parallel_fraction must match the planted ratio."""
    torch.manual_seed(3)
    m, n = 10, 4
    d_raw = torch.randn(m, n)
    D_hat = d_raw / torch.linalg.norm(d_raw.flatten())
    orth_raw = torch.randn(m, n)
    orth_raw = orth_raw - torch.dot(orth_raw.flatten(), D_hat.flatten()) * D_hat  # force exact orthogonality
    orth_hat = orth_raw / torch.linalg.norm(orth_raw.flatten())

    k_par, k_perp = 2.0, 5.0
    M = k_par * D_hat + k_perp * orth_hat
    U_R = -M / 2.0  # (U_R+U_T)/2 = 0-direction is degenerate; use a nonzero common direction instead below
    U_T = M / 2.0
    # Give U_R/U_T a real common direction equal to D_hat so decompose's
    # own D = normalize((U_R+U_T)/2) recovers D_hat (not degenerate).
    U_R = D_hat - M / 2.0
    U_T = D_hat + M / 2.0

    M_parallel, M_perp, parallel_fraction, D_hat_recovered = qrl.decompose_parallel_orthogonal(M, U_R, U_T)

    expected_fraction = k_par / (k_par ** 2 + k_perp ** 2) ** 0.5
    assert parallel_fraction == pytest.approx(expected_fraction, abs=1e-4)
    assert float(torch.linalg.norm((M_parallel - k_par * D_hat).flatten())) < 1e-4
    assert float(torch.linalg.norm((M_perp - k_perp * orth_hat).flatten())) < 1e-4


def test_load_and_verify_cache_failed_engagement_on_corruption():
    with tempfile.TemporaryDirectory(prefix="q2rho-unit-") as td:
        bad_dir = qrl._write_synthetic_cache(Path(td), m_pre=6, n=3, seed=9, corrupt=True)
        with pytest.raises(qrl.EngagementFailure):
            qrl.load_and_verify_cache(bad_dir)


def test_load_and_verify_cache_passes_on_clean_data():
    with tempfile.TemporaryDirectory(prefix="q2rho-unit-") as td:
        good_dir = qrl._write_synthetic_cache(Path(td), m_pre=6, n=3, seed=9, corrupt=False)
        loaded = qrl.load_and_verify_cache(good_dir)
        assert loaded["shapes"]["grad_post_gate"]["shape"] == [12, 3]
        assert loaded["shapes"]["pre_momentum"]["dtype"] == "torch.bfloat16"
        assert all(v["sha256_match"] for v in loaded["verify_report"].values())


def test_reset_arm_independent_of_momentum_content():
    """RESET arm uses an explicit zero momentum buffer -- its update must be
    identical regardless of what `pre_momentum` (only consumed by the
    TRANSPLANT arm) actually contains. Catches a silent argument-order /
    zero-fallback confusion (the #513 defect class in the reused module)."""
    torch.manual_seed(21)
    m, n = 16, 4
    grad = torch.randn(2 * m, n)
    mom_a = torch.randn(m, n)
    mom_b = torch.randn(m, n) * 100.0  # wildly different content

    U_R_a, U_T_a = qrl.reconstruct_arms(grad, mom_a, lr=0.02)
    U_R_b, U_T_b = qrl.reconstruct_arms(grad, mom_b, lr=0.02)

    assert float(torch.linalg.norm((U_R_a - U_R_b).flatten())) < 1e-6, (
        "RESET arm changed when only the (unconsumed) momentum buffer changed")
    assert float(torch.linalg.norm((U_T_a - U_T_b).flatten())) > 1e-3, (
        "TRANSPLANT arm did not respond to a large momentum-content change"
    )


def test_sample_semi_orthonormal_is_orthonormal():
    gen = torch.Generator().manual_seed(42)
    m, n = 30, 7
    W = qrl._sample_semi_orthonormal(m, n, gen)
    gram = W.T @ W
    assert torch.allclose(gram, torch.eye(n), atol=1e-4)


def test_empirical_rotation_null_threshold_is_nonnegative_and_bounded():
    torch.manual_seed(5)
    G = torch.randn(24, 5)
    M = torch.randn(24, 5)
    draws, threshold, S = qrl.empirical_rotation_null(G, M, n_draws=100, seed=1)
    assert threshold >= 0.0
    assert threshold <= 1.0 + 1e-6
    assert len(draws) == 100
    assert len(S) == 5


def test_cli_selftest_smoke():
    """Shells out to the module's own --selftest CLI path -- the acceptance
    bar's own integration test ('runs in CI'); catches any regression the
    unit tests above don't (e.g. a broken argparse wiring or a broken
    print-marker contract main() relies on)."""
    result = subprocess.run(
        [sys.executable, str(_REPO / "scripts" / "c8_prelaunch" / "q2_rho_leg.py"), "--selftest"],
        capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Q2_RHO_LEG_SELFTEST_PASS" in result.stdout
