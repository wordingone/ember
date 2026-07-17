# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Executable semantic-training-data verifier regressions."""

from __future__ import annotations

import hashlib
import base64
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "tools" / "ember-restart-3b" / "verify_training_data.py"
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))
from verify_capability_record import expected_receipt


def _write_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_generator(root: Path) -> str:
    path = root / "generator.py"
    path.write_text("# owned semantic generator fixture\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()

class TrainingDataVerifierTests(unittest.TestCase):
    def test_text_verify_uses_one_byte_snapshot_per_authority_artifact(self) -> None:
        """The receipt must describe the exact bytes parsed for every bound input."""
        import verify_training_data

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tokenizer = root / "tokenizer.json"
            tokenizer_hash = _write_json(tokenizer, {"model": {"vocab": {"token-0": 0, "token-1": 1, "token-2": 2, "token-3": 3}}})
            source = root / "source.json"
            source_hash = _write_json(source, {"schema_version": "ember-owned-source-v1", "capability": "text", "model_mediated": False, "borrowed_labels": False})
            records = root / "records.json"
            records_hash = _write_json(records, {"schema_version": "ember-owned-semantic-records-v1", "records": [{"token_ids": [0, 1, 2], "target_ids": [1, 2, 3]}]})
            data = root / "data.json"
            data_sha256 = _write_json(data, {"schema_version": "ember-owned-training-data-v1", "capability": "text", "data_class": "SEMANTIC_PRETRAINING", "tokenizer_sha256": tokenizer_hash, "model_mediated": False, "borrowed_labels": False, "record_count": 1, "token_count": 3, "source_manifest": {"path": "source.json", "sha256": source_hash}, "records_artifact": {"path": "records.json", "sha256": records_hash}})
            tracked = {path.resolve() for path in (data, tokenizer, source, records, Path(verify_training_data.__file__))}
            original_bytes, original_text = Path.read_bytes, Path.read_text
            reads: dict[Path, int] = {}

            def read_bytes_once(path: Path, *args: object, **kwargs: object) -> bytes:
                resolved = path.resolve()
                if resolved in tracked:
                    reads[resolved] = reads.get(resolved, 0) + 1
                return original_bytes(path, *args, **kwargs)

            def reject_authority_text(path: Path, *args: object, **kwargs: object) -> str:
                if path.resolve() in tracked:
                    raise AssertionError("authority bytes must be parsed from their one read snapshot")
                return original_text(path, *args, **kwargs)

            with patch.object(Path, "read_bytes", new=read_bytes_once), patch.object(Path, "read_text", new=reject_authority_text):
                receipt = verify_training_data.verify(data, tokenizer, "text", root=root)
        self.assertEqual(reads, {path: 1 for path in tracked})
        self.assertEqual(receipt["data_manifest_sha256"], data_sha256)
        from checkpoint_artifacts import SPECIALIST_VERIFICATION_FIELDS

        self.assertEqual(
            set(receipt) | {"runtime_semantic_model_contract_sha256"},
            SPECIALIST_VERIFICATION_FIELDS,
        )

    def test_audio_manifest_rejects_raw_frames_with_fabricated_caption_target(self) -> None:
        from tokenizers import Tokenizer, models, pre_tokenizers
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generator_hash = _write_generator(root); tokenizer = root / "tokenizer.json"
            frozen = Tokenizer(models.WordLevel({**{"<unk>": 0, "audio": 1, "signal": 2, "has": 3, "positive": 4, "negative": 5, "silent": 6, "frames": 7, "0": 8}, **{f"token-{index}": index for index in range(9, 32_000)}}, unk_token="<unk>")); frozen.pre_tokenizer = pre_tokenizers.Whitespace(); frozen.save(str(tokenizer)); tokenizer_hash = hashlib.sha256(tokenizer.read_bytes()).hexdigest()
            config = root / "config.json"; config_hash = _write_json(config, {"model": {"vocab_size": 32_000, "image_projection": {"input_shape": [48, 48, 3]}, "audio_projection": {"frame_samples": 640}}})
            source = root / "source.json"; source_hash = _write_json(source, {"schema_version": "ember-owned-source-v1", "capability": "audio", "model_mediated": False, "borrowed_labels": False, "semantic_provenance": {"schema_version": "ember-owned-semantic-source-v1", "origin": "owned_raw_samples", "target_derivation": "raw_audio_signal_execution", "source_description": "Owned PCM signal generator with labels recomputed from raw samples.", "minimum_record_count": 4096, "minimum_token_count": 24576, "generator": {"path": "generator.py", "sha256": generator_hash}}})
            raw = base64.b64encode(b"\x00" * (640 * 2)).decode("ascii")
            record = {"active_expert": "audio", "token_ids": [31_999, 1], "target_ids": [1, 2], "audio_frames_i16le_base64": [raw], "image_coordinates": [], "multimodal_spans": [{"start": 0, "length": 1, "modality": "audio", "attention_mode": "causal"}], "target_text": "fabricated label", "capability_evidence": {"audio": {"caption_sha256": "0" * 64, "derivation": "raw_audio_signal_execution"}}}
            records = root / "records.json"; records_hash = _write_json(records, {"schema_version": "ember-owned-semantic-records-v1", "records": [record]})
            data = root / "data.json"; _write_json(data, {"schema_version": "ember-owned-training-data-v1", "capability": "audio", "data_class": "SEMANTIC_PRETRAINING", "tokenizer_sha256": tokenizer_hash, "model_mediated": False, "borrowed_labels": False, "record_count": 1, "token_count": 2, "model_config": {"path": "config.json", "sha256": config_hash}, "source_manifest": {"path": "source.json", "sha256": source_hash}, "records_artifact": {"path": "records.json", "sha256": records_hash}})
            completed = subprocess.run([sys.executable, str(VERIFIER), "--data-manifest", str(data), "--tokenizer", str(tokenizer), "--capability", "audio"], cwd=root, text=True, capture_output=True, timeout=15, check=False)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("locally derived raw-signal caption", completed.stderr)
    def test_image_manifest_rejects_raw_patch_with_fabricated_caption_target(self) -> None:
        from tokenizers import Tokenizer, models, pre_tokenizers

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generator_hash = _write_generator(root)
            tokenizer = root / "tokenizer.json"
            frozen = Tokenizer(models.WordLevel({**{"<unk>": 0, "image": 1, "scene": 2, "has": 3, "red": 4, "green": 5, "blue": 6, "squares": 7, "0": 8}, **{f"token-{index}": index for index in range(9, 32_000)}}, unk_token="<unk>"))
            frozen.pre_tokenizer = pre_tokenizers.Whitespace()
            frozen.save(str(tokenizer))
            tokenizer_hash = hashlib.sha256(tokenizer.read_bytes()).hexdigest()
            config = root / "config.json"
            config_hash = _write_json(config, {"model": {"vocab_size": 32_000, "image_projection": {"input_shape": [48, 48, 3]}, "audio_projection": {"frame_samples": 640}}})
            source = root / "source.json"
            source_hash = _write_json(source, {"schema_version": "ember-owned-source-v1", "capability": "image", "model_mediated": False, "borrowed_labels": False, "semantic_provenance": {"schema_version": "ember-owned-semantic-source-v1", "origin": "owned_raw_samples", "target_derivation": "raw_image_property_execution", "source_description": "Owned RGB scene generator with labels recomputed from raw pixels.", "minimum_record_count": 4096, "minimum_token_count": 24576, "generator": {"path": "generator.py", "sha256": generator_hash}}})
            raw = base64.b64encode(bytes(48 * 48 * 3)).decode("ascii")
            record = {"active_expert": "vision", "token_ids": [31_998, 31_998, 31_998, 31_998, 1], "target_ids": [31_998, 31_998, 31_998, 1, 2], "image_patches_u8_base64": [raw, raw, raw, raw], "image_coordinates": [[0, 0], [1, 0], [0, 1], [1, 1]], "multimodal_spans": [{"start": 0, "length": 4, "modality": "image", "attention_mode": "isolated"}], "target_text": "fabricated label", "capability_evidence": {"image": {"caption_sha256": "0" * 64, "derivation": "raw_image_property_execution"}}}
            records = root / "records.json"
            records_hash = _write_json(records, {"schema_version": "ember-owned-semantic-records-v1", "records": [record]})
            data = root / "data.json"
            _write_json(data, {"schema_version": "ember-owned-training-data-v1", "capability": "image", "data_class": "SEMANTIC_PRETRAINING", "tokenizer_sha256": tokenizer_hash, "model_mediated": False, "borrowed_labels": False, "record_count": 1, "token_count": 5, "model_config": {"path": "config.json", "sha256": config_hash}, "source_manifest": {"path": "source.json", "sha256": source_hash}, "records_artifact": {"path": "records.json", "sha256": records_hash}})
            completed = subprocess.run([sys.executable, str(VERIFIER), "--data-manifest", str(data), "--tokenizer", str(tokenizer), "--capability", "image"], cwd=root, text=True, capture_output=True, timeout=15, check=False)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("locally derived raw-scene caption", completed.stderr)

    def test_specialist_manifest_rejects_smoke_sized_or_unqualified_source(self) -> None:
        """A deterministic one-row patch is a fixture, never specialist pretraining."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generator_hash = _write_generator(root)
            tokenizer = root / "tokenizer.json"
            tokenizer_hash = _write_json(
                tokenizer,
                {"model": {"vocab": {f"token-{index}": index for index in range(32_000)}}},
            )
            config = root / "config.json"
            config_hash = _write_json(
                config,
                {"model": {"vocab_size": 32_000, "image_projection": {"input_shape": [48, 48, 3]}, "audio_projection": {"frame_samples": 640}}},
            )
            source = root / "sources" / "image.json"
            source_hash = _write_json(
                source,
                {
                    "schema_version": "ember-owned-source-v1",
                    "capability": "image",
                    "model_mediated": False,
                    "borrowed_labels": False,
                },
            )
            records = root / "records" / "image.json"
            records_hash = _write_json(
                records,
                {"schema_version": "ember-owned-semantic-records-v1", "records": []},
            )
            data = root / "data" / "image.json"
            _write_json(
                data,
                {
                    "schema_version": "ember-owned-training-data-v1",
                    "capability": "image",
                    "data_class": "SEMANTIC_PRETRAINING",
                    "tokenizer_sha256": tokenizer_hash,
                    "model_mediated": False,
                    "borrowed_labels": False,
                    "record_count": 1,
                    "token_count": 3,
                    "model_config": {"path": "config.json", "sha256": config_hash},
                    "source_manifest": {"path": "sources/image.json", "sha256": source_hash},
                    "records_artifact": {"path": "records/image.json", "sha256": records_hash},
                },
            )
            completed = subprocess.run(
                [sys.executable, str(VERIFIER), "--data-manifest", str(data), "--tokenizer", str(tokenizer), "--capability", "image"],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("semantic source", completed.stderr)
    def test_specialist_manifest_requires_content_addressed_generator_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generator_hash = _write_generator(root)
            tokenizer = root / "tokenizer.json"
            tokenizer_hash = _write_json(tokenizer, {"model": {"vocab": {f"token-{index}": index for index in range(32_000)}}})
            config = root / "config.json"
            config_hash = _write_json(config, {"model": {"vocab_size": 32_000, "image_projection": {"input_shape": [48, 48, 3]}, "audio_projection": {"frame_samples": 640}}})
            source = root / "source.json"
            source_hash = _write_json(source, {"schema_version": "ember-owned-source-v1", "capability": "image", "model_mediated": False, "borrowed_labels": False, "semantic_provenance": {"schema_version": "ember-owned-semantic-source-v1", "origin": "owned_raw_samples", "target_derivation": "raw_image_property_execution", "source_description": "Owned RGB source deliberately omits a content-addressed generator binding.", "minimum_record_count": 4096, "minimum_token_count": 24576}})
            records = root / "records.json"
            records_hash = _write_json(records, {"schema_version": "ember-owned-semantic-records-v1", "records": []})
            data = root / "data.json"
            _write_json(data, {"schema_version": "ember-owned-training-data-v1", "capability": "image", "data_class": "SEMANTIC_PRETRAINING", "tokenizer_sha256": tokenizer_hash, "model_mediated": False, "borrowed_labels": False, "record_count": 0, "token_count": 0, "model_config": {"path": "config.json", "sha256": config_hash}, "source_manifest": {"path": "source.json", "sha256": source_hash}, "records_artifact": {"path": "records.json", "sha256": records_hash}})
            completed = subprocess.run([sys.executable, str(VERIFIER), "--data-manifest", str(data), "--tokenizer", str(tokenizer), "--capability", "image"], cwd=root, text=True, capture_output=True, timeout=15, check=False)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("generator", completed.stderr)
    def test_text_semantic_manifest_is_recomputed_from_bound_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generator_hash = _write_generator(root)
            tokenizer = root / "tokenizer.json"
            tokenizer_hash = _write_json(
                tokenizer,
                {"model": {"vocab": {f"token-{index}": index for index in range(8, 32)}}},
            )
            source = root / "sources" / "text.json"
            source_hash = _write_json(
                source,
                {
                    "schema_version": "ember-owned-source-v1",
                    "capability": "text",
                    "model_mediated": False,
                    "borrowed_labels": False,
                },
            )
            records = root / "records" / "text.json"
            records_hash = _write_json(
                records,
                {
                    "schema_version": "ember-owned-semantic-records-v1",
                    "records": [{"token_ids": [8, 9, 10], "target_ids": [9, 10, 11]}],
                },
            )
            data = root / "data" / "text.json"
            _write_json(
                data,
                {
                    "schema_version": "ember-owned-training-data-v1",
                    "capability": "text",
                    "data_class": "SEMANTIC_PRETRAINING",
                    "tokenizer_sha256": tokenizer_hash,
                    "model_mediated": False,
                    "borrowed_labels": False,
                    "record_count": 1,
                    "token_count": 3,
                    "source_manifest": {"path": "sources/text.json", "sha256": source_hash},
                    "records_artifact": {"path": "records/text.json", "sha256": records_hash},
                },
            )
            completed = subprocess.run(
                [sys.executable, str(VERIFIER), "--data-manifest", str(data), "--tokenizer", str(tokenizer), "--capability", "text"],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        receipt = json.loads(completed.stdout)
        self.assertEqual(receipt["result"], "VERIFIED")
        self.assertEqual(receipt["capability"], "text")
        self.assertEqual(receipt["semantic_checks"], ["token_roundtrip", "source_target_pair"])
        self.assertEqual(receipt["record_count"], 1)
        self.assertEqual(receipt["token_count"], 3)
    def test_reasoning_semantic_manifest_executes_local_receipt(self) -> None:
        from tokenizers import Tokenizer, models, pre_tokenizers
        from build_owned_reasoning_tool_trajectories import build_records
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generator_hash = _write_generator(root)
            tokenizer = root / "tokenizer.json"
            frozen = Tokenizer(models.WordLevel({"<unk>": 0, "reasoning": 1, "sum": 2, "plus": 3, "equals": 4, **{str(index): index + 5 for index in range(2048)}}, unk_token="<unk>"))
            frozen.pre_tokenizer = pre_tokenizers.Whitespace()
            frozen.save(str(tokenizer))
            token_hash = hashlib.sha256(tokenizer.read_bytes()).hexdigest()
            source = root / "source.json"
            source_hash = _write_json(source, {"schema_version": "ember-owned-source-v1", "capability": "reasoning", "model_mediated": False, "borrowed_labels": False, "semantic_provenance": {"schema_version": "ember-owned-semantic-source-v1", "origin": "owned_raw_samples", "target_derivation": "local_answer_execution", "source_description": "Owned arithmetic trajectory generator with independently executed sums.", "minimum_record_count": 4096, "minimum_token_count": 24576, "generator": {"path": "generator.py", "sha256": generator_hash}}})
            records = root / "records.json"
            records_list = build_records(frozen, count=4_096, capability="reasoning")
            records_hash = _write_json(records, {"schema_version": "ember-owned-semantic-records-v1", "records": records_list})
            data = root / "data.json"
            _write_json(data, {"schema_version": "ember-owned-training-data-v1", "capability": "reasoning", "data_class": "SEMANTIC_PRETRAINING", "tokenizer_sha256": token_hash, "model_mediated": False, "borrowed_labels": False, "record_count": len(records_list), "token_count": sum(len(record["token_ids"]) for record in records_list), "source_manifest": {"path": "source.json", "sha256": source_hash}, "records_artifact": {"path": "records.json", "sha256": records_hash}})
            completed = subprocess.run([sys.executable, str(VERIFIER), "--data-manifest", str(data), "--tokenizer", str(tokenizer), "--capability", "reasoning"], cwd=root, text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["semantic_checks"], ["token_roundtrip", "source_target_pair", "local_answer_execution"])
    def test_reasoning_manifest_rejects_target_ids_not_encoded_from_frozen_transcript(self) -> None:
        from tokenizers import Tokenizer, models, pre_tokenizers
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generator_hash = _write_generator(root)
            tokenizer = root / "tokenizer.json"
            vocabulary = {"<unk>": 0, "reasoning": 1, "sum": 2, "plus": 3, "equals": 4, "1": 5, "2": 6, "3": 7}
            frozen = Tokenizer(models.WordLevel(vocabulary, unk_token="<unk>"))
            frozen.pre_tokenizer = pre_tokenizers.Whitespace()
            frozen.save(str(tokenizer))
            tokenizer_hash = hashlib.sha256(tokenizer.read_bytes()).hexdigest()
            source = root / "source.json"
            source_hash = _write_json(source, {"schema_version": "ember-owned-source-v1", "capability": "reasoning", "model_mediated": False, "borrowed_labels": False, "semantic_provenance": {"schema_version": "ember-owned-semantic-source-v1", "origin": "owned_raw_samples", "target_derivation": "local_answer_execution", "source_description": "Owned arithmetic trajectories whose targets are executed locally from operands.", "minimum_record_count": 4096, "minimum_token_count": 24576, "generator": {"path": "generator.py", "sha256": generator_hash}}})
            transcript = "reasoning sum 1 plus 2 equals 3"
            encoded = list(frozen.encode(transcript).ids)
            forged = [0] * 33
            records_list = []
            for index in range(128):
                record = {"schema_version": "ember-owned-semantic-record-v1", "sample_id": f"owned-reasoning-{index:08d}", "token_ids": forged[:-1], "target_ids": forged[1:], "target_text": transcript, "active_expert": "reasoning", "capability_evidence": {"reasoning": {"operands": [1, 2], "target": 3, "trace": [1, 2, 3]}}, "image_coordinates": [], "multimodal_spans": []}
                record["capability_receipt"] = expected_receipt(record)
                records_list.append(record)
            records = root / "records.json"
            records_hash = _write_json(records, {"schema_version": "ember-owned-semantic-records-v1", "records": records_list})
            data = root / "data.json"
            _write_json(data, {"schema_version": "ember-owned-training-data-v1", "capability": "reasoning", "data_class": "SEMANTIC_PRETRAINING", "tokenizer_sha256": tokenizer_hash, "model_mediated": False, "borrowed_labels": False, "record_count": 128, "token_count": len(forged[:-1]) * 128, "source_manifest": {"path": "source.json", "sha256": source_hash}, "records_artifact": {"path": "records.json", "sha256": records_hash}})
            completed = subprocess.run([sys.executable, str(VERIFIER), "--data-manifest", str(data), "--tokenizer", str(tokenizer), "--capability", "reasoning"], cwd=root, text=True, capture_output=True, timeout=30, check=False)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("frozen tokenizer", completed.stderr)


if __name__ == "__main__":
    unittest.main()
