# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Unit tests for the fail-closed host commit-capacity setup contract."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from host_setup_contract import (
    BYTES_PER_GIB,
    DENSE_A1_RESERVE_BYTES,
    DENSE_A1_TRANSIENT_CHECKPOINT_BYTES,
    DENSE_A1_REFERENCE_ACTIVE_PARAMETERS,
    HostMechanismProfile,
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
        self.assertEqual(
            profile.required_headroom_bytes,
            12_000_000_000 + 8 * BYTES_PER_GIB + 6 * BYTES_PER_GIB,
        )


class DenseA1ProfileTests(unittest.TestCase):
    def test_default_profile_matches_898_amendment_receipted_math(self) -> None:
        profile = dense_a1_full_state_cpu_offload_profile()
        self.assertEqual(profile.active_parameters, DENSE_A1_REFERENCE_ACTIVE_PARAMETERS)
        self.assertEqual(profile.optimizer_state_bytes, 3_840_000_000 * 12)
        # 42.9 GiB optimizer state (rounded), 8 GiB transient, 6 GiB reserve
        # per the amendment's receipted 56.9 GiB total.
        optimizer_gib = profile.optimizer_state_bytes / BYTES_PER_GIB
        self.assertAlmostEqual(optimizer_gib, 42.9, delta=0.1)
        required_gib = profile.required_headroom_bytes / BYTES_PER_GIB
        self.assertAlmostEqual(required_gib, 56.9, delta=0.1)
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

    def test_exact_headroom_boundary_passes(self) -> None:
        profile = self._profile(required_gib=10)
        result = validate_host_setup_contract(
            profile, available_commit_bytes_probe=lambda: profile.required_headroom_bytes
        )
        self.assertEqual(result["status"], "PASS")

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
        self.assertIn("PagingFiles", message)
        self.assertIn("reboot", message)
        self.assertIn("not a supported path", message)

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
