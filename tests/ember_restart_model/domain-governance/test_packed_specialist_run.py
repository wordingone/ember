# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed receipt and comparison contracts for issue #1413 packed arms."""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))

from src.ember.model.model import RestartDecoderConfig
from packed_specialist_run import (
    active_route_optimizer_sha256,
    active_route_parameter_sha256,
    all_parameter_sha256,
    build_packed_arm_receipt,
    build_packed_comparison,
    build_packed_graph_bf16_diagnostic_receipt,
    build_resume_equivalence_receipt,
    checkpoint_serialized_bytes_from_writer_receipt,
    packed_genesis_lineage_sha256,
    prepare_packed_execution_slice,
    release_first_runtime_for_resume,
    run_durable_resume_leg,
    run_issue1946_profile,
)


class PackedSpecialistRunTests(unittest.TestCase):
    def test_issue1946_runner_binds_every_required_instrument_before_live_arms(self) -> None:
        source = inspect.getsource(run_issue1946_profile)
        for required in (
            "gpu_covariate",
            "torch.profiler.profile",
            "all_parameter_sha256",
            "complete_update_cuda_event_seconds",
            "complete_update_phase_timings_seconds",
            "build_issue1946_preflight_receipt",
            "build_issue1946_arm_receipt",
        ):
            self.assertIn(required, source)

    def test_graph_bf16_diagnostic_is_nonpromotable_and_requires_exact_mechanisms(self) -> None:
        segment = {
            "steps": 2,
            "losses": [10.0, 9.0],
            "step_timings_seconds": [0.2, 0.2],
            "data_cursor": {
                "packed_selection_cursor": {"selected_ordinal": 128},
                "global_step": 2, "tokens_seen": 1920,
                "processed_tokens_seen": 1920, "pack_ordinal": 2,
            },
            "measurement_preparation": {
                "regions_per_signature": 4, "signature_count": 1,
                "region_count": 4, "optimizer_state_preinitialized_parameters": 7,
                "no_capture_in_measured_window": True,
            },
            "stage2_runtime": {
                "fp8_dispatches": 0, "fp8_fallbacks": 0,
                "cuda_graph_captures": 1, "cuda_graph_replays": 2,
                "cuda_graph_fallbacks": 0,
            },
        }
        receipt = build_packed_graph_bf16_diagnostic_receipt(
            identity=self._identity(), segment=segment,
            runtime_custody={"governor": "test"},
        )
        self.assertEqual(receipt["claim_boundary"], "DIAGNOSTIC_ONLY_NOT_CLOSE_EVIDENCE")
        self.assertEqual(receipt["losses"], [10.0, 9.0])
        unsigned = dict(receipt)
        claimed = unsigned.pop("self_sha256")
        self.assertEqual(
            claimed,
            hashlib.sha256(
                json.dumps(
                    unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                ).encode("utf-8")
            ).hexdigest(),
        )
        refused = dict(segment)
        refused["stage2_runtime"] = dict(segment["stage2_runtime"], fp8_dispatches=1)
        with self.assertRaisesRegex(ValueError, "mechanisms"):
            build_packed_graph_bf16_diagnostic_receipt(
                identity=self._identity(), segment=refused,
                runtime_custody={"governor": "test"},
            )

    def test_checkpoint_size_comes_from_the_admission_writer_receipt(self) -> None:
        self.assertEqual(
            checkpoint_serialized_bytes_from_writer_receipt({"serialized_bytes": 123}),
            123,
        )
        with self.assertRaisesRegex(ValueError, "writer receipt lacks serialized bytes"):
            checkpoint_serialized_bytes_from_writer_receipt({})

    def test_durable_cleanup_does_not_materialize_a_retaining_locals_snapshot(self) -> None:
        self.assertNotIn("locals()", inspect.getsource(run_durable_resume_leg))

    def test_release_first_runtime_synchronizes_and_rechecks_production_floor(self) -> None:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=2, attention_heads=4, vocab_size=64,
        )
        events: list[str] = []

        def mark(name: str, result: object = None):
            def invoke(*_args, **_kwargs):
                events.append(name)
                return result
            return invoke

        with (
            patch("packed_specialist_run.torch.cuda.is_available", return_value=True),
            patch("packed_specialist_run.torch.cuda.synchronize", side_effect=mark("sync")),
            patch("packed_specialist_run.gc.collect", side_effect=mark("gc", 7)),
            patch("packed_specialist_run.torch.cuda.empty_cache", side_effect=mark("empty")),
            patch(
                "packed_specialist_run.torch.cuda.mem_get_info",
                side_effect=mark("info", (23_000_000_000, 24_000_000_000)),
            ),
            patch(
                "packed_specialist_run.production_memory_preflight",
                side_effect=mark("floor", {"required_bytes": 21_021_705_216}),
            ) as floor,
        ):
            receipt = release_first_runtime_for_resume(config)

        self.assertEqual(events, ["sync", "gc", "empty", "sync", "info", "floor"])
        self.assertEqual(receipt["gc_collected"], 7)
        self.assertEqual(receipt["post_release_free_bytes"], 23_000_000_000)
        self.assertEqual(receipt["device_total_bytes"], 24_000_000_000)
        self.assertEqual(receipt["production_memory_preflight"]["required_bytes"], 21_021_705_216)
        floor.assert_called_once_with(
            total_parameters=config.structural_parameter_count(),
            active_parameters=config.structural_parameter_count() - (
                (len(config.expert_names) - 1)
                * config.layers * 12 * config.hidden_size * config.hidden_size
            ),
            device_free_bytes=23_000_000_000,
        )

    def test_release_first_runtime_refuses_when_measured_floor_is_still_low(self) -> None:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=2, attention_heads=4, vocab_size=64,
        )
        with (
            patch("packed_specialist_run.torch.cuda.is_available", return_value=True),
            patch("packed_specialist_run.torch.cuda.synchronize"),
            patch("packed_specialist_run.gc.collect", return_value=0),
            patch("packed_specialist_run.torch.cuda.empty_cache"),
            patch(
                "packed_specialist_run.torch.cuda.mem_get_info",
                return_value=(1_000_000_000, 24_000_000_000),
            ),
            self.assertRaisesRegex(MemoryError, "BF16 production envelope requires"),
        ):
            release_first_runtime_for_resume(config)

    @staticmethod
    def _audio_record(config: RestartDecoderConfig, index: int) -> dict[str, object]:
        tokens = [config.audio_token_id] * 4 + list(range(1, 12))
        return {
            "schema_version": "ember-owned-semantic-record-v1",
            "sample_id": f"audio-{index}", "active_expert": "audio",
            "token_ids": tokens, "target_ids": [*tokens[1:], 1],
            "image_patches_u8_base64": [],
            "audio_frames_i16le_base64": [base64.b64encode(bytes(1280)).decode()] * 4,
            "image_coordinates": [],
            "multimodal_spans": [{
                "start": 0, "length": 4, "modality": "audio", "attention_mode": "causal",
            }],
        }

    @staticmethod
    def _selection(records: list[dict[str, object]]):
        class Selection:
            receipt = {"selected_record_count": len(records)}

            def iter_from(self, cursor: object = None):
                start = 0 if cursor is None else int(cursor["selected_ordinal"])
                for index in range(start, len(records)):
                    yield records[index], {
                        "selection_receipt_sha256": "a" * 64,
                        "selected_ordinal": index + 1,
                    }
        return Selection()

    @staticmethod
    def _identity() -> dict[str, object]:
        return {
            "source_commit": "a" * 40,
            "runner_source_sha256": "b" * 64,
            "model_config_sha256": "c" * 64,
            "stream_manifest_sha256": "d" * 64,
            "stream_build_receipt_sha256": "e" * 64,
            "selection_receipt_sha256": "f" * 64,
            "density_raw_sha256": "1" * 64,
            "density_self_sha256": "2" * 64,
            "census_raw_sha256": "3" * 64,
            "census_self_sha256": "4" * 64,
            "execution_record_order_sha256": "5" * 64,
            "execution_tokens_sha256": "6" * 64,
            "pack_sequence_sha256": "7" * 64,
            "genesis_lineage_sha256": "8" * 64,
            "lineage_mode": "FRESH_GENESIS_NO_EXTERNAL_PREDECESSOR",
            "seed": 83,
            "initial_cursor": {
                "selected_ordinal": 0,
                "global_step": 0,
                "tokens_seen": 0,
                "processed_tokens_seen": 0,
                "pack_ordinal": 0,
            },
            "pack_records": 64,
        }

    def _arm(self, *, arm: str, elapsed: float, losses: list[float] | None = None,
             padding_tokens: int = 0, fallbacks: int = 0,
             force_reference: bool | None = None,
             reference_losses: list[float] | None = None) -> dict[str, object]:
        normalized_losses = losses or [10.0, 9.5, 9.0, 8.5]
        carry_reference = arm == "bf16_packed_eager" if force_reference is None else force_reference
        return build_packed_arm_receipt(
            arm=arm,
            identity=self._identity(),
            steps=4,
            true_source_tokens=3840,
            processed_padded_tokens=3840 + padding_tokens,
            padding_tokens=padding_tokens,
            losses=normalized_losses,
            single_record_reference_losses=(
                (reference_losses or [10.0, 9.5, 9.0, 8.5]) if carry_reference else None
            ),
            step_timings_seconds=[elapsed / 4] * 4,
            max_memory_allocated_bytes=20_000_000_000,
            max_memory_reserved_bytes=21_000_000_000,
            mechanisms={
                "fp8_dispatches": 672 if arm == "census_bound_stage2" else 0,
                "fp8_fallbacks": fallbacks,
                "cuda_graph_captures": 1 if arm == "census_bound_stage2" else 0,
                "cuda_graph_replays": 4 if arm == "census_bound_stage2" else 0,
                "cuda_graph_fallbacks": 0,
                "captures_during_preparation": 1 if arm == "census_bound_stage2" else 0,
                "captures_during_measured_window": 0,
            },
            fp8_installation=(
                {
                    "schema_version": "ember-fp8-down-projection-installation-v2",
                    "scope": "final_decoder_layer_shared_swiglu_down_4h_to_h",
                    "layer_indexes": [41],
                    "installed_sites": 1,
                    "sites": ["layers.41.shared_ffn.down"],
                    "fallbacks": 0,
                }
                if arm == "census_bound_stage2" else {
                    "schema_version": "ember-fp8-down-projection-installation-v2",
                    "scope": "NONE",
                    "layer_indexes": [],
                    "installed_sites": 0,
                    "sites": [],
                    "fallbacks": 0,
                }
            ),
            measurement_preparation={
                "regions_per_signature": 4, "signature_count": 1,
                "region_count": 4, "optimizer_state_preinitialized_parameters": 7,
                "no_capture_in_measured_window": True,
            },
            final_cursor={
                "selected_ordinal": 256,
                "global_step": 4,
                "tokens_seen": 3840,
                "processed_tokens_seen": 3840 + padding_tokens,
                "pack_ordinal": 4,
            },
            runtime_custody={
                "canonical_disk_budget_runner": {
                    "schema_version": "ember-canonical-disk-budget-startup-v1",
                    "assertion_sha256": "a" * 64,
                    "cache_bindings_sha256": "b" * 64,
                },
                "b_floor_preflight": {
                    "status": "PASS", "required_free_gib": 255,
                },
                "governor": {"status": "PASS"},
                "memory_preflight": {"parameter_dtype": "bfloat16"},
            },
        )

    def test_arm_counts_only_true_source_tokens_for_close_rate(self) -> None:
        arm = self._arm(arm="bf16_packed_eager", elapsed=3.0, padding_tokens=160)
        self.assertEqual(arm["true_tokens_per_second"], 1280.0)
        self.assertEqual(arm["processed_tokens_per_second"], 4000 / 3.0)
        self.assertEqual(arm["claim_boundary"], "THROUGHPUT_ONLY_NO_CAPABILITY_CLAIM")

    def test_accelerated_arm_binds_exact_fp8_site_scope(self) -> None:
        arm = self._arm(arm="census_bound_stage2", elapsed=3.0)
        self.assertEqual(arm["fp8_installation"]["sites"], ["layers.41.shared_ffn.down"])
        changed = dict(arm["fp8_installation"])
        changed["sites"] = ["layers.40.shared_ffn.down"]
        with self.assertRaisesRegex(ValueError, "FP8 installation"):
            build_packed_arm_receipt(
                arm="census_bound_stage2", identity=self._identity(), steps=4,
                true_source_tokens=3840, processed_padded_tokens=3840, padding_tokens=0,
                losses=[10.0, 9.5, 9.0, 8.5], single_record_reference_losses=None,
                step_timings_seconds=[0.75] * 4,
                max_memory_allocated_bytes=20_000_000_000,
                max_memory_reserved_bytes=21_000_000_000,
                mechanisms=arm["mechanisms"], fp8_installation=changed,
                measurement_preparation=arm["measurement_preparation"],
                final_cursor=arm["final_cursor"], runtime_custody=arm["runtime_custody"],
            )

    def test_comparison_requires_matched_identity_loss_and_strict_speed_gate(self) -> None:
        baseline = self._arm(arm="bf16_packed_eager", elapsed=4.0)
        accelerated = self._arm(
            arm="census_bound_stage2", elapsed=3.0,
            losses=[10.05, 9.48, 9.02, 8.49],
        )
        comparison = build_packed_comparison(baseline, accelerated)
        self.assertEqual(comparison["status"], "PASS")
        self.assertGreater(comparison["accelerated_true_tokens_per_second"], 1000.0)
        self.assertTrue(comparison["close_evidence"]["strictly_greater_than_1000_true_tokens_per_second"])
        self.assertTrue(comparison["close_evidence"]["unchanged_single_record_reference_within_one_percent"])

        slow = self._arm(arm="census_bound_stage2", elapsed=3.84)
        with self.assertRaisesRegex(ValueError, "greater than 1000 true source tok/s"):
            build_packed_comparison(baseline, slow)

    def test_arm_requires_reference_only_for_baseline_and_refuses_one_percent_boundary(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a single-record reference"):
            self._arm(
                arm="bf16_packed_eager", elapsed=4.0, force_reference=False,
            )
        with self.assertRaisesRegex(ValueError, "strictly within one percent"):
            self._arm(
                arm="bf16_packed_eager", elapsed=4.0,
                losses=[101.0, 95.0, 90.0, 85.0], force_reference=True,
                reference_losses=[100.0, 95.0, 90.0, 85.0],
            )
        with self.assertRaisesRegex(ValueError, "cannot carry BF16"):
            self._arm(
                arm="census_bound_stage2", elapsed=3.0, force_reference=True,
            )

        baseline = self._arm(
            arm="bf16_packed_eager", elapsed=4.0,
            losses=[100.0, 95.0, 90.0, 85.0],
            reference_losses=[100.0, 95.0, 90.0, 85.0],
        )
        accelerated = self._arm(
            arm="census_bound_stage2", elapsed=3.0,
            losses=[101.0, 95.0, 90.0, 85.0],
        )
        with self.assertRaisesRegex(ValueError, "matched 1 percent tolerance"):
            build_packed_comparison(baseline, accelerated)

    def test_comparison_refuses_identity_drift_and_any_fallback(self) -> None:
        baseline = self._arm(arm="bf16_packed_eager", elapsed=4.0)
        accelerated = self._arm(arm="census_bound_stage2", elapsed=3.0)
        drifted = dict(accelerated)
        drifted["execution_record_order_sha256"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "self hash|identity"):
            build_packed_comparison(baseline, drifted)
        with self.assertRaisesRegex(ValueError, "fallback"):
            build_packed_comparison(
                baseline,
                self._arm(arm="census_bound_stage2", elapsed=3.0, fallbacks=1),
            )

    def test_execution_slice_binds_every_pack_and_fresh_genesis(self) -> None:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=2, attention_heads=4, vocab_size=64,
        )
        records = [self._audio_record(config, index) for index in range(128)]
        execution = prepare_packed_execution_slice(
            selection=self._selection(records), config=config,
            device=torch.device("cpu"), packs=2,
        )
        self.assertEqual(execution["record_count"], 128)
        self.assertEqual(execution["true_source_tokens"], 1920)
        self.assertEqual(len(execution["pack_signatures"]), 2)
        self.assertEqual(execution["end_selection_cursor"]["selected_ordinal"], 128)
        lineage = packed_genesis_lineage_sha256(
            source_commit="a" * 40, model_config_sha256="b" * 64, seed=83,
        )
        self.assertEqual(len(lineage), 64)
        self.assertNotEqual(
            lineage,
            packed_genesis_lineage_sha256(
                source_commit="a" * 40, model_config_sha256="b" * 64, seed=84,
            ),
        )

    def test_resume_equivalence_requires_bit_exact_next_pack_state(self) -> None:
        checkpoint_cursor = {
            "packed_selection_cursor": {"selected_ordinal": 64},
            "global_step": 1, "tokens_seen": 960,
            "processed_tokens_seen": 960, "pack_ordinal": 1,
        }
        observation = {
            "next_loss": 9.5,
            "final_cursor": {
                "packed_selection_cursor": {"selected_ordinal": 128},
                "global_step": 2, "tokens_seen": 1920,
                "processed_tokens_seen": 1920, "pack_ordinal": 2,
            },
            "active_route_parameter_sha256": "a" * 64,
            "active_route_optimizer_sha256": "b" * 64,
        }
        receipt = build_resume_equivalence_receipt(
            identity=self._identity(), checkpoint_manifest_sha256="c" * 64,
            checkpoint_serialized_bytes=1024, counter_receipt_sha256="d" * 64,
            checkpoint_cursor=checkpoint_cursor,
            uninterrupted=observation, resumed=dict(observation),
            runtime_custody={
                "b_floor_at_start": {"status": "PASS"},
                "b_floor_after_checkpoint": {"status": "PASS"},
            },
        )
        self.assertEqual(receipt["status"], "PASS")
        drifted = dict(observation)
        drifted["active_route_optimizer_sha256"] = "e" * 64
        with self.assertRaisesRegex(ValueError, "differs"):
            build_resume_equivalence_receipt(
                identity=self._identity(), checkpoint_manifest_sha256="c" * 64,
                checkpoint_serialized_bytes=1024, counter_receipt_sha256="d" * 64,
                checkpoint_cursor=checkpoint_cursor,
                uninterrupted=observation, resumed=drifted,
                runtime_custody={
                    "b_floor_at_start": {"status": "PASS"},
                    "b_floor_after_checkpoint": {"status": "PASS"},
                },
            )

    def test_active_route_digests_cover_shared_audio_and_optimizer_state(self) -> None:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=2, attention_heads=4, vocab_size=64,
        )
        model = __import__("model").UnifiedDecoder(config, genesis_seed=1413)
        model._activate_expert("audio")
        before = active_route_parameter_sha256(model)
        all_before = all_parameter_sha256(model)
        with torch.no_grad():
            next(
                parameter for name, parameter in model.named_parameters()
                if ".experts.reasoning." in name
            ).add_(1)
        self.assertEqual(before, active_route_parameter_sha256(model))
        self.assertNotEqual(all_before, all_parameter_sha256(model))
        selected = [
            parameter for name, parameter in model.named_parameters()
            if ".experts." not in name or ".experts.audio." in name
        ]
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        for parameter in selected:
            parameter.grad = torch.ones_like(parameter)
        optimizer.step()
        self.assertNotEqual(before, active_route_parameter_sha256(model))
        self.assertEqual(len(active_route_optimizer_sha256(model, optimizer)), 64)


if __name__ == "__main__":
    unittest.main()
