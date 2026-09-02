#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Unit tests for spectral measurement SVD plumbing.

Tests verify that torch.linalg.svdvals correctly computes top singular values
on known matrices and that the spectral norm (largest singular value) extraction
is faithful.
"""
import torch
import math


def test_identity_matrix_spectral_norm():
    """Identity matrix has spectral norm = 1."""
    I = torch.eye(5, dtype=torch.float32)
    singular_values = torch.linalg.svdvals(I)
    top_sv = singular_values[0].item()
    assert abs(top_sv - 1.0) < 1e-6, f"Expected 1.0, got {top_sv}"
    print("PASS: test_identity_matrix_spectral_norm")


def test_diagonal_matrix_spectral_norm():
    """Diagonal matrix has spectral norm = largest absolute diagonal element."""
    diag_vals = torch.tensor([1.5, 0.3, 2.7, 0.1], dtype=torch.float32)
    D = torch.diag(diag_vals)
    singular_values = torch.linalg.svdvals(D)
    top_sv = singular_values[0].item()
    expected = 2.7
    assert abs(top_sv - expected) < 1e-6, f"Expected {expected}, got {top_sv}"
    print("PASS: test_diagonal_matrix_spectral_norm")


def test_scaled_identity_spectral_norm():
    """Scaled identity matrix has spectral norm = scaling factor."""
    scale = 2.5
    I_scaled = scale * torch.eye(4, dtype=torch.float32)
    singular_values = torch.linalg.svdvals(I_scaled)
    top_sv = singular_values[0].item()
    assert abs(top_sv - scale) < 1e-6, f"Expected {scale}, got {top_sv}"
    print("PASS: test_scaled_identity_spectral_norm")


def test_rank_one_matrix_spectral_norm():
    """Rank-1 matrix has one nonzero singular value."""
    u = torch.tensor([[1.0], [2.0], [3.0]], dtype=torch.float32)
    v = torch.tensor([[1.0, 2.0]], dtype=torch.float32)
    A = u @ v  # rank-1 matrix
    singular_values = torch.linalg.svdvals(A)
    # Should have one large singular value and rest near-zero
    top_sv = singular_values[0].item()
    # Frobenius norm of rank-1 matrix is the singular value
    A_norm = torch.norm(A).item()
    assert abs(top_sv - A_norm) < 1e-5, f"Expected {A_norm}, got {top_sv}"
    print("PASS: test_rank_one_matrix_spectral_norm")


def test_ratio_of_scaled_matrices():
    """Test ratio computation on scaled versions of a matrix."""
    # Create a base matrix
    base = torch.tensor([[2.0, 1.0], [1.0, 3.0]], dtype=torch.float32)

    # Pre-scale
    scale_pre = 1.0
    A_pre = scale_pre * base
    sv_pre = torch.linalg.svdvals(A_pre)[0].item()

    # Post-scale (e.g., 0.707 * pre)
    scale_post = 0.707
    A_post = scale_post * base
    sv_post = torch.linalg.svdvals(A_post)[0].item()

    # Ratio should be scale_post / scale_pre
    ratio = sv_post / sv_pre
    expected_ratio = scale_post / scale_pre
    assert abs(ratio - expected_ratio) < 1e-5, \
        f"Expected ratio {expected_ratio}, got {ratio}"
    print("PASS: test_ratio_of_scaled_matrices")


def test_rms_crosscheck():
    """Test that RMS (root mean square) of an update matches expected value."""
    # A simple 2D update vector
    update = torch.tensor([[1.0, 2.0], [3.0, 4.0]], dtype=torch.float32)
    rms_val = torch.sqrt((update ** 2).mean()).item()
    # Expected: sqrt((1+4+9+16)/4) = sqrt(30/4) = sqrt(7.5)
    expected = math.sqrt(7.5)
    assert abs(rms_val - expected) < 1e-6, f"Expected {expected}, got {rms_val}"
    print("PASS: test_rms_crosscheck")


def test_rms_zero_detection():
    """Test that RMS correctly detects zero tensors."""
    zero_tensor = torch.zeros(3, 4, dtype=torch.float32)
    rms_val = torch.sqrt((zero_tensor ** 2).mean()).item()
    assert rms_val < 1e-10, f"Expected near-zero RMS, got {rms_val}"
    print("PASS: test_rms_zero_detection")


def test_svdvals_shape():
    """Test that svdvals returns correct number of singular values."""
    A = torch.randn(5, 3, dtype=torch.float32)
    svs = torch.linalg.svdvals(A)
    # For a 5x3 matrix, there should be min(5,3) = 3 singular values
    assert len(svs) == 3, f"Expected 3 singular values, got {len(svs)}"
    print("PASS: test_svdvals_shape")


def run_all_tests():
    """Run all unit tests."""
    tests = [
        test_identity_matrix_spectral_norm,
        test_diagonal_matrix_spectral_norm,
        test_scaled_identity_spectral_norm,
        test_rank_one_matrix_spectral_norm,
        test_ratio_of_scaled_matrices,
        test_rms_crosscheck,
        test_rms_zero_detection,
        test_svdvals_shape,
    ]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {test.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    return passed == len(tests)


if __name__ == "__main__":
    import sys
    success = run_all_tests()
    sys.exit(0 if success else 1)
