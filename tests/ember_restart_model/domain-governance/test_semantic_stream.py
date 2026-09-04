# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Manifest-bound owned token-stream regression tests."""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))

from batch import decode_owned_batch
from model import RestartDecoderConfig, UnifiedDecoder
from pretrain import run_manifest_bound_semantic_segment, run_pretraining_segment
from semantic_stream import ManifestBoundTokenStream


class SemanticStreamTests(unittest.TestCase):
    def _receipt(self, root: Path, shard_tokens: list[list[int]]) -> tuple[Path, Path, Path]:
        tokenizer = root / "tokenizer.json"
        vocab = {f"token-{index}": index for index in range(8, 1025)}
        tokenizer.write_text(json.dumps({"model": {"vocab": vocab}}, sort_keys=True), encoding="utf-8")
        shards = []
        for index, tokens in enumerate(shard_tokens):
            shard = root / f"v0-{index:05d}.bin"
            shard.write_bytes(struct.pack(f"<{len(tokens)}H", *tokens))
            shards.append({"name": shard.name, "sha256": hashlib.sha256(shard.read_bytes()).hexdigest(), "n_tokens": len(tokens)})
        receipt = {
            "ticket": "TOKEN-SHARDS-V0", "shards": shards,
            "total_stream_tokens": sum(item["n_tokens"] for item in shards),
            "reserved_band_guard": {"max_id_lt": 32},
            "premises": {"tokenizer_json": {"path": tokenizer.name, "sha256": hashlib.sha256(tokenizer.read_bytes()).hexdigest()}},
        }
        receipt_path = root / "token-shards-v0.json"
        receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
        return receipt_path, root, tokenizer

    def test_emits_receipt_and_tokenizer_bound_shared_next_token_episode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, shards_root, tokenizer = self._receipt(root, [[0x0102, 0x0304, 10, 11, 12, 13]])
            stream = ManifestBoundTokenStream.from_receipt(receipt_path=receipt, shards_root=shards_root, tokenizer_path=tokenizer)
            expected_receipt_sha256 = hashlib.sha256(receipt.read_bytes()).hexdigest()
            expected_tokenizer_sha256 = hashlib.sha256(tokenizer.read_bytes()).hexdigest()
            episode, cursor = stream.next_episode(shard_index=0, token_offset=0, sequence_length=4)
        self.assertEqual(episode["active_expert"], "shared")
        self.assertEqual(episode["token_ids"], [0x0102, 0x0304, 10, 11])
        self.assertEqual(episode["target_ids"], [0x0304, 10, 11, 12])
        self.assertEqual(cursor, {"shard_index": 0, "token_offset": 4, "tokens_seen": 4})
        self.assertEqual(stream.receipt_sha256, expected_receipt_sha256)
        self.assertEqual(stream.tokenizer_sha256, expected_tokenizer_sha256)

    def test_shared_stream_record_decodes_and_updates_only_shared_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, shards_root, tokenizer = self._receipt(root, [[8, 9, 10, 11, 12, 13]])
            episode, _ = ManifestBoundTokenStream.from_receipt(receipt_path=receipt, shards_root=shards_root, tokenizer_path=tokenizer).next_episode(shard_index=0, token_offset=0, sequence_length=4)
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        batch = decode_owned_batch(episode, config, device=torch.device("cpu"))
        self.assertEqual(batch["active_expert"], "shared")
        model = UnifiedDecoder(config, genesis_seed=43)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        experts_before = {name: parameter.detach().clone() for name, parameter in model.named_parameters() if ".experts." in name}
        result = run_pretraining_segment(model=model, optimizer=optimizer, records=[episode], config=config, device=torch.device("cpu"), checkpoint_every=1, checkpoint_callback=lambda _step, _result: None, require_complete_coverage=False)
        self.assertEqual(result["expert_examples"], {"vision": 0, "audio": 0, "reasoning": 0, "tool": 0})
        self.assertTrue(all(torch.equal(parameter.detach(), experts_before[name]) for name, parameter in model.named_parameters() if ".experts." in name))

    def test_rejects_a_shard_whose_bytes_no_longer_match_the_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, shards_root, tokenizer = self._receipt(root, [[8, 9, 10, 11, 12, 13]])
            (shards_root / "v0-00000.bin").write_bytes(struct.pack("<6H", 8, 9, 10, 11, 12, 14))
            with self.assertRaisesRegex(ValueError, "sha256"):
                ManifestBoundTokenStream.from_receipt(receipt_path=receipt, shards_root=shards_root, tokenizer_path=tokenizer)

    def test_rejects_tokenizer_bytes_that_do_not_match_the_receipt_premise(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, shards_root, tokenizer = self._receipt(root, [[8, 9, 10, 11, 12, 13]])
            tokenizer.write_text('{"model":{"vocab":{}}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "tokenizer sha256"):
                ManifestBoundTokenStream.from_receipt(receipt_path=receipt, shards_root=shards_root, tokenizer_path=tokenizer)

    def test_rolls_deterministically_into_the_next_receipt_bound_shard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, shards_root, tokenizer = self._receipt(root, [[8, 9, 10], [11, 12, 13]])
            stream = ManifestBoundTokenStream.from_receipt(receipt_path=receipt, shards_root=shards_root, tokenizer_path=tokenizer)
            expected_receipt_sha256 = hashlib.sha256(receipt.read_bytes()).hexdigest()
            expected_tokenizer_sha256 = hashlib.sha256(tokenizer.read_bytes()).hexdigest()
            episode, cursor = stream.next_episode(shard_index=0, token_offset=0, sequence_length=4)
        self.assertEqual(episode["token_ids"], [8, 9, 10, 11])
        self.assertEqual(episode["target_ids"], [9, 10, 11, 12])
        self.assertEqual(cursor, {"shard_index": 1, "token_offset": 1, "tokens_seen": 4})


    def test_progress_callback_is_forwarded_through_the_semantic_segment(self) -> None:
        """Issue #1719 blocker 1: the semantic path is the only >=100-contiguous-step-capable
        mode, but run_manifest_bound_semantic_segment never forwarded a progress_callback to
        its own inner run_pretraining_segment call -- per-step loss/grad-norm (R1-E1/R1-E2)
        was architecturally unreachable from this path even though the shared primitive
        already supports it.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, shards_root, tokenizer = self._receipt(root, [[8, 9, 10, 11, 12, 13, 14]])
            stream = ManifestBoundTokenStream.from_receipt(receipt_path=receipt, shards_root=shards_root, tokenizer_path=tokenizer)
            config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
            model = UnifiedDecoder(config, genesis_seed=53)
            optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
            progress: list[dict[str, object]] = []
            run_manifest_bound_semantic_segment(
                model=model, optimizer=optimizer, stream=stream, config=config, device=torch.device("cpu"),
                sequence_length=2, steps=2, checkpoint_every=2,
                checkpoint_callback=lambda _step, _state: None,
                progress_callback=progress.append,
            )
        self.assertEqual([event["step"] for event in progress], [1, 2])
        self.assertTrue(all(isinstance(event["loss"], float) for event in progress))
        self.assertTrue(all(isinstance(event["grad_norm"], float) and event["grad_norm"] > 0.0 for event in progress))

    def test_segment_carries_receipt_bound_shard_cursor_into_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, shards_root, tokenizer = self._receipt(root, [[8, 9, 10, 11, 12, 13, 14]])
            stream = ManifestBoundTokenStream.from_receipt(
                receipt_path=receipt, shards_root=shards_root, tokenizer_path=tokenizer
            )
            config = RestartDecoderConfig.small_for_tests(
                hidden_size=32, layers=2, attention_heads=4, vocab_size=64
            )
            model = UnifiedDecoder(config, genesis_seed=47)
            optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
            checkpoints: list[dict[str, object]] = []
            result = run_manifest_bound_semantic_segment(
                model=model,
                optimizer=optimizer,
                stream=stream,
                config=config,
                device=torch.device("cpu"),
                sequence_length=2,
                steps=2,
                checkpoint_every=1,
                checkpoint_callback=lambda _step, state: checkpoints.append(state),
            )
        self.assertEqual(result["steps"], 2)
        self.assertEqual(result["tokens_seen"], 4)
        self.assertEqual(result["expert_examples"], {"vision": 0, "audio": 0, "reasoning": 0, "tool": 0})
        self.assertEqual(result["data_cursor"]["shard"], "TOKEN-SHARDS-V0:" + stream.receipt_sha256[:12])
        self.assertEqual(result["data_cursor"]["record_index"], 2)
        self.assertEqual(
            result["data_cursor"],
            {"shard": "TOKEN-SHARDS-V0:" + stream.receipt_sha256[:12], "record_index": 2, "receipt_sha256": stream.receipt_sha256, "tokenizer_sha256": stream.tokenizer_sha256, "shard_index": 0, "token_offset": 4, "global_step": 2, "tokens_seen": 4},
        )
    def test_resume_cursor_rejects_declared_identity_or_counter_drift_before_training(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, shards_root, tokenizer = self._receipt(root, [[8, 9, 10, 11, 12, 13, 14]])
            stream = ManifestBoundTokenStream.from_receipt(receipt_path=receipt, shards_root=shards_root, tokenizer_path=tokenizer)
            baseline = {
                "shard": "TOKEN-SHARDS-V0:" + stream.receipt_sha256[:12],
                "record_index": 1,
                "receipt_sha256": stream.receipt_sha256,
                "tokenizer_sha256": stream.tokenizer_sha256,
                "shard_index": 0,
                "token_offset": 2,
                "global_step": 1,
                "tokens_seen": 2,
            }
            for field, value in (("shard", "TOKEN-SHARDS-V0:wrong"), ("record_index", 0), ("global_step", 0), ("tokens_seen", 0)):
                cursor = dict(baseline)
                cursor[field] = value
                with self.assertRaisesRegex(ValueError, "semantic stream resume cursor identity"):
                    run_manifest_bound_semantic_segment(
                        model=object(), optimizer=object(), stream=stream, config=object(), device=torch.device("cpu"),
                        sequence_length=2, steps=1, checkpoint_every=1, checkpoint_callback=lambda _step, _state: None,
                        initial_data_cursor=cursor, initial_global_step=1, initial_tokens_seen=2,
                    )
    def test_interrupted_resume_uses_each_receipt_bound_episode_once_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, shards_root, tokenizer = self._receipt(root, [[8, 9, 10, 11, 12, 13, 14]])
            stream = ManifestBoundTokenStream.from_receipt(receipt_path=receipt, shards_root=shards_root, tokenizer_path=tokenizer)
            config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)

            def train(model: UnifiedDecoder, optimizer: torch.optim.Optimizer, *, steps: int, cursor: dict[str, object] | None = None, initial_step: int = 0, initial_tokens: int = 0) -> tuple[list[list[int]], dict[str, object]]:
                observed: list[list[int]] = []
                original_forward = model.forward

                def forward(input_ids: torch.Tensor, **kwargs: object) -> torch.Tensor:
                    observed.extend(input_ids.detach().cpu().tolist())
                    return original_forward(input_ids, **kwargs)

                model.forward = forward  # type: ignore[method-assign]
                checkpoints: list[dict[str, object]] = []
                result = run_manifest_bound_semantic_segment(
                    model=model, optimizer=optimizer, stream=stream, config=config, device=torch.device("cpu"),
                    sequence_length=2, steps=steps, checkpoint_every=1,
                    checkpoint_callback=lambda _step, state: checkpoints.append(dict(state["data_cursor"])),
                    initial_data_cursor=cursor, initial_global_step=initial_step, initial_tokens_seen=initial_tokens,
                )
                self.assertEqual(checkpoints[-1], result["data_cursor"])
                return observed, result["data_cursor"]

            uninterrupted_model = UnifiedDecoder(config, genesis_seed=71)
            uninterrupted, uninterrupted_cursor = train(uninterrupted_model, torch.optim.AdamW(uninterrupted_model.parameters(), lr=1e-3), steps=3)

            first_model = UnifiedDecoder(config, genesis_seed=71)
            first_optimizer = torch.optim.AdamW(first_model.parameters(), lr=1e-3)
            first, cursor = train(first_model, first_optimizer, steps=1)
            resumed_model = UnifiedDecoder(config, genesis_seed=999)
            resumed_model.load_state_dict(first_model.state_dict())
            resumed_optimizer = torch.optim.AdamW(resumed_model.parameters(), lr=1e-3)
            resumed_optimizer.load_state_dict(first_optimizer.state_dict())
            remaining, resumed_cursor = train(
                resumed_model, resumed_optimizer, steps=2, cursor=cursor, initial_step=1, initial_tokens=2,
            )

        self.assertEqual(first + remaining, uninterrupted)
        self.assertEqual(first + remaining, [[8, 9], [10, 11], [12, 13]])
        self.assertEqual(resumed_cursor, uninterrupted_cursor)
