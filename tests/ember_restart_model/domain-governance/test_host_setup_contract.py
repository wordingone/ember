# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Unit tests for the fail-closed host commit-capacity setup contract."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))

from host_setup_contract import (
    BYTES_PER_GIB,
    DENSE_A1_JOB_MEMORY_OVERSHOOT_BASIS_POINTS,
    DENSE_A1_RESERVE_BYTES,
    DENSE_A1_TRANSIENT_CHECKPOINT_BYTES,
    DENSE_A1_REFERENCE_ACTIVE_PARAMETERS,
    HostMechanismProfile,
    HostJobMemoryEnvelopeRefusal,
    HostSetupContractRefusal,
    dense_a1_full_state_cpu_offload_profile,
    validate_host_setup_contract,
)


class HostMechanismProfileTests(unittest.TestCase):
    def test_profile_rejects_nonpositive_fields(self) -> None:
        for kwargs in (
            {"active_parameters": 0},
            {"active_parameters": -1},
            {"bytes_per_param": 0},
            {"transient_bytes": 0},
            {"reserve_bytes": 0},
        ):
            base = {
                "name": "test-mechanism",
                "active_parameters": 1000,
                "bytes_per_param": 12,
                "transient_bytes": BYTES_PER_GIB,
                "reserve_bytes": BYTES_PER_GIB,
            }
            base.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                HostMechanismProfile(**base)

    def test_profile_rejects_empty_name(self) -> None:
        with self.assertRaises(ValueError):
            HostMechanismProfile(
                name="", active_parameters=1000, bytes_per_param=12,
                transient_bytes=BYTES_PER_GIB, reserve_bytes=BYTES_PER_GIB,
            )

    def test_required_headroom_is_sum_of_all_three_components(self) -> None:
        profile = HostMechanismProfile(
            name="test-mechanism",
            active_parameters=1_000_000_000,
            bytes_per_param=12,
            transient_bytes=8 * BYTES_PER_GIB,
            reserve_bytes=6 * BYTES_PER_GIB,
        )
        self.assertEqual(profile.optimizer_state_bytes, 12_000_000_000)
        self.assertEqual(profile.simulated_peak_commit_bytes, 12_000_000_000 + 8 * BYTES_PER_GIB)
        self.assertEqual(profile.overshoot_margin_bytes, 0)
        self.assertEqual(profile.maximum_job_memory_bytes, profile.simulated_peak_commit_bytes)
        self.assertEqual(
            profile.required_headroom_bytes,
            12_000_000_000 + 8 * BYTES_PER_GIB + 6 * BYTES_PER_GIB,
        )

    def test_job_memory_margin_rounds_up_at_617_basis_points(self) -> None:
        profile = HostMechanismProfile(
            name="cuda-test-mechanism",
            active_parameters=1,
            bytes_per_param=1,
            transient_bytes=1,
            reserve_bytes=1,
            overshoot_allowance_basis_points=617,
            overshoot_allowance_basis="windows-job-object-cuda-wddm-measured",
        )
        self.assertEqual(profile.simulated_peak_commit_bytes, 2)
        self.assertEqual(profile.overshoot_margin_bytes, 1)
        self.assertEqual(profile.maximum_job_memory_bytes, 3)
        self.assertEqual(profile.required_headroom_bytes, 4)

    def test_profile_refuses_u64_envelope_overflow(self) -> None:
        with self.assertRaises(ValueError):
            HostMechanismProfile(
                name="overflow",
                active_parameters=2**63,
                bytes_per_param=2,
                transient_bytes=1,
                reserve_bytes=1,
            )


class DenseA1ProfileTests(unittest.TestCase):
    def test_default_profile_matches_898_amendment_receipted_math(self) -> None:
        profile = dense_a1_full_state_cpu_offload_profile()
        self.assertEqual(profile.active_parameters, DENSE_A1_REFERENCE_ACTIVE_PARAMETERS)
        self.assertEqual(profile.optimizer_state_bytes, 46_069_942_272)
        self.assertEqual(
            profile.overshoot_allowance_basis_points,
            DENSE_A1_JOB_MEMORY_OVERSHOOT_BASIS_POINTS,
        )
        self.assertEqual(
            profile.overshoot_allowance_basis,
            "windows_job_object_cuda_wddm_measured",
        )
        # The amendment's 42.9 GiB optimizer state plus 8 GiB transient is
        # the simulated job peak. The L2-measured 6.17% allowance is added to
        # the hard job cap; the 6 GiB host reserve remains outside that cap.
        optimizer_gib = profile.optimizer_state_bytes / BYTES_PER_GIB
        self.assertAlmostEqual(optimizer_gib, 42.9, delta=0.1)
        self.assertAlmostEqual(profile.simulated_peak_commit_bytes / BYTES_PER_GIB, 50.9, delta=0.1)
        self.assertAlmostEqual(profile.maximum_job_memory_bytes / BYTES_PER_GIB, 54.0, delta=0.1)
        required_gib = profile.required_headroom_bytes / BYTES_PER_GIB
        self.assertAlmostEqual(required_gib, 60.0, delta=0.1)
        self.assertEqual(profile.simulated_peak_commit_bytes, 54_659_876_864)
        self.assertEqual(profile.overshoot_margin_bytes, 3_372_514_403)
        self.assertEqual(profile.maximum_job_memory_bytes, 58_032_391_267)
        self.assertEqual(profile.required_headroom_bytes, 64_474_842_211)
        self.assertEqual(profile.transient_bytes, DENSE_A1_TRANSIENT_CHECKPOINT_BYTES)
        self.assertEqual(profile.reserve_bytes, DENSE_A1_RESERVE_BYTES)

    def test_custom_active_parameters_scales_optimizer_state_only(self) -> None:
        profile = dense_a1_full_state_cpu_offload_profile(active_parameters=1_000_000_000)
        self.assertEqual(profile.optimizer_state_bytes, 12_000_000_000)
        self.assertEqual(profile.transient_bytes, DENSE_A1_TRANSIENT_CHECKPOINT_BYTES)
        self.assertEqual(profile.reserve_bytes, DENSE_A1_RESERVE_BYTES)

    def test_nonpositive_active_parameters_rejected(self) -> None:
        for value in (0, -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                dense_a1_full_state_cpu_offload_profile(active_parameters=value)


class ValidateHostSetupContractTests(unittest.TestCase):
    def _profile(self, required_gib: float) -> HostMechanismProfile:
        # Construct a profile whose required_headroom_bytes is exactly the
        # requested GiB value, for precise boundary testing. bytes_per_param
        # and active_parameters are both fixed at 1 so transient_bytes alone
        # carries the requested total minus the 1-byte reserve floor.
        required_bytes = int(required_gib * BYTES_PER_GIB)
        return HostMechanismProfile(
            name="boundary-test-mechanism",
            active_parameters=1,
            bytes_per_param=1,
            transient_bytes=required_bytes - 2,
            reserve_bytes=1,
        )

    def test_sufficient_headroom_passes(self) -> None:
        profile = self._profile(required_gib=10)
        result = validate_host_setup_contract(
            profile, available_commit_bytes_probe=lambda: 10 * BYTES_PER_GIB + 1
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["mechanism"], profile.name)
        self.assertEqual(result["required_headroom_bytes"], profile.required_headroom_bytes)
        self.assertEqual(result["available_commit_bytes"], 10 * BYTES_PER_GIB + 1)
        envelope = result["job_memory_envelope"]
        self.assertEqual(envelope["schema_version"], "ember-host-job-memory-envelope-v1")
        self.assertEqual(envelope["simulated_peak_commit_bytes"], profile.simulated_peak_commit_bytes)
        self.assertEqual(envelope["maximum_job_memory_bytes"], profile.maximum_job_memory_bytes)
        self.assertEqual(envelope["host_reserve_bytes"], profile.reserve_bytes)

    def test_exact_headroom_boundary_passes(self) -> None:
        profile = self._profile(required_gib=10)
        result = validate_host_setup_contract(
            profile, available_commit_bytes_probe=lambda: profile.required_headroom_bytes
        )
        self.assertEqual(result["status"], "PASS")

    def test_expected_derived_job_cap_must_match_exactly(self) -> None:
        profile = dense_a1_full_state_cpu_offload_profile(active_parameters=1_000_000)
        result = validate_host_setup_contract(
            profile,
            available_commit_bytes_probe=lambda: profile.required_headroom_bytes,
            expected_maximum_job_memory_bytes=profile.maximum_job_memory_bytes,
        )
        self.assertEqual(
            result["job_memory_envelope"]["maximum_job_memory_bytes"],
            profile.maximum_job_memory_bytes,
        )
        with self.assertRaises(HostJobMemoryEnvelopeRefusal) as context:
            validate_host_setup_contract(
                profile,
                available_commit_bytes_probe=lambda: profile.required_headroom_bytes,
                expected_maximum_job_memory_bytes=profile.maximum_job_memory_bytes - 1,
            )
        self.assertEqual(context.exception.expected_maximum_job_memory_bytes, profile.maximum_job_memory_bytes - 1)
        self.assertEqual(context.exception.derived_maximum_job_memory_bytes, profile.maximum_job_memory_bytes)

    def test_insufficient_headroom_refuses_with_precise_shortfall(self) -> None:
        profile = dense_a1_full_state_cpu_offload_profile()
        available = 40 * BYTES_PER_GIB
        with self.assertRaises(HostSetupContractRefusal) as context:
            validate_host_setup_contract(
                profile, available_commit_bytes_probe=lambda: available
            )
        error = context.exception
        self.assertEqual(error.available_commit_bytes, available)
        self.assertEqual(error.required_headroom_bytes, profile.required_headroom_bytes)
        self.assertEqual(error.shortfall_bytes, profile.required_headroom_bytes - available)
        message = str(error)
        self.assertIn("dense-a1-full-state-cpu-offload", message)
        self.assertIn("shortfall", message)
        self.assertNotIn("PagingFiles", message)
        self.assertNotIn("reboot", message)
        self.assertIn("fit the existing envelope", message)
        self.assertIn("redesign to need less", message)
        self.assertIn("fail closed", message)

    def test_probe_must_be_callable(self) -> None:
        profile = self._profile(required_gib=1)
        with self.assertRaises(ValueError):
            validate_host_setup_contract(profile, available_commit_bytes_probe=1024)  # type: ignore[arg-type]

    def test_probe_must_return_nonnegative_int(self) -> None:
        profile = self._profile(required_gib=1)
        for bad_value in (-1, 1.5, "8"):
            with self.subTest(bad_value=bad_value), self.assertRaises(ValueError):
                validate_host_setup_contract(
                    profile, available_commit_bytes_probe=lambda value=bad_value: value
                )


if __name__ == "__main__":
    unittest.main()
