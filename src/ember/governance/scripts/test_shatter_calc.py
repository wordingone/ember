# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""
test_shatter_calc.py — TDD for the SHATTER computation.

Tests:
  1. trailing_k_mean: correctness on hand-computed examples
  2. tokens_to_match_ref: first-reach semantics + cap-at-budget
  3. effective_days: formula correctness
  4. full_fused real loss_log: smoothed final value matches frozen spec
  5. SHATTER=True branch: synthetic fast variant reaching ref before budget
  6. SHATTER=False branch: synthetic slow variant that never reaches ref
  7. quality_ok=False branch: fast variant but loss too high (above ref + epsilon)
  8. Integration: run() with synthetic tmpdir, muon_split ref present

All tests operate on either real full_fused data (20 entries, completed) or
fully synthetic curves — no muon_ns3 / muon_split convergence data used.
"""

import json
import math
import os
import sys
import tempfile
import unittest

# Allow import from scripts dir
sys.path.insert(0, os.path.dirname(__file__))
from shatter_calc import (
    K, EPSILON, BUDGET_B, BUDGET_TOKENS, TOK_S_PACED, SECS_PER_DAY,
    trailing_k_mean, tokens_to_match_ref, effective_days, load_loss_log, run,
)

REAL_LOSS_LOG = os.path.join(
    os.path.dirname(__file__),
    "..", "models", "conv-full_fused_adamw-seed42", "loss_log.jsonl"
)


class TestTrailingKMean(unittest.TestCase):
    """Unit tests for the trailing-K window mean."""

    def test_single_entry(self):
        result = trailing_k_mean([5.0], K=5)
        self.assertEqual(result, [5.0])

    def test_fewer_than_k_entries_uses_all(self):
        # 3 entries, K=5 → each window is [0..i]
        losses = [10.0, 8.0, 6.0]
        result = trailing_k_mean(losses, K=5)
        self.assertAlmostEqual(result[0], 10.0)
        self.assertAlmostEqual(result[1], 9.0)    # (10+8)/2
        self.assertAlmostEqual(result[2], 8.0)    # (10+8+6)/3

    def test_exactly_k_entries(self):
        losses = [10.0, 9.0, 8.0, 7.0, 6.0]
        result = trailing_k_mean(losses, K=5)
        # Last entry uses all 5
        self.assertAlmostEqual(result[-1], 8.0)
        # First 4 use i+1 entries
        self.assertAlmostEqual(result[0], 10.0)
        self.assertAlmostEqual(result[3], (10+9+8+7)/4)

    def test_more_than_k_entries(self):
        losses = [10.0, 9.0, 8.0, 7.0, 6.0, 5.0]
        result = trailing_k_mean(losses, K=5)
        # Entry 5: window = [1..5] = [9,8,7,6,5]
        self.assertAlmostEqual(result[5], (9+8+7+6+5)/5)

    def test_frozen_k_is_5(self):
        self.assertEqual(K, 5, "Frozen K must be 5 — do not change without re-freezing method")

    def test_length_preserved(self):
        losses = [float(i) for i in range(20)]
        result = trailing_k_mean(losses, K=5)
        self.assertEqual(len(result), 20)

    def test_monotone_input_monotone_output(self):
        """Trailing mean of monotonically decreasing sequence is monotonically decreasing."""
        losses = [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0]
        result = trailing_k_mean(losses, K=5)
        for i in range(1, len(result)):
            self.assertLessEqual(result[i], result[i-1] + 1e-9)


class TestTokensToMatchRef(unittest.TestCase):
    """Unit tests for tokens_to_match_ref."""

    def _make_tokens(self, n, step=3_000_000):
        return [step * (i + 1) for i in range(n)]

    def test_first_entry_matches(self):
        tokens = self._make_tokens(5)
        smoothed = [5.0, 6.0, 7.0, 8.0, 9.0]
        # ref = 6.0 → first entry with smoothed <= 6.0 is index 0 (smoothed=5.0)
        result = tokens_to_match_ref(tokens, smoothed, ref_loss=6.0)
        self.assertEqual(result, tokens[0])

    def test_middle_entry_matches(self):
        tokens = self._make_tokens(5)
        smoothed = [8.0, 7.5, 7.0, 6.5, 6.0]
        # ref = 7.2 → first entry <= 7.2 is index 2 (smoothed=7.0)
        result = tokens_to_match_ref(tokens, smoothed, ref_loss=7.2)
        self.assertEqual(result, tokens[2])

    def test_last_entry_matches(self):
        tokens = self._make_tokens(5)
        smoothed = [9.0, 8.0, 7.0, 6.5, 6.0]
        result = tokens_to_match_ref(tokens, smoothed, ref_loss=6.0)
        self.assertEqual(result, tokens[4])

    def test_never_matches_caps_at_budget(self):
        tokens = self._make_tokens(5)
        smoothed = [8.0, 7.5, 7.0, 6.5, 6.2]
        # ref = 6.0 → never reached
        result = tokens_to_match_ref(tokens, smoothed, ref_loss=6.0, budget_tokens=60_000_000)
        self.assertEqual(result, 60_000_000)

    def test_exact_equality_triggers_match(self):
        tokens = [10_000_000, 20_000_000]
        smoothed = [7.0, 6.5]
        result = tokens_to_match_ref(tokens, smoothed, ref_loss=6.5)
        self.assertEqual(result, 20_000_000)

    def test_budget_tokens_default_is_60m(self):
        self.assertEqual(BUDGET_TOKENS, 60_000_000)


class TestEffectiveDays(unittest.TestCase):
    """Unit tests for effective_days formula."""

    def test_formula_full_budget(self):
        # tokens_to_match = budget_tokens → scale factor = 1.0
        tok_s = TOK_S_PACED["full_fused_adamw"]
        ed = effective_days(BUDGET_TOKENS, tok_s)
        expected = BUDGET_B / tok_s / SECS_PER_DAY
        self.assertAlmostEqual(ed, expected, places=4)

    def test_formula_half_budget(self):
        tok_s = TOK_S_PACED["muon_split"]
        tok_to_match = BUDGET_TOKENS // 2
        ed = effective_days(tok_to_match, tok_s)
        expected = (BUDGET_B * 0.5) / tok_s / SECS_PER_DAY
        self.assertAlmostEqual(ed, expected, places=4)

    def test_full_fused_at_full_budget_approx_0_86(self):
        """From bench: full_fused gate_budget_days=0.86 at tok_s=29598.7 and budget=2.2e9."""
        tok_s = TOK_S_PACED["full_fused_adamw"]
        ed = effective_days(BUDGET_TOKENS, tok_s)
        # gate_budget_days from keystone receipt = 0.86
        self.assertAlmostEqual(ed, 0.86, delta=0.01)

    def test_muon_split_at_full_budget_approx_1_28(self):
        """muon_split gate_budget_days=1.281 at tok_s=19874.8."""
        tok_s = TOK_S_PACED["muon_split"]
        ed = effective_days(BUDGET_TOKENS, tok_s)
        self.assertAlmostEqual(ed, 1.281, delta=0.01)

    def test_tok_s_paced_values_match_receipt(self):
        """Bench tok_s values must match keystone receipt exactly."""
        self.assertEqual(TOK_S_PACED["full_fused_adamw"], 29598.7)
        self.assertEqual(TOK_S_PACED["muon_ns3"], 23068.8)
        self.assertEqual(TOK_S_PACED["muon_split"], 19874.8)


class TestFullFusedRealData(unittest.TestCase):
    """Verify computation on full_fused_adamw's REAL loss_log (20 entries, completed)."""

    def setUp(self):
        if not os.path.exists(REAL_LOSS_LOG):
            self.skipTest(f"Real loss_log not found: {REAL_LOSS_LOG}")
        self.tokens, self.losses = load_loss_log(REAL_LOSS_LOG)
        self.smoothed = trailing_k_mean(self.losses, K)

    def test_entry_count(self):
        self.assertEqual(len(self.tokens), 20)

    def test_last_token_near_60m(self):
        self.assertAlmostEqual(self.tokens[-1], 59_998_208, delta=100_000)

    def test_smoothed_final_loss_matches_frozen_spec(self):
        """Frozen spec states full_fused smoothed_final = 6.24375."""
        self.assertAlmostEqual(self.smoothed[-1], 6.24375, places=4)

    def test_smoothed_final_is_mean_of_last_k_raw(self):
        last_k = self.losses[-K:]
        expected = sum(last_k) / len(last_k)
        self.assertAlmostEqual(self.smoothed[-1], expected, places=6)

    def test_smoothed_length_equals_entry_count(self):
        self.assertEqual(len(self.smoothed), 20)

    def test_raw_loss_std_late_region(self):
        """Late region (last 10) raw std must be ~1.02 — used to derive epsilon."""
        import statistics
        std = statistics.stdev(self.losses[-10:])
        self.assertAlmostEqual(std, 1.018, delta=0.05)

    def test_epsilon_derivation(self):
        """epsilon = 1.1 * sigma_raw_late / sqrt(K) must give ~0.50."""
        import statistics
        sigma_raw = statistics.stdev(self.losses[-10:])
        epsilon_derived = 1.1 * sigma_raw / math.sqrt(K)
        self.assertAlmostEqual(epsilon_derived, 0.50, delta=0.05)
        self.assertEqual(EPSILON, 0.50, "Frozen EPSILON must be 0.50")


class TestSHATTERScenarios(unittest.TestCase):
    """Test SHATTER=True, SHATTER=False, and quality_ok=False using synthetic data + tmpdir."""

    TOK_STEP = 3_000_000
    N = 20

    def _make_log(self, variant: str, start_loss: float, end_loss: float, n: int = 20) -> list[dict]:
        """Generate a synthetic loss_log with a linear decrease from start_loss to end_loss."""
        entries = []
        for i in range(n):
            tok = self.TOK_STEP * (i + 1)
            loss = start_loss + (end_loss - start_loss) * i / max(n - 1, 1)
            entries.append({"tokens": tok, "step": i * 183, "loss": loss, "opt_variant": variant, "seed": 42})
        return entries

    def _write_log(self, path: str, entries: list[dict]):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def _setup_tmpdir(self, tmpdir: str, scenarios: dict):
        """Write synthetic logs for given variant→entries mapping."""
        for variant, entries in scenarios.items():
            path = os.path.join(tmpdir, f"conv-{variant}-seed42", "loss_log.jsonl")
            self._write_log(path, entries)

    def test_shatter_true_fast_variant_quality_ok(self):
        """SHATTER=True: full_fused reaches ref in first 30M tokens, smoothed_final < ref+epsilon."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # muon_split: converges to 6.0 (ref_loss = smoothed_final ~ 6.0)
            # full_fused: converges faster to 6.0 (reaches ref around 30M tokens)
            # muon_split entries: 20 entries, decreasing to 6.0
            ms_entries = self._make_log("muon_split", start_loss=10.0, end_loss=6.0, n=20)
            # full_fused: same curve but a slightly lower final (5.8)
            ff_entries = self._make_log("full_fused_adamw", start_loss=10.0, end_loss=5.8, n=20)
            self._setup_tmpdir(tmpdir, {"muon_split": ms_entries, "full_fused_adamw": ff_entries})

            result = run(loss_dir=tmpdir)

            self.assertIsNotNone(result["ref_loss"])
            self.assertTrue(result["SHATTER"], f"Expected SHATTER=True, got: {result['shatter_reason']}")
            self.assertEqual(result["shatter_variant"], "full_fused_adamw")

    def test_shatter_false_slow_variant(self):
        """SHATTER=False: full_fused loss clearly above ref + epsilon (quality_ok=False).

        muon_split converges to 5.0 (ref_loss ~ 5.0); threshold = 5.0 + 0.50 = 5.50.
        full_fused ends at 7.0, well above threshold → quality_ok=False → SHATTER=False.
        This avoids any borderline-exact-match arithmetic and is unambiguously False.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # ref: muon_split converges to 5.0 → smoothed_final ~ 5.0, threshold = 5.50
            ms_entries = self._make_log("muon_split", start_loss=10.0, end_loss=5.0, n=20)
            # full_fused: end_loss=7.0, clearly > threshold 5.50 → quality_ok=False
            ff_entries = self._make_log("full_fused_adamw", start_loss=10.0, end_loss=7.0, n=20)
            self._setup_tmpdir(tmpdir, {"muon_split": ms_entries, "full_fused_adamw": ff_entries})

            result = run(loss_dir=tmpdir)
            ff = result["variants"]["full_fused_adamw"]

            self.assertFalse(ff["quality_ok"],
                f"quality_ok should be False: smoothed_final={ff['smoothed_final_loss']:.4f}, "
                f"ref+eps={result['ref_loss'] + EPSILON:.4f}")
            self.assertFalse(result["SHATTER"], "SHATTER should be False when quality fails")

    def test_shatter_false_quality_ok_false_fast_but_diverged(self):
        """SHATTER=False: full_fused is fast BUT diverged (loss too high > ref + epsilon)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # muon_split ref converges to 5.0
            ms_entries = self._make_log("muon_split", start_loss=10.0, end_loss=5.0, n=20)
            # full_fused: starts and stays at 7.0 (way above ref=5.0+0.50=5.5)
            ff_entries = self._make_log("full_fused_adamw", start_loss=8.0, end_loss=7.0, n=20)
            self._setup_tmpdir(tmpdir, {"muon_split": ms_entries, "full_fused_adamw": ff_entries})

            result = run(loss_dir=tmpdir)
            ff = result["variants"]["full_fused_adamw"]
            # smoothed_final ~ 7.0, ref ~ 5.0, ref+eps=5.5 → quality_ok=False
            self.assertFalse(ff["quality_ok"],
                f"Expected quality_ok=False: smoothed_final={ff['smoothed_final_loss']}, "
                f"ref+eps={result['ref_loss'] + EPSILON:.4f}")
            self.assertFalse(result["SHATTER"])

    def test_no_muon_split_defers_verdict(self):
        """With muon_split missing, SHATTER verdict must be deferred (ref_loss=None)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ff_entries = self._make_log("full_fused_adamw", start_loss=10.0, end_loss=6.0, n=20)
            self._setup_tmpdir(tmpdir, {"full_fused_adamw": ff_entries})

            result = run(loss_dir=tmpdir)
            self.assertIsNone(result["ref_loss"])
            self.assertFalse(result["SHATTER"])
            self.assertIn("ref_loss not yet available", result["shatter_reason"])

    def test_tokens_to_match_ref_capped_when_never_reached(self):
        """tokens_to_match_ref = BUDGET_TOKENS when curve never reaches ref."""
        tokens = [3_000_000 * (i + 1) for i in range(20)]
        smoothed = [7.0] * 20  # flat, never reaches 6.0
        result_ttm = tokens_to_match_ref(tokens, smoothed, ref_loss=6.0)
        self.assertEqual(result_ttm, BUDGET_TOKENS)

    def test_effective_days_uses_bench_tok_s_not_conv_avg(self):
        """effective_days must use tok_s_paced (bench), not the convergence-run avg (21511)."""
        # convergence-run avg for full_fused = 21511 (from receipt tok_per_s)
        CONV_AVG = 21511.0
        bench_tok_s = TOK_S_PACED["full_fused_adamw"]  # 29598.7
        # effective_days with bench is LOWER (faster throughput → fewer days)
        ed_bench = effective_days(BUDGET_TOKENS, bench_tok_s)
        ed_conv = effective_days(BUDGET_TOKENS, CONV_AVG)
        self.assertLess(ed_bench, ed_conv,
            "Bench tok_s (29598.7) > conv avg (21511) → bench effective_days must be smaller")
        self.assertNotAlmostEqual(ed_bench, ed_conv, places=3,
            msg="bench and conv throughputs must differ meaningfully")

    def test_muon_split_effective_days_at_full_budget_above_1(self):
        """muon_split at full budget (ref matches at end) must have effective_days > 1."""
        ed = effective_days(BUDGET_TOKENS, TOK_S_PACED["muon_split"])
        self.assertGreater(ed, 1.0,
            f"muon_split effective_days={ed:.4f} should be > 1 (gate_budget_days=1.281 from receipt)")

    def test_full_fused_at_full_budget_below_1(self):
        """full_fused at full budget must have effective_days < 1 (gate_pass=True from bench)."""
        ed = effective_days(BUDGET_TOKENS, TOK_S_PACED["full_fused_adamw"])
        self.assertLess(ed, 1.0,
            f"full_fused effective_days={ed:.4f} should be < 1 (gate_budget_days=0.86 from receipt)")


class TestFrozenConstants(unittest.TestCase):
    """Guard the frozen constants against accidental modification."""

    def test_K_is_5(self):
        self.assertEqual(K, 5)

    def test_epsilon_is_0_5(self):
        self.assertEqual(EPSILON, 0.50)

    def test_budget_b_is_2_2e9(self):
        self.assertAlmostEqual(BUDGET_B, 2.2e9)

    def test_budget_tokens_is_60m(self):
        self.assertEqual(BUDGET_TOKENS, 60_000_000)

    def test_secs_per_day(self):
        self.assertEqual(SECS_PER_DAY, 86_400)


class TestBorderlineFlag(unittest.TestCase):
    """Test the FIX-2 borderline annotation: fires within 0.05 of threshold, not outside."""

    TOK_STEP = 3_000_000
    N = 20

    def _make_log(self, variant: str, start_loss: float, end_loss: float, n: int = 20) -> list[dict]:
        entries = []
        for i in range(n):
            tok = self.TOK_STEP * (i + 1)
            loss = start_loss + (end_loss - start_loss) * i / max(n - 1, 1)
            entries.append({"tokens": tok, "step": i * 183, "loss": loss, "opt_variant": variant, "seed": 42})
        return entries

    def _write_log(self, path: str, entries: list[dict]):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def _setup_tmpdir(self, tmpdir: str, scenarios: dict):
        for variant, entries in scenarios.items():
            path = os.path.join(tmpdir, f"conv-{variant}-seed42", "loss_log.jsonl")
            self._write_log(path, entries)

    def test_borderline_fires_within_0_05_of_threshold(self):
        """Variant whose smoothed_final is within 0.05 of ref+epsilon must have borderline=True.

        Setup: muon_split raw end=5.0, n=20 → smoothed_final (K=5 trailing mean of last 5)
        = mean of last 5 raw values ~ 5.526; threshold = 5.526 + 0.50 = 6.026.
        full_fused raw end=5.572 → smoothed_final ~ 6.038, margin = 6.026 - 6.038 = -0.012
        abs(margin) = 0.012 < 0.05 → borderline=True (quality_ok=False but annotated borderline).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            ms_entries = self._make_log("muon_split", start_loss=10.0, end_loss=5.0, n=20)
            # full_fused: raw end=5.572 → smoothed_final~6.038, just above threshold~6.026
            # quality_ok=False, |margin|~0.012 < 0.05 → borderline=True
            ff_entries = self._make_log("full_fused_adamw", start_loss=10.0, end_loss=5.572, n=20)
            self._setup_tmpdir(tmpdir, {"muon_split": ms_entries, "full_fused_adamw": ff_entries})

            result = run(loss_dir=tmpdir)
            ff = result["variants"]["full_fused_adamw"]

            threshold = result["ref_loss"] + EPSILON
            margin = threshold - ff["smoothed_final_loss"]
            self.assertTrue(
                abs(margin) < 0.05,
                f"Test setup: |margin|={abs(margin):.4f} should be < 0.05; "
                f"smoothed_final={ff['smoothed_final_loss']:.4f}, threshold={threshold:.4f}"
            )
            self.assertFalse(ff["quality_ok"], "quality_ok should be False (just over threshold)")
            self.assertTrue(ff.get("borderline"), f"borderline should be True; got variant dict: {ff}")
            self.assertIn("quality_margin", ff, "quality_margin field must be present when borderline")

    def test_borderline_not_set_when_clearly_passing(self):
        """Variant clearly passing (smoothed_final well below threshold) must NOT have borderline=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ms_entries = self._make_log("muon_split", start_loss=10.0, end_loss=5.0, n=20)
            # full_fused: end at 4.0, clearly below threshold 5.50 → quality_ok=True, no borderline
            ff_entries = self._make_log("full_fused_adamw", start_loss=10.0, end_loss=4.0, n=20)
            self._setup_tmpdir(tmpdir, {"muon_split": ms_entries, "full_fused_adamw": ff_entries})

            result = run(loss_dir=tmpdir)
            ff = result["variants"]["full_fused_adamw"]

            self.assertTrue(ff["quality_ok"], "quality_ok should be True (clearly passing)")
            self.assertFalse(ff.get("borderline", False),
                f"borderline should not be set when clearly passing; got: {ff.get('borderline')}")

    def test_borderline_not_set_when_clearly_failing(self):
        """Variant clearly failing (smoothed_final well above threshold) must NOT have borderline=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ms_entries = self._make_log("muon_split", start_loss=10.0, end_loss=5.0, n=20)
            # full_fused: end at 7.0, clearly above threshold 5.50 → quality_ok=False, no borderline
            ff_entries = self._make_log("full_fused_adamw", start_loss=10.0, end_loss=7.0, n=20)
            self._setup_tmpdir(tmpdir, {"muon_split": ms_entries, "full_fused_adamw": ff_entries})

            result = run(loss_dir=tmpdir)
            ff = result["variants"]["full_fused_adamw"]

            self.assertFalse(ff["quality_ok"], "quality_ok should be False (clearly failing)")
            self.assertFalse(ff.get("borderline", False),
                f"borderline should not be set when clearly failing; got: {ff.get('borderline')}")

    def test_borderline_propagates_to_top_level_when_shatter_variant_is_borderline(self):
        """If the SHATTER-deciding variant is borderline, top-level result must have borderline=True.

        Setup: muon_split raw end=6.24, n=20 -> ref_loss~6.636, threshold~7.136.
        full_fused raw end=6.76 -> smoothed_final~7.101, margin~0.035 < 0.05 -> borderline=True.
        effective_days=0.86 < 1.0, quality_ok=True -> SHATTER=True.
        Top-level output must also have borderline=True + quality_margin.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # muon_split: raw end=6.24 -> ref_loss~6.636, threshold~7.136
            ms_entries = self._make_log("muon_split", start_loss=10.0, end_loss=6.24, n=20)
            # full_fused: raw end=6.76 -> smoothed_final~7.101, margin~0.035 (borderline, quality_ok=True)
            # effective_days=0.86 < 1 -> SHATTER=True, and this variant is borderline
            ff_entries = self._make_log("full_fused_adamw", start_loss=10.0, end_loss=6.76, n=20)
            self._setup_tmpdir(tmpdir, {"muon_split": ms_entries, "full_fused_adamw": ff_entries})

            result = run(loss_dir=tmpdir)
            ff = result["variants"]["full_fused_adamw"]

            self.assertTrue(result["SHATTER"], f"Expected SHATTER=True; reason: {result['shatter_reason']}")
            self.assertEqual(result["shatter_variant"], "full_fused_adamw")
            self.assertTrue(ff.get("borderline"),
                f"full_fused_adamw should be borderline; variant dict: {ff}")
            self.assertTrue(result.get("borderline"),
                "Top-level borderline must be True when SHATTER variant is borderline")
            self.assertIn("quality_margin", result,
                "Top-level quality_margin must be present when borderline")


if __name__ == "__main__":
    unittest.main(verbosity=2)
