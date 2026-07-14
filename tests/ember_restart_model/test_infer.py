# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Prompt-only autoregressive inference regressions."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import torch
from tokenizers import Tokenizer, models, pre_tokenizers

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))
sys.path.insert(0, str(ROOT / "scripts"))
from model import RestartDecoderConfig

from infer import _prompt_batch, canonical_prediction_envelope, frozen_split_prompt, load_frozen_tokenizer, greedy_generate
from ember_restart.prediction_contract import validate_predictions


class _GreedyModel:
    def __init__(self, tokens: list[int], vocab_size: int = 32) -> None:
        self.tokens = iter(tokens)
        self.vocab_size = vocab_size
        self.inputs: list[list[int]] = []

    def __call__(self, input_ids: torch.Tensor, **_kwargs: object) -> torch.Tensor:
        self.inputs.append(input_ids.squeeze(0).tolist())
        next_token = next(self.tokens)
        logits = torch.full((1, input_ids.shape[1], self.vocab_size), -100.0)
        logits[0, -1, next_token] = 100.0
        return logits


class InferenceTests(unittest.TestCase):
    def test_frozen_tokenizer_encodes_split_prompt_decodes_answer_and_rejects_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tokenizer_path = root / "tokenizer.json"
            fixture = Tokenizer(models.WordLevel({"<unk>": 0, "hello": 1, "Ember": 2, "answer": 3}, unk_token="<unk>"))
            fixture.pre_tokenizer = pre_tokenizers.Whitespace()
            fixture.add_special_tokens(["<|endoftext|>"])
            fixture.save(str(tokenizer_path))
            tokenizer_sha256 = hashlib.sha256(tokenizer_path.read_bytes()).hexdigest()
            tokenizer = load_frozen_tokenizer(tokenizer_path, expected_sha256=tokenizer_sha256)
            split = root / "frozen-split.json"
            self.assertEqual(tokenizer.eos_token_ids, {4})
            split.write_text(json.dumps({"schema_version": "ember-owned-frozen-inference-split-v1", "tokenizer_sha256": tokenizer_sha256, "rows": [{"id": "row-1", "prompt": "hello Ember", "active_expert": "shared"}]}), encoding="utf-8")
            row_id, prompt = frozen_split_prompt(split, "row-1", tokenizer)
            self.assertEqual((row_id, prompt["active_expert"]), ("row-1", "shared"))
            self.assertEqual(tokenizer.decode(prompt["token_ids"]), "hello Ember")
            with self.assertRaisesRegex(ValueError, "tokenizer sha256"):
                frozen_split_prompt(split, "row-1", load_frozen_tokenizer(tokenizer_path, expected_sha256="0" * 64))
        envelope = canonical_prediction_envelope(
            checkpoint_manifest_sha256="a" * 64, model_config_sha256="b" * 64, tokenizer_sha256=tokenizer_sha256,
            inference_implementation_sha256="d" * 64, benchmark_id="fixture", benchmark_version="v1", capability="text",
            split_sha256="e" * 64, protocol_sha256="f" * 64, max_new_tokens=2, stop_token_ids=[3], row_id="row-1",
            input_sha256="1" * 64, generated_token_ids=tokenizer.encode(" answer"), stop_reason="eos", decoded_text=" answer",
        )
        self.assertEqual(envelope["rows"][0]["output"]["text"], " answer")
    def test_shared_prompt_decodes_without_target_ids_and_rejects_target_leakage(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        prompt = {"schema_version": "ember-owned-inference-prompt-v1", "id": "prompt-1", "active_expert": "shared", "token_ids": [8, 9, 10]}
        row_id, batch = _prompt_batch(prompt, config, device=torch.device("cpu"))
        self.assertEqual((row_id, batch["active_expert"], batch["input_ids"].tolist()), ("prompt-1", "shared", [[8, 9, 10]]))
        with self.assertRaisesRegex(ValueError, "rejects target_ids"):
            _prompt_batch({**prompt, "target_ids": [9, 10, 11]}, config, device=torch.device("cpu"))
    def test_greedy_generation_uses_only_prompt_then_appends_until_stop(self) -> None:
        model = _GreedyModel([7, 2])
        generated, reason = greedy_generate(
            model=model,
            prompt_ids=torch.tensor([[4, 5]]),
            model_kwargs={},
            max_new_tokens=4,
            stop_token_ids={2},
        )
        self.assertEqual(generated, [7, 2])
        self.assertEqual(reason, "eos")
        self.assertEqual(model.inputs, [[4, 5], [4, 5, 7]])

    def test_canonical_envelope_is_non_teacher_forced_and_contract_valid(self) -> None:
        envelope = canonical_prediction_envelope(
            checkpoint_manifest_sha256="a" * 64,
            model_config_sha256="b" * 64,
            tokenizer_sha256="c" * 64,
            inference_implementation_sha256="d" * 64,
            benchmark_id="fixture",
            benchmark_version="v1",
            capability="text",
            split_sha256="e" * 64,
            protocol_sha256="f" * 64,
            max_new_tokens=2,
            stop_token_ids=[2],
            row_id="prompt-1",
            input_sha256="1" * 64,
            generated_token_ids=[7, 2],
            stop_reason="eos",
            decoded_text="fixture answer",
        )
        self.assertIs(validate_predictions(envelope), envelope)
        self.assertFalse(envelope["decoding"]["teacher_forcing"])


if __name__ == "__main__":
    unittest.main()
