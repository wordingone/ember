#!/usr/bin/env python3
"""RED regression pair + amendments for the issue #585 MDE paired-covariance cure.

Binding spec: the coordinator disposition on issue #585 (comment 4931087645),
sign-corrected by the tighten-only amendment (comment 4931147752), plus the
exact-power addendum (independent-audit comment 4931301214). Each test in this
file FAILS against the pre-cure consumer (git blob e172da54, the raw-marginal
schema v1 tool) and PASSES against the cured schema-v2 tool:

  1. Pairing sensitivity (disposition point 4a): two synthetic receipt sets
     with IDENTICAL marginal arm distributions but DIFFERENT pairing structure
     must produce DIFFERENT MDEs. The pre-cure tool computes sigma from the
     marginal (order-invariant), so it produces identical MDEs -- caught here.
  2. Raw-only usability (disposition point 4b): input carrying only a raw
     (unpaired) per_seed_eval_loss array must FAIL the usability check rather
     than silently producing an MDE. The pre-cure tool accepted it -- caught.
  3. Signed-delta known-sign fixture (amendment comment 4931147752 point 4):
     accepted receipts carry delta_i = control - treatment (positive =
     treatment better, matching the #123 terminal grammar); a sign-flipped
     emission and a wrong delta_convention literal are both hard-SKIPPED.
  4. Exact power (addendum comment 4931301214): achieved two-sided
     noncentral-t power at the published MDE must be >= the labeled target.
     The pre-cure central-t shortcut achieves only ~0.7913 at the 0.80 label
     (ncp 3.7174096824423772 vs exact 3.761059553825027) -- caught here.

CPU-only; all fixtures are synthetic and written to pytest tmp dirs.
"""
import json
import math
import statistics
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src" / "ember" / "governance" / "scripts" / "c8_prelaunch"))
sys.path.insert(0, str(_REPO / "scripts"))

import compute_mde  # noqa: E402

# Audit counterexample (issue #585 comments 4931087645 / 4931112873, verified
# by independent replay): identical marginals, opposite pairing structure.
CONTROL = [0.0, 1.0, 2.0, 3.0, 4.0]
TREAT_ALIGNED = [0.1, 1.1, 2.1, 3.1, 4.1]           # = CONTROL + 0.1
TREAT_REVERSED = list(reversed(TREAT_ALIGNED))      # same marginal, reversed pairing
RAW_MARGINAL_SD = 1.5811388300841895                # sd of either treatment marginal
DELTA_SD_ALIGNED = 0.0                              # paired-delta sd ~ 0 (exactly constant delta)
DELTA_SD_REVERSED = 3.1622776601683795              # paired-delta sd, reversed pairing

# Exact-power addendum constants (comment 4931301214, independently replayed).
NCP_SHORTCUT_DF4 = 3.7174096824423772
NCP_EXACT_DF4 = 3.761059553825027
MDE_EXACT_AT_AUDIT_SIGMA = 2.6594707149561274       # 1.5811388300841895/sqrt(5) * ncp_exact


def _write_json(path: Path, obj: dict) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f)


def _dual_schema_receipt(cls: str, control, treatment) -> dict:
    """A receipt carrying BOTH the legacy v1 marginal (what the pre-cure tool
    reads) AND the full schema-v2 pairing structure (what the cured tool
    reads). This is what makes the pairing-sensitivity test executable against
    both code states: pre-cure sees identical marginals, post-cure sees the
    pairing. Deltas are SIGNED control - treatment per the amendment."""
    return {
        "comparison_class": cls,
        "per_seed_eval_loss": list(treatment),  # legacy v1 marginal (ignored post-cure)
        "seed_id": [f"s{i + 1}" for i in range(len(control))],
        "control_eval_loss": list(control),
        "treatment_eval_loss": list(treatment),
        "delta_convention": "control_minus_treatment",
        "per_seed_delta_nats": [c - t for c, t in zip(control, treatment)],
    }


def _run_mde(tmp_path: Path, receipts: list[dict], subdir: str):
    d = tmp_path / subdir
    d.mkdir()
    for i, r in enumerate(receipts):
        _write_json(d / f"synthetic-remeasure-{i}.json", r)
    return compute_mde.run(str(d), str(d / "out"), 5, 0.05, 0.80)


class TestPairingSensitivity:
    """Disposition point 4a: identical marginals, different pairing -> different MDEs."""

    def test_identical_marginals_different_pairing_different_mde(self, tmp_path):
        aligned = [
            _dual_schema_receipt("f1_mechanism", CONTROL, TREAT_ALIGNED),
            _dual_schema_receipt("f1_mechanism", CONTROL, TREAT_ALIGNED),
        ]
        reversed_ = [
            _dual_schema_receipt("f1_mechanism", CONTROL, TREAT_REVERSED),
            _dual_schema_receipt("f1_mechanism", CONTROL, TREAT_REVERSED),
        ]

        code_a, receipt_a, msg_a = _run_mde(tmp_path, aligned, "aligned")
        code_r, receipt_r, msg_r = _run_mde(tmp_path, reversed_, "reversed")
        assert code_a == 0 and receipt_a is not None, f"aligned set must be usable: {msg_a}"
        assert code_r == 0 and receipt_r is not None, f"reversed set must be usable: {msg_r}"

        mde_a = receipt_a["mde_at_n5"]["f1_mechanism"]["mde"]
        mde_r = receipt_r["mde_at_n5"]["f1_mechanism"]["mde"]

        # The defect this cures: the pre-cure tool reports the SAME MDE
        # (2.6286055949035347, from the shared marginal) for both pairings.
        assert mde_a != pytest.approx(mde_r), (
            "identical MDEs for different pairing structures: the tool is "
            "reading marginals, not paired deltas (issue #585 defect)"
        )
        # Direction and magnitude: aligned pairing has ~zero delta variance;
        # reversed pairing has delta sd 3.1622776601683795.
        assert mde_a == pytest.approx(0.0, abs=1e-9), f"aligned-pairing MDE should be ~0, got {mde_a}"
        assert mde_r > 5.0, f"reversed-pairing MDE should exceed 5 nats, got {mde_r}"

        # sigma itself must be the paired-delta sd, not the marginal sd.
        sigma_a = receipt_a["sigma_seed_per_class"]["f1_mechanism"]["sigma_seed"]
        sigma_r = receipt_r["sigma_seed_per_class"]["f1_mechanism"]["sigma_seed"]
        assert sigma_a == pytest.approx(DELTA_SD_ALIGNED, abs=1e-9)
        assert sigma_r == pytest.approx(DELTA_SD_REVERSED, abs=1e-9)
        assert sigma_a != pytest.approx(RAW_MARGINAL_SD) and sigma_r != pytest.approx(RAW_MARGINAL_SD)


class TestRawOnlyRejection:
    """Disposition points 3 + 4b: raw-only receipts must fail usability, receipted."""

    def test_raw_only_receipt_fails_usability(self, tmp_path):
        d = tmp_path / "rawonly"
        d.mkdir()
        _write_json(d / "synthetic-remeasure-raw.json", {
            "comparison_class": "f1_mechanism",
            "per_seed_eval_loss": TREAT_ALIGNED,
        })
        usable, skipped = compute_mde.scan_receipts(str(d))
        assert usable == [], f"raw-only receipt must NOT be usable, got {usable}"
        assert len(skipped) == 1, f"the rejection must itself be receipted in skipped: {skipped}"
        assert "raw-only" in skipped[0]["reason"], f"skip reason must name the raw-only class: {skipped[0]}"

    def test_raw_only_input_never_silently_produces_mde(self, tmp_path):
        receipts = [
            {"comparison_class": "f1_mechanism", "per_seed_eval_loss": TREAT_ALIGNED},
            {"comparison_class": "f1_mechanism", "per_seed_eval_loss": TREAT_REVERSED},
        ]
        code, receipt, msg = _run_mde(tmp_path, receipts, "rawonly2")
        assert code == 1 and receipt is None, (
            f"raw-only input silently produced an MDE (code={code}): the "
            f"usability check must fail instead (issue #585 point 4b); msg={msg}"
        )
        out = tmp_path / "rawonly2" / "out"
        assert not (out.is_dir() and any(out.iterdir())), "no mde-*.json may be written for raw-only input"


class TestSignedDeltaConvention:
    """Sign amendment (comment 4931147752): delta = control - treatment, checked as a field."""

    def test_known_sign_fixture_accepted_with_positive_deltas(self, tmp_path):
        # treatment better: control [2.0, 2.2] vs treatment [1.5, 1.9]
        # -> signed deltas [+0.5, +0.3] (positive = treatment better).
        d = tmp_path / "sign"
        d.mkdir()
        _write_json(d / "synthetic-stabilize-signed.json", {
            "comparison_class": "f1_mechanism",
            "seed_id": ["s1", "s2"],
            "control_eval_loss": [2.0, 2.2],
            "treatment_eval_loss": [1.5, 1.9],
            "delta_convention": "control_minus_treatment",
            "per_seed_delta_nats": [0.5, 0.30000000000000004],
        })
        usable, skipped = compute_mde.scan_receipts(str(d))
        assert len(usable) == 1, f"known-sign fixture must be usable: skipped={skipped}"
        got = usable[0]["per_seed_delta_nats"]
        assert got[0] == pytest.approx(0.5) and got[1] == pytest.approx(0.3), (
            f"signed per-seed deltas must be control-treatment (positive = treatment better), got {got}"
        )
        assert usable[0]["sigma_seed"] == pytest.approx(statistics.stdev([0.5, 0.3]))

    def test_sign_flipped_delta_emission_rejected(self, tmp_path):
        # Same arms, but per_seed_delta_nats emitted as treatment - control
        # (the pre-amendment sign) under the correct convention label: the
        # signed recompute must catch it. Legacy marginal included so the
        # PRE-CURE tool accepts this receipt -- which is exactly the defect.
        d = tmp_path / "signflip"
        d.mkdir()
        _write_json(d / "synthetic-stabilize-flipped.json", {
            "comparison_class": "f1_mechanism",
            "per_seed_eval_loss": [1.5, 1.9],
            "seed_id": ["s1", "s2"],
            "control_eval_loss": [2.0, 2.2],
            "treatment_eval_loss": [1.5, 1.9],
            "delta_convention": "control_minus_treatment",
            "per_seed_delta_nats": [-0.5, -0.30000000000000004],  # WRONG SIGN
        })
        usable, skipped = compute_mde.scan_receipts(str(d))
        assert usable == [], f"sign-flipped per_seed_delta_nats must be rejected, got usable={usable}"
        assert len(skipped) == 1 and "mismatch" in skipped[0]["reason"], (
            f"rejection must be receipted as a signed-delta mismatch: {skipped}"
        )

    def test_wrong_delta_convention_literal_rejected(self, tmp_path):
        d = tmp_path / "conv"
        d.mkdir()
        _write_json(d / "synthetic-stabilize-conv.json", {
            "comparison_class": "f1_mechanism",
            "per_seed_eval_loss": [1.5, 1.9],
            "seed_id": ["s1", "s2"],
            "control_eval_loss": [2.0, 2.2],
            "treatment_eval_loss": [1.5, 1.9],
            "delta_convention": "treatment_minus_control",  # pre-amendment label
            "per_seed_delta_nats": [-0.5, -0.30000000000000004],
        })
        usable, skipped = compute_mde.scan_receipts(str(d))
        assert usable == [], f"wrong delta_convention literal must be rejected, got usable={usable}"
        assert len(skipped) == 1 and "delta_convention" in skipped[0]["reason"], (
            f"rejection must be receipted as a delta_convention violation: {skipped}"
        )


class TestExactPower:
    """Exact-power addendum (comment 4931301214): achieved power >= the labeled target."""

    @staticmethod
    def _achieved_power(mde: float, sigma: float, n: int, alpha: float) -> float:
        # Computed here from first principles (scipy nct directly), NOT via
        # any helper in compute_mde -- so this test measures the tool's
        # output against the distributional truth, whichever code is loaded.
        from scipy.stats import nct, t
        df = n - 1
        t_crit = t.ppf(1 - alpha / 2, df)
        ncp = mde / (sigma / math.sqrt(n))
        return float(nct.cdf(-t_crit, df, ncp) + nct.sf(t_crit, df, ncp))

    def test_achieved_power_at_published_mde_meets_label(self):
        sigma = RAW_MARGINAL_SD  # the audit counterexample's sigma
        mde = compute_mde.mde_one_sample(sigma, 5, 0.05, 0.80)
        achieved = self._achieved_power(mde, sigma, 5, 0.05)
        # Pre-cure central-t shortcut: achieved = 0.7913424089377923 -> FAILS.
        assert achieved >= 0.80 - 1e-9, (
            f"achieved power {achieved} at the published MDE is below the "
            f"labeled 0.80: the MDE solve is anti-conservative (addendum 4931301214)"
        )

    def test_mde_matches_exact_noncentral_solution(self):
        mde = compute_mde.mde_one_sample(RAW_MARGINAL_SD, 5, 0.05, 0.80)
        # Pre-cure: 2.6286055949035347 (shortcut) -> FAILS against the exact value.
        assert mde == pytest.approx(MDE_EXACT_AT_AUDIT_SIGMA, abs=1e-9), (
            f"MDE {mde} != exact noncentral-t solution {MDE_EXACT_AT_AUDIT_SIGMA}"
        )
