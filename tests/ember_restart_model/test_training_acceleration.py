# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed source prebuild for the issue #1413 training accelerators."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

import training_acceleration


def _disabled_contract() -> dict[str, object]:
    return {
        "schema_version": "ember-training-acceleration-v1",
        "enabled": False,
        "activation_gate": "stage2_real_path_receipt_required",
        "fp8": {
            "enabled": False,
            "format": "float8_e4m3fn",
            "kernel": "torch._scaled_mm",
            "required_compute_capability": "8.9",
            "sites": "swiglu_down_4h_to_h",
            "fallback": "refuse",
        },
        "cuda_graph": {
            "enabled": False,
            "capture_region": "forward_loss_backward",
            "fallback": "refuse",
            "signature_census_sha256": None,
            "checkpoint_rng_policy": "preserve_rng_state",
            "checkpoint_recompute_identity": "exact_signature_and_kernel_receipts",
        },
        "close_gate": {
            "minimum_tokens_per_second_exclusive": 1000,
            "require_both_mechanisms": True,
            "maximum_fallbacks": 0,
        },
    }


class TrainingAccelerationPolicyTests(unittest.TestCase):
    def test_stage1_contract_is_closed_and_disabled(self) -> None:
        policy = training_acceleration.parse_stage1_policy(_disabled_contract())
        self.assertFalse(policy.enabled)
        self.assertFalse(policy.fp8_enabled)
        self.assertFalse(policy.cuda_graph_enabled)
        self.assertIsNone(policy.signature_census_sha256)

        foreign = _disabled_contract()
        foreign["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "closed key set"):
            training_acceleration.parse_stage1_policy(foreign)

    def test_stage1_refuses_activation_before_real_path_receipt(self) -> None:
        for branch in ("enabled", "fp8", "cuda_graph"):
            contract = _disabled_contract()
            if branch == "enabled":
                contract["enabled"] = True
            else:
                nested = dict(contract[branch])
                nested["enabled"] = True
                contract[branch] = nested
            with self.assertRaisesRegex(ValueError, "Stage 2"):
                training_acceleration.parse_stage1_policy(contract)

    def test_signature_registry_is_census_bound_but_not_single_signature(self) -> None:
        signatures = ("a" * 64, "b" * 64)
        with self.assertRaisesRegex(ValueError, "signature census"):
            training_acceleration.Stage2SignatureRegistry(
                census_sha256=None, approved_signatures=signatures,
            )
        registry = training_acceleration.Stage2SignatureRegistry(
            census_sha256="c" * 64, approved_signatures=signatures,
        )
        self.assertEqual(registry.require(signatures[0]), signatures[0])
        self.assertEqual(registry.require(signatures[1]), signatures[1])
        with self.assertRaisesRegex(RuntimeError, "outside the approved signature census"):
            registry.require("d" * 64)


class TrainingSignatureCensusTests(unittest.TestCase):
    @staticmethod
    def _batch(*, expert: str = "reasoning", sequence: int = 4) -> dict[str, object]:
        return {
            "input_ids": torch.ones((1, sequence), dtype=torch.int64),
            "target_ids": torch.ones((1, sequence), dtype=torch.int64),
            "image_patches": None,
            "audio_frames": None,
            "image_coordinates": torch.empty((0, 2), dtype=torch.int64),
            "spans": [],
            "active_expert": expert,
        }

    def test_signature_is_deterministic_and_binds_static_training_shape(self) -> None:
        first = training_acceleration.training_step_signature(
            self._batch(), gradient_checkpointing=True,
        )
        repeated = training_acceleration.training_step_signature(
            self._batch(), gradient_checkpointing=True,
        )
        self.assertEqual(first, repeated)
        self.assertEqual(first["schema_version"], "ember-training-step-signature-v1")
        self.assertEqual(len(first["signature_sha256"]), 64)

        changed_shape = training_acceleration.training_step_signature(
            self._batch(sequence=5), gradient_checkpointing=True,
        )
        changed_expert = training_acceleration.training_step_signature(
            self._batch(expert="tool"), gradient_checkpointing=True,
        )
        changed_checkpointing = training_acceleration.training_step_signature(
            self._batch(), gradient_checkpointing=False,
        )
        self.assertNotEqual(first["signature_sha256"], changed_shape["signature_sha256"])
        self.assertNotEqual(first["signature_sha256"], changed_expert["signature_sha256"])
        self.assertNotEqual(first["signature_sha256"], changed_checkpointing["signature_sha256"])

    def test_census_counts_signatures_and_refuses_overwrite(self) -> None:
        census = training_acceleration.TrainingSignatureCensus(
            source_commit="1" * 40,
            model_config_sha256="2" * 64,
            input_identity_sha256="3" * 64,
            runner_source_sha256="4" * 64,
        )
        first = training_acceleration.training_step_signature(
            self._batch(), gradient_checkpointing=True,
        )
        second = training_acceleration.training_step_signature(
            self._batch(expert="tool"), gradient_checkpointing=True,
        )
        census.observe(first)
        census.observe(first)
        census.observe(second)
        receipt = census.receipt()
        self.assertEqual(receipt["observed_steps"], 3)
        self.assertEqual(receipt["signature_count"], 2)
        self.assertEqual(
            receipt["approved_signatures"],
            sorted((first["signature_sha256"], second["signature_sha256"])),
        )
        self.assertEqual(len(receipt["self_sha256"]), 64)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "census.json"
            census.write_receipt(output)
            self.assertEqual(
                training_acceleration.load_training_signature_census(output),
                receipt,
            )
            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                census.write_receipt(output)


class CheckpointCaptureProofTests(unittest.TestCase):
    def test_checkpoint_recompute_requires_rng_and_exact_region_identity(self) -> None:
        identity = {
            "graph_signature_sha256": "1" * 64,
            "fp8_kernel_receipt_sha256": "2" * 64,
            "checkpoint_region_sha256": "3" * 64,
        }
        receipt = training_acceleration.verify_checkpoint_recompute_capture(
            initial_identity=identity,
            recompute_identity=dict(identity),
            preserve_rng_state=True,
            use_reentrant=False,
        )
        self.assertEqual(receipt["checkpoint_recompute_identity"], "MATCH")
        self.assertEqual(receipt["rng_policy"], "preserve_rng_state")

        drifted = dict(identity)
        drifted["checkpoint_region_sha256"] = "4" * 64
        with self.assertRaisesRegex(RuntimeError, "recompute identity drift"):
            training_acceleration.verify_checkpoint_recompute_capture(
                initial_identity=identity,
                recompute_identity=drifted,
                preserve_rng_state=True,
                use_reentrant=False,
            )
        with self.assertRaisesRegex(RuntimeError, "RNG preservation"):
            training_acceleration.verify_checkpoint_recompute_capture(
                initial_identity=identity,
                recompute_identity=identity,
                preserve_rng_state=False,
                use_reentrant=False,
            )
        with self.assertRaisesRegex(RuntimeError, "non-reentrant"):
            training_acceleration.verify_checkpoint_recompute_capture(
                initial_identity=identity,
                recompute_identity=identity,
                preserve_rng_state=True,
                use_reentrant=True,
            )

    def test_graph_pool_is_census_bound_multi_signature_and_never_falls_back(self) -> None:
        class FakeGraph:
            def __init__(self, region: object) -> None:
                self.region = region
                self.replays = 0

            def replay(self) -> None:
                self.replays += 1

        class FakeBackend:
            def capture(self, region: object) -> FakeGraph:
                region()
                return FakeGraph(region)

        signatures = ("5" * 64, "6" * 64)
        registry = training_acceleration.Stage2SignatureRegistry(
            census_sha256="7" * 64,
            approved_signatures=signatures,
        )
        pool = training_acceleration.CudaGraphTrainingStepPool(
            registry=registry,
            backend=FakeBackend(),
        )
        calls: list[str] = []
        for signature in signatures:
            pool.capture(
                signature_sha256=signature,
                region=lambda current=signature: calls.append(current),
                optimizer_identity=lambda: "8" * 64,
                cursor_identity=lambda: "9" * 64,
            )
            pool.replay(signature)
        self.assertEqual(calls, list(signatures))
        self.assertEqual(pool.receipt()["signature_count"], 2)
        self.assertEqual(pool.receipt()["captures"], 2)
        self.assertEqual(pool.receipt()["replays"], 2)
        self.assertEqual(pool.receipt()["fallbacks"], 0)
        with self.assertRaisesRegex(RuntimeError, "outside the approved signature census"):
            pool.replay("a" * 64)

    def test_graph_capture_refuses_warmup_optimizer_or_cursor_mutation(self) -> None:
        class FakeBackend:
            def capture(self, region: object) -> object:
                region()
                return object()

        signature = "5" * 64
        pool = training_acceleration.CudaGraphTrainingStepPool(
            registry=training_acceleration.Stage2SignatureRegistry(
                census_sha256="7" * 64,
                approved_signatures=(signature,),
            ),
            backend=FakeBackend(),
        )
        optimizer_identity = ["8" * 64]

        def mutating_region() -> None:
            optimizer_identity[0] = "a" * 64

        with self.assertRaisesRegex(RuntimeError, "optimizer or cursor"):
            pool.capture(
                signature_sha256=signature,
                region=mutating_region,
                optimizer_identity=lambda: optimizer_identity[0],
                cursor_identity=lambda: "9" * 64,
            )


class Fp8DownProjectionTests(unittest.TestCase):
    @staticmethod
    def _fake_scaled_mm(
        activation: torch.Tensor,
        weight_transposed: torch.Tensor,
        scale_a: torch.Tensor,
        scale_b: torch.Tensor,
        *,
        out_dtype: torch.dtype,
        use_fast_accum: bool,
    ) -> torch.Tensor:
        del use_fast_accum
        return (
            activation.float().matmul(weight_transposed.float())
            * scale_a.float()
            * scale_b.float()
        ).to(out_dtype)

    def test_live_master_weight_requires_explicit_post_step_refresh_without_forward_copy(self) -> None:
        linear = torch.nn.Linear(16, 4, bias=False, dtype=torch.bfloat16)
        original_weight = linear.weight
        wrapped = training_acceleration.DynamicFp8DownProjection.from_linear(
            linear,
            kernel=self._fake_scaled_mm,
            allow_test_device=True,
        )
        self.assertIs(wrapped.weight, original_weight)
        self.assertEqual(list(wrapped.state_dict()), ["weight"])
        sample = torch.randn(2, 16, dtype=torch.bfloat16)
        first = wrapped(sample)
        self.assertEqual(wrapped.kernel_receipt()["per_forward_weight_materialization_copies"], 0)

        optimizer = torch.optim.SGD(wrapped.parameters(), lr=0.25)
        first.float().square().mean().backward()
        self.assertTrue(torch.isfinite(wrapped.weight.grad).all())
        optimizer.step()
        with self.assertRaisesRegex(RuntimeError, "stale FP8 weight"):
            wrapped(sample)
        wrapped.refresh_after_optimizer_step()
        second = wrapped(sample)
        self.assertFalse(torch.equal(first, second))
        receipt = wrapped.kernel_receipt()
        self.assertEqual(receipt["compute_capability"], "TEST_ONLY")
        self.assertEqual(receipt["activation_operand_layout"], "row_major_contiguous")
        self.assertEqual(receipt["weight_operand_layout"], "column_major_transposed_view")
        self.assertEqual(receipt["per_forward_weight_materialization_copies"], 0)
        self.assertEqual(receipt["accumulation_mode"], "fast_accum")
        self.assertEqual(receipt["weight_refreshes"], 2)

    def test_real_kernel_receipt_requires_sm89_layout_and_zero_forward_weight_copies(self) -> None:
        valid = {
            "schema_version": "ember-fp8-scaled-mm-kernel-receipt-v1",
            "kernel": "torch._scaled_mm",
            "compute_capability": "8.9",
            "activation_dtype": "float8_e4m3fn",
            "weight_dtype": "float8_e4m3fn",
            "output_dtype": "bfloat16",
            "activation_operand_layout": "row_major_contiguous",
            "weight_operand_layout": "column_major_transposed_view",
            "per_forward_weight_materialization_copies": 0,
            "accumulation_mode": "fast_accum",
            "weight_refreshes": 2,
            "dispatches": 1,
            "fallbacks": 0,
        }
        self.assertEqual(training_acceleration.validate_fp8_kernel_receipt(valid), valid)
        for key, value in (
            ("compute_capability", "9.0"),
            ("weight_operand_layout", "row_major_copy"),
            ("per_forward_weight_materialization_copies", 1),
            ("accumulation_mode", "precise_accum"),
        ):
            invalid = dict(valid)
            invalid[key] = value
            with self.assertRaisesRegex(ValueError, "SM89|layout|materialization|accumulation"):
                training_acceleration.validate_fp8_kernel_receipt(invalid)

    def test_fp8_site_refuses_non_bfloat16_master_or_activation(self) -> None:
        with self.assertRaisesRegex(ValueError, "BF16 master"):
            training_acceleration.DynamicFp8DownProjection.from_linear(
                torch.nn.Linear(16, 4, bias=False, dtype=torch.float32),
                kernel=self._fake_scaled_mm,
                allow_test_device=True,
            )
        wrapped = training_acceleration.DynamicFp8DownProjection.from_linear(
            torch.nn.Linear(16, 4, bias=False, dtype=torch.bfloat16),
            kernel=self._fake_scaled_mm,
            allow_test_device=True,
        )
        with self.assertRaisesRegex(RuntimeError, "BF16 activation"):
            wrapped(torch.randn(2, 16, dtype=torch.float32))


class CloseGateTests(unittest.TestCase):
    def test_close_gate_requires_both_mechanisms_zero_fallbacks_and_strict_floor(self) -> None:
        accepted = {
            "fp8_dispatches": 4,
            "cuda_graph_replays": 4,
            "fp8_fallbacks": 0,
            "cuda_graph_fallbacks": 0,
            "tokens_per_second": 1000.01,
            "real_training_path": True,
        }
        self.assertEqual(training_acceleration.validate_close_evidence(accepted), accepted)
        for key, value in (
            ("fp8_dispatches", 0),
            ("cuda_graph_replays", 0),
            ("fp8_fallbacks", 1),
            ("cuda_graph_fallbacks", 1),
            ("tokens_per_second", 1000.0),
            ("real_training_path", False),
        ):
            refused = dict(accepted)
            refused[key] = value
            with self.assertRaisesRegex(ValueError, "real training path|both mechanisms|fallback|greater than 1000"):
                training_acceleration.validate_close_evidence(refused)


if __name__ == "__main__":
    unittest.main()
