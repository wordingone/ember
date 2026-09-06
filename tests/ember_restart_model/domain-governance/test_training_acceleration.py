# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed source prebuild for the issue #1413 training accelerators."""

from __future__ import annotations

import copy
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

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))

import training_acceleration
from src.ember.model.model import MultimodalSpan, RestartDecoderConfig, UnifiedDecoder


W2_SCOPE = "final_decoder_layer_shared_and_selected_expert_swiglu_down_4h_to_h"


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
            "sites": "final_decoder_layer_shared_swiglu_down_4h_to_h",
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

    def test_fp8_installation_wraps_only_final_shared_down_site_and_preserves_state_keys(self) -> None:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=16, layers=2, attention_heads=4, vocab_size=64,
        )
        model = UnifiedDecoder(config, genesis_seed=19).to(dtype=torch.bfloat16)
        state_keys = list(model.state_dict())
        receipt = training_acceleration.install_fp8_down_projections(
            model, allow_test_device=True,
        )
        self.assertEqual(receipt, {
            "schema_version": "ember-fp8-down-projection-installation-v2",
            "scope": "final_decoder_layer_shared_swiglu_down_4h_to_h",
            "layer_indexes": [config.layers - 1],
            "installed_sites": 1,
            "sites": [f"layers.{config.layers - 1}.shared_ffn.down"],
            "fallbacks": 0,
        })
        self.assertEqual(list(model.state_dict()), state_keys)
        for index, layer in enumerate(model.layers):
            expected_type = (
                training_acceleration.DynamicFp8DownProjection
                if index == config.layers - 1 else torch.nn.Linear
            )
            self.assertIsInstance(layer.shared_ffn.down, expected_type)
            for expert in layer.experts.values():
                self.assertIsInstance(expert.down, torch.nn.Linear)
        with self.assertRaisesRegex(RuntimeError, "already installed"):
            training_acceleration.install_fp8_down_projections(model, allow_test_device=True)

    @staticmethod
    def _w2_model() -> UnifiedDecoder:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=8, layers=14, attention_heads=2, vocab_size=16,
        )
        return UnifiedDecoder(config, genesis_seed=1945).to(dtype=torch.bfloat16)

    @staticmethod
    def _model_identity(model: UnifiedDecoder) -> tuple[object, ...]:
        return (
            tuple(model.state_dict()),
            tuple((name, id(parameter)) for name, parameter in model.named_parameters()),
            tuple((name, tensor.detach().clone()) for name, tensor in model.state_dict().items()),
            tuple((name, id(module), type(module)) for name, module in model.named_modules()),
        )

    def _assert_model_identity(self, expected: tuple[object, ...], model: UnifiedDecoder) -> None:
        actual = self._model_identity(model)
        self.assertEqual(actual[0], expected[0])
        self.assertEqual(actual[1], expected[1])
        self.assertEqual(actual[3], expected[3])
        self.assertEqual(len(actual[2]), len(expected[2]))
        for (actual_name, actual_tensor), (expected_name, expected_tensor) in zip(actual[2], expected[2]):
            self.assertEqual(actual_name, expected_name)
            self.assertTrue(torch.equal(actual_tensor, expected_tensor))

    def test_w2_scope_refuses_non_fourteen_layer_model_before_mutation(self) -> None:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=8, layers=2, attention_heads=2, vocab_size=16,
        )
        model = UnifiedDecoder(config, genesis_seed=1945).to(dtype=torch.bfloat16)
        before = self._model_identity(model)
        with self.assertRaisesRegex(ValueError, "exactly 14 decoder layers"):
            training_acceleration.install_fp8_down_projections(
                model, installation_scope=W2_SCOPE, allow_test_device=True,
            )
        self._assert_model_identity(before, model)

    def test_w2_scope_refuses_expert_key_drift_before_mutation(self) -> None:
        for mutation in ("missing", "extra", "renamed"):
            with self.subTest(mutation=mutation):
                model = self._w2_model()
                experts = model.layers[13].experts
                if mutation == "missing":
                    del experts["tool"]
                elif mutation == "extra":
                    experts["extra"] = copy.deepcopy(experts["tool"])
                else:
                    renamed = experts["tool"]
                    del experts["tool"]
                    experts["renamed"] = renamed
                before = self._model_identity(model)
                with self.assertRaisesRegex(ValueError, "exact expert keys"):
                    training_acceleration.install_fp8_down_projections(
                        model, installation_scope=W2_SCOPE, allow_test_device=True,
                    )
                self._assert_model_identity(before, model)

    def test_w2_scope_refuses_malformed_or_preinstalled_expert_before_mutation(self) -> None:
        for mutation in ("wrong_type", "preinstalled"):
            with self.subTest(mutation=mutation):
                model = self._w2_model()
                target = model.layers[13].experts["reasoning"]
                if mutation == "wrong_type":
                    target.down = torch.nn.Identity()
                else:
                    target.down = training_acceleration.DynamicFp8DownProjection.from_linear(
                        target.down, kernel=Fp8DownProjectionTests._fake_scaled_mm,
                        allow_test_device=True,
                    )
                before = self._model_identity(model)
                with self.assertRaisesRegex((ValueError, RuntimeError), "expert down projection"):
                    training_acceleration.install_fp8_down_projections(
                        model, installation_scope=W2_SCOPE, allow_test_device=True,
                    )
                self._assert_model_identity(before, model)

    def test_w2_scope_accepts_only_supported_mixed_state(self) -> None:
        model = self._w2_model()
        shared = model.layers[13].shared_ffn
        shared.down = training_acceleration.DynamicFp8DownProjection.from_linear(
            shared.down, kernel=Fp8DownProjectionTests._fake_scaled_mm,
            allow_test_device=True,
        )
        receipt = training_acceleration.install_fp8_down_projections(
            model, installation_scope=W2_SCOPE,
            kernel=Fp8DownProjectionTests._fake_scaled_mm, allow_test_device=True,
        )
        self.assertEqual(receipt["installed_sites"], 5)
        self.assertEqual(receipt["newly_installed_sites"], 4)
        self.assertEqual(len(tuple(training_acceleration.iter_fp8_down_projections(model))), 5)

    def test_w2_scope_fresh_install_is_exact_and_default_receipt_is_unchanged(self) -> None:
        default_model = RestartDecoderConfig.small_for_tests(
            hidden_size=8, layers=2, attention_heads=2, vocab_size=16,
        )
        default_receipt = training_acceleration.install_fp8_down_projections(
            UnifiedDecoder(default_model, genesis_seed=1945).to(dtype=torch.bfloat16),
            allow_test_device=True,
        )
        self.assertEqual(default_receipt, {
            "schema_version": "ember-fp8-down-projection-installation-v2",
            "scope": "final_decoder_layer_shared_swiglu_down_4h_to_h",
            "layer_indexes": [1],
            "installed_sites": 1,
            "sites": ["layers.1.shared_ffn.down"],
            "fallbacks": 0,
        })

        model = self._w2_model()
        state_keys = tuple(model.state_dict())
        receipt = training_acceleration.install_fp8_down_projections(
            model, installation_scope=W2_SCOPE,
            kernel=Fp8DownProjectionTests._fake_scaled_mm, allow_test_device=True,
        )
        expected_sites = ["layers.13.shared_ffn.down"] + [
            f"layers.13.experts.{name}.down" for name in ("vision", "audio", "reasoning", "tool")
        ]
        self.assertEqual(tuple(model.state_dict()), state_keys)
        self.assertEqual(receipt["scope"], W2_SCOPE)
        self.assertEqual(receipt["layer_indexes"], [13])
        self.assertEqual(receipt["installed_sites"], 5)
        self.assertEqual(receipt["newly_installed_sites"], 5)
        self.assertEqual(receipt["sites"], expected_sites)
        self.assertEqual(receipt["fallbacks"], 0)

    def test_w2_scope_refresh_and_routed_dispatch_evidence_are_grouped(self) -> None:
        model = self._w2_model()
        installation = training_acceleration.install_fp8_down_projections(
            model, installation_scope=W2_SCOPE,
            kernel=Fp8DownProjectionTests._fake_scaled_mm, allow_test_device=True,
        )
        sites = dict(model.named_modules())
        reasoning = sites["layers.13.experts.reasoning.down"]
        with torch.no_grad():
            reasoning.weight.add_(1)
        self.assertEqual(training_acceleration.refresh_fp8_after_optimizer_step(model), 5)
        self.assertEqual(reasoning.kernel_receipt()["weight_refreshes"], 2)

        ids = torch.tensor([[1, 2]], dtype=torch.int64)
        for expert in ("vision", "audio", "reasoning", "tool"):
            model(ids, active_expert=expert)
        groups = training_acceleration.fp8_installation_group_receipt(model, installation)
        self.assertEqual(groups["existing_shared"]["installed_sites"], 1)
        self.assertEqual(groups["new_active_expert"]["installed_sites"], 4)
        self.assertEqual(groups["existing_shared"]["dispatches"], 4)
        self.assertEqual(groups["new_active_expert"]["dispatches"], 4)
        self.assertEqual(groups["existing_shared"]["fallbacks"], 0)
        self.assertEqual(groups["new_active_expert"]["fallbacks"], 0)
        self.assertEqual(groups["existing_shared"]["weight_refreshes"], 2)
        self.assertEqual(groups["new_active_expert"]["weight_refreshes"], 8)

        with torch.no_grad():
            for site in training_acceleration.iter_fp8_down_projections(model):
                site.weight.add_(1)
        self.assertEqual(training_acceleration.refresh_fp8_after_optimizer_step(model), 5)
        groups = training_acceleration.fp8_installation_group_receipt(model, installation)
        self.assertEqual(groups["existing_shared"]["weight_refreshes"], 3)
        self.assertEqual(groups["new_active_expert"]["weight_refreshes"], 12)

    def test_post_optimizer_refresh_touches_every_fp8_site(self) -> None:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=16, layers=1, attention_heads=4, vocab_size=64,
        )
        model = UnifiedDecoder(config, genesis_seed=23).to(dtype=torch.bfloat16)
        training_acceleration.install_fp8_down_projections(model, allow_test_device=True)
        sites = list(training_acceleration.iter_fp8_down_projections(model))
        with torch.no_grad():
            sites[0].weight.add_(1)
        refreshed = training_acceleration.refresh_fp8_after_optimizer_step(model)
        # forced for every site (#2167): the production 8-bit optimizer never bumps the version counter
        self.assertEqual(refreshed, len(sites))
        self.assertTrue(all(site.kernel_receipt()["weight_refreshes"] == 2 for site in sites))


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
        path = ROOT / "docs" / "domains" / "governance" / "spec" / "llmq" / "ember-training-signature-census-v1.json"
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
        for signature in signatures:
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
        scale_shapes: list[tuple[tuple[int, ...], tuple[int, ...]]] = []

        def tracked_scaled_mm(
            activation: torch.Tensor,
            weight_transposed: torch.Tensor,
            scale_a: torch.Tensor,
            scale_b: torch.Tensor,
            *,
            out_dtype: torch.dtype,
            use_fast_accum: bool,
        ) -> torch.Tensor:
            scale_shapes.append((tuple(scale_a.shape), tuple(scale_b.shape)))
            return self._fake_scaled_mm(
                activation, weight_transposed, scale_a, scale_b,
                out_dtype=out_dtype, use_fast_accum=use_fast_accum,
            )

        wrapped = training_acceleration.DynamicFp8DownProjection.from_linear(
            linear,
            kernel=tracked_scaled_mm,
            allow_test_device=True,
        )
        self.assertIs(wrapped.weight, original_weight)
        self.assertEqual(list(wrapped.state_dict()), ["weight"])
        sample = torch.randn(2, 16, dtype=torch.bfloat16)
        first = wrapped(sample)
        self.assertEqual(scale_shapes, [((), ())])
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
        self.assertEqual(receipt["native_kernel_scaling"], "tensorwise_unit")
        self.assertEqual(receipt["activation_scaling"], "emulated_rowwise_per_token")
        self.assertEqual(receipt["weight_scaling"], "emulated_columnwise_per_output_channel")
        self.assertEqual(receipt["per_forward_weight_materialization_copies"], 0)
        self.assertEqual(receipt["accumulation_mode"], "fast_accum")
        self.assertEqual(receipt["weight_refreshes"], 2)

    def test_emulated_rowwise_scaling_reduces_heterogeneous_fp8_error(self) -> None:
        torch.manual_seed(7)
        linear = torch.nn.Linear(128, 32, bias=False, dtype=torch.bfloat16)
        with torch.no_grad():
            linear.weight.copy_(
                torch.randn_like(linear.weight)
                * torch.linspace(0.01, 10.0, 32, dtype=torch.bfloat16)[:, None]
            )
        wrapped = training_acceleration.DynamicFp8DownProjection.from_linear(
            linear, kernel=self._fake_scaled_mm, allow_test_device=True,
        )
        activation = (
            torch.randn(4, 128, dtype=torch.bfloat16)
            * torch.tensor([[0.001], [0.1], [1.0], [100.0]], dtype=torch.bfloat16)
        )
        reference = activation.float().matmul(linear.weight.float().transpose(0, 1))
        emulated_rowwise = wrapped(activation).float()

        activation_scale = activation.abs().amax().float() / 448.0
        weight_scale = linear.weight.abs().amax().float() / 448.0
        tensorwise = (
            (activation.float() / activation_scale)
            .clamp(-448.0, 448.0)
            .to(torch.float8_e4m3fn)
            .float()
            .matmul(
                (linear.weight.float() / weight_scale)
                .clamp(-448.0, 448.0)
                .to(torch.float8_e4m3fn)
                .float()
                .transpose(0, 1)
            )
            * activation_scale
            * weight_scale
        ).to(torch.bfloat16).float()
        rowwise_small_row_error = torch.linalg.vector_norm(
            emulated_rowwise[0] - reference[0]
        ) / torch.linalg.vector_norm(reference[0])
        tensorwise_small_row_error = torch.linalg.vector_norm(
            tensorwise[0] - reference[0]
        ) / torch.linalg.vector_norm(reference[0])
        self.assertLess(
            float(rowwise_small_row_error.detach()),
            float(tensorwise_small_row_error.detach()) / 5.0,
        )

    def test_real_kernel_receipt_requires_sm89_layout_and_zero_forward_weight_copies(self) -> None:
        valid = {
            "schema_version": "ember-fp8-scaled-mm-kernel-receipt-v2",
            "kernel": "torch._scaled_mm",
            "compute_capability": "8.9",
            "activation_dtype": "float8_e4m3fn",
            "weight_dtype": "float8_e4m3fn",
            "output_dtype": "bfloat16",
            "activation_operand_layout": "row_major_contiguous",
            "weight_operand_layout": "column_major_transposed_view",
            "per_forward_weight_materialization_copies": 0,
            "native_kernel_scaling": "tensorwise_unit",
            "activation_scaling": "emulated_rowwise_per_token",
            "weight_scaling": "emulated_columnwise_per_output_channel",
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
            ("native_kernel_scaling", "rowwise"),
            ("activation_scaling", "tensorwise"),
            ("accumulation_mode", "precise_accum"),
        ):
            invalid = dict(valid)
            invalid[key] = value
            with self.assertRaisesRegex(ValueError, "SM89|layout|materialization|scaling|accumulation"):
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


W5_SCOPE = "all_decoder_layers_shared_swiglu_up_gate_h_to_8h"


class Fp8UpGateProjectionTests(unittest.TestCase):
    """Issue #2167 (W5): shared SwiGLU up+gate site class, installer, arm switch."""

    @staticmethod
    def _fake_scaled_mm(activation, weight_transposed, scale_a, scale_b, *, out_dtype, use_fast_accum):
        del use_fast_accum
        return (activation.float().matmul(weight_transposed.float()) * scale_a.float() * scale_b.float()).to(out_dtype)

    @staticmethod
    def _w5_model(layers: int = 14) -> UnifiedDecoder:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=8, layers=layers, attention_heads=2, vocab_size=16,
        )
        return UnifiedDecoder(config, genesis_seed=2167).to(dtype=torch.bfloat16)

    @staticmethod
    def _identity(model: UnifiedDecoder) -> tuple[object, ...]:
        return (
            tuple(model.state_dict()),
            tuple((name, id(parameter)) for name, parameter in model.named_parameters()),
            tuple((name, id(module), type(module)) for name, module in model.named_modules()),
        )

    def _install(self, model: UnifiedDecoder, **overrides) -> dict[str, object]:
        kwargs = {"kernel": self._fake_scaled_mm, "allow_test_device": True, "installation_scope": W5_SCOPE}
        kwargs.update(overrides)
        return training_acceleration.install_fp8_up_gate_projections(model, **kwargs)

    def test_w5_install_is_exact_preserves_state_keys_and_refuses_reinstall(self) -> None:
        model = self._w5_model()
        state_keys = list(model.state_dict())
        receipt = self._install(model)
        self.assertEqual(receipt, {
            "schema_version": "ember-fp8-down-projection-installation-v2",
            "scope": W5_SCOPE,
            "layer_indexes": list(range(14)),
            "installed_sites": 14,
            "sites": [f"layers.{index}.shared_ffn.up_gate" for index in range(14)],
            "fallbacks": 0,
        })
        self.assertEqual(list(model.state_dict()), state_keys)
        for layer in model.layers:
            self.assertIsInstance(layer.shared_ffn.up_gate, training_acceleration.DynamicFp8UpGateProjection)
            self.assertIsInstance(layer.shared_ffn.down, torch.nn.Linear)
            for expert in layer.experts.values():
                self.assertIsInstance(expert.up_gate, torch.nn.Linear)
                self.assertIsInstance(expert.down, torch.nn.Linear)
        self.assertEqual(len(training_acceleration.iter_fp8_down_projections(model)), 14)
        identity = self._identity(model)
        with self.assertRaisesRegex(RuntimeError, "already installed"):
            self._install(model)
        self.assertEqual(self._identity(model), identity)
        # the #1413 down installer still resolves its single final shared site beside the W5 sites
        down_receipt = training_acceleration.install_fp8_down_projections(
            model, kernel=self._fake_scaled_mm, allow_test_device=True,
        )
        self.assertEqual(down_receipt["installed_sites"], 1)
        self.assertEqual(len(training_acceleration.iter_fp8_down_projections(model)), 15)

    def test_w5_planted_negatives_refuse_before_any_mutation(self) -> None:
        # (1) wrong-shape weight at the module boundary, both directions
        with self.assertRaisesRegex(ValueError, "H-to-8H up\\+gate"):
            training_acceleration.DynamicFp8UpGateProjection.from_linear(
                torch.nn.Linear(16, 4, bias=False, dtype=torch.bfloat16),
                kernel=self._fake_scaled_mm, allow_test_device=True,
            )
        with self.assertRaisesRegex(ValueError, "4H-to-H down"):
            training_acceleration.DynamicFp8DownProjection.from_linear(
                torch.nn.Linear(4, 32, bias=False, dtype=torch.bfloat16),
                kernel=self._fake_scaled_mm, allow_test_device=True,
            )
        # (2) an expert up+gate already installed is refused, shared sites untouched
        model = self._w5_model()
        expert = model.layers[3].experts["tool"]
        expert.up_gate = training_acceleration.DynamicFp8UpGateProjection.from_linear(
            expert.up_gate, kernel=self._fake_scaled_mm, allow_test_device=True,
        )
        identity = self._identity(model)
        with self.assertRaisesRegex(RuntimeError, "installed expert up\\+gate site: layers.3.experts.tool.up_gate"):
            self._install(model)
        self.assertEqual(self._identity(model), identity)
        # (3) layer count other than 14, and an unknown scope string, refuse before mutation
        small = self._w5_model(layers=2)
        small_identity = self._identity(small)
        with self.assertRaisesRegex(ValueError, "exactly 14 decoder layers"):
            self._install(small)
        self.assertEqual(self._identity(small), small_identity)
        fresh = self._w5_model()
        fresh_identity = self._identity(fresh)
        with self.assertRaisesRegex(ValueError, "explicit W5 scope"):
            self._install(fresh, installation_scope="final_decoder_layer_shared_swiglu_down_4h_to_h")
        with self.assertRaisesRegex(ValueError, "explicit W5 scope"):
            self._install(fresh, installation_scope=None)
        self.assertEqual(self._identity(fresh), fresh_identity)
        # (4) a biased site is refused before mutation
        biased = self._w5_model()
        biased.layers[7].shared_ffn.up_gate = torch.nn.Linear(8, 64, bias=True, dtype=torch.bfloat16)
        biased_identity = self._identity(biased)
        with self.assertRaisesRegex(ValueError, "bias-free"):
            self._install(biased)
        self.assertEqual(self._identity(biased), biased_identity)

    def test_w5_arm_switch_bf16_is_the_original_computation_and_fp8_dispatches_only_in_fp8_arm(self) -> None:
        model = self._w5_model()
        self._install(model)
        sample = torch.randn(3, 8, dtype=torch.bfloat16)
        site = model.layers[0].shared_ffn.up_gate
        self.assertEqual(training_acceleration.set_fp8_arm(model, "bf16"), 14)
        self.assertTrue(torch.equal(site(sample), torch.nn.functional.linear(sample, site.weight)))
        self.assertEqual(site.arm_receipt(), {
            "site_class": "shared_swiglu_up_gate_h_to_8h", "arm": "bf16", "fp8_dispatches": 0, "bf16_dispatches": 1,
        })
        self.assertEqual(training_acceleration.set_fp8_arm(model, "fp8"), 14)
        fp8_out = site(sample)
        self.assertEqual(fp8_out.shape, (3, 64))
        self.assertEqual(fp8_out.dtype, torch.bfloat16)
        reference = torch.nn.functional.linear(sample, site.weight).detach().float()
        self.assertLess(float((fp8_out.float() - reference).abs().max()), 0.2 * float(reference.abs().max()) + 1e-3)
        self.assertEqual(site.arm_receipt()["fp8_dispatches"], 1)
        with self.assertRaisesRegex(ValueError, "one of fp8, bf16"):
            site.set_arm("fp16")
        with self.assertRaisesRegex(ValueError, "one of fp8, bf16"):
            training_acceleration.set_fp8_arm(model, "int8")
        # the kernel receipt (closed keys) is unchanged by the arm switch
        training_acceleration.validate_fp8_kernel_receipt({**site.kernel_receipt(), "compute_capability": "8.9"})
        arm_receipt = training_acceleration.fp8_arm_receipt(model)
        self.assertEqual((arm_receipt["sites"], arm_receipt["arms"], arm_receipt["fallbacks"]), (14, ["fp8"], 0))

    def test_w5_refresh_after_step_touches_every_site_exactly_once(self) -> None:
        model = self._w5_model()
        self._install(model)
        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        tokens = torch.randint(0, 16, (1, 6))
        loss = model(tokens, active_expert="shared").float().square().mean()
        loss.backward()
        optimizer.step()
        with self.assertRaisesRegex(RuntimeError, "stale FP8 weight"):
            model.layers[0].shared_ffn.up_gate(torch.randn(2, 8, dtype=torch.bfloat16))
        self.assertEqual(training_acceleration.refresh_fp8_after_optimizer_step(model), 14)
        # forced, never if-stale: a second call re-quantizes again (#2167 probe finding)
        self.assertEqual(training_acceleration.refresh_fp8_after_optimizer_step(model), 14)
        self.assertEqual({site.kernel_receipt()["weight_refreshes"] for site in training_acceleration.iter_fp8_down_projections(model)}, {3})

    def test_w5_refresh_is_forced_when_the_optimizer_does_not_bump_the_version_counter(self) -> None:
        # bitsandbytes AdamW8bit writes parameter storage from its kernel; the version counter
        # does not move, so the forward guard is blind. Modelled here through the .data alias.
        model = self._w5_model()
        self._install(model)
        site = model.layers[0].shared_ffn.up_gate
        before = site._weight_fp8.clone()
        with torch.no_grad():
            site.weight.data.add_(1)
        self.assertEqual(site.weight._version, site._refreshed_weight_version)
        self.assertEqual(training_acceleration.refresh_fp8_after_optimizer_step(model), 14)
        self.assertFalse(torch.equal(site._weight_fp8, before))
        self.assertEqual(site.kernel_receipt()["weight_refreshes"], 2)

    def test_refresh_count_validation_refuses_the_probe_signature(self) -> None:
        # probe #2 at 970f7b70: 14 sites, 30 steps, 14 refreshes = install only, no per-step refresh
        with self.assertRaisesRegex(RuntimeError, "FP8_REFRESH_COUNT_REFUSED:14!=434"):
            training_acceleration.validate_fp8_refresh_count(installed_sites=14, optimizer_steps=30, weight_refreshes=14)
        self.assertEqual(training_acceleration.validate_fp8_refresh_count(installed_sites=14, optimizer_steps=30, weight_refreshes=434), 434)


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

    def test_graph_only_diagnostic_receipt_is_closed_and_rejected_by_production_comparator(self) -> None:
        diagnostic = self._arm("census_bound_stage2")
        diagnostic.update({
            "schema_version": "ember-stage2-graph-only-diagnostic-v1",
            "arm": "graph_only_bf16_down",
            "claim_boundary": "DIAGNOSTIC_ONLY_NOT_CLOSE_EVIDENCE",
            "production_accelerated_arm_self_sha256": "9" * 64,
            "pre_optimizer_sync": "NONE",
        })
        diagnostic["mechanisms"] = dict(
            diagnostic["mechanisms"], fp8_dispatches=0,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            diagnostic_path = root / "diagnostic.json"
            baseline_path = root / "baseline.json"
            output_path = root / "comparison.json"
            receipt = training_acceleration.write_stage2_graph_only_diagnostic_receipt(
                diagnostic_path, diagnostic,
            )
            self.assertEqual(receipt["mechanisms"]["fp8_dispatches"], 0)
            self.assertGreater(receipt["mechanisms"]["cuda_graph_replays"], 0)
            self.assertEqual(
                training_acceleration.load_stage2_graph_only_diagnostic_receipt(
                    diagnostic_path,
                ),
                diagnostic,
            )
            training_acceleration.write_stage2_arm_receipt(
                baseline_path, self._arm("bf16_baseline"),
            )
            with self.assertRaisesRegex(ValueError, "closed v2 key set"):
                training_acceleration.compare_stage2_ab_receipts(
                    baseline_path, diagnostic_path, output_path,
                )

            refused = dict(diagnostic)
            refused["mechanisms"] = dict(refused["mechanisms"], fp8_dispatches=1)
            with self.assertRaisesRegex(ValueError, "zero FP8 dispatches"):
                training_acceleration.write_stage2_graph_only_diagnostic_receipt(
                    root / "refused.json", refused,
                )

            synchronized = dict(diagnostic, pre_optimizer_sync="current_stream_synchronize")
            training_acceleration.write_stage2_graph_only_diagnostic_receipt(
                root / "synchronized.json", synchronized,
            )

    def test_eager_workspace_diagnostic_receipt_refuses_graphs_fp8_and_close_comparison(self) -> None:
        diagnostic = self._arm("census_bound_stage2")
        diagnostic.update({
            "schema_version": "ember-stage2-eager-workspace-diagnostic-v1",
            "arm": "eager_workspace_bf16",
            "claim_boundary": "DIAGNOSTIC_ONLY_NOT_CLOSE_EVIDENCE",
            "production_accelerated_arm_self_sha256": "9" * 64,
            "post_step1_parameter_delta_l2": {
                "active_expert_bank": 0.25,
                "trunk": 0.5,
            },
        })
        diagnostic["mechanisms"] = dict(
            diagnostic["mechanisms"],
            fp8_dispatches=0,
            cuda_graph_captures=0,
            cuda_graph_replays=0,
        )
        diagnostic["captures_during_preparation"] = 0
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "eager-workspace.json"
            receipt = training_acceleration.write_stage2_eager_workspace_diagnostic_receipt(
                path, diagnostic,
            )
            self.assertEqual(receipt["mechanisms"]["cuda_graph_replays"], 0)
            baseline = root / "baseline.json"
            training_acceleration.write_stage2_arm_receipt(
                baseline, self._arm("bf16_baseline"),
            )
            with self.assertRaisesRegex(ValueError, "closed v2 key set"):
                training_acceleration.compare_stage2_ab_receipts(
                    baseline, path, root / "comparison.json",
                )

            refused = dict(diagnostic)
            refused["mechanisms"] = dict(refused["mechanisms"], cuda_graph_replays=1)
            with self.assertRaisesRegex(ValueError, "cannot engage CUDA graphs"):
                training_acceleration.write_stage2_eager_workspace_diagnostic_receipt(
                    root / "refused.json", refused,
                )


if __name__ == "__main__":
    unittest.main()
