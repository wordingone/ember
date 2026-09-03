# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed contracts for issue #1413 packed specialist census."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))

from model import RestartDecoderConfig
from packed_specialist_probe import build_packed_density_receipt, take_exact_pack


class PackedSpecialistProbeTests(unittest.TestCase):
    @staticmethod
    def _selection(records: list[dict[str, object]]):
        class Selection:
            receipt = {
                "schema_version": "ember-owned-specialist-stream-selection-receipt-v1",
                "capability": "audio", "selection_rule_id": "all_records_semantic_pretraining_v1",
                "selected_record_count": len(records), "selected_token_count": sum(len(row["token_ids"]) for row in records),
            }

            def iter_from(self, cursor: object = None):
                start = 0 if cursor is None else int(cursor["next_source_index"])
                for index in range(start, len(records)):
                    yield records[index], {
                        "schema_version": "ember-owned-specialist-stream-selection-cursor-v1",
                        "selection_receipt_sha256": "a" * 64,
                        "selection_rule_id": "all_records_semantic_pretraining_v1",
                        "selected_ordinal": index + 1, "next_source_index": index + 1,
                    }
        return Selection()

    @staticmethod
    def _audio_record(config: RestartDecoderConfig, index: int) -> dict[str, object]:
        import base64
        tokens = [config.audio_token_id] * 4 + list(range(1, 12))
        return {
            "schema_version": "ember-owned-semantic-record-v1", "sample_id": f"audio-{index}",
            "active_expert": "audio", "token_ids": tokens, "target_ids": [*tokens[1:], 1],
            "image_patches_u8_base64": [],
            "audio_frames_i16le_base64": [base64.b64encode(bytes(1280)).decode()] * 4,
            "image_coordinates": [],
            "multimodal_spans": [{"start": 0, "length": 4, "modality": "audio", "attention_mode": "causal"}],
        }

    def test_exact_audio64_pack_and_density_receipt_bind_true_tokens(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        records = [self._audio_record(config, index) for index in range(64)]
        selection = self._selection(records)
        pack, end_cursor = take_exact_pack(selection, cursor=None, pack_records=64)
        receipt = build_packed_density_receipt(
            selection_receipt=selection.receipt, records=pack, end_cursor=end_cursor,
            batch_shape={"record_count": 64, "true_source_tokens": 960, "processed_padded_tokens": 960, "padding_tokens": 0, "record_order_sha256": "b" * 64, "tokens_sha256": "c" * 64, "pack_signature_sha256": "d" * 64},
            source_commit="e" * 40, stream_manifest_sha256="f" * 64,
            stream_build_receipt_sha256="1" * 64, model_config_sha256="2" * 64,
        )
        self.assertEqual(receipt["fixed_shape"], {"capability": "audio", "pack_records": 64, "tokens_per_record": 15})
        self.assertEqual(receipt["true_source_tokens"], 960)
        self.assertEqual(receipt["max_step_seconds_for_1000_true_tps"], 0.96)
        unsigned = dict(receipt)
        claimed = unsigned.pop("self_sha256")
        self.assertEqual(claimed, hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest())

    def test_density_receipt_refuses_padding_or_non_audio64_shape(self) -> None:
        records = [{"token_ids": [1] * 15}] * 64
        kwargs = {
            "selection_receipt": {"capability": "audio", "selection_rule_id": "all_records_semantic_pretraining_v1"},
            "records": records, "end_cursor": {"selected_ordinal": 64}, "source_commit": "e" * 40,
            "stream_manifest_sha256": "f" * 64, "stream_build_receipt_sha256": "1" * 64,
            "model_config_sha256": "2" * 64,
        }
        with self.assertRaisesRegex(ValueError, "zero-padding audio-64"):
            build_packed_density_receipt(batch_shape={"record_count": 64, "true_source_tokens": 959, "processed_padded_tokens": 960, "padding_tokens": 1, "record_order_sha256": "b" * 64, "tokens_sha256": "c" * 64, "pack_signature_sha256": "d" * 64}, **kwargs)
        with self.assertRaisesRegex(ValueError, "zero-padding audio-64"):
            build_packed_density_receipt(batch_shape={"record_count": 32, "true_source_tokens": 480, "processed_padded_tokens": 480, "padding_tokens": 0, "record_order_sha256": "b" * 64, "tokens_sha256": "c" * 64, "pack_signature_sha256": "d" * 64}, **kwargs)


if __name__ == "__main__":
    unittest.main()
