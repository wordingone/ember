# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Acceptance tests for independently verified routed multimodal pretraining."""

from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from model import RestartDecoderConfig, UnifiedDecoder
from pretrain import run_pretraining_segment
from verify_capability_record import expected_receipt


class PretrainingSegmentTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
