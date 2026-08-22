# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Acceptance tests for independently verified routed multimodal pretraining."""

from __future__ import annotations

import base64
import gc
import hashlib
import json
import math
import sys
import tempfile
import unittest
import weakref
from pathlib import Path
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from model import RestartDecoderConfig, UnifiedDecoder
from batch import decode_owned_batch
import pretrain
from pretrain import run_pretraining_segment
import training_acceleration
from specialist_stream import SELECTION_CURSOR_SCHEMA_VERSION, SELECTION_RECEIPT_SCHEMA_VERSION
from verify_capability_record import expected_receipt


class PretrainingSegmentTests(unittest.TestCase):
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

    def test_core_only_text_episode_updates_shared_state_without_crediting_or_updating_an_expert(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=41)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        experts_before = {name: parameter.detach().clone() for name, parameter in model.named_parameters() if ".experts." in name}
        shared_before = model.token_embedding.weight.detach().clone()
        record = {
            "schema_version": "ember-owned-semantic-text-v1",
            "active_expert": "shared",
            "token_ids": [8, 9, 10, 11],
            "target_ids": [9, 10, 11, 12],
        }
        result = run_pretraining_segment(
            model=model, optimizer=optimizer, records=[record], config=config, device=torch.device("cpu"),
            checkpoint_every=1, checkpoint_callback=lambda _step, _result: None, require_complete_coverage=False,
        )
        self.assertEqual(result["modality_examples"], {"text": 1, "image": 0, "audio": 0, "reasoning": 0, "tool": 0})
        self.assertEqual(result["expert_examples"], {"vision": 0, "audio": 0, "reasoning": 0, "tool": 0})
        self.assertTrue(all(torch.equal(parameter.detach(), experts_before[name]) for name, parameter in model.named_parameters() if ".experts." in name))
        self.assertFalse(torch.equal(model.token_embedding.weight.detach(), shared_before))

    def test_optional_signature_observer_sees_real_decoded_batch_without_changing_counters(self) -> None:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=2, attention_heads=4, vocab_size=64,
        )
        model = UnifiedDecoder(config, genesis_seed=43)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        observed: list[dict[str, object]] = []
        record = {
            "schema_version": "ember-owned-semantic-text-v1",
            "active_expert": "shared",
            "token_ids": [8, 9, 10, 11],
            "target_ids": [9, 10, 11, 12],
        }
        result = run_pretraining_segment(
            model=model,
            optimizer=optimizer,
            records=[record],
            config=config,
            device=torch.device("cpu"),
            checkpoint_every=1,
            checkpoint_callback=lambda _step, _result: None,
            signature_observer=observed.append,
            require_complete_coverage=False,
        )
        self.assertEqual(result["steps"], 1)
        self.assertEqual(result["tokens_seen"], 4)
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["schema_version"], "ember-training-step-signature-v1")
        self.assertEqual(observed[0]["contract"]["active_expert"], "shared")
        self.assertEqual(observed[0]["contract"]["tensors"]["input_ids"]["shape"], [1, 4])

    def test_census_bound_executor_warms_captures_and_replays_real_step(self) -> None:
        loss_refs: list[weakref.ReferenceType[torch.Tensor]] = []

        class FakeGraph:
            def __init__(self, region: object) -> None:
                self.region = region

            def replay(self) -> None:
                self.region()

        class FakeBackend:
            preparation_regions_per_signature = 4

            def __init__(self) -> None:
                self.warmups = 0
                self.captures = 0
                self.warmup_loss_released = False

            def warmup(self, region: object, zero_grad: object) -> None:
                self.warmups += 1
                for _ in range(3):
                    zero_grad()
                    region()
                zero_grad()

            def capture(self, region: object) -> FakeGraph:
                self.captures += 1
                gc.collect()
                self.warmup_loss_released = bool(loss_refs) and loss_refs[-1]() is None
                region()
                return FakeGraph(region)

        config = RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=1, attention_heads=4, vocab_size=64,
        )
        record = {
            "schema_version": "ember-owned-semantic-text-v1",
            "active_expert": "shared",
            "token_ids": [8, 9, 10, 11],
            "target_ids": [9, 10, 11, 12],
        }
        batch = decode_owned_batch(record, config, device=torch.device("cpu"))
        census = training_acceleration.TrainingSignatureCensus(
            source_commit="1" * 40,
            model_config_sha256="2" * 64,
            input_identity_sha256="3" * 64,
            runner_source_sha256="4" * 64,
        )
        census.observe(training_acceleration.training_step_signature(
            batch, gradient_checkpointing=bool(config.gradient_checkpointing),
        ))
        with tempfile.TemporaryDirectory() as directory:
            census_path = Path(directory) / "census.json"
            census.write_receipt(census_path)
            authority = training_acceleration.load_stage2_activation_authority(
                census_path,
                expected_raw_sha256=hashlib.sha256(census_path.read_bytes()).hexdigest(),
            )
            model = UnifiedDecoder(config, genesis_seed=43).to(dtype=torch.bfloat16)
            optimizer = torch.optim.SGD(model.parameters(), lr=1e-3)
            backend = FakeBackend()
            executor = pretrain.CensusBoundStage2Executor(
                model=model,
                optimizer=optimizer,
                config=config,
                authority=authority,
                graph_backend=backend,
                fp8_kernel=self._fake_scaled_mm,
                allow_test_device=True,
            )
            real_cross_entropy = pretrain.F.cross_entropy

            def tracked_cross_entropy(*args: object, **kwargs: object) -> torch.Tensor:
                loss = real_cross_entropy(*args, **kwargs)
                loss_refs.append(weakref.ref(loss))
                return loss

            with patch.object(
                pretrain.F, "cross_entropy", side_effect=tracked_cross_entropy,
            ):
                result = run_pretraining_segment(
                    model=model,
                    optimizer=optimizer,
                    records=[record],
                    config=config,
                    device=torch.device("cpu"),
                    checkpoint_every=1,
                    checkpoint_callback=lambda _step, _result: None,
                    stage2_executor=executor,
                    measurement_preparation_regions_per_signature=4,
                    require_complete_coverage=False,
                )
        runtime = result["stage2_runtime"]
        self.assertEqual(backend.warmups, 1)
        self.assertEqual(backend.captures, 1)
        self.assertTrue(backend.warmup_loss_released)
        self.assertEqual(runtime["cuda_graph_captures"], 1)
        self.assertEqual(runtime["cuda_graph_replays"], 1)
        self.assertEqual(runtime["captures_during_preparation"], 1)
        self.assertEqual(runtime["captures_during_measured_window"], 0)
        self.assertGreater(runtime["fp8_dispatches"], 0)
        self.assertEqual(runtime["fp8_fallbacks"], 0)
        self.assertEqual(len(result["step_timings_seconds"]), 1)
        self.assertEqual(result["measurement_preparation"], {
            "regions_per_signature": 4,
            "signature_count": 1,
            "region_count": 4,
            "no_capture_in_measured_window": True,
        })
        self.assertAlmostEqual(
            result["tokens_per_second"],
            result["tokens_seen"] / sum(result["step_timings_seconds"]),
        )

    def test_census_bound_executor_snapshots_loss_before_a_pool_mate_replay(self) -> None:
        signatures = ("5" * 64, "6" * 64)
        shared_pool_loss = torch.tensor(0.0)

        class FakeAuthority:
            @staticmethod
            def resolve(batch: object, *, gradient_checkpointing: bool) -> str:
                del gradient_checkpointing
                return batch["signature"]

        class FakeGraphPool:
            @staticmethod
            def contains(signature: str) -> bool:
                return signature in signatures

            @staticmethod
            def replay(signature: str) -> None:
                shared_pool_loss.fill_(1.0 if signature == signatures[0] else 2.0)
                executor._loss_snapshots[signature].copy_(shared_pool_loss)

        class FakeOptimizer:
            @staticmethod
            def zero_grad(*, set_to_none: bool) -> None:
                del set_to_none

        executor = object.__new__(pretrain.CensusBoundStage2Executor)
        executor._measurement_prepared = True
        executor.authority = FakeAuthority()
        executor.graph_pool = FakeGraphPool()
        executor.config = RestartDecoderConfig.small_for_tests()
        executor._static_batches = {signature: {} for signature in signatures}
        executor.optimizer = FakeOptimizer()
        executor._losses = {
            signature: [shared_pool_loss] for signature in signatures
        }
        executor._loss_snapshots = {
            signature: torch.empty_like(shared_pool_loss) for signature in signatures
        }
        executor._captures_during_measured_window = 0

        first = executor.forward_loss_backward(
            {"signature": signatures[0]}, cursor_identity="7" * 64,
        )
        second = executor.forward_loss_backward(
            {"signature": signatures[1]}, cursor_identity="8" * 64,
        )

        self.assertEqual(float(first), 1.0)
        self.assertEqual(float(second), 2.0)

    def _record(self, config: RestartDecoderConfig, *, expert: str, sample_id: str | None = None) -> dict[str, object]:
        image = bytes(index % 251 for index in range(48 * 48 * 3))
        audio = (torch.arange(640, dtype=torch.int16) - 320).numpy().tobytes()
        record: dict[str, object] = {
            "schema_version": "ember-owned-bootstrap-batch-v1",
            "sample_id": sample_id or f"owned-pretrain-{expert}",
            "active_expert": expert,
            "capability_evidence": {},
        }
        if expert == "vision":
            record.update({
                "token_ids": [1, config.image_token_id, 2], "target_ids": [2, 3, 4],
                "image_patches_u8_base64": [base64.b64encode(image).decode("ascii")],
                "image_coordinates": [[0, 0]],
                "multimodal_spans": [{"start": 1, "length": 1, "modality": "image", "attention_mode": "isolated"}],
            })
        elif expert == "audio":
            record.update({
                "token_ids": [1, config.audio_token_id, 2], "target_ids": [2, 3, 4],
                "audio_frames_i16le_base64": [base64.b64encode(audio).decode("ascii")],
                "image_coordinates": [],
                "multimodal_spans": [{"start": 1, "length": 1, "modality": "audio", "attention_mode": "causal"}],
            })
        else:
            record.update({"token_ids": [1, 2, 3], "target_ids": [2, 3, 4], "image_coordinates": [], "multimodal_spans": []})
            if expert == "reasoning":
                record["capability_evidence"] = {"reasoning": {"operands": [1, 2], "target": 3, "trace": [1, 2, 3]}}
            else:
                record["capability_evidence"] = {"tool": {"name": "owned_calculator", "arguments": {"expression": "1+2"}, "observation": {"value": 3}}}
            record["capability_receipt"] = expected_receipt(record)
        return record

    def _domain_records(self, config: RestartDecoderConfig) -> list[dict[str, object]]:
        return [self._record(config, expert=expert) for expert in ("vision", "audio", "reasoning", "tool")]

    def test_complete_optimizer_updates_each_routed_expert_only_on_its_episode(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=23)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        self.assertEqual({id(parameter) for group in optimizer.param_groups for parameter in group["params"]}, {id(parameter) for parameter in model.parameters()})
        for expert in ("vision", "audio", "reasoning", "tool"):
            before = {name: parameter.detach().clone() for name, parameter in model.named_parameters() if ".experts." in name}
            run_pretraining_segment(
                model=model, optimizer=optimizer, records=[self._record(config, expert=expert)], config=config,
                device=torch.device("cpu"), checkpoint_every=1, checkpoint_callback=lambda _step, _result: None,
                require_complete_coverage=False,
            )
            for name, parameter in model.named_parameters():
                if ".experts." in name:
                    self.assertEqual(not torch.equal(parameter.detach(), before[name]), f".experts.{expert}." in name, name)

    def test_segment_requires_all_capabilities_and_domain_experts(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=17)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        checkpoints: list[int] = []
        result = run_pretraining_segment(
            model=model, optimizer=optimizer, records=self._domain_records(config), config=config,
            device=torch.device("cpu"), checkpoint_every=1, checkpoint_callback=lambda step, _result: checkpoints.append(step),
        )
        self.assertEqual(result["steps"], 4)
        self.assertEqual(result["tokens_seen"], 12)
        self.assertEqual(result["modality_examples"], {"text": 4, "image": 1, "audio": 1, "reasoning": 1, "tool": 1})
        self.assertEqual(result["expert_examples"], {"vision": 1, "audio": 1, "reasoning": 1, "tool": 1})
        self.assertEqual(checkpoints, [1, 2, 3, 4])

    def test_checkpoint_interval_publishes_bounded_milestones_and_mandatory_final_state(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=27)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        checkpoints: list[int] = []
        result = run_pretraining_segment(model=model, optimizer=optimizer, records=self._domain_records(config)[:3], config=config, device=torch.device("cpu"), checkpoint_every=2, checkpoint_callback=lambda step, _result: checkpoints.append(step), require_complete_coverage=False)
        self.assertEqual(result["global_step"], 3)
        self.assertEqual(checkpoints, [2, 3])

    def test_bounded_canary_resumes_the_last_full_shard_record_without_skip_or_replay(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        records = self._domain_records(config)
        model = UnifiedDecoder(config, genesis_seed=71)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        first_checkpoints: list[dict[str, object]] = []
        first = run_pretraining_segment(
            model=model, optimizer=optimizer, records=records, config=config, device=torch.device("cpu"),
            checkpoint_every=1, checkpoint_callback=lambda _step, state: first_checkpoints.append(state),
            require_complete_coverage=False, max_records=3, data_shard_id="owned-four-domain-production-rung-v1",
        )
        self.assertEqual(first["data_cursor"]["record_index"], 3)
        self.assertEqual(first["global_step"], 3)
        self.assertEqual([state["data_cursor"]["record_index"] for state in first_checkpoints], [1, 2, 3])
        resumed_checkpoints: list[dict[str, object]] = []
        resumed = run_pretraining_segment(
            model=model, optimizer=optimizer, records=records, config=config, device=torch.device("cpu"),
            checkpoint_every=1, checkpoint_callback=lambda _step, state: resumed_checkpoints.append(state),
            initial_global_step=int(first["global_step"]), initial_tokens_seen=int(first["tokens_seen"]),
            initial_data_cursor=int(first["data_cursor"]["record_index"]),
            require_complete_coverage=False, max_records=1, data_shard_id="owned-four-domain-production-rung-v1",
        )
        self.assertEqual(resumed["data_cursor"]["record_index"], 4)
        self.assertEqual(resumed["global_step"], 4)
        self.assertEqual(resumed["expert_examples"], {"vision": 0, "audio": 0, "reasoning": 0, "tool": 1})
        self.assertEqual([state["data_cursor"]["record_index"] for state in resumed_checkpoints], [4])
    def test_forward_interruption_happens_before_optimizer_mutation(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=61)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        before = {name: value.detach().clone() for name, value in model.state_dict().items()}
        checkpoints: list[object] = []

        def interrupted_forward(*_args: object, **_kwargs: object) -> torch.Tensor:
            raise RuntimeError("injected pre-step interruption")

        model.forward = interrupted_forward  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "pre-step interruption"):
            run_pretraining_segment(
                model=model, optimizer=optimizer, records=[self._record(config, expert="vision")],
                config=config, device=torch.device("cpu"), checkpoint_every=1,
                checkpoint_callback=lambda _step, state: checkpoints.append(state), require_complete_coverage=False,
            )
        self.assertEqual(checkpoints, [])
        self.assertEqual(optimizer.state, {})
        self.assertTrue(all(torch.equal(value, before[name]) for name, value in model.state_dict().items()))

    def test_post_update_interruption_carries_the_exact_resume_cursor(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=62)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        before = model.token_embedding.weight.detach().clone()
        observed: list[tuple[int, dict[str, object]]] = []

        def interrupt_after_checkpoint(step: int, state: dict[str, object]) -> None:
            observed.append((step, state))
            raise KeyboardInterrupt("injected post-update interruption")

        with self.assertRaisesRegex(KeyboardInterrupt, "post-update interruption"):
            run_pretraining_segment(
                model=model, optimizer=optimizer, records=[self._record(config, expert="vision")],
                config=config, device=torch.device("cpu"), checkpoint_every=1,
                checkpoint_callback=interrupt_after_checkpoint, require_complete_coverage=False,
            )
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0][0], 1)
        self.assertEqual(observed[0][1]["data_cursor"], {"shard": "owned-pretraining", "record_index": 1, "global_step": 1, "tokens_seen": 3})
        self.assertFalse(torch.equal(model.token_embedding.weight.detach(), before))
        self.assertTrue(optimizer.state)

    def test_empty_and_exhausted_segments_never_replay_or_synthesize_records(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one owned record"):
            run_pretraining_segment(
                model=object(), optimizer=object(), records=[], config=object(), device=torch.device("cpu"),
                checkpoint_every=1, checkpoint_callback=lambda _step, _state: None,
            )

        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=63)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        checkpoints: list[object] = []
        result = run_pretraining_segment(
            model=model, optimizer=optimizer, records=[self._record(config, expert="vision")], config=config,
            device=torch.device("cpu"), checkpoint_every=1, checkpoint_callback=lambda _step, state: checkpoints.append(state),
            initial_global_step=11, initial_tokens_seen=2048, initial_data_cursor=1,
            require_complete_coverage=False,
        )
        self.assertEqual(result["steps"], 0)
        self.assertEqual(result["data_cursor"], {"shard": "owned-pretraining", "record_index": 1, "global_step": 11, "tokens_seen": 2048})
        self.assertEqual(checkpoints, [])
        self.assertEqual(optimizer.state, {})

    def test_nonfinite_loss_refuses_before_backward_or_optimizer_mutation(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=64)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        before = {name: value.detach().clone() for name, value in model.state_dict().items()}

        def nonfinite_forward(input_ids: torch.Tensor, **_kwargs: object) -> torch.Tensor:
            return torch.full((input_ids.shape[0], input_ids.shape[1], config.vocab_size), float("nan"))

        model.forward = nonfinite_forward  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "non-finite loss"):
            run_pretraining_segment(
                model=model, optimizer=optimizer, records=[self._record(config, expert="vision")],
                config=config, device=torch.device("cpu"), checkpoint_every=1,
                checkpoint_callback=lambda _step, _state: None, require_complete_coverage=False,
            )
        self.assertEqual(optimizer.state, {})
        self.assertTrue(all(torch.equal(value, before[name]) for name, value in model.state_dict().items()))

    def test_progress_callback_observes_every_completed_optimizer_step(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=28)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        progress: list[dict[str, object]] = []
        result = run_pretraining_segment(
            model=model,
            optimizer=optimizer,
            records=self._domain_records(config)[:2],
            config=config,
            device=torch.device("cpu"),
            checkpoint_every=2,
            checkpoint_callback=lambda _step, _result: None,
            progress_callback=progress.append,
            initial_global_step=7,
            require_complete_coverage=False,
        )
        self.assertEqual([event["step"] for event in progress], [8, 9])
        self.assertEqual([event["total_steps"] for event in progress], [9, 9])
        self.assertEqual([event["loss"] for event in progress], result["losses"])
        self.assertTrue(all(isinstance(event["step_ms"], float) and event["step_ms"] > 0 for event in progress))
        # grad_norm: clip_grad_norm_'s pre-clip return value, no longer discarded (#1434).
        self.assertTrue(all(
            isinstance(event["grad_norm"], float) and math.isfinite(event["grad_norm"]) and event["grad_norm"] > 0.0
            for event in progress
        ))
        self.assertNotEqual(progress[0]["grad_norm"], progress[1]["grad_norm"])
        # router/expert entropy + utilization derived from the cumulative expert_examples
        # counts: step 1 routes only to "vision" (zero entropy, fully concentrated),
        # step 2 adds "audio" (even split, entropy = ln(2)). Values that must move,
        # not a runner that could pass by recording a constant.
        self.assertEqual(progress[0]["router_entropy_nats"], 0.0)
        # assertEqual cannot distinguish -0.0 from 0.0 (they compare equal); a signed
        # zero here would still serialize as "-0.0" into the receipted JSONL (#1434
        # review). copysign is the correct way to assert on the sign bit itself.
        self.assertEqual(math.copysign(1.0, progress[0]["router_entropy_nats"]), 1.0)
        self.assertAlmostEqual(progress[1]["router_entropy_nats"], math.log(2))
        self.assertEqual(progress[0]["expert_utilization"], {"vision": 1.0, "audio": 0.0, "reasoning": 0.0, "tool": 0.0})
        self.assertEqual(progress[1]["expert_utilization"], {"vision": 0.5, "audio": 0.5, "reasoning": 0.0, "tool": 0.0})

    def test_expert_routing_entropy_matches_the_natural_log_definition_with_zero_count_convention(self) -> None:
        """Pure math: p_i = count_i / total, H = -sum(p_i * log(p_i)), 0 * log(0) = 0."""
        entropy, utilization = pretrain._expert_routing_entropy({"vision": 0, "audio": 0, "reasoning": 0, "tool": 0})
        self.assertEqual(entropy, 0.0)
        self.assertEqual(math.copysign(1.0, entropy), 1.0)
        self.assertEqual(utilization, {"vision": 0.0, "audio": 0.0, "reasoning": 0.0, "tool": 0.0})

        entropy, utilization = pretrain._expert_routing_entropy({"vision": 4, "audio": 0, "reasoning": 0, "tool": 0})
        self.assertEqual(entropy, 0.0)
        self.assertEqual(math.copysign(1.0, entropy), 1.0)
        self.assertEqual(utilization, {"vision": 1.0, "audio": 0.0, "reasoning": 0.0, "tool": 0.0})

        entropy, utilization = pretrain._expert_routing_entropy({"vision": 1, "audio": 1, "reasoning": 1, "tool": 1})
        self.assertAlmostEqual(entropy, math.log(4))
        self.assertEqual(utilization, {"vision": 0.25, "audio": 0.25, "reasoning": 0.25, "tool": 0.25})

        entropy, utilization = pretrain._expert_routing_entropy({"vision": 3, "audio": 1, "reasoning": 0, "tool": 0})
        expected_entropy = -(0.75 * math.log(0.75) + 0.25 * math.log(0.25))
        self.assertAlmostEqual(entropy, expected_entropy)
        self.assertEqual(utilization, {"vision": 0.75, "audio": 0.25, "reasoning": 0.0, "tool": 0.0})

    def test_expert_routing_entropy_never_serializes_a_signed_zero(self) -> None:
        """A single fully-concentrated expert must not leave -0.0 in the receipted JSON.

        -sum(1.0 * log(1.0)) is -0.0 in IEEE 754 (the general formula's only way to
        reach exactly zero); json.dumps(-0.0) writes the literal "-0.0" into the
        telemetry JSONL receipt, a spurious sign on a value that is definitionally
        nonnegative. assertEqual cannot catch this (-0.0 == 0.0 is True) -- this test
        checks the sign bit and the actual serialized bytes directly (#1434 review).
        """
        for counts in (
            {"vision": 4, "audio": 0, "reasoning": 0, "tool": 0},
            {"vision": 0, "audio": 7, "reasoning": 0, "tool": 0},
            {"vision": 0, "audio": 0, "reasoning": 0, "tool": 1},
        ):
            entropy, _utilization = pretrain._expert_routing_entropy(counts)
            self.assertEqual(entropy, 0.0)
            self.assertEqual(math.copysign(1.0, entropy), 1.0, f"signed zero for counts={counts}")
            self.assertNotIn("-0.0", json.dumps({"router_entropy_nats": entropy}))

    def test_selection_progress_callback_records_grad_norm_and_router_entropy(self) -> None:
        """run_selection_pretraining_segment mirrors run_pretraining_segment's telemetry (#1434)."""

        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        records = [self._record(config, expert=expert, sample_id=f"selection-progress-{expert}") for expert in ("vision", "audio")]

        class TwoRecordSelection:
            receipt = {"schema_version": SELECTION_RECEIPT_SCHEMA_VERSION, "capability": "image"}

            def iter_from(self, cursor: object = None):
                start = 0 if cursor is None else int(cursor["next_source_index"])
                for index in range(start, len(records)):
                    yield records[index], {
                        "schema_version": SELECTION_CURSOR_SCHEMA_VERSION,
                        "selection_receipt_sha256": "b" * 64,
                        "selection_rule_id": "image_scene_split_train_v1",
                        "selected_ordinal": index + 1,
                        "next_source_index": index + 1,
                    }

        model = UnifiedDecoder(config, genesis_seed=44)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        progress: list[dict[str, object]] = []
        getattr(pretrain, "run_selection_pretraining_segment")(
            model=model, optimizer=optimizer, selection=TwoRecordSelection(), config=config, device=torch.device("cpu"),
            checkpoint_every=2, checkpoint_callback=lambda _step, _state: None,
            progress_callback=progress.append, require_complete_coverage=False,
        )
        self.assertEqual([event["step"] for event in progress], [1, 2])
        self.assertTrue(all(
            isinstance(event["grad_norm"], float) and math.isfinite(event["grad_norm"]) and event["grad_norm"] > 0.0
            for event in progress
        ))
        self.assertNotEqual(progress[0]["grad_norm"], progress[1]["grad_norm"])
        self.assertEqual(progress[0]["router_entropy_nats"], 0.0)
        self.assertAlmostEqual(progress[1]["router_entropy_nats"], math.log(2))
        self.assertEqual(progress[0]["expert_utilization"], {"vision": 1.0, "audio": 0.0, "reasoning": 0.0, "tool": 0.0})
        self.assertEqual(progress[1]["expert_utilization"], {"vision": 0.5, "audio": 0.5, "reasoning": 0.0, "tool": 0.0})

    def test_rejects_self_declared_reasoning_or_tool_without_executed_receipt(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=29)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        record = self._record(config, expert="tool")
        del record["capability_receipt"]
        with self.assertRaisesRegex(ValueError, "content-addressed local verifier receipt"):
            run_pretraining_segment(model=model, optimizer=optimizer, records=[record], config=config, device=torch.device("cpu"), checkpoint_every=1, checkpoint_callback=lambda _step, _result: None, require_complete_coverage=False)

    def test_rejects_receipt_when_reasoning_target_or_tool_observation_is_tampered(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=30)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        reasoning = self._record(config, expert="reasoning")
        reasoning["capability_evidence"]["reasoning"]["target"] = 4
        with self.assertRaisesRegex(ValueError, "verifier did not pass"):
            run_pretraining_segment(model=model, optimizer=optimizer, records=[reasoning], config=config, device=torch.device("cpu"), checkpoint_every=1, checkpoint_callback=lambda _step, _result: None, require_complete_coverage=False)
        tool = self._record(config, expert="tool")
        tool["capability_evidence"]["tool"]["observation"]["value"] = 4
        with self.assertRaisesRegex(ValueError, "verifier did not pass"):
            run_pretraining_segment(model=model, optimizer=optimizer, records=[tool], config=config, device=torch.device("cpu"), checkpoint_every=1, checkpoint_callback=lambda _step, _result: None, require_complete_coverage=False)
    def test_actual_bfloat16_pretraining_segment_normalizes_raw_modalities(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=31).to(dtype=torch.bfloat16)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        result = run_pretraining_segment(model=model, optimizer=optimizer, records=self._domain_records(config), config=config, device=torch.device("cpu"), checkpoint_every=4, checkpoint_callback=lambda _step, _result: None)
        self.assertEqual(result["steps"], 4)
        self.assertTrue(all(torch.isfinite(torch.tensor(value)) for value in result["losses"]))

    def test_actual_pretraining_forwards_explicit_coordinates_and_domain_spans(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=37)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        calls: list[tuple[torch.Tensor, object]] = []
        original_forward = model.forward
        def observed_forward(input_ids: torch.Tensor, *args: object, **kwargs: object) -> torch.Tensor:
            calls.append((kwargs["image_coordinates"], kwargs["spans"]))
            return original_forward(input_ids, *args, **kwargs)
        model.forward = observed_forward  # type: ignore[method-assign]
        run_pretraining_segment(model=model, optimizer=optimizer, records=self._domain_records(config), config=config, device=torch.device("cpu"), checkpoint_every=4, checkpoint_callback=lambda _step, _result: None)
        self.assertEqual(len(calls), 4)
        self.assertTrue(torch.equal(calls[0][0], torch.tensor([[0, 0]])))
        self.assertEqual([(span.start, span.length, span.modality) for span in calls[0][1]], [(1, 1, "image")])
        self.assertTrue(torch.equal(calls[1][0], torch.empty((0, 2), dtype=torch.long)))
        self.assertEqual([(span.start, span.length, span.modality) for span in calls[1][1]], [(1, 1, "audio")])
        self.assertEqual(calls[2][1], [])
        self.assertEqual(calls[3][1], [])
    def test_selection_consumer_is_sequential_and_resume_cursor_matches_uninterrupted_updates(self) -> None:
        """P2B consumes an iterable selection without Sequence access or record replay."""

        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        records = [self._record(config, expert="vision", sample_id=f"selection-{index}") for index in range(3)]

        class NoSequenceSelection:
            receipt = {"schema_version": SELECTION_RECEIPT_SCHEMA_VERSION, "capability": "image"}

            def __init__(self, values: list[dict[str, object]]) -> None:
                self.values = values
                self.yielded: list[str] = []

            def __len__(self) -> int:
                raise AssertionError("selection consumer must not call __len__")

            def __getitem__(self, _index: object) -> dict[str, object]:
                raise AssertionError("selection consumer must not call __getitem__")

            def iter_from(self, cursor: object = None):
                start = 0 if cursor is None else int(cursor["next_source_index"])
                for index in range(start, len(self.values)):
                    self.yielded.append(str(self.values[index]["sample_id"]))
                    yield self.values[index], {
                        "schema_version": SELECTION_CURSOR_SCHEMA_VERSION,
                        "selection_receipt_sha256": "a" * 64,
                        "selection_rule_id": "image_scene_split_train_v1",
                        "selected_ordinal": index + 1,
                        "next_source_index": index + 1,
                    }

        def run_segment(selection: NoSequenceSelection, *, max_records: int | None, initial_cursor: dict[str, object] | None = None, initial_step: int = 0, initial_tokens: int = 0) -> tuple[dict[str, object], list[tuple[int, dict[str, object]]]]:
            model = UnifiedDecoder(config, genesis_seed=43)
            optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
            callbacks: list[tuple[int, dict[str, object]]] = []
            result = getattr(pretrain, "run_selection_pretraining_segment")(
                model=model, optimizer=optimizer, selection=selection, config=config, device=torch.device("cpu"),
                checkpoint_every=1, checkpoint_callback=lambda step, state: callbacks.append((step, state)),
                initial_selection_cursor=initial_cursor, initial_global_step=initial_step,
                initial_tokens_seen=initial_tokens, max_records=max_records,
                require_complete_coverage=False,
            )
            return result, callbacks

        uninterrupted = NoSequenceSelection(records)
        uninterrupted_result, uninterrupted_callbacks = run_segment(uninterrupted, max_records=None)
        interrupted = NoSequenceSelection(records)
        first, first_callbacks = run_segment(interrupted, max_records=2)
        resumed, resumed_callbacks = run_segment(
            interrupted, max_records=None,
            initial_cursor=first["data_cursor"]["selection_cursor"],
            initial_step=first["global_step"], initial_tokens=first["tokens_seen"],
        )

        self.assertEqual(uninterrupted.yielded, ["selection-0", "selection-1", "selection-2"])
        self.assertEqual(interrupted.yielded, uninterrupted.yielded)
        def assert_completed_callbacks(callbacks: list[tuple[int, dict[str, object]]], expected_steps: list[int]) -> None:
            self.assertEqual([step for step, _state in callbacks], expected_steps)
            for step, state in callbacks:
                cursor = state["data_cursor"]
                self.assertEqual(cursor["global_step"], step)
                self.assertEqual(cursor["tokens_seen"], step * 3)
                self.assertEqual(cursor["selection_cursor"], {
                    "schema_version": SELECTION_CURSOR_SCHEMA_VERSION,
                    "selection_receipt_sha256": "a" * 64,
                    "selection_rule_id": "image_scene_split_train_v1",
                    "selected_ordinal": step,
                    "next_source_index": step,
                })

        assert_completed_callbacks(uninterrupted_callbacks, [1, 2, 3])
        assert_completed_callbacks(first_callbacks, [1, 2])
        assert_completed_callbacks(resumed_callbacks, [3])
        self.assertEqual(resumed_callbacks[0][0], uninterrupted_callbacks[2][0])
        self.assertEqual(resumed_callbacks[0][1]["global_step"], uninterrupted_callbacks[2][1]["global_step"])
        self.assertEqual(resumed_callbacks[0][1]["data_cursor"], uninterrupted_callbacks[2][1]["data_cursor"])
        self.assertEqual(first["global_step"], 2)
        self.assertEqual(first["tokens_seen"], 6)
        self.assertEqual(first["data_cursor"]["selection_cursor"], {
            "schema_version": SELECTION_CURSOR_SCHEMA_VERSION,
            "selection_receipt_sha256": "a" * 64,
            "selection_rule_id": "image_scene_split_train_v1",
            "selected_ordinal": 2,
            "next_source_index": 2,
        })
        self.assertEqual(resumed["data_cursor"]["selection_cursor"], uninterrupted_result["data_cursor"]["selection_cursor"])
        self.assertEqual(resumed["global_step"], uninterrupted_result["global_step"])
        self.assertEqual(resumed["tokens_seen"], uninterrupted_result["tokens_seen"])




if __name__ == "__main__":
    unittest.main()
