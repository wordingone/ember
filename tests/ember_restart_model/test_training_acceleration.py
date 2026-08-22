# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed source prebuild for the issue #1413 training accelerators."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

import training_acceleration
from model import MultimodalSpan, RestartDecoderConfig, UnifiedDecoder


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

    def test_stage2_authority_reopens_exact_census_bytes(self) -> None:
        batch = {
            "input_ids": torch.ones((1, 4), dtype=torch.int64),
            "target_ids": torch.ones((1, 4), dtype=torch.int64),
            "image_patches": None,
            "audio_frames": None,
            "image_coordinates": torch.empty((0, 2), dtype=torch.int64),
            "spans": [],
            "active_expert": "reasoning",
        }
        measured = training_acceleration.training_step_signature(
            batch, gradient_checkpointing=True,
        )
        contract = measured["contract"]
        signature = measured["signature_sha256"]
        unsigned = {
            "schema_version": "ember-training-signature-census-v1",
            "status": "OBSERVED_NOT_ACTIVATED",
            "source_commit": "1" * 40,
            "model_config_sha256": "2" * 64,
            "input_identity_sha256": "3" * 64,
            "runner_source_sha256": "4" * 64,
            "capture_region": "forward_loss_backward",
            "activation_enabled": False,
            "fallbacks": 0,
            "observed_steps": 2,
            "signature_count": 1,
            "approved_signatures": [signature],
            "signatures": [{"signature_sha256": signature, "count": 2, "contract": contract}],
        }
        receipt = dict(unsigned)
        receipt["self_sha256"] = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "census.json"
            path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            raw_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            authority = training_acceleration.load_stage2_activation_authority(
                path, expected_raw_sha256=raw_sha256,
            )
            self.assertEqual(authority.census_raw_sha256, raw_sha256)
            self.assertEqual(authority.registry.require(signature), signature)
            with patch.object(
                training_acceleration.hashlib,
                "sha256",
                side_effect=AssertionError("runtime signature resolution must not hash"),
            ):
                self.assertEqual(
                    authority.resolve(batch, gradient_checkpointing=True),
                    signature,
                )
            changed = dict(batch)
            changed["input_ids"] = torch.ones((1, 5), dtype=torch.int64)
            with self.assertRaisesRegex(RuntimeError, "outside the approved signature census"):
                authority.resolve(changed, gradient_checkpointing=True)
            with self.assertRaisesRegex(ValueError, "raw hash mismatch"):
                training_acceleration.load_stage2_activation_authority(
                    path, expected_raw_sha256="b" * 64,
                )

    def test_fp8_installation_wraps_only_swiglu_down_sites_and_preserves_state_keys(self) -> None:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=16, layers=2, attention_heads=4, vocab_size=64,
        )
        model = UnifiedDecoder(config, genesis_seed=19).to(dtype=torch.bfloat16)
        state_keys = list(model.state_dict())
        receipt = training_acceleration.install_fp8_down_projections(
            model, allow_test_device=True,
        )
        expected_sites = config.layers * (1 + len(config.expert_names))
        self.assertEqual(receipt["installed_sites"], expected_sites)
        self.assertEqual(list(model.state_dict()), state_keys)
        for layer in model.layers:
            self.assertIsInstance(layer.shared_ffn.down, training_acceleration.DynamicFp8DownProjection)
            for expert in layer.experts.values():
                self.assertIsInstance(expert.down, training_acceleration.DynamicFp8DownProjection)
        with self.assertRaisesRegex(RuntimeError, "already installed"):
            training_acceleration.install_fp8_down_projections(model, allow_test_device=True)

    def test_post_optimizer_refresh_touches_only_stale_fp8_sites(self) -> None:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=16, layers=1, attention_heads=4, vocab_size=64,
        )
        model = UnifiedDecoder(config, genesis_seed=23).to(dtype=torch.bfloat16)
        training_acceleration.install_fp8_down_projections(model, allow_test_device=True)
        sites = list(training_acceleration.iter_fp8_down_projections(model))
        with torch.no_grad():
            sites[0].weight.add_(1)
        refreshed = training_acceleration.refresh_fp8_after_optimizer_step(model)
        self.assertEqual(refreshed, 1)
        self.assertEqual(sites[0].kernel_receipt()["weight_refreshes"], 2)
        self.assertTrue(all(site.kernel_receipt()["weight_refreshes"] == 1 for site in sites[1:]))


class TrainingSignatureCensusTests(unittest.TestCase):
    def test_signature_descriptor_covers_every_multimodal_span_field(self) -> None:
        self.assertEqual(
            {field.name for field in fields(MultimodalSpan)},
            {"start", "length", "modality", "attention_mode"},
        )

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

    def test_checked_in_census_is_the_exact_reviewed_full_route_authority(self) -> None:
        path = ROOT / "docs" / "spec" / "llmq" / "ember-training-signature-census-v1.json"
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(),
            "86e37ad5868da1ef77419d643c3ff31ee0a38b7e9f603b9c0807376958ef5d0c",
        )
        census = training_acceleration.load_training_signature_census(path)
        self.assertEqual(census["source_commit"], "728421bcca5092a89df483f7df804c7177c337a7")
        self.assertEqual(census["self_sha256"], "329115ccfdc11508da5b4918df08fe8ab95bbe20e483023843877e0d332dda77")
        self.assertEqual(census["observed_steps"], 4)
        self.assertEqual(census["signature_count"], 4)
        self.assertEqual([row["count"] for row in census["signatures"]], [1, 1, 1, 1])
        self.assertEqual(census["fallbacks"], 0)
        self.assertFalse(census["activation_enabled"])


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

    def test_cuda_graph_backend_reuses_the_first_graph_private_pool(self) -> None:
        class FakeCudaGraph:
            def __init__(self) -> None:
                self.pool_token = object()

            def pool(self) -> object:
                return self.pool_token

        graphs = [FakeCudaGraph(), FakeCudaGraph()]
        observed_pools: list[object | None] = []

        @contextmanager
        def fake_graph_context(
            graph: FakeCudaGraph, *, pool: object | None = None,
        ) -> object:
            del graph
            observed_pools.append(pool)
            yield

        with (
            patch.object(torch.cuda, "is_available", return_value=True),
            patch.object(torch.cuda, "CUDAGraph", side_effect=graphs),
            patch.object(torch.cuda, "graph", side_effect=fake_graph_context),
        ):
            backend = training_acceleration.TorchCudaGraphBackend()
            backend.capture(lambda: None)
            backend.capture(lambda: None)

        self.assertIsNone(observed_pools[0])
        self.assertIs(observed_pools[1], graphs[0].pool_token)

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

    @staticmethod
    def _arm(arm: str) -> dict[str, object]:
        accelerated = arm == "census_bound_stage2"
        elapsed = 1.0 if accelerated else 2048.0 / 900.0
        return {
            "schema_version": "ember-stage2-training-arm-v2",
            "arm": arm,
            "source_commit": "a" * 40,
            "runner_source_sha256": "1" * 64,
            "model_config_sha256": "2" * 64,
            "input_identity_sha256": "3" * 64,
            "record_order_sha256": "4" * 64,
            "checkpoint_lineage_sha256": "5" * 64,
            "census_raw_sha256": "6" * 64 if accelerated else None,
            "preparation_regions_per_signature": 4,
            "preparation_signature_count": 2,
            "preparation_region_count": 8,
            "optimizer_state_preinitialized_parameters": 12,
            "capture_gradient_zeroing": (
                "eager_default_stream_outside_capture" if accelerated else "NOT_APPLICABLE"
            ),
            "preparation_memory_allocated_bytes_by_signature": (
                {"7" * 64: 100, "8" * 64: 200} if accelerated else {}
            ),
            "captures_during_preparation": 2 if accelerated else 0,
            "captures_during_measured_window": 0,
            "no_capture_in_measured_window": True,
            "seed": 83,
            "initial_cursor": {"record_index": 0, "global_step": 0, "tokens_seen": 0},
            "steps": 2,
            "tokens": 2048,
            "losses": [9.0, 8.0] if not accelerated else [9.01, 8.01],
            "step_timings_seconds": [elapsed / 2.0, elapsed / 2.0],
            "step_elapsed_seconds": elapsed,
            "tokens_per_second": 2048.0 if accelerated else 900.0,
            "max_memory_allocated_bytes": 100,
            "max_memory_reserved_bytes": 200,
            "mechanisms": {
                "fp8_dispatches": 8 if accelerated else 0,
                "fp8_fallbacks": 0,
                "cuda_graph_captures": 2 if accelerated else 0,
                "cuda_graph_replays": 2 if accelerated else 0,
                "cuda_graph_fallbacks": 0,
                "shared_trunk_gradient_parameters": 10 if accelerated else 0,
                "shared_trunk_gradient_bytes": 1000 if accelerated else 0,
                "expert_bank_gradient_workspace_parameters": 2 if accelerated else 0,
                "gradient_workspace_bytes": 200 if accelerated else 0,
                "gradient_workspace_rebinds": 3 if accelerated else 0,
                "inactive_grad_none_assertions": 4 if accelerated else 0,
            },
        }

    def test_matched_ab_receipt_binds_identity_loss_mechanisms_and_floor(self) -> None:
        baseline = self._arm("bf16_baseline")
        accelerated = self._arm("census_bound_stage2")
        receipt = training_acceleration.build_stage2_ab_comparison(
            baseline, accelerated,
        )
        self.assertEqual(receipt["status"], "PASS")
        self.assertLess(receipt["max_relative_loss_delta"], 0.01)
        self.assertGreater(receipt["throughput_speedup"], 2.0)
        self.assertEqual(len(receipt["self_sha256"]), 64)

        refused = self._arm("census_bound_stage2")
        refused["tokens_per_second"] = 2049.0
        with self.assertRaisesRegex(ValueError, "raw step timings"):
            training_acceleration.build_stage2_ab_comparison(baseline, refused)

        for mutation, message in (
            (("runner_source_sha256", "7" * 64), "identity"),
            (("optimizer_state_preinitialized_parameters", 13), "identity"),
            (("losses", [9.0, 7.0]), "matched loss"),
        ):
            refused = self._arm("census_bound_stage2")
            refused[mutation[0]] = mutation[1]
            with self.assertRaisesRegex(ValueError, message):
                training_acceleration.build_stage2_ab_comparison(baseline, refused)

        refused = self._arm("census_bound_stage2")
        refused["step_timings_seconds"] = [1.024, 1.024]
        refused["step_elapsed_seconds"] = 2.048
        refused["tokens_per_second"] = 1000.0
        with self.assertRaisesRegex(ValueError, "greater than 1000"):
            training_acceleration.build_stage2_ab_comparison(baseline, refused)

        refused = self._arm("census_bound_stage2")
        refused["mechanisms"] = dict(refused["mechanisms"], fp8_fallbacks=1)
        with self.assertRaisesRegex(ValueError, "fallback"):
            training_acceleration.build_stage2_ab_comparison(baseline, refused)

        refused = self._arm("census_bound_stage2")
        refused["optimizer_state_preinitialized_parameters"] = 0
        with self.assertRaisesRegex(ValueError, "optimizer state"):
            training_acceleration.build_stage2_ab_comparison(baseline, refused)

        refused = self._arm("census_bound_stage2")
        refused["mechanisms"] = dict(refused["mechanisms"], gradient_workspace_bytes=0)
        with self.assertRaisesRegex(ValueError, "workspace evidence"):
            training_acceleration.build_stage2_ab_comparison(baseline, refused)

        refused = self._arm("census_bound_stage2")
        refused["capture_gradient_zeroing"] = "inside_capture"
        with self.assertRaisesRegex(ValueError, "gradient zeroing"):
            training_acceleration.build_stage2_ab_comparison(baseline, refused)

        refused = self._arm("census_bound_stage2")
        refused["captures_during_measured_window"] = 1
        refused["no_capture_in_measured_window"] = False
        with self.assertRaisesRegex(ValueError, "measured window"):
            training_acceleration.build_stage2_ab_comparison(baseline, refused)

        refused = self._arm("census_bound_stage2")
        refused["preparation_region_count"] = 12
        with self.assertRaisesRegex(ValueError, "preparation|identity"):
            training_acceleration.build_stage2_ab_comparison(baseline, refused)

    def test_stage2_arm_and_comparison_receipts_refuse_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline_path = root / "baseline.json"
            accelerated_path = root / "accelerated.json"
            comparison_path = root / "comparison.json"
            training_acceleration.write_stage2_arm_receipt(
                baseline_path, self._arm("bf16_baseline"),
            )
            training_acceleration.write_stage2_arm_receipt(
                accelerated_path, self._arm("census_bound_stage2"),
            )
            comparison = training_acceleration.compare_stage2_ab_receipts(
                baseline_path, accelerated_path, comparison_path,
            )
            self.assertEqual(comparison["status"], "PASS")
            self.assertEqual(
                comparison["baseline_raw_sha256"],
                hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
            )
            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                training_acceleration.compare_stage2_ab_receipts(
                    baseline_path, accelerated_path, comparison_path,
                )


if __name__ == "__main__":
    unittest.main()
