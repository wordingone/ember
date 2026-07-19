# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The trusted parameter counter must inspect checkpoint realization under -I."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from checkpoint_artifacts import load_checkpoint_artifacts
import parameter_counter
from specialist_stream import SELECTION_CURSOR_SCHEMA_VERSION, canonical_record_bytes
from model import RestartDecoderConfig, UnifiedDecoder
from checkpoint_fixture import write_checkpoint_artifacts





from parameter_counter import REALIZATION_RECEIPT_FIELDS, _CheckpointMetadataUnpickler, _StorageRef, _TensorTypeSentinel, _rebuild_tensor, _rebuild_tensor_from_type, execute_counter, main, validate_realization_receipt


class CounterCliTests(unittest.TestCase):
    def test_counter_reads_authority_snapshots_and_each_shard_once(self) -> None:
        """A realization receipt cannot hash one checkpoint revision and inspect another."""
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=71)
        model._activate_expert("shared")
        optimizer = torch.optim.AdamW((parameter for parameter in model.parameters() if parameter.requires_grad), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(json.dumps({"architecture_revision": "ember-sparse-3b-v2", "model": {"hidden_size": 32, "layers": 2, "attention_heads": 4, "vocab_size": 64, "tied_embeddings": True, "image_projection": {"input_shape": [48, 48, 3], "output_size": 32}, "audio_projection": {"frame_samples": 640, "output_size": 32}, "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]}}}), encoding="utf-8")
            write_checkpoint_artifacts(model, optimizer, root / "checkpoint", launch_seed=71, rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))}, data_cursor={"shard": "TOKEN-SHARDS-V0:test", "record_index": 0, "global_step": 0, "tokens_seen": 0}, model_config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(), contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes())
            manifest_path = root / "checkpoint" / "checkpoint-manifest.json"
            expected_subject = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            tracked = {path.resolve() for path in (config_path, manifest_path, *(root / "checkpoint" / name for name in ("shared.pt", "replay-state.pt", "expert-vision.pt", "expert-audio.pt", "expert-reasoning.pt", "expert-tool.pt")))}
            original_open, original_text = Path.open, Path.read_text
            opens: dict[Path, int] = {}

            def open_once(path: Path, *args: object, **kwargs: object):
                resolved = path.resolve()
                if resolved in tracked:
                    opens[resolved] = opens.get(resolved, 0) + 1
                return original_open(path, *args, **kwargs)

            def reject_authority_text(path: Path, *args: object, **kwargs: object) -> str:
                if path.resolve() in tracked:
                    raise AssertionError("counter must parse authority JSON from one byte snapshot")
                return original_text(path, *args, **kwargs)

            with patch.object(Path, "open", new=open_once), patch.object(Path, "read_text", new=reject_authority_text):
                receipt = execute_counter(model_config=config_path, checkpoint_manifest=manifest_path, active_expert="shared")
        self.assertEqual(receipt["subject_checkpoint_sha256"], expected_subject)
        self.assertEqual(opens, {path: 1 for path in tracked})
    def test_isolated_cli_rejects_corrupt_realization_and_reports_measurement(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=7)
        model._activate_expert("shared")
        optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_payload = {
                "architecture_revision": "ember-sparse-3b-v2",
                "model": {
                    "hidden_size": 32, "layers": 2, "attention_heads": 4, "vocab_size": 64,
                    "tied_embeddings": True,
                    "image_projection": {"input_shape": [48, 48, 3], "output_size": 32},
                    "audio_projection": {"frame_samples": 640, "output_size": 32},
                    "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]},
                },
            }
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
            write_checkpoint_artifacts(
                model, optimizer, root / "checkpoint", launch_seed=7,
                rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))},
                data_cursor={"shard": "owned-bootstrap-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                model_config_sha256=config_sha256, contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes(),
            )
            command = [
                sys.executable, "-I", str(ROOT / "tools" / "ember-restart-3b" / "parameter_counter.py"),
                "--model-config", str(config_path),
                "--checkpoint-manifest", str(root / "checkpoint" / "checkpoint-manifest.json"),
                "--active-expert", "shared",
            ]
            completed = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            measured = json.loads(completed.stdout)
            self.assertEqual(measured["result"], "MEASURED")
            self.assertEqual(measured["active_expert_ids"], ["shared"])
            self.assertRegex(measured["counter_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(measured["schema_version"], "ember-sparse-realization-receipt-v1")
            self.assertEqual(measured["verification_boundary"], "VERIFIED_MEASURED")
            self.assertEqual(measured["subject_checkpoint_sha256"], hashlib.sha256((root / "checkpoint" / "checkpoint-manifest.json").read_bytes()).hexdigest())
            self.assertEqual(measured["expert_parameter_sha256"], measured["expert_genesis_sha256"])
            self.assertEqual(set(measured), REALIZATION_RECEIPT_FIELDS)
            (root / "checkpoint" / "expert-tool.pt").write_bytes(b"corrupt")
            rejected = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("mismatch", rejected.stderr)


    def test_isolated_cli_measures_shared_semantic_path_without_specialist_bank(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=9)
        model._activate_expert("shared")
        optimizer = torch.optim.AdamW((parameter for parameter in model.parameters() if parameter.requires_grad), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_payload = {
                "architecture_revision": "ember-sparse-3b-v2",
                "model": {
                    "hidden_size": 32, "layers": 2, "attention_heads": 4, "vocab_size": 64,
                    "tied_embeddings": True,
                    "image_projection": {"input_shape": [48, 48, 3], "output_size": 32},
                    "audio_projection": {"frame_samples": 640, "output_size": 32},
                    "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]},
                },
            }
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
            write_checkpoint_artifacts(
                model, optimizer, root / "checkpoint", launch_seed=9,
                rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))},
                data_cursor={"shard": "TOKEN-SHARDS-V0:receipt", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                model_config_sha256=config_sha256, contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes(),
            )
            command = [
                sys.executable, "-I", str(ROOT / "tools" / "ember-restart-3b" / "parameter_counter.py"),
                "--model-config", str(config_path),
                "--checkpoint-manifest", str(root / "checkpoint" / "checkpoint-manifest.json"),
                "--active-expert", "shared",
            ]
            completed = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        measured = json.loads(completed.stdout)
        self.assertEqual(measured["active_expert_ids"], ["shared"])
        self.assertEqual(measured["active_parameters"], model.count_unique_trainable_parameters())
    def test_isolated_cli_rejects_shared_checkpoint_with_specialist_drift_from_genesis(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=13)
        model._activate_expert("shared")
        optimizer = torch.optim.AdamW((parameter for parameter in model.parameters() if parameter.requires_grad), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_payload = {
                "architecture_revision": "ember-sparse-3b-v2",
                "model": {
                    "hidden_size": 32, "layers": 2, "attention_heads": 4, "vocab_size": 64,
                    "tied_embeddings": True,
                    "image_projection": {"input_shape": [48, 48, 3], "output_size": 32},
                    "audio_projection": {"frame_samples": 640, "output_size": 32},
                    "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]},
                },
            }
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            write_checkpoint_artifacts(
                model, optimizer, root / "checkpoint", launch_seed=13,
                rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))},
                data_cursor={"shard": "TOKEN-SHARDS-V0:receipt", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                model_config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(), contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes(),
            )
            checkpoint = root / "checkpoint"
            payload = torch.load(checkpoint / "expert-vision.pt", map_location="cpu", weights_only=True)
            payload["model"]["layers.0.experts.vision.up_gate.weight"].add_(1)
            torch.save(payload, checkpoint / "expert-vision.pt")
            manifest_path = checkpoint / "checkpoint-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            digest = hashlib.sha256((checkpoint / "expert-vision.pt").read_bytes()).hexdigest()
            manifest["expert_checkpoint_sha256"]["vision"] = digest
            for record in manifest["shards"]:
                if record["path"] == "expert-vision.pt":
                    record["sha256"] = digest
                    record["bytes"] = (checkpoint / "expert-vision.pt").stat().st_size
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            command = [sys.executable, "-I", str(ROOT / "tools" / "ember-restart-3b" / "parameter_counter.py"), "--model-config", str(config_path), "--checkpoint-manifest", str(manifest_path), "--active-expert", "shared"]
            completed = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("genesis", completed.stderr)
    def test_counter_rejects_specialist_active_v3_without_external_parent_and_root(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=41)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(json.dumps({"architecture_revision": "ember-sparse-3b-v2", "model": {"hidden_size": 32, "layers": 2, "attention_heads": 4, "vocab_size": 64, "tied_embeddings": True, "image_projection": {"input_shape": [48, 48, 3], "output_size": 32}, "audio_projection": {"frame_samples": 640, "output_size": 32}, "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]}}}), encoding="utf-8")
            write_checkpoint_artifacts(model, optimizer, root / "checkpoint", launch_seed=41, rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))}, data_cursor={"shard": "test", "record_index": 0, "global_step": 0, "tokens_seen": 0}, model_config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(), contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes())
            with self.assertRaisesRegex(ValueError, "v4"):
                execute_counter(model_config=config_path, checkpoint_manifest=root / "checkpoint" / "checkpoint-manifest.json", active_expert="reasoning")

    def test_counter_requires_external_parent_and_root_for_specialist_v4(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=43)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(json.dumps({"architecture_revision": "ember-sparse-3b-v2", "model": {"hidden_size": 32, "layers": 2, "attention_heads": 4, "vocab_size": 64, "tied_embeddings": True, "image_projection": {"input_shape": [48, 48, 3], "output_size": 32}, "audio_projection": {"frame_samples": 640, "output_size": 32}, "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]}}}), encoding="utf-8")
            receipt = write_checkpoint_artifacts(model, optimizer, root / "checkpoint", launch_seed=43, rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))}, data_cursor={"shard": "test", "record_index": 0, "global_step": 0, "tokens_seen": 0}, model_config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(), contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes())
            manifest_path = root / "checkpoint" / "checkpoint-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.update({"schema_version": "ember-sparse-checkpoint-v4", "contract_version": 4, "expert_parameter_sha256": manifest["expert_genesis_sha256"], "lineage": {"parent_checkpoint_sha256": "a" * 64, "root_genesis_checkpoint_sha256": "b" * 64, "trained_expert_ids": ["reasoning"], "episode": {"active_expert": "reasoning", "data_verification_receipt": {}, "data_verification_receipt_sha256": "c" * 64}}})
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "external parent and root"):
                execute_counter(model_config=config_path, checkpoint_manifest=manifest_path, active_expert="reasoning")
            with self.assertRaisesRegex(ValueError, "parent checkpoint hash"):
                execute_counter(model_config=config_path, checkpoint_manifest=manifest_path, active_expert="reasoning", parent_manifest=manifest_path, root_manifest=manifest_path)



    def test_counter_rejects_v4_active_parameter_digest_equal_to_parent(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(json.dumps({"architecture_revision": "ember-sparse-3b-v2", "model": {"hidden_size": 32, "layers": 2, "attention_heads": 4, "vocab_size": 64, "tied_embeddings": True, "image_projection": {"input_shape": [48, 48, 3], "output_size": 32}, "audio_projection": {"frame_samples": 640, "output_size": 32}, "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]}}}), encoding="utf-8")
            model = UnifiedDecoder(config, genesis_seed=51)
            model._activate_expert("shared")
            optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
            root_receipt = write_checkpoint_artifacts(model, optimizer, root / "root", launch_seed=51, rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))}, data_cursor={"shard": "root", "record_index": 0, "global_step": 0, "tokens_seen": 0}, model_config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(), contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes())
            root_manifest = root / "root" / "checkpoint-manifest.json"
            candidate = UnifiedDecoder(config, genesis_seed=999)
            candidate_optimizer = torch.optim.AdamW(candidate.parameters(), lr=1e-4)
            load_checkpoint_artifacts(candidate, candidate_optimizer, root / "root", {**root_receipt, "checkpoint_manifest_sha256": hashlib.sha256(root_manifest.read_bytes()).hexdigest()})
            candidate._activate_expert("vision")
            next(parameter for name, parameter in candidate.named_parameters() if ".experts.vision." in name).data.add_(1)
            verification = {"schema_version": "ember-training-data-verification-v1", "result": "VERIFIED", "capability": "image", "data_manifest_sha256": "a" * 64, "tokenizer_sha256": "b" * 64, "verifier_sha256": "c" * 64, "data_class": "SEMANTIC_PRETRAINING", "record_count": 1, "token_count": 3, "source_manifest_sha256": "d" * 64, "records_artifact_sha256": "e" * 64, "semantic_checks": ["token_roundtrip", "source_target_pair", "raw_image_text_pair"], "generator_replay_verified": True, "admission": "ADMISSIBLE_SEMANTIC_CONTRACT", "semantic_model_contract_sha256": "f" * 64, "runtime_semantic_model_contract_sha256": "f" * 64}
            execution_slice = {"schema_version": "ember-specialist-execution-slice-v1", "start_record": 0, "record_count": 1, "token_count": 3, "records_sha256": "1" * 64, "tokens_sha256": "2" * 64, "scene_split_record_count": 1}
            scene_selection = {"schema_version": "ember-specialist-scene-split-selection-v1", "capability": "image", "scene_split": "train", "full_records_artifact_sha256": "e" * 64, "selected_record_count": 1, "selected_token_count": 3, "selected_records_sha256": "1" * 64, "selected_tokens_sha256": "2" * 64}
            receipt = write_checkpoint_artifacts(candidate, candidate_optimizer, root / "candidate", launch_seed=52, rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))}, data_cursor={"shard": "vision", "record_index": 1, "global_step": 1, "tokens_seen": 3}, model_config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(), contract_sha256="d" * 64, expert_genesis_sha256={name: "0" * 64 for name in ("vision", "audio", "reasoning", "tool")}, specialist_lineage={"parent_manifest": root_manifest, "root_manifest": root_manifest, "trained_expert_ids": ["vision"], "data_verification_receipt": verification, "execution_slice": execution_slice, "scene_split_selection": scene_selection})
            candidate_manifest = root / "candidate" / "checkpoint-manifest.json"
            manifest = json.loads(candidate_manifest.read_text(encoding="utf-8"))
            original_manifest = json.loads(json.dumps(manifest))
            manifest["lineage"]["episode"]["execution_slice"]["records_sha256"] = "3" * 64
            candidate_manifest.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "execution slice hash"):
                execute_counter(model_config=config_path, checkpoint_manifest=candidate_manifest, active_expert="vision", parent_manifest=root_manifest, root_manifest=root_manifest)
            manifest = original_manifest
            manifest["lineage"]["trained_expert_ids"] = []
            candidate_manifest.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "closed expert accretion"):
                execute_counter(model_config=config_path, checkpoint_manifest=candidate_manifest, active_expert="vision", parent_manifest=root_manifest, root_manifest=root_manifest)
            manifest["lineage"]["trained_expert_ids"] = ["vision"]
            manifest["expert_parameter_sha256"]["vision"] = root_receipt["expert_genesis_sha256"]["vision"]
            candidate_manifest.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "active expert parameter"):
                execute_counter(model_config=config_path, checkpoint_manifest=candidate_manifest, active_expert="vision", parent_manifest=root_manifest, root_manifest=root_manifest)

    def test_counter_cli_forwards_external_parent_and_root(self) -> None:
        import parameter_counter
        with patch.object(parameter_counter, "execute_counter", return_value={"result": "MEASURED"}) as execute:
            with patch.object(sys, "argv", ["parameter_counter.py", "--model-config", "config.json", "--checkpoint-manifest", "candidate.json", "--active-expert", "vision", "--parent-manifest", "parent.json", "--root-manifest", "root.json"]):
                self.assertEqual(main(), 0)
        execute.assert_called_once_with(model_config=Path("config.json"), checkpoint_manifest=Path("candidate.json"), active_expert="vision", parent_manifest=Path("parent.json"), root_manifest=Path("root.json"))

    def test_safe_metadata_rebuild_from_tensor_subtype_discards_subtype_state(self) -> None:
        metadata = _rebuild_tensor_from_type(
            _rebuild_tensor,
            _TensorTypeSentinel,
            (_StorageRef(6), 0, (2, 3), (3, 1)),
            {"untrusted": "subtype-state"},
        )
        self.assertEqual(metadata.shape, (2, 3))
    def test_safe_metadata_unpickler_rejects_arbitrary_global(self) -> None:
        with self.assertRaisesRegex(ValueError, "disallowed global"):
            _CheckpointMetadataUnpickler(io.BytesIO()).find_class("subprocess", "Popen")
    def test_realization_receipt_schema_is_closed_at_producer_and_admission(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=73)
        model._activate_expert("shared")
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(json.dumps({"architecture_revision": "ember-sparse-3b-v2", "model": {"hidden_size": 32, "layers": 2, "attention_heads": 4, "vocab_size": 64, "tied_embeddings": True, "image_projection": {"input_shape": [48, 48, 3], "output_size": 32}, "audio_projection": {"frame_samples": 640, "output_size": 32}, "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]}}}), encoding="utf-8")
            write_checkpoint_artifacts(model, optimizer, root / "checkpoint", launch_seed=73, rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)}, data_cursor={"shard": "schema", "record_index": 0, "global_step": 0, "tokens_seen": 0}, model_config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(), contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes())
            manifest = json.loads((root / "checkpoint" / "checkpoint-manifest.json").read_text(encoding="utf-8"))
            measured = execute_counter(model_config=config_path, checkpoint_manifest=root / "checkpoint" / "checkpoint-manifest.json", active_expert="shared")
            self.assertEqual(set(measured), REALIZATION_RECEIPT_FIELDS)
            validate_realization_receipt(measured)
            with self.assertRaisesRegex(ValueError, "closed schema"):
                validate_realization_receipt({key: value for key, value in measured.items() if key != "expert_parameter_sha256"})
            forged = dict(measured)
            forged["unexpected"] = True
            with self.assertRaisesRegex(ValueError, "closed schema"):
                validate_realization_receipt(forged)

    def test_p2b_stream_episode_requires_closed_selection_identity_and_progress(self) -> None:
        """P2B lineage is disjoint from execution-slice-v1 and binds one stream episode."""

        selection = {
            "schema_version": "ember-owned-specialist-stream-selection-receipt-v1",
            "stream_manifest_sha256": "857835d9722e5d6410f4c6c34c537ad2af12bfb98c4d3eb242b3a2c99e591427",
            "stream_build_receipt_sha256": "2e68402c914e842fe23c6ef69f1f8e957d858f7ad2de4d5467dfc65c949ead1e",
            "corpus_root_sha256": "42d1aac14c1e59563d348b7a53ce83dcce499a48217569d7d00a3966199141ab",
            "family_root_sha256": "4" * 64,
            "capability": "image",
            "selection_rule_id": "image_scene_split_train_v1",
            "selected_record_count": 8,
            "selected_token_count": 24,
            "selected_records_sha256": "5" * 64,
            "selection_commitment_sha256": "6" * 64,
        }
        selection_sha256 = hashlib.sha256(canonical_record_bytes(selection)).hexdigest()
        start = {"schema_version": SELECTION_CURSOR_SCHEMA_VERSION, "selection_receipt_sha256": selection_sha256, "selection_rule_id": "image_scene_split_train_v1", "selected_ordinal": 0, "next_source_index": 0}
        end = {**start, "selected_ordinal": 2, "next_source_index": 3}
        episode = {
            "schema_version": "ember-specialist-stream-episode-v1", "active_expert": "vision",
            "selection_receipt": selection, "selection_receipt_sha256": selection_sha256,
            "start_selection_cursor": start, "end_selection_cursor": end,
            "completed_updates": 2, "training_token_delta": 6,
            "stream_manifest_sha256": selection["stream_manifest_sha256"], "stream_build_receipt_sha256": selection["stream_build_receipt_sha256"],
            "corpus_root_sha256": selection["corpus_root_sha256"], "family_root_sha256": "4" * 64,
        }
        validator = getattr(parameter_counter, "validate_p2b_stream_episode")
        self.assertEqual(validator(episode, active_expert="vision"), episode)
        for field, value in (("selection_receipt_sha256", "0" * 64), ("active_expert", "audio"), ("completed_updates", 0)):
            with self.subTest(field=field):
                forged = dict(episode)
                forged[field] = value
                with self.assertRaises(ValueError):
                    validator(forged, active_expert="vision")
        wrong_cursor_schema = {**episode, "start_selection_cursor": {**start, "schema_version": "ember-specialist-stream-selection-cursor-v1"}}
        with self.assertRaises(ValueError):
            validator(wrong_cursor_schema, active_expert="vision")
        def refresh(item: dict[str, object]) -> None:
            receipt = item["selection_receipt"]
            assert isinstance(receipt, dict)
            digest = hashlib.sha256(canonical_record_bytes(receipt)).hexdigest()
            item["selection_receipt_sha256"] = digest
            for key in ("start_selection_cursor", "end_selection_cursor"):
                cursor = item[key]
                assert isinstance(cursor, dict)
                cursor["selection_receipt_sha256"] = digest

        def reject(label: str, mutate: object, *, rehash: bool = False) -> None:
            candidate = copy.deepcopy(episode)
            assert callable(mutate)
            mutate(candidate)
            if rehash:
                refresh(candidate)
            with self.subTest(label=label), self.assertRaises(ValueError):
                validator(candidate, active_expert="vision")

        reject("mixed_execution_slice", lambda item: item.__setitem__("execution_slice", {}))
        reject("receipt_capability", lambda item: item["selection_receipt"].__setitem__("capability", "audio"), rehash=True)
        reject("receipt_rule", lambda item: item["selection_receipt"].__setitem__("selection_rule_id", "all_records_semantic_pretraining_v1"), rehash=True)
        reject("receipt_hash", lambda item: item.__setitem__("selection_receipt_sha256", "0" * 64))
        reject("start_receipt", lambda item: item["start_selection_cursor"].__setitem__("selection_receipt_sha256", "0" * 64))
        reject("end_receipt", lambda item: item["end_selection_cursor"].__setitem__("selection_receipt_sha256", "0" * 64))
        reject("start_rule", lambda item: item["start_selection_cursor"].__setitem__("selection_rule_id", "all_records_semantic_pretraining_v1"))
        reject("end_rule", lambda item: item["end_selection_cursor"].__setitem__("selection_rule_id", "all_records_semantic_pretraining_v1"))
        reject("end_beyond_count", lambda item: item["end_selection_cursor"].__setitem__("selected_ordinal", 9))
        reject("ordinal_nonadvance", lambda item: item["end_selection_cursor"].__setitem__("selected_ordinal", 0))
        reject("source_nonadvance", lambda item: item["end_selection_cursor"].__setitem__("next_source_index", 0))
        reject("zero_updates", lambda item: item.__setitem__("completed_updates", 0))
        reject("delta_mismatch", lambda item: item.__setitem__("completed_updates", 1))
        reject("zero_tokens", lambda item: item.__setitem__("training_token_delta", 0))
        reject("wrong_expert", lambda item: item.__setitem__("active_expert", "audio"))
        for field in ("stream_manifest_sha256", "stream_build_receipt_sha256", "corpus_root_sha256", "family_root_sha256"):
            reject(f"duplicate_{field}", lambda item, field=field: item.__setitem__(field, "0" * 64))
        for field in ("stream_manifest_sha256", "stream_build_receipt_sha256", "corpus_root_sha256"):
            def noncanonical(item: dict[str, object], field: str = field) -> None:
                receipt = item["selection_receipt"]
                assert isinstance(receipt, dict)
                receipt[field] = "0" * 64
                item[field] = "0" * 64
            reject(f"noncanonical_{field}", noncanonical, rehash=True)


if __name__ == "__main__":
    unittest.main()
