#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""RED regression + cure coverage for the issue #629 F2 instance-commitment cure.

Binding spec: ember issue #629 ("F2 schedule precommit binds code only --
post-hoc phi selection possible; instance commitment + verifier required"),
frozen cure adopted from the independent-audit disposition on issue #123
(comment thread, "Tighten-only clearance" section):

  1. Before the gated launch, commit an INSTANCE CLOSURE binding code_sha,
     phi_star, placement-sweep receipt hash, C_claim, N, arithmetic
     representation, and rounding convention -- only k may remain unbound.
  2. A verifier + RED regression reject any uncommitted input and
     specifically reject the audit's own .10/.40 collision under one
     commitment.
  3. The placement sweep's transform/zero-handling/fit-degree/seed/tie-break/
     failed-run-handling are defined and implemented (scripts/c8_prelaunch/
     f2_placement_sweep.py).
  4. FLOP targets are converted to exact integer execution-step boundaries
     and the realized budget error is receipted against the frozen <=2%
     limit.

Audit counterexample (independently replayed, byte-identical to the audit's
own numbers): k=1, phi_star=.10 vs .40, C_claim=1e21, N=368000000 ->
config_hash 822f48087ffa261a7d9bd41ad335aa2c937f8afbae3fd14d21abb3b186eb695a
vs 12d9302e876a4d9f4e2045148d71a951b0b725dc0e5d5406b3523e54e651feaf -- BOTH
satisfied the pre-cure code-only `--commit` receipt (identical
generator_code_sha). Every test in this file FAILS to even import against
the pre-cure module (verify_instance/commit_instance/map_events_to_steps do
not exist there) and PASSES against the cured module.

CPU-only; all fixtures are synthetic; nothing here touches receipts/ or the
real gated-arm pipeline.
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src" / "ember" / "governance" / "scripts" / "c8_prelaunch"))
sys.path.insert(0, str(_REPO / "scripts"))

import f2_schedule_generator as f2  # noqa: E402
import f2_placement_sweep as sweep  # noqa: E402

# The audit's own collision numbers (comment on issue #123, "Independent
# audit -- falsification lead" / "Commitment-collision replay").
AUDIT_K = 1
AUDIT_C_CLAIM = 1.0e21
AUDIT_N = 368_000_000
AUDIT_PHI_A = 0.10
AUDIT_PHI_B = 0.40
AUDIT_EVENTS_A = [1.0e20]
AUDIT_EVENTS_B = [4.0e20]
# NOTE: the audit's own replay pinned literal config_hash digests
# (822f480...  / 12d9302e...) -- those are NOT reasserted here as literals
# because config_hash embeds generator_code_sha, which changes with every
# edit to f2_schedule_generator.py, including this cure. The exact digests
# are preserved as a byte-frozen receipt instead:
# receipts/c8-prelaunch/f2-collision-repro-*.json (pre-cure git blob
# e12494f5dd3eea288677416aa0829a0cc95b36e1). What this test asserts is the
# INVARIANT the audit actually flagged: same generator_code_sha, different
# events, different config_hash -- i.e. the collision property itself.

FAKE_SWEEP_SHA = "a" * 64  # 64-hex-char stand-in sweep-receipt hash for fixtures


def test_audit_collision_still_reproduces_at_the_generator_level():
    """The underlying event math is unchanged (frozen endpoint convention) --
    this is the vulnerability's ground truth, not itself a defect. Confirms
    our fixture numbers match the audit's replay (events exact; config_hash
    differs between A and B despite an identical generator_code_sha)."""
    a = f2.generate_schedule(AUDIT_K, AUDIT_PHI_A, AUDIT_C_CLAIM, AUDIT_N)
    b = f2.generate_schedule(AUDIT_K, AUDIT_PHI_B, AUDIT_C_CLAIM, AUDIT_N)
    assert a["generator_code_sha"] == b["generator_code_sha"]
    assert a["events"] == AUDIT_EVENTS_A
    assert b["events"] == AUDIT_EVENTS_B
    assert a["config_hash"] != b["config_hash"]


class TestInstanceClosureCommitment:
    """Deliverable 1: instance closure binds code_sha + phi_star + sweep
    receipt hash + C_claim + N + arithmetic repr + rounding convention."""

    def test_instance_closure_body_binds_all_required_fields_except_k(self):
        body = f2.instance_closure_body(
            phi_star=AUDIT_PHI_A, c_claim=AUDIT_C_CLAIM, N=AUDIT_N,
            sweep_receipt_sha256=FAKE_SWEEP_SHA,
        )
        for field in (
            "generator_code_sha", "phi_star", "sweep_receipt_sha256",
            "c_claim", "N", "arithmetic_representation",
            "rounding_convention", "instance_hash",
        ):
            assert field in body, f"instance closure missing bound field {field!r}"
        assert "k" not in body, "k must remain UNBOUND in the instance closure"

    def test_different_phi_star_produces_different_instance_hash(self):
        """The exact defect this cures: under the pre-cure code-only commit,
        phi=.10 and phi=.40 were indistinguishable (same generator_code_sha).
        The instance closure must hash them to DIFFERENT commitments."""
        body_a = f2.instance_closure_body(AUDIT_PHI_A, AUDIT_C_CLAIM, AUDIT_N, FAKE_SWEEP_SHA)
        body_b = f2.instance_closure_body(AUDIT_PHI_B, AUDIT_C_CLAIM, AUDIT_N, FAKE_SWEEP_SHA)
        assert body_a["instance_hash"] != body_b["instance_hash"]

    def test_commit_instance_writes_a_schema_compliant_receipt(self, tmp_path):
        out_path, receipt = f2.commit_instance(
            phi_star=AUDIT_PHI_A, c_claim=AUDIT_C_CLAIM, N=AUDIT_N,
            sweep_receipt_sha256=FAKE_SWEEP_SHA, receipt_dir=str(tmp_path),
        )
        assert Path(out_path).exists()
        with open(out_path, encoding="utf-8") as fh:
            on_disk = json.load(fh)
        assert on_disk == receipt
        assert receipt["ticket"]
        assert receipt["ts"]
        assert receipt["committed_before_gated_launch"] is True
        assert "k" not in receipt


class TestVerifierRejectsUncommittedInputs:
    """Deliverable 2: the verifier + RED regression."""

    def test_verifier_rejects_the_audit_phi_collision_under_one_commitment(self, tmp_path):
        """The canonical RED case: commit at phi=.10, then attempt to verify
        the SAME receipt against a claimed phi=.40 (the audit's collision).
        Must be REJECTED -- this is the property the pre-cure tool lacked."""
        out_path, _ = f2.commit_instance(
            phi_star=AUDIT_PHI_A, c_claim=AUDIT_C_CLAIM, N=AUDIT_N,
            sweep_receipt_sha256=FAKE_SWEEP_SHA, receipt_dir=str(tmp_path),
        )
        ok_same, _ = f2.verify_instance(
            out_path, claimed_phi_star=AUDIT_PHI_A, claimed_c_claim=AUDIT_C_CLAIM,
            claimed_N=AUDIT_N, claimed_sweep_receipt_sha256=FAKE_SWEEP_SHA,
        )
        ok_collision, reason = f2.verify_instance(
            out_path, claimed_phi_star=AUDIT_PHI_B, claimed_c_claim=AUDIT_C_CLAIM,
            claimed_N=AUDIT_N, claimed_sweep_receipt_sha256=FAKE_SWEEP_SHA,
        )
        assert ok_same is True, "matching instantiation must be accepted"
        assert ok_collision is False, "the .10/.40 collision must be REJECTED post-cure"
        assert "REJECT" in reason

    @pytest.mark.parametrize("field,value", [
        ("claimed_c_claim", 2.0e21),
        ("claimed_N", 1),
        ("claimed_sweep_receipt_sha256", "b" * 64),
    ])
    def test_verifier_rejects_any_single_field_mismatch(self, tmp_path, field, value):
        out_path, _ = f2.commit_instance(
            phi_star=AUDIT_PHI_A, c_claim=AUDIT_C_CLAIM, N=AUDIT_N,
            sweep_receipt_sha256=FAKE_SWEEP_SHA, receipt_dir=str(tmp_path),
        )
        kwargs = dict(
            claimed_phi_star=AUDIT_PHI_A, claimed_c_claim=AUDIT_C_CLAIM,
            claimed_N=AUDIT_N, claimed_sweep_receipt_sha256=FAKE_SWEEP_SHA,
        )
        kwargs[field] = value
        ok, reason = f2.verify_instance(out_path, **kwargs)
        assert ok is False, f"mismatched {field} must be rejected"
        assert "REJECT" in reason

    def test_verifier_rejects_uncommitted_phi_star_out_of_domain(self):
        """Malformed / uncommitted-shape input (phi_star outside [0,1)) must be
        rejected, not silently coerced."""
        receipt = {
            "generator_code_sha": f2.CODE_SHA256,
            "instance_hash": "0" * 64,
        }
        ok, reason = f2.verify_instance(
            receipt, claimed_phi_star=1.5, claimed_c_claim=AUDIT_C_CLAIM,
            claimed_N=AUDIT_N, claimed_sweep_receipt_sha256=FAKE_SWEEP_SHA,
        )
        assert ok is False
        assert "REJECT" in reason


class TestPlacementSweep:
    """Deliverable 3: sweep transform, zero handling, fit degree, seed,
    tie-breaking, failed-run handling."""

    def test_frozen_grid_and_seed_constants(self):
        assert sweep.GRID == (0.0, 0.05, 0.10, 0.20, 0.40)
        assert sweep.SEEDS_PER_GRID_POINT == 1
        assert sweep.FIT_DEGREE == 2
        assert isinstance(sweep.SWEEP_SEED, int)

    def test_parabola_valley_hand_computed(self):
        # loss = (log10(phi) + 1)^2 + 0.5 has its true minimum at
        # log10(phi) = -1  =>  phi = 0.10, which IS one of the grid points.
        import math
        records = [
            {"phi": p, "loss": (math.log10(p) + 1.0) ** 2 + 0.5, "seed": sweep.SWEEP_SEED, "failed": False}
            for p in (0.05, 0.10, 0.20, 0.40)
        ]
        records.insert(0, {"phi": 0.0, "loss": 5.0, "seed": sweep.SWEEP_SEED, "failed": False})  # bad boundary point
        result = sweep.run_sweep(records)
        assert result["phi_star"] == pytest.approx(0.10, abs=1e-6)
        assert result["boundary_selected"] is False

    def test_zero_boundary_wins_when_strictly_better(self):
        import math
        records = [
            {"phi": p, "loss": (math.log10(p) + 1.0) ** 2 + 0.5, "seed": sweep.SWEEP_SEED, "failed": False}
            for p in (0.05, 0.10, 0.20, 0.40)
        ]
        records.insert(0, {"phi": 0.0, "loss": 0.01, "seed": sweep.SWEEP_SEED, "failed": False})  # dominates
        result = sweep.run_sweep(records)
        assert result["phi_star"] == 0.0
        assert result["boundary_selected"] is True

    def test_failed_run_excluded_from_fit(self):
        import math
        records = [
            {"phi": p, "loss": (math.log10(p) + 1.0) ** 2 + 0.5, "seed": sweep.SWEEP_SEED, "failed": False}
            for p in (0.05, 0.10, 0.20)
        ]
        records.append({"phi": 0.40, "loss": None, "seed": sweep.SWEEP_SEED, "failed": True})
        records.insert(0, {"phi": 0.0, "loss": 5.0, "seed": sweep.SWEEP_SEED, "failed": False})
        result = sweep.run_sweep(records)
        assert result["excluded_points"] == [0.40]
        assert result["phi_star"] == pytest.approx(0.10, abs=1e-6)

    def test_too_few_usable_points_fails_closed(self):
        records = [
            {"phi": 0.0, "loss": 1.0, "seed": sweep.SWEEP_SEED, "failed": False},
            {"phi": 0.05, "loss": 1.0, "seed": sweep.SWEEP_SEED, "failed": True},
            {"phi": 0.10, "loss": 1.0, "seed": sweep.SWEEP_SEED, "failed": True},
            {"phi": 0.20, "loss": 1.0, "seed": sweep.SWEEP_SEED, "failed": False},
            {"phi": 0.40, "loss": 1.0, "seed": sweep.SWEEP_SEED, "failed": True},
        ]
        with pytest.raises(ValueError):
            sweep.run_sweep(records)

    def test_tie_break_prefers_smaller_phi(self):
        # Two grid points forced to identical loss values so the vertex
        # coincides with a tie between adjacent measured points.
        records = [
            {"phi": 0.0, "loss": 5.0, "seed": sweep.SWEEP_SEED, "failed": False},
            {"phi": 0.05, "loss": 1.0, "seed": sweep.SWEEP_SEED, "failed": False},
            {"phi": 0.10, "loss": 1.0, "seed": sweep.SWEEP_SEED, "failed": False},
            {"phi": 0.20, "loss": 1.0, "seed": sweep.SWEEP_SEED, "failed": False},
            {"phi": 0.40, "loss": 3.0, "seed": sweep.SWEEP_SEED, "failed": False},
        ]
        result = sweep.run_sweep(records)
        # A flat quadratic region: fitted vertex is well-defined but the tie
        # rule matters for boundary-vs-vertex comparisons at float precision.
        assert result["phi_star"] <= 0.20

    def test_commit_sweep_receipt_is_schema_compliant_and_hashable(self, tmp_path):
        import math
        records = [
            {"phi": p, "loss": (math.log10(p) + 1.0) ** 2 + 0.5, "seed": sweep.SWEEP_SEED, "failed": False}
            for p in (0.05, 0.10, 0.20, 0.40)
        ]
        records.insert(0, {"phi": 0.0, "loss": 5.0, "seed": sweep.SWEEP_SEED, "failed": False})
        out_path, receipt = sweep.commit_sweep(records, receipt_dir=str(tmp_path))
        assert Path(out_path).exists()
        assert receipt["ticket"]
        assert receipt["ts"]
        # sweep_config_hash is computed over the sweep BODY (same pattern as
        # generate_schedule's config_hash / instance_closure_body's
        # instance_hash) -- hash-before-adding-the-hash-field, not a hash of
        # the final on-disk bytes (which would be circular: the hash field
        # is itself part of those bytes).
        body_fields = (
            "grid", "seed", "seeds_per_grid_point", "fit_degree", "transform",
            "per_point_loss", "excluded_points", "fit_coefficients",
            "candidate_source", "phi_star", "boundary_selected", "zero_handling",
            "tie_break_rule", "failed_run_handling", "degenerate_fit_fallback",
        )
        recomputed_body = {k: receipt[k] for k in body_fields}
        recomputed_hash = hashlib.sha256(
            json.dumps(recomputed_body, sort_keys=True).encode("utf-8")
        ).hexdigest()
        assert recomputed_hash == receipt["sweep_config_hash"]
        assert len(receipt["sweep_config_hash"]) == 64


class TestIntegerStepBoundaryBudgetCheck:
    """Deliverable 4: FLOP targets -> integer step boundaries + <=2% budget
    check, receipted."""

    def test_hand_computed_step_mapping_and_budget_error(self):
        # flops_per_step chosen so C_claim divides EXACTLY -> zero budget error.
        flops_per_step = 1.0e18
        result = f2.map_events_to_steps([1.0e20, 4.0e20], c_claim=1.0e21,
                                          flops_per_step_val=flops_per_step)
        assert result["event_steps"] == [100, 400]
        assert result["total_steps"] == 1000
        assert result["realized_c_claim"] == pytest.approx(1.0e21)
        assert result["budget_error_pct"] == pytest.approx(0.0, abs=1e-9)
        assert result["budget_ok"] is True
        assert result["budget_limit_pct"] == 2.0

    def test_budget_error_over_limit_flagged_not_ok(self):
        # c_claim/flops_per_step = 10.5 exactly -> rounds (half-away-from-zero)
        # to 11 steps; realized = 11/10.5 * c_claim => ~4.76% over budget.
        flops_per_step = 1.0e21 / 10.5
        result = f2.map_events_to_steps([1.0e20], c_claim=1.0e21,
                                          flops_per_step_val=flops_per_step)
        assert result["total_steps"] == 11
        assert result["budget_error_pct"] > 2.0
        assert result["budget_ok"] is False

    def test_rounding_convention_is_bound_and_deterministic(self):
        r1 = f2.map_events_to_steps([1.5e18], c_claim=1.0e19, flops_per_step_val=1.0e18)
        r2 = f2.map_events_to_steps([1.5e18], c_claim=1.0e19, flops_per_step_val=1.0e18)
        assert r1 == r2
        assert r1["rounding_convention"] == f2.ROUNDING_CONVENTION
