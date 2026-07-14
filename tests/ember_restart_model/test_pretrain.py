# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU-small acceptance for real, routed multimodal pretraining segments."""

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


class PretrainingSegmentTests(unittest.TestCase):
    def _record(
        self,
        config: RestartDecoderConfig,
        *,
        expert: str = "reasoning",
        sample_id: str = "owned-pretrain-0001",
    ) -> dict[str, object]:
        image = bytes(index % 251 for index in range(48 * 48 * 3))
        audio = (torch.arange(640, dtype=torch.int16) - 320).numpy().tobytes()
        return {
            "schema_version": "ember-owned-bootstrap-batch-v1",
            "sample_id": sample_id,
            "token_ids": [1, config.image_token_id, 2, config.audio_token_id],
            "target_ids": [2, 3, 4, 5],
            "image_u8_base64": base64.b64encode(image).decode("ascii"),
            "audio_i16le_base64": base64.b64encode(audio).decode("ascii"),
            "active_expert": expert,
            "image_coordinates": [[0, 0]],
            "multimodal_spans": [
                {"start": 1, "length": 1, "modality": "image", "attention_mode": "isolated"},
                {"start": 3, "length": 1, "modality": "audio", "attention_mode": "causal"},
            ],
            "capability_evidence": {
                "reasoning": {
                    "trace_token_ids": [11, 12],
                    "verified_target": {"kind": "integer_sum", "value": "3"},
                },
                "tool": {
                    "name": "owned_calculator",
                    "arguments": {"expression": "1+2"},
                    "observation": {"value": 3},
                },
            },
        }

    def _domain_records(self, config: RestartDecoderConfig) -> list[dict[str, object]]:
        return [
            self._record(config, expert=expert, sample_id=f"owned-pretrain-{expert}")
            for expert in ("vision", "audio", "reasoning", "tool")
        ]

    def test_complete_optimizer_updates_each_routed_expert_only_on_its_episode(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=23)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        self.assertEqual(
            {id(parameter) for group in optimizer.param_groups for parameter in group["params"]},
            {id(parameter) for parameter in model.parameters()},
        )
        for expert in ("vision", "audio", "reasoning", "tool"):
            before = {
                name: parameter.detach().clone()
                for name, parameter in model.named_parameters()
                if ".experts." in name
            }
            run_pretraining_segment(
                model=model,
                optimizer=optimizer,
                records=[self._record(config, expert=expert)],
                config=config,
                device=torch.device("cpu"),
                checkpoint_every=1,
                checkpoint_callback=lambda _step, _result: None,
                require_complete_coverage=False,
            )
            for name, parameter in model.named_parameters():
                if ".experts." not in name:
                    continue
                selected = f".experts.{expert}." in name
                self.assertEqual(not torch.equal(parameter.detach(), before[name]), selected, name)

    def test_segment_requires_all_capabilities_and_domain_experts(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=17)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        checkpoints: list[int] = []
        result = run_pretraining_segment(
            model=model,
            optimizer=optimizer,
            records=self._domain_records(config),
            config=config,
            device=torch.device("cpu"),
            checkpoint_every=1,
            checkpoint_callback=lambda step, _result: checkpoints.append(step),
        )
        self.assertEqual(result["steps"], 4)
        self.assertEqual(result["tokens_seen"], 16)
        self.assertEqual(
            result["modality_examples"],
            {"text": 4, "image": 4, "audio": 4, "reasoning": 4, "tool": 4},
        )
        self.assertEqual(result["expert_examples"], {"vision": 1, "audio": 1, "reasoning": 1, "tool": 1})
        self.assertEqual(checkpoints, [1, 2, 3, 4])
        self.assertTrue(all(torch.isfinite(torch.tensor(value)) for value in result["losses"]))

    def test_actual_bfloat16_pretraining_segment_normalizes_raw_modalities(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=31).to(dtype=torch.bfloat16)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        result = run_pretraining_segment(
            model=model,
            optimizer=optimizer,
            records=self._domain_records(config),
            config=config,
            device=torch.device("cpu"),
            checkpoint_every=4,
            checkpoint_callback=lambda _step, _result: None,
        )
        self.assertEqual(result["steps"], 4)
        self.assertTrue(all(torch.isfinite(torch.tensor(value)) for value in result["losses"]))
    def test_actual_pretraining_forwards_explicit_coordinates_and_isolated_spans(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=37)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        calls: list[tuple[torch.Tensor, object]] = []
        original_forward = model.forward

        def observed_forward(input_ids: torch.Tensor, *args: object, **kwargs: object) -> torch.Tensor:
            calls.append((kwargs["image_coordinates"], kwargs["spans"]))
            return original_forward(input_ids, *args, **kwargs)

        model.forward = observed_forward  # type: ignore[method-assign]
        run_pretraining_segment(
            model=model,
            optimizer=optimizer,
            records=self._domain_records(config),
            config=config,
            device=torch.device("cpu"),
            checkpoint_every=4,
            checkpoint_callback=lambda _step, _result: None,
        )
        self.assertEqual(len(calls), 4)
        for coordinates, spans in calls:
            self.assertTrue(torch.equal(coordinates, torch.tensor([[0, 0]])))
            self.assertEqual([(span.start, span.length, span.attention_mode) for span in spans], [(1, 1, "isolated"), (3, 1, "causal")])
    def test_rejects_missing_verified_reasoning_or_tool_semantics(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=29)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        record = self._record(config, expert="tool")
        record["capability_evidence"] = {"reasoning": {"trace_token_ids": []}}
        with self.assertRaisesRegex(ValueError, "tool"):
            run_pretraining_segment(
                model=model,
                optimizer=optimizer,
                records=[record],
                config=config,
                device=torch.device("cpu"),
                checkpoint_every=1,
                checkpoint_callback=lambda _step, _result: None,
            )


if __name__ == "__main__":
    unittest.main()