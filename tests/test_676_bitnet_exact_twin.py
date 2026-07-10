"""Pytest coverage for ember_bitnet_exact_twin.py (issue #676, prereg #674).

CPU-only, fast. Runs the module's embedded selftest suite (18 checks) as
one pytest node, plus a handful of direct assertions on the public API so
pytest failures point at the exact contract clause that broke, not just
"the selftest failed".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import ember_bitnet_exact_twin as bt  # noqa: E402


def test_embedded_selftest_suite_all_pass():
    receipt = bt._run_tests(verbose=False)
    assert receipt["all_passed"], receipt["errors"]
    assert receipt["failed"] == 0
    assert receipt["total"] >= 18
    assert receipt["verdict"] == "EMBER_BITNET_EXACT_TWIN_SELFTEST_PASS"


def test_frozen_param_count_literal():
    assert bt.FROZEN_PARAM_COUNT == 102_448_512
    assert bt.derive_param_count(bt.FROZEN_CONFIG) == 102_448_512


def test_frozen_identity_fields():
    cfg = bt.FROZEN_CONFIG
    assert (cfg.vocab, cfg.seq, cfg.hidden, cfg.depth) == (32_000, 1_024, 768, 9)
    assert (cfg.q_heads, cfg.kv_heads, cfg.head_dim) == (12, 4, 64)
    assert cfg.ffn_hidden == 3_072
    assert cfg.rope_theta == 10_000.0
    assert cfg.norm_eps == 1e-6
    assert bt.FROZEN_MTP_HEADS == 0


@pytest.mark.parametrize("ternary", [False, True])
def test_both_arms_build_at_exact_count(ternary):
    model = bt.build_exact_twin(ternary=ternary)
    assert bt.realized_param_count(model) == 102_448_512


def test_dense_arm_has_no_quantizer():
    dense = bt.build_exact_twin(ternary=False)
    bt.assert_dense_no_quantizer(dense)
    assert bt.ternary_value_fractions(dense) == {}


def test_ternary_arm_quantizer_scope_is_attn_ffn_only():
    ternary = bt.build_exact_twin(ternary=True)
    bt.assert_ternary_quantizer_scope(ternary)
    fracs = bt.ternary_value_fractions(ternary)
    assert len(fracs) == 7 * bt.FROZEN_CONFIG.depth


def test_arms_are_shape_isomorphic():
    dense = bt.build_exact_twin(ternary=False)
    ternary = bt.build_exact_twin(ternary=True)
    bt.assert_arms_isomorphic(dense, ternary)  # must not raise


def test_realized_head_and_norm_accounting_matches_frozen_identity():
    model = bt.build_exact_twin(ternary=False)
    acct = bt.realized_head_accounting(model)
    assert acct["realized_q_heads"] == 12
    assert acct["realized_kv_heads"] == 4
    assert acct["realized_head_dim"] == 64
    assert acct["realized_qk_norm_q_dim"] == 64
    assert acct["realized_qk_norm_k_dim"] == 64
    assert acct["realized_tied_embedding"] is True
    assert acct["realized_mtp_heads"] == 0
    assert acct["realized_depth"] == 9


def test_manifest_mismatch_causes_load_time_refusal():
    """Prereg gate item 7: a deliberate mismatch MUST cause load-time
    refusal, not a warning."""
    expected = bt.build_manifest(seed=0, token_order_hash="tok-a", eval_manifest_hash="eval-a")
    candidate = bt.build_manifest(seed=0, token_order_hash="tok-a", eval_manifest_hash="eval-B-WRONG")
    with pytest.raises(bt.ManifestMismatchError):
        bt.verify_manifest(candidate, expected)


def test_manifest_verify_passes_on_identical_manifest():
    m = bt.build_manifest(seed=7, token_order_hash="tok-x", eval_manifest_hash="eval-x")
    bt.verify_manifest(m, m)  # must not raise


def test_no_bias_anywhere_either_arm():
    for ternary in (False, True):
        model = bt.build_exact_twin(ternary=ternary)
        bt.assert_no_bias_anywhere(model)  # must not raise


def test_param_count_mismatch_is_fail_closed():
    with pytest.raises(bt.ParamCountMismatchError):
        bt.assert_exact_param_count(bt.build_exact_twin(ternary=False), expected=1)
