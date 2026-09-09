# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The trusted parameter counter must inspect checkpoint realization under -I."""

from __future__ import annotations

import copy
from contextlib import nullcontext
import hashlib
import importlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch
import torch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))
sys.path.insert(0, str(ROOT / "tests" / "ember_restart_model" / "domain-governance"))
from repository_layout import resolve_repository_authority  # noqa: E402

_STREAM_MANIFEST_AUTHORITY = resolve_repository_authority(ROOT, "specialist_stream_manifest")
_STREAM_RECEIPT_AUTHORITY = resolve_repository_authority(ROOT, "specialist_stream_build_receipt")

from checkpoint_artifacts import (
    build_packed_fresh_genesis_specialist_lineage,
    load_checkpoint_artifacts,
)
import parameter_counter
from specialist_stream import SELECTION_CURSOR_SCHEMA_VERSION, TRAINING_CURSOR_SCHEMA_VERSION, canonical_record_bytes, open_specialist_stream
from src.ember.model.model import RestartDecoderConfig, UnifiedDecoder
_checkpoint_fixture_spec = importlib.util.spec_from_file_location(
    "issue898_counter_checkpoint_fixture", Path(__file__).with_name("checkpoint_fixture.py")
)
assert _checkpoint_fixture_spec is not None and _checkpoint_fixture_spec.loader is not None
_checkpoint_fixture = importlib.util.module_from_spec(_checkpoint_fixture_spec)
_checkpoint_fixture_spec.loader.exec_module(_checkpoint_fixture)
write_checkpoint_artifacts = _checkpoint_fixture.write_checkpoint_artifacts





from parameter_counter import REALIZATION_RECEIPT_FIELDS, _CheckpointMetadataUnpickler, _StorageRef, _TensorTypeSentinel, _rebuild_tensor, _rebuild_tensor_from_type, execute_counter, main, validate_realization_receipt


def _write_external_genesis_fixture(root: Path) -> tuple[Path, Path, Path, str]:
    """Build a tiny v5 bundle plus its independent genesis authority."""

    config_path = root / "config.json"
    config_payload = {
        "architecture_revision": "ember-sparse-3b-v2",
        "model": {
            "hidden_size": 32,
            "layers": 2,
            "attention_heads": 4,
            "vocab_size": 64,
            "tied_embeddings": True,
            "image_projection": {"input_shape": [48, 48, 3], "output_size": 32},
            "audio_projection": {"frame_samples": 640, "output_size": 32},
            "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]},
        },
    }
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    model = UnifiedDecoder(RestartDecoderConfig.small_for_tests(
        hidden_size=32, layers=2, attention_heads=4, vocab_size=64
    ), genesis_seed=913)
    model._activate_expert("shared")
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
    model(
        torch.tensor([[1, 2, 3]], dtype=torch.long),
        active_expert="shared",
    ).float().square().mean().backward()
    optimizer.step()
    optimizer.zero_grad(set_to_none=True)
    checkpoint = root / "checkpoint"
    write_checkpoint_artifacts(
        model,
        optimizer,
        checkpoint,
        launch_seed=913,
        rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
        data_cursor={"shard": "owned", "record_index": 1, "global_step": 1, "tokens_seen": 3},
        model_config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
        contract_sha256="d" * 64,
        expert_genesis_sha256=model.expert_bank_genesis_hashes(),
        optimizer_state_layout="owner-sharded-v1",
    )
    manifest_path = checkpoint / "checkpoint-manifest.json"
    authority_path = root / "expert-genesis-authority.json"
    authority_path.write_text(json.dumps({
        "schema_version": "ember-expert-genesis-authority-v1",
        "architecture_revision": "ember-sparse-3b-v2",
        "model_config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "contract_sha256": "d" * 64,
        "checkpoint_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "expert_genesis_sha256": model.expert_bank_genesis_hashes(),
    }, sort_keys=True), encoding="utf-8")
    authority_sha256 = hashlib.sha256(authority_path.read_bytes()).hexdigest()
    return config_path, manifest_path, authority_path, authority_sha256


class CounterCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._bundle_test_directory = tempfile.TemporaryDirectory(dir="B:/tmp")
        self.bundle_test_root = Path(self._bundle_test_directory.name)

    def tearDown(self) -> None:
        self._bundle_test_directory.cleanup()

    def test_counter_admits_closed_packed_fresh_genesis_specialist_lineage_without_external_parent(self) -> None:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=2, attention_heads=4, vocab_size=64,
        )
        model = UnifiedDecoder(config, genesis_seed=83)
        model._activate_expert("audio")
        genesis = model.expert_bank_genesis_hashes()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(json.dumps({
                "architecture_revision": "ember-sparse-3b-v2",
                "model": {
                    "hidden_size": 32, "layers": 2, "attention_heads": 4,
                    "vocab_size": 64, "tied_embeddings": True,
                    "image_projection": {"input_shape": [48, 48, 3], "output_size": 32},
                    "audio_projection": {"frame_samples": 640, "output_size": 32},
                    "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]},
                },
            }), encoding="utf-8")
            config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
            initial_cursor = {
                "selected_ordinal": 0, "global_step": 0, "tokens_seen": 0,
                "processed_tokens_seen": 0, "pack_ordinal": 0,
            }
            checkpoint_cursor = {
                "selected_ordinal": 64, "global_step": 1, "tokens_seen": 960,
                "processed_tokens_seen": 960, "pack_ordinal": 1,
            }
            lineage = build_packed_fresh_genesis_specialist_lineage(
                source_commit="a" * 40, model_config_sha256=config_sha256,
                seed=83, active_expert="audio",
                selection_receipt_sha256="b" * 64,
                execution_record_order_sha256="c" * 64,
                execution_tokens_sha256="d" * 64,
                pack_sequence_sha256="e" * 64,
                initial_cursor=initial_cursor, checkpoint_cursor=checkpoint_cursor,
            )
            writer_kwargs = {
                "launch_seed": 83,
                "rng_state": {
                    "cpu": torch.get_rng_state().clone(),
                    "cuda": (
                        torch.cuda.get_rng_state().clone()
                        if torch.cuda.is_available()
                        else torch.tensor([1, 2, 3], dtype=torch.uint8)
                    ),
                },
                "data_cursor": {
                    "shard": "PACKED_SELECTION:bbbbbbbbbbbb", "record_index": 64,
                    "global_step": 1, "tokens_seen": 960,
                    "processed_tokens_seen": 960, "pack_ordinal": 1,
                    "packed_selection_cursor": {"selected_ordinal": 64},
                },
                "model_config_sha256": config_sha256,
                "contract_sha256": "f" * 64,
                "expert_genesis_sha256": genesis,
                "optimizer_state_layout": "owner-sharded-v1",
                "specialist_lineage": lineage,
            }
            with self.assertRaisesRegex(ValueError, "active expert did not change from genesis"):
                write_checkpoint_artifacts(
                    model, optimizer, root / "unchanged-audio-refused", **writer_kwargs,
                )
            model(
                torch.tensor([[1, 2, 3]], dtype=torch.long),
                active_expert="audio",
            ).float().square().mean().backward()
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            checkpoint = root / "checkpoint"
            checkpoint_receipt = write_checkpoint_artifacts(
                model, optimizer, checkpoint, **writer_kwargs,
            )
            manifest_path = checkpoint / "checkpoint-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["lineage"], lineage)
            self.assertEqual(manifest["optimizer_state_owner_ids"], ["shared", "audio"])
            resumed_model = UnifiedDecoder(config, genesis_seed=83)
            resumed_model._activate_expert("audio")
            resumed_optimizer = torch.optim.AdamW(resumed_model.parameters(), lr=1e-4)
            resumed = load_checkpoint_artifacts(
                resumed_model, resumed_optimizer, checkpoint, checkpoint_receipt,
            )
            self.assertEqual(resumed["data_cursor"], writer_kwargs["data_cursor"])
            self.assertEqual(
                resumed_model.expert_bank_genesis_hashes(),
                model.expert_bank_genesis_hashes(),
            )
            measured = execute_counter(
                model_config=config_path, checkpoint_manifest=manifest_path,
                active_expert="audio",
            )
            self.assertEqual(measured["result"], "MEASURED")
            self.assertEqual(measured["active_expert_ids"], ["audio"])
            seed_drift = copy.deepcopy(manifest)
            seed_drift["lineage"]["seed"] = 84
            seed_drift["lineage"]["genesis_lineage_sha256"] = hashlib.sha256(
                json.dumps({
                    "schema_version": "ember-issue1413-packed-fresh-genesis-v1",
                    "lineage_mode": "FRESH_GENESIS_NO_EXTERNAL_PREDECESSOR",
                    "source_commit": "a" * 40,
                    "model_config_sha256": config_sha256,
                    "seed": 84,
                }, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            unsigned = {
                key: value for key, value in seed_drift["lineage"].items()
                if key != "lineage_sha256"
            }
            seed_drift["lineage"]["lineage_sha256"] = hashlib.sha256(
                json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            manifest_path.write_text(json.dumps(seed_drift, sort_keys=True), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "launch seed mismatch"):
                execute_counter(
                    model_config=config_path, checkpoint_manifest=manifest_path,
                    active_expert="audio",
                )
            forged = copy.deepcopy(manifest)
            forged["lineage"]["genesis_lineage_sha256"] = "0" * 64
            unsigned = {
                key: value for key, value in forged["lineage"].items()
                if key != "lineage_sha256"
            }
            forged["lineage"]["lineage_sha256"] = hashlib.sha256(
                json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            manifest_path.write_text(json.dumps(forged, sort_keys=True), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lineage hash drifted"):
                execute_counter(
                    model_config=config_path, checkpoint_manifest=manifest_path,
                    active_expert="audio",
                )
            manifest["lineage"]["pack_sequence_sha256"] = "9" * 64
            manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "self hash drifted"):
                execute_counter(
                    model_config=config_path, checkpoint_manifest=manifest_path,
                    active_expert="audio",
                )

    def test_counter_inspects_v5_owner_sharded_optimizer_records(self) -> None:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=2, attention_heads=4, vocab_size=64
        )
        model = UnifiedDecoder(config, genesis_seed=913)
        model._activate_expert("shared")
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        model(
            torch.tensor([[1, 2, 3]], dtype=torch.long),
            active_expert="shared",
        ).float().square().mean().backward()
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_payload = {
                "architecture_revision": "ember-sparse-3b-v2",
                "model": {
                    "hidden_size": 32,
                    "layers": 2,
                    "attention_heads": 4,
                    "vocab_size": 64,
                    "tied_embeddings": True,
                    "image_projection": {"input_shape": [48, 48, 3], "output_size": 32},
                    "audio_projection": {"frame_samples": 640, "output_size": 32},
                    "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]},
                },
            }
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            checkpoint = root / "checkpoint"
            write_checkpoint_artifacts(
                model,
                optimizer,
                checkpoint,
                launch_seed=913,
                rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                data_cursor={"shard": "owned", "record_index": 1, "global_step": 1, "tokens_seen": 3},
                model_config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
                contract_sha256="d" * 64,
                expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                optimizer_state_layout="owner-sharded-v1",
            )
            manifest_path = checkpoint / "checkpoint-manifest.json"
            authority_path = root / "expert-genesis-authority.json"
            authority_path.write_text(json.dumps({
                "schema_version": "ember-expert-genesis-authority-v1",
                "architecture_revision": "ember-sparse-3b-v2",
                "model_config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                "contract_sha256": "d" * 64,
                "checkpoint_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "expert_genesis_sha256": model.expert_bank_genesis_hashes(),
            }, sort_keys=True), encoding="utf-8")
            authority_sha256 = hashlib.sha256(authority_path.read_bytes()).hexdigest()
            measured = execute_counter(
                model_config=config_path,
                checkpoint_manifest=manifest_path,
                active_expert="shared",
                expert_genesis_authority=authority_path,
                expert_genesis_authority_sha256=authority_sha256,
            )
            self.assertEqual(measured["result"], "MEASURED")
            self.assertEqual(measured["active_expert_ids"], ["shared"])
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "parameter_counter.py"),
                    "--model-config",
                    str(config_path),
                    "--checkpoint-manifest",
                    str(manifest_path),
                    "--active-expert",
                    "shared",
                    "--expert-genesis-authority",
                    str(authority_path),
                    "--expert-genesis-authority-sha256",
                    authority_sha256,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["result"], "MEASURED")

    def test_counter_rejects_external_genesis_authority_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path, manifest_path, authority_path, _authority_sha256 = _write_external_genesis_fixture(Path(directory))
            with self.assertRaisesRegex(ValueError, "content hash mismatch"):
                execute_counter(
                    model_config=config_path,
                    checkpoint_manifest=manifest_path,
                    active_expert="shared",
                    expert_genesis_authority=authority_path,
                    expert_genesis_authority_sha256="0" * 64,
                )

    def test_counter_rejects_missing_or_malformed_external_genesis_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, manifest_path, authority_path, _authority_sha256 = _write_external_genesis_fixture(root)
            with self.assertRaisesRegex(ValueError, "required together"):
                execute_counter(
                    model_config=config_path,
                    checkpoint_manifest=manifest_path,
                    active_expert="shared",
                    expert_genesis_authority=authority_path,
                )
            authority_path.write_text("[]", encoding="utf-8")
            malformed_sha256 = hashlib.sha256(authority_path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "must contain a JSON object"):
                execute_counter(
                    model_config=config_path,
                    checkpoint_manifest=manifest_path,
                    active_expert="shared",
                    expert_genesis_authority=authority_path,
                    expert_genesis_authority_sha256=malformed_sha256,
                )

    def test_counter_rejects_external_genesis_map_disagreement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, manifest_path, authority_path, _authority_sha256 = _write_external_genesis_fixture(root)
            authority = json.loads(authority_path.read_text(encoding="utf-8"))
            authority["expert_genesis_sha256"]["vision"] = "0" * 64
            authority_path.write_text(json.dumps(authority, sort_keys=True), encoding="utf-8")
            authority_sha256 = hashlib.sha256(authority_path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "disagrees with external authority"):
                execute_counter(
                    model_config=config_path,
                    checkpoint_manifest=manifest_path,
                    active_expert="shared",
                    expert_genesis_authority=authority_path,
                    expert_genesis_authority_sha256=authority_sha256,
                )

    def test_counter_rejects_external_genesis_authority_field_drift(self) -> None:
        for field, message in (
            ("model_config_sha256", "model-config hash mismatch"),
            ("contract_sha256", "contract hash mismatch"),
            ("checkpoint_manifest_sha256", "checkpoint hash mismatch"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config_path, manifest_path, authority_path, _authority_sha256 = _write_external_genesis_fixture(root)
                authority = json.loads(authority_path.read_text(encoding="utf-8"))
                authority[field] = "0" * 64
                authority_path.write_text(json.dumps(authority, sort_keys=True), encoding="utf-8")
                authority_sha256 = hashlib.sha256(authority_path.read_bytes()).hexdigest()
                with self.assertRaisesRegex(ValueError, message):
                    execute_counter(
                        model_config=config_path,
                        checkpoint_manifest=manifest_path,
                        active_expert="shared",
                        expert_genesis_authority=authority_path,
                        expert_genesis_authority_sha256=authority_sha256,
                    )

    def test_counter_rejects_v5_top_level_split_shard_identity_drift(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=39)
        model._activate_expert("shared")
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(json.dumps({
                "architecture_revision": "ember-sparse-3b-v2",
                "model": {
                    "hidden_size": 32, "layers": 2, "attention_heads": 4, "vocab_size": 64,
                    "tied_embeddings": True,
                    "image_projection": {"input_shape": [48, 48, 3], "output_size": 32},
                    "audio_projection": {"frame_samples": 640, "output_size": 32},
                    "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]},
                },
            }), encoding="utf-8")
            checkpoint = root / "checkpoint"
            write_checkpoint_artifacts(
                model, optimizer, checkpoint, launch_seed=39, rng_state={
                    "cpu": torch.get_rng_state().clone(),
                    "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8),
                },
                data_cursor={"shard": "owned", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                model_config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
                contract_sha256="d" * 64,
                expert_genesis_sha256=model.expert_bank_genesis_hashes(),
            )
            manifest_path = checkpoint / "checkpoint-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["shared_model_shard_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "split shard identity"):
                execute_counter(
                    model_config=config_path,
                    checkpoint_manifest=manifest_path,
                    active_expert="shared",
                )

    def test_p2b_tokenizer_runtime_bundle_is_closed_and_path_free(self) -> None:
        """P2B imports only a caller-supplied, content-addressed tokenizer bundle."""
        runtime_bundle = importlib.import_module("tokenizer_runtime_bundle")
        bundle_parent = self.bundle_test_root / "bundle-closure"
        bundle_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=bundle_parent) as directory:
            root = Path(directory)
            bundle_root, manifest_path, emitted = runtime_bundle.materialize_tokenizer_runtime_bundle(
                bundle_parent=root,
            )
            self.assertEqual(emitted["schema_version"], "ember-p2b-tokenizer-runtime-bundle-v1")
            self.assertEqual(set(emitted), {"schema_version", "distribution", "record_sha256", "compatibility", "files", "root_sha256", "manifest_sha256"})
            self.assertEqual(emitted["manifest_sha256"], hashlib.sha256(manifest_path.read_bytes()).hexdigest())
            self.assertNotIn(str(root), json.dumps(emitted, sort_keys=True))
            self.assertEqual(
                runtime_bundle.validate_tokenizer_runtime_bundle(
                    bundle_root=bundle_root, manifest_path=manifest_path,
                ),
                emitted,
            )
            (bundle_root / "unexpected.txt").write_text("extra", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unexpected"):
                runtime_bundle.validate_tokenizer_runtime_bundle(
                    bundle_root=bundle_root, manifest_path=manifest_path,
                )
        self.assertFalse(root.exists())

    def test_p2b_tokenizer_runtime_bundle_rejects_record_drift_and_import_escape(self) -> None:
        """RECORD, metadata, and the private import boundary remain closed."""
        runtime_bundle = importlib.import_module("tokenizer_runtime_bundle")
        bundle_parent = self.bundle_test_root / "bundle-drift"
        bundle_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=bundle_parent) as directory:
            root = Path(directory)
            omitted_root, omitted_manifest_path, _ = runtime_bundle.materialize_tokenizer_runtime_bundle(bundle_parent=root / "omitted")
            omitted = json.loads(omitted_manifest_path.read_text(encoding="utf-8"))
            omitted["files"] = [item for item in omitted["files"] if not item["path"].endswith(".dist-info/METADATA")]
            omitted["root_sha256"] = runtime_bundle._root_commitment(omitted["files"])
            omitted_manifest_path.write_bytes(json.dumps(omitted, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            with self.assertRaisesRegex(ValueError, "METADATA"):
                runtime_bundle.validate_tokenizer_runtime_bundle(bundle_root=omitted_root, manifest_path=omitted_manifest_path)

            version_root, version_manifest_path, _ = runtime_bundle.materialize_tokenizer_runtime_bundle(bundle_parent=root / "version")
            version = json.loads(version_manifest_path.read_text(encoding="utf-8"))
            version["distribution"]["version"] = "0.0.0"
            version_manifest_path.write_bytes(json.dumps(version, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            with self.assertRaisesRegex(ValueError, "METADATA version"):
                runtime_bundle.validate_tokenizer_runtime_bundle(bundle_root=version_root, manifest_path=version_manifest_path)

            with self.assertRaisesRegex(ValueError, "RECORD hash"):
                runtime_bundle._decode_record_sha256("%%%")
            padded = __import__("base64").urlsafe_b64encode(bytes(32)).decode("ascii")
            with self.assertRaisesRegex(ValueError, "RECORD hash"):
                runtime_bundle._decode_record_sha256(padded)

            zero_root = root / "zero"
            (zero_root / "tokenizers").mkdir(parents=True)
            dist_info = zero_root / "tokenizers-0.dist-info"
            dist_info.mkdir()
            empty_path = zero_root / "tokenizers" / "__init__.py"
            empty_path.write_bytes(b"")
            metadata_path = dist_info / "METADATA"
            metadata_path.write_text("Name: tokenizers\nVersion: 0\n", encoding="utf-8")
            empty_record_hash = __import__("base64").urlsafe_b64encode(hashlib.sha256(b"").digest()).decode("ascii").rstrip("=")
            metadata_bytes = metadata_path.read_bytes()
            metadata_record_hash = __import__("base64").urlsafe_b64encode(hashlib.sha256(metadata_bytes).digest()).decode("ascii").rstrip("=")
            record_path = dist_info / "RECORD"
            record_path.write_text(
                f"tokenizers/__init__.py,sha256={empty_record_hash},0\n"
                f"tokenizers-0.dist-info/METADATA,sha256={metadata_record_hash},{len(metadata_bytes)}\n"
                "tokenizers-0.dist-info/RECORD,,\n", encoding="utf-8",
            )
            zero_files = [
                {"path": "tokenizers-0.dist-info/METADATA", "bytes": len(metadata_bytes), "sha256": hashlib.sha256(metadata_bytes).hexdigest()},
                {"path": "tokenizers-0.dist-info/RECORD", "bytes": len(record_path.read_bytes()), "sha256": hashlib.sha256(record_path.read_bytes()).hexdigest()},
                {"path": "tokenizers/__init__.py", "bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()},
            ]
            zero_manifest = {
                "schema_version": runtime_bundle.SCHEMA_VERSION,
                "distribution": {"name": "tokenizers", "version": "0"},
                "record_sha256": hashlib.sha256(record_path.read_bytes()).hexdigest(),
                "compatibility": runtime_bundle._compatibility(),
                "files": zero_files,
                "root_sha256": runtime_bundle._root_commitment(zero_files),
            }
            zero_manifest_path = zero_root / "tokenizer-runtime-manifest.json"
            zero_manifest_path.write_bytes(json.dumps(zero_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            self.assertEqual(runtime_bundle.validate_tokenizer_runtime_bundle(bundle_root=zero_root, manifest_path=zero_manifest_path)["files"], zero_files)

            swap_root, swap_manifest_path, swap = runtime_bundle.materialize_tokenizer_runtime_bundle(bundle_parent=root / "swap")
            source = swap_root / "tokenizers" / "__init__.py"
            original_bytes = source.read_bytes()

            def attempt_replacement(_bundle_root: Path) -> None:
                source.write_bytes(original_bytes + b"\n# replacement attempt\n")

            saved_tokenizers = {
                name: module for name, module in sys.modules.items()
                if name == "tokenizers" or name.startswith("tokenizers.")
            }
            for name in saved_tokenizers:
                sys.modules.pop(name, None)
            try:
                with patch.object(runtime_bundle, "_after_final_validation_before_import_for_test", side_effect=attempt_replacement):
                    with self.assertRaises(PermissionError):
                        with runtime_bundle.lease_tokenizer_runtime_bundle(bundle_root=swap_root, manifest_path=swap_manifest_path):
                            self.fail("replacement boundary unexpectedly entered")
            finally:
                sys.modules.update(saved_tokenizers)
            self.assertEqual(source.read_bytes(), original_bytes)
            source.unlink()
            self.assertFalse(source.exists())
            source.write_bytes(original_bytes)

            extra_root, extra_manifest_path, _ = runtime_bundle.materialize_tokenizer_runtime_bundle(bundle_parent=root / "extra")
            extra_path = extra_root / "unlisted.py"
            extra_script = (
                "import sys\n"
                f"sys.path.insert(0, {str(ROOT / 'src' / 'ember' / 'infrastructure' / 'tools' / 'ember-restart-3b')!r})\n"
                "import tokenizer_runtime_bundle as runtime\n"
                f"root = {str(extra_root)!r}\n"
                f"manifest = {str(extra_manifest_path)!r}\n"
                "runtime._after_final_validation_before_import_for_test = lambda value: runtime.Path(value, 'unlisted.py').write_bytes(b'unlisted = True\\n')\n"
                "try:\n"
                "    with runtime.lease_tokenizer_runtime_bundle(bundle_root=runtime.Path(root), manifest_path=runtime.Path(manifest)):\n"
                "        raise AssertionError('unlisted private-root byte entered')\n"
                "except ValueError as error:\n"
                "    assert 'unexpected' in str(error), error\n"
            )
            completed = subprocess.run([sys.executable, "-I", "-B", "-c", extra_script], check=False, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            extra_path.unlink()
            self.assertFalse(extra_path.exists())

            success_root, success_manifest_path, _ = runtime_bundle.materialize_tokenizer_runtime_bundle(bundle_parent=root / "success")
            success_source = success_root / "tokenizers" / "__init__.py"
            lease_script = (
                "import hashlib, sys\n"
                f"sys.path.insert(0, {str(ROOT / 'src' / 'ember' / 'infrastructure' / 'tools' / 'ember-restart-3b')!r})\n"
                "import tokenizer_runtime_bundle as runtime\n"
                f"root = {str(success_root)!r}\n"
                f"manifest = {str(success_manifest_path)!r}\n"
                "before = sys.dont_write_bytecode\n"
                "with runtime.lease_tokenizer_runtime_bundle(bundle_root=runtime.Path(root), manifest_path=runtime.Path(manifest)) as authority:\n"
                "    assert authority['manifest_sha256'] == hashlib.sha256(runtime.Path(manifest).read_bytes()).hexdigest()\n"
                "    assert root in sys.path\n"
                "assert root not in sys.path\n"
                "assert sys.dont_write_bytecode == before\n"
                "assert not any(isinstance(getattr(value, '__file__', None), str) and root in str(value.__file__) for value in sys.modules.values())\n"
            )
            completed = subprocess.run([sys.executable, "-I", "-B", "-c", lease_script], check=False, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            success_source.unlink()
            success_source.write_bytes(source.read_bytes())

            foreign_root, foreign_manifest_path, _ = runtime_bundle.materialize_tokenizer_runtime_bundle(bundle_parent=root / "foreign")
            with patch.dict(sys.modules, {"tokenizers": object()}):
                with self.assertRaisesRegex(ValueError, "preloaded module"):
                    with runtime_bundle.lease_tokenizer_runtime_bundle(bundle_root=foreign_root, manifest_path=foreign_manifest_path):
                        self.fail("foreign tokenizer module unexpectedly entered")
        self.assertFalse(root.exists())

    def test_tokenizer_runtime_lease_refuses_reachable_transient_unlisted_import(self) -> None:
        """An unlisted private-root module cannot execute during the final import window."""

        runtime_bundle = importlib.import_module("tokenizer_runtime_bundle")
        bundle_parent = self.bundle_test_root / "bundle-transient-import"
        bundle_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=bundle_parent) as directory:
            root = Path(directory)
            bundle_root, manifest_path, _ = runtime_bundle.materialize_tokenizer_runtime_bundle(bundle_parent=root)
            marker = root / "transient-import-executed"
            script = (
                "import sys\n"
                f"sys.path.insert(0, {str(ROOT / 'src' / 'ember' / 'infrastructure' / 'tools' / 'ember-restart-3b')!r})\n"
                "import tokenizer_runtime_bundle as runtime\n"
                f"root = runtime.Path({str(bundle_root)!r})\n"
                f"manifest = runtime.Path({str(manifest_path)!r})\n"
                f"marker = runtime.Path({str(marker)!r})\n"
                "sys.modules.pop('enum', None)\n"
                "def seam(bundle_root):\n"
                "    target = runtime.Path(bundle_root, 'enum.py')\n"
                "    target.write_text(\"from pathlib import Path\\nPath(\" + repr(str(marker)) + \").write_text('executed')\\nPath(__file__).unlink()\\nraise ImportError('transient enum')\\n\", encoding='utf-8')\n"
                "runtime._after_final_validation_before_import_for_test = seam\n"
                "try:\n"
                "    with runtime.lease_tokenizer_runtime_bundle(bundle_root=root, manifest_path=manifest):\n"
                "        raise AssertionError('transient import reached runtime lease')\n"
                "except (ImportError, ValueError):\n"
                "    pass\n"
                "assert not marker.exists(), 'transient unlisted module executed'\n"
            )
            completed = subprocess.run([sys.executable, "-I", "-B", "-c", script], check=False, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_tokenizer_runtime_lease_preserves_body_failure_when_release_fails(self) -> None:
        """Cleanup attempts every release without replacing a consumer failure."""

        runtime_bundle = importlib.import_module("tokenizer_runtime_bundle")
        bundle_parent = self.bundle_test_root / "bundle-release-failure"
        bundle_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=bundle_parent) as directory:
            root = Path(directory)
            bundle_root, manifest_path, _ = runtime_bundle.materialize_tokenizer_runtime_bundle(bundle_parent=root)
            script = (
                "import sys\n"
                f"sys.path.insert(0, {str(ROOT / 'src' / 'ember' / 'infrastructure' / 'tools' / 'ember-restart-3b')!r})\n"
                "import tokenizer_runtime_bundle as runtime\n"
                f"root = runtime.Path({str(bundle_root)!r})\n"
                f"manifest = runtime.Path({str(manifest_path)!r})\n"
                "closed = []\n"
                "class CloseHandle:\n"
                "    argtypes = None\n"
                "    restype = None\n"
                "    def __call__(self, handle):\n"
                "        value = int(handle.value)\n"
                "        closed.append(value)\n"
                "        return 0 if value == 42 else 1\n"
                "class Kernel32:\n"
                "    def __init__(self):\n"
                "        self.CloseHandle = CloseHandle()\n"
                "runtime._hold_windows_read_locks = lambda paths: [41, 42, 43]\n"
                "runtime.ctypes.WinDLL = lambda *args, **kwargs: Kernel32()\n"
                "runtime.ctypes.get_last_error = lambda: 5\n"
                "try:\n"
                "    with runtime.lease_tokenizer_runtime_bundle(bundle_root=root, manifest_path=manifest):\n"
                "        raise RuntimeError('consumer failure')\n"
                "except RuntimeError as error:\n"
                "    assert str(error) == 'consumer failure'\n"
                "    assert 'handle cleanup failed' in error._tokenizer_runtime_cleanup_error\n"
                "else:\n"
                "    raise AssertionError('consumer failure was not preserved')\n"
                "assert closed == [41, 42, 43], closed\n"
            )
            completed = subprocess.run([sys.executable, "-I", "-B", "-c", script], check=False, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_tokenizer_runtime_release_attempts_every_handle_after_a_failure(self) -> None:
        """One CloseHandle failure does not leak later private-runtime handles."""

        runtime_bundle = importlib.import_module("tokenizer_runtime_bundle")
        closed: list[int] = []

        class CloseHandle:
            argtypes: object | None = None
            restype: object | None = None

            def __call__(self, handle: object) -> int:
                value = getattr(handle, "value", None)
                self_value = int(value)
                closed.append(self_value)
                return 0 if self_value == 42 else 1

        class Kernel32:
            def __init__(self) -> None:
                self.CloseHandle = CloseHandle()

        with patch.object(runtime_bundle.ctypes, "WinDLL", return_value=Kernel32()), \
             patch.object(runtime_bundle.ctypes, "get_last_error", return_value=5):
            errors = runtime_bundle._release_windows_read_locks([41, 42, 43])
        self.assertEqual(closed, [41, 42, 43])
        self.assertEqual(len(errors), 1)
        self.assertIn("unable to release", str(errors[0]))

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
            tracked = {
                path.resolve()
                for path in (
                    config_path,
                    manifest_path,
                    *(
                        root / "checkpoint" / name
                        for name in (
                            "shared-model.pt",
                            "optimizer-state.pt",
                            "replay-state.pt",
                            "expert-vision.pt",
                            "expert-audio.pt",
                            "expert-reasoning.pt",
                            "expert-tool.pt",
                        )
                    ),
                )
            }
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
                sys.executable, "-I", str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "parameter_counter.py"),
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
                sys.executable, "-I", str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "parameter_counter.py"),
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
            command = [sys.executable, "-I", str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "parameter_counter.py"), "--model-config", str(config_path), "--checkpoint-manifest", str(manifest_path), "--active-expert", "shared"]
            completed = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("genesis", completed.stderr)

    def test_isolated_cli_measures_p2b_stream_episode_with_explicit_authority(self) -> None:
        """The production isolated counter reopens caller-bound P2B bytes before MEASURED."""
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
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
        manifest_path = _STREAM_MANIFEST_AUTHORITY.path
        build_path = _STREAM_RECEIPT_AUTHORITY.path
        manifest_bytes, build_bytes = manifest_path.read_bytes(), build_path.read_bytes()
        stream = open_specialist_stream(
            repo_root=ROOT, manifest_path=manifest_path,
            expected_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            expected_corpus_root_sha256="c2edce94125d9b7d88676ebbfa5aca3c447aa2d264ac6b74d7dfae5cf94e7178",
        )
        selection = stream.prepare_execution_selection(
            capability="image", selection_rule_id="image_scene_split_train_v1",
            build_receipt_path=build_path,
            expected_build_receipt_sha256=hashlib.sha256(build_bytes).hexdigest(),
        )
        record, end = next(selection.iter_from())
        receipt = selection.receipt
        receipt_sha256 = hashlib.sha256(canonical_record_bytes(receipt)).hexdigest()
        start = {**end, "selected_ordinal": 0, "next_source_index": 0}
        episode = {
            "schema_version": "ember-specialist-stream-episode-v1", "active_expert": "vision",
            "selection_receipt": receipt, "selection_receipt_sha256": receipt_sha256,
            "start_selection_cursor": start, "end_selection_cursor": end,
            "completed_updates": 1, "training_token_delta": len(record["token_ids"]),
            "stream_manifest_sha256": receipt["stream_manifest_sha256"],
            "stream_build_receipt_sha256": receipt["stream_build_receipt_sha256"],
            "corpus_root_sha256": receipt["corpus_root_sha256"], "family_root_sha256": receipt["family_root_sha256"],
        }
        bundle_test_root = self.bundle_test_root
        bundle_test_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=bundle_test_root) as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
            root_model = UnifiedDecoder(config, genesis_seed=101)
            root_model._activate_expert("shared")
            root_optimizer = torch.optim.AdamW(root_model.parameters(), lr=1e-4)
            write_checkpoint_artifacts(
                root_model, root_optimizer, root / "root", launch_seed=101,
                rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                data_cursor={"shard": "root", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                model_config_sha256=config_sha256, contract_sha256="d" * 64,
                expert_genesis_sha256=root_model.expert_bank_genesis_hashes(),
            )
            candidate_model = UnifiedDecoder(config, genesis_seed=101)
            candidate_model._activate_expert("vision")
            with torch.no_grad():
                next(parameter for name, parameter in candidate_model.named_parameters() if ".experts.vision." in name).add_(1)
            candidate_optimizer = torch.optim.AdamW(candidate_model.parameters(), lr=1e-4)
            write_checkpoint_artifacts(
                candidate_model, candidate_optimizer, root / "candidate", launch_seed=101,
                rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                data_cursor={"schema_version": TRAINING_CURSOR_SCHEMA_VERSION, "selection_cursor": end, "global_step": 1, "tokens_seen": len(record["token_ids"])},
                model_config_sha256=config_sha256, contract_sha256="d" * 64,
                expert_genesis_sha256=root_model.expert_bank_genesis_hashes(),
                specialist_lineage={
                    "parent_manifest": root / "root" / "checkpoint-manifest.json",
                    "root_manifest": root / "root" / "checkpoint-manifest.json",
                    "trained_expert_ids": ["vision"], "episode": episode,
                },
            )
            runtime_bundle = importlib.import_module("tokenizer_runtime_bundle")
            bundle_root, bundle_manifest, bundle_receipt = runtime_bundle.materialize_tokenizer_runtime_bundle(
                bundle_parent=root / "tokenizer-runtime",
            )
            bundle_manifest_sha256 = hashlib.sha256(bundle_manifest.read_bytes()).hexdigest()
            self.assertGreater(sum(item["bytes"] for item in bundle_receipt["files"]), 0)
            command = [
                sys.executable, "-I", str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "parameter_counter.py"),
                "--model-config", str(config_path),
                "--checkpoint-manifest", str(root / "candidate" / "checkpoint-manifest.json"),
                "--active-expert", "vision", "--parent-manifest", str(root / "root" / "checkpoint-manifest.json"),
                "--root-manifest", str(root / "root" / "checkpoint-manifest.json"),
                "--p2b-repo-root", str(ROOT), "--p2b-stream-manifest", str(manifest_path),
                "--p2b-stream-build-receipt", str(build_path),
                "--p2b-tokenizer-runtime-root", str(bundle_root),
                "--p2b-tokenizer-runtime-manifest", str(bundle_manifest),
            ]
            measured = subprocess.run(command, check=False, capture_output=True, text=True)
            swapped = root / "swapped-stream.json"
            swapped.write_bytes(build_bytes)
            rejected_command = list(command)
            rejected_command[rejected_command.index("--p2b-stream-manifest") + 1] = str(swapped)
            rejected = subprocess.run(rejected_command, check=False, capture_output=True, text=True)
        self.assertEqual(measured.returncode, 0, measured.stderr)
        measured_receipt = json.loads(measured.stdout)
        self.assertEqual(measured_receipt["result"], "MEASURED")
        runtime_authority = measured_receipt["runtime_authority"]
        self.assertEqual(runtime_authority["kind"], "P2B_TOKENIZERS_RECORD_V1")
        self.assertEqual(runtime_authority["runtime_manifest_sha256"], bundle_manifest_sha256)
        self.assertGreater(runtime_authority["file_count"], 0)
        self.assertGreater(runtime_authority["total_bytes"], 0)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("do not match the selected repository authorities", rejected.stderr)
    def test_counter_rejects_specialist_active_v3_without_external_parent_and_root(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=41)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(json.dumps({"architecture_revision": "ember-sparse-3b-v2", "model": {"hidden_size": 32, "layers": 2, "attention_heads": 4, "vocab_size": 64, "tied_embeddings": True, "image_projection": {"input_shape": [48, 48, 3], "output_size": 32}, "audio_projection": {"frame_samples": 640, "output_size": 32}, "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]}}}), encoding="utf-8")
            write_checkpoint_artifacts(model, optimizer, root / "checkpoint", launch_seed=41, rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))}, data_cursor={"shard": "test", "record_index": 0, "global_step": 0, "tokens_seen": 0}, model_config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(), contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes())
            with self.assertRaisesRegex(ValueError, "lineage manifest"):
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
            manifest.update({"expert_parameter_sha256": manifest["expert_genesis_sha256"], "lineage": {"parent_checkpoint_sha256": "a" * 64, "root_genesis_checkpoint_sha256": "b" * 64, "trained_expert_ids": ["reasoning"], "episode": {"active_expert": "reasoning", "data_verification_receipt": {}, "data_verification_receipt_sha256": "c" * 64}}})
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "external parent and root"):
                execute_counter(model_config=config_path, checkpoint_manifest=manifest_path, active_expert="reasoning")
            with self.assertRaisesRegex(ValueError, "parent checkpoint hash"):
                execute_counter(model_config=config_path, checkpoint_manifest=manifest_path, active_expert="reasoning", parent_manifest=manifest_path, root_manifest=manifest_path)

    def test_counter_admits_full_coverage_root_and_rejects_tampered_projection(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=61)
        # Capture the true pre-training genesis once, before any optimizer step.
        # (Previously this fixture recomputed "genesis" hashes AFTER training,
        # which made every full-coverage-root receipt's genesis map trivially
        # equal to its trained bytes -- the exact gap issue #1329 finding 2
        # closes with an inverted byte-verification.)
        genesis_hashes = model.expert_bank_genesis_hashes()
        genesis_vision_tensors = {
            name: parameter.detach().clone()
            for name, parameter in model.named_parameters()
            if ".experts.vision." in name
        }
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        # Mirror the governed vertical: every record's routed expert is activated
        # and stepped before the single end-of-run checkpoint, so the optimizer
        # holds post-update state for the complete specialist set.
        for name in ("vision", "audio", "reasoning", "tool"):
            model._activate_expert(name)
            for parameter in model.parameters():
                if parameter.requires_grad:
                    parameter.grad = torch.zeros_like(parameter)
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
        model._activate_expert("tool")
        trained_hashes = model.expert_bank_genesis_hashes()
        for name in ("vision", "audio", "reasoning", "tool"):
            self.assertNotEqual(trained_hashes[name], genesis_hashes[name], f"fixture must actually train {name} away from genesis")

        def resign(projection: dict[str, Any]) -> None:
            unsigned = {key: value for key, value in projection.items() if key != "projection_sha256"}
            projection["projection_sha256"] = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(json.dumps({"architecture_revision": "ember-sparse-3b-v2", "model": {"hidden_size": 32, "layers": 2, "attention_heads": 4, "vocab_size": 64, "tied_embeddings": True, "image_projection": {"input_shape": [48, 48, 3], "output_size": 32}, "audio_projection": {"frame_samples": 640, "output_size": 32}, "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]}}}), encoding="utf-8")
            write_checkpoint_artifacts(model, optimizer, root / "checkpoint", launch_seed=61, rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))}, data_cursor={"shard": "vertical", "record_index": 4, "global_step": 4, "tokens_seen": 8}, model_config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(), contract_sha256="d" * 64, expert_genesis_sha256=genesis_hashes, max_serialized_bytes=1 << 30, max_transient_scratch_bytes=1 << 30)
            manifest_path = root / "checkpoint" / "checkpoint-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertIsNone(manifest.get("lineage"))
            self.assertEqual(manifest["active_expert_ids"], ["tool"])
            self.assertEqual(manifest["storage_projection"]["optimizer_state_active_expert_ids"], ["vision", "audio", "reasoning", "tool"])
            self.assertEqual(manifest["expert_genesis_sha256"], genesis_hashes)
            original = json.loads(json.dumps(manifest))

            receipt = execute_counter(model_config=config_path, checkpoint_manifest=manifest_path, active_expert="tool")
            self.assertEqual(receipt["active_expert_ids"], ["tool"])
            self.assertEqual(receipt["active_parameters"], model.count_unique_trainable_parameters())
            # Decided episode-scope semantics (finding 3): the receipt reports
            # the per-step routed-active scope, not the wider per-episode
            # trained set, even for a full-coverage root realization.
            self.assertEqual(receipt["episode_trainable_parameters"], receipt["active_parameters"])
            self.assertLess(receipt["active_parameters"], receipt["allocated_parameters"])
            self.assertEqual(receipt["result"], "MEASURED")

            with self.assertRaisesRegex(ValueError, "must not carry external lineage manifests"):
                execute_counter(model_config=config_path, checkpoint_manifest=manifest_path, active_expert="tool", parent_manifest=manifest_path, root_manifest=manifest_path)

            manifest = json.loads(json.dumps(original))
            manifest["storage_projection"]["projection_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lineage manifest"):
                execute_counter(model_config=config_path, checkpoint_manifest=manifest_path, active_expert="tool")

            manifest = json.loads(json.dumps(original))
            manifest["storage_projection"]["optimizer_state_active_expert_ids"] = ["tool"]
            resign(manifest["storage_projection"])
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lineage manifest"):
                execute_counter(model_config=config_path, checkpoint_manifest=manifest_path, active_expert="tool")

            manifest = json.loads(json.dumps(original))
            manifest["storage_projection"]["active_expert"] = "vision"
            resign(manifest["storage_projection"])
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lineage manifest"):
                execute_counter(model_config=config_path, checkpoint_manifest=manifest_path, active_expert="tool")

            manifest = json.loads(json.dumps(original))
            manifest.pop("storage_projection")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lineage manifest"):
                execute_counter(model_config=config_path, checkpoint_manifest=manifest_path, active_expert="tool")

            # --- Finding 1: route-bytes cross-check (widening-tamper inverse test) ---
            # Reviewer's proven attack on #1327: build a genuine single/partial-route
            # checkpoint, widen ONLY the id list to the four-expert set, re-sign the
            # digest. The id list alone was previously sufficient for admission; the
            # route-bytes cross-check must now refuse it.
            manifest = json.loads(json.dumps(original))
            manifest["storage_projection"]["optimizer_state_tensor_storage_by_route_bytes"]["vision"] = 0
            resign(manifest["storage_projection"])
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lineage manifest"):
                execute_counter(model_config=config_path, checkpoint_manifest=manifest_path, active_expert="tool")

            manifest = json.loads(json.dumps(original))
            manifest["storage_projection"]["optimizer_state_tensor_storage_by_route_bytes"] = {
                "shared": 0, "vision": 0, "audio": 0, "reasoning": 0, "tool": 1,
            }
            resign(manifest["storage_projection"])
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lineage manifest"):
                execute_counter(model_config=config_path, checkpoint_manifest=manifest_path, active_expert="tool")

            manifest = json.loads(json.dumps(original))
            del manifest["storage_projection"]["optimizer_state_tensor_storage_by_route_bytes"]["vision"]
            resign(manifest["storage_projection"])
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lineage manifest"):
                execute_counter(model_config=config_path, checkpoint_manifest=manifest_path, active_expert="tool")

            # The genuine, untampered manifest still admits (route bytes cross-check
            # does not disturb the honest full-coverage-root receipt).
            manifest_path.write_text(json.dumps(original), encoding="utf-8")
            execute_counter(model_config=config_path, checkpoint_manifest=manifest_path, active_expert="tool")

            # --- Finding 2: inverted genesis byte-verification ---
            # Revert the on-disk vision expert bank to its true pre-training
            # genesis bytes while every other admission signal (route bytes,
            # projection digest, id list, manifest genesis map) stays genuine --
            # the manifest still CLAIMS vision was trained (full coverage), but
            # the bytes prove it was not.
            manifest = json.loads(json.dumps(original))
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            expert_path = root / "checkpoint" / "expert-vision.pt"
            payload = torch.load(expert_path, map_location="cpu", weights_only=True)
            for layer in range(2):
                for suffix in ("up_gate.weight", "down.weight"):
                    key = f"layers.{layer}.experts.vision.{suffix}"
                    payload["model"][key].copy_(genesis_vision_tensors[key])
            torch.save(payload, expert_path)
            digest = hashlib.sha256(expert_path.read_bytes()).hexdigest()
            manifest["expert_checkpoint_sha256"]["vision"] = digest
            for record in manifest["shards"]:
                if record["path"] == "expert-vision.pt":
                    record["sha256"] = digest
                    record["bytes"] = expert_path.stat().st_size
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "untrained"):
                execute_counter(model_config=config_path, checkpoint_manifest=manifest_path, active_expert="tool")



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
        execute.assert_called_once_with(
            model_config=Path("config.json"), checkpoint_manifest=Path("candidate.json"), active_expert="vision",
            parent_manifest=Path("parent.json"), root_manifest=Path("root.json"),
            p2b_repo_root=None, p2b_stream_manifest=None, p2b_stream_build_receipt=None,
            p2b_tokenizer_runtime_root=None, p2b_tokenizer_runtime_manifest=None,
        )

    def test_counter_cli_forwards_explicit_p2b_artifact_authority(self) -> None:
        """The P2B-only CLI surface passes caller-owned artifact locations unchanged."""
        import parameter_counter
        with patch.object(parameter_counter, "execute_counter", return_value={"result": "MEASURED"}) as execute:
            with patch.object(sys, "argv", [
                "parameter_counter.py", "--model-config", "config.json", "--checkpoint-manifest", "candidate.json",
                "--active-expert", "vision", "--parent-manifest", "parent.json", "--root-manifest", "root.json",
                "--p2b-repo-root", "repo", "--p2b-stream-manifest", "stream.json",
                "--p2b-stream-build-receipt", "build.json",
                "--p2b-tokenizer-runtime-root", "runtime", "--p2b-tokenizer-runtime-manifest", "runtime.json",
            ]):
                self.assertEqual(main(), 0)
        execute.assert_called_once_with(
            model_config=Path("config.json"), checkpoint_manifest=Path("candidate.json"), active_expert="vision",
            parent_manifest=Path("parent.json"), root_manifest=Path("root.json"),
            p2b_repo_root=Path("repo"), p2b_stream_manifest=Path("stream.json"),
            p2b_stream_build_receipt=Path("build.json"),
            p2b_tokenizer_runtime_root=Path("runtime"), p2b_tokenizer_runtime_manifest=Path("runtime.json"),
        )

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
            forged = dict(measured)
            forged["runtime_authority"] = {
                "schema_version": "ember-counter-runtime-authority-v1",
                "kind": "P2B_TOKENIZERS_RECORD_V1",
            }
            with self.assertRaisesRegex(ValueError, "runtime authority"):
                validate_realization_receipt(forged)

    def test_p2b_stream_episode_requires_closed_selection_identity_and_progress(self) -> None:
        """P2B lineage is disjoint from execution-slice-v1 and binds one stream episode."""

        selection = {
            "schema_version": "ember-owned-specialist-stream-selection-receipt-v1",
            "stream_manifest_sha256": _STREAM_MANIFEST_AUTHORITY.expected_sha256,
            "stream_build_receipt_sha256": _STREAM_RECEIPT_AUTHORITY.expected_sha256,
            "corpus_root_sha256": "c2edce94125d9b7d88676ebbfa5aca3c447aa2d264ac6b74d7dfae5cf94e7178",
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

        reopen = getattr(parameter_counter, "validate_p2b_counter_stream_authority")
        manifest_path = _STREAM_MANIFEST_AUTHORITY.path
        build_path = _STREAM_RECEIPT_AUTHORITY.path
        for label, invalid_bytes in (
            ("missing", None),
            ("mutable_bytearray", bytearray(b"{}")),
            ("opaque_object", object()),
        ):
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, "stream authority bytes"):
                reopen(
                    episode, active_expert="vision", repo_root=ROOT,
                    stream_manifest_path=manifest_path, stream_build_receipt_path=build_path,
                    stream_manifest_bytes=invalid_bytes, stream_build_receipt_bytes=b"{}",  # type: ignore[arg-type]
                )
        with self.assertRaisesRegex(ValueError, "stream manifest authority mismatch"):
            reopen(
                episode, active_expert="vision", repo_root=ROOT,
                stream_manifest_path=manifest_path, stream_build_receipt_path=build_path,
                stream_manifest_bytes=b"{}", stream_build_receipt_bytes=b"{}",
            )
        with self.assertRaisesRegex(ValueError, "stream build receipt authority mismatch"):
            reopen(
                episode, active_expert="vision", repo_root=ROOT,
                stream_manifest_path=manifest_path, stream_build_receipt_path=build_path,
                stream_manifest_bytes=manifest_path.read_bytes(), stream_build_receipt_bytes=b"{}",
            )
        for field in ("stream_manifest_sha256", "stream_build_receipt_sha256", "corpus_root_sha256"):
            def noncanonical(item: dict[str, object], field: str = field) -> None:
                receipt = item["selection_receipt"]
                assert isinstance(receipt, dict)
                receipt[field] = "0" * 64
                item[field] = "0" * 64
            reject(f"noncanonical_{field}", noncanonical, rehash=True)

    def test_p2b_counter_reopens_exact_bound_stream_selection(self) -> None:
        """Counter admission must reopen the end cursor against canonical stream authorities."""
        manifest_path = _STREAM_MANIFEST_AUTHORITY.path
        build_path = _STREAM_RECEIPT_AUTHORITY.path
        manifest_bytes = manifest_path.read_bytes()
        build_bytes = build_path.read_bytes()
        receipt = {
            "schema_version": "ember-owned-specialist-stream-selection-receipt-v1",
            "stream_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "stream_build_receipt_sha256": hashlib.sha256(build_bytes).hexdigest(),
            "corpus_root_sha256": "c2edce94125d9b7d88676ebbfa5aca3c447aa2d264ac6b74d7dfae5cf94e7178",
            "family_root_sha256": "4" * 64,
            "capability": "image",
            "selection_rule_id": "image_scene_split_train_v1",
            "selected_record_count": 2,
            "selected_token_count": 6,
            "selected_records_sha256": "5" * 64,
            "selection_commitment_sha256": "6" * 64,
        }
        receipt_sha256 = hashlib.sha256(canonical_record_bytes(receipt)).hexdigest()
        start = {"schema_version": SELECTION_CURSOR_SCHEMA_VERSION, "selection_receipt_sha256": receipt_sha256, "selection_rule_id": "image_scene_split_train_v1", "selected_ordinal": 0, "next_source_index": 0}
        end = {**start, "selected_ordinal": 1, "next_source_index": 1}
        episode = {
            "schema_version": "ember-specialist-stream-episode-v1", "active_expert": "vision",
            "selection_receipt": receipt, "selection_receipt_sha256": receipt_sha256,
            "start_selection_cursor": start, "end_selection_cursor": end,
            "completed_updates": 1, "training_token_delta": 3,
            "stream_manifest_sha256": receipt["stream_manifest_sha256"],
            "stream_build_receipt_sha256": receipt["stream_build_receipt_sha256"],
            "corpus_root_sha256": receipt["corpus_root_sha256"], "family_root_sha256": receipt["family_root_sha256"],
        }

        class Stream:
            families = {"image": {"corpus_root_sha256": "4" * 64}}

            def open_execution_selection(self, **kwargs: object) -> object:
                self.open_kwargs = kwargs
                return object()

        stream = Stream()
        reopen = getattr(parameter_counter, "validate_p2b_counter_stream_authority")
        with patch.object(parameter_counter, "open_specialist_stream", return_value=stream) as opener:
            self.assertEqual(
                reopen(episode, active_expert="vision", repo_root=ROOT,
                       stream_manifest_path=manifest_path, stream_build_receipt_path=build_path,
                       stream_manifest_bytes=manifest_bytes, stream_build_receipt_bytes=build_bytes),
                episode,
            )
        opener.assert_called_once_with(
            repo_root=ROOT.resolve(), manifest_path=manifest_path,
            expected_manifest_sha256=receipt["stream_manifest_sha256"],
            expected_corpus_root_sha256=receipt["corpus_root_sha256"],
            manifest_bytes=manifest_bytes,
        )
        self.assertEqual(stream.open_kwargs, {
            "receipt": receipt, "cursor": end, "build_receipt_path": build_path,
            "expected_build_receipt_sha256": receipt["stream_build_receipt_sha256"],
            "expected_selection_receipt_sha256": receipt_sha256,
            "build_receipt_bytes": build_bytes,
        })

    def test_p2b_counter_reopens_real_checked_in_selection_authority(self) -> None:
        """A P2B counter admission reopens one real bound selection cursor from checked-in bytes."""
        manifest_path = _STREAM_MANIFEST_AUTHORITY.path
        build_path = _STREAM_RECEIPT_AUTHORITY.path
        manifest_bytes = manifest_path.read_bytes()
        build_bytes = build_path.read_bytes()
        stream = open_specialist_stream(
            repo_root=ROOT, manifest_path=manifest_path,
            expected_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            expected_corpus_root_sha256="c2edce94125d9b7d88676ebbfa5aca3c447aa2d264ac6b74d7dfae5cf94e7178",
        )
        selection = stream.prepare_execution_selection(
            capability="image", selection_rule_id="image_scene_split_train_v1",
            build_receipt_path=build_path,
            expected_build_receipt_sha256=hashlib.sha256(build_bytes).hexdigest(),
        )
        record, end = next(selection.iter_from())
        receipt = selection.receipt
        receipt_sha256 = hashlib.sha256(canonical_record_bytes(receipt)).hexdigest()
        start = {**end, "selected_ordinal": 0, "next_source_index": 0}
        episode = {
            "schema_version": "ember-specialist-stream-episode-v1", "active_expert": "vision",
            "selection_receipt": receipt, "selection_receipt_sha256": receipt_sha256,
            "start_selection_cursor": start, "end_selection_cursor": end,
            "completed_updates": 1, "training_token_delta": len(record["token_ids"]),
            "stream_manifest_sha256": receipt["stream_manifest_sha256"],
            "stream_build_receipt_sha256": receipt["stream_build_receipt_sha256"],
            "corpus_root_sha256": receipt["corpus_root_sha256"], "family_root_sha256": receipt["family_root_sha256"],
        }
        result = parameter_counter.validate_p2b_counter_stream_authority(
            episode, active_expert="vision", repo_root=ROOT,
            stream_manifest_path=manifest_path, stream_build_receipt_path=build_path,
            stream_manifest_bytes=manifest_bytes, stream_build_receipt_bytes=build_bytes,
        )
        self.assertEqual(result, episode)

    def test_counter_dispatches_p2b_episode_to_independent_stream_authority(self) -> None:
        """The counter keeps the new P2B episode branch disjoint from legacy v4 episodes."""
        episode = {"schema_version": "ember-specialist-stream-episode-v1", "active_expert": "vision"}
        lineage = {
            "parent_checkpoint_sha256": "a" * 64,
            "root_genesis_checkpoint_sha256": "b" * 64,
            "trained_expert_ids": ["vision"],
            "episode": episode,
        }
        dispatch = getattr(parameter_counter, "_validate_specialist_counter_episode")
        with patch.object(parameter_counter, "validate_p2b_counter_stream_authority", return_value=episode) as validate:
            self.assertEqual(
                dispatch(
                    lineage, active_expert="vision", repo_root=ROOT,
                    stream_manifest_path=ROOT / "manifest.json",
                    stream_build_receipt_path=ROOT / "build-receipt.json",
                    stream_manifest_bytes=b"manifest", stream_build_receipt_bytes=b"build",
                ),
                episode,
            )
        validate.assert_called_once_with(
            episode, active_expert="vision", repo_root=ROOT,
            stream_manifest_path=ROOT / "manifest.json",
            stream_build_receipt_path=ROOT / "build-receipt.json",
            stream_manifest_bytes=b"manifest", stream_build_receipt_bytes=b"build",
        )
        self.assertIsNone(
            dispatch(
                {**lineage, "episode": {"active_expert": "vision", "execution_slice": {}}},
                active_expert="vision", repo_root=ROOT,
                stream_manifest_path=ROOT / "manifest.json",
                stream_build_receipt_path=ROOT / "build-receipt.json",
                stream_manifest_bytes=b"manifest", stream_build_receipt_bytes=b"build",
            )
        )

    def test_legacy_specialist_counter_episode_contract_remains_accepted(self) -> None:
        """Extracting P2B dispatch does not narrow the established v4 episode contract."""
        verification = {
            "schema_version": "ember-training-data-verification-v1", "result": "VERIFIED", "capability": "image",
            "data_manifest_sha256": "a" * 64, "tokenizer_sha256": "b" * 64, "verifier_sha256": "c" * 64,
            "data_class": "SEMANTIC_PRETRAINING", "record_count": 1, "token_count": 3,
            "source_manifest_sha256": "d" * 64, "records_artifact_sha256": "e" * 64,
            "semantic_checks": ["token_roundtrip"], "generator_replay_verified": True,
            "admission": "ADMISSIBLE_SEMANTIC_CONTRACT", "semantic_model_contract_sha256": "f" * 64,
            "runtime_semantic_model_contract_sha256": "f" * 64,
        }
        execution_slice = {
            "schema_version": "ember-specialist-execution-slice-v1", "start_record": 0,
            "record_count": 1, "token_count": 3, "records_sha256": "1" * 64,
            "tokens_sha256": "2" * 64, "scene_split_record_count": 1,
        }
        scene_split_selection = {
            "schema_version": "ember-specialist-scene-split-selection-v1", "capability": "image",
            "scene_split": "train", "full_records_artifact_sha256": "e" * 64,
            "selected_record_count": 1, "selected_token_count": 3,
            "selected_records_sha256": "1" * 64, "selected_tokens_sha256": "2" * 64,
        }
        episode = {
            "active_expert": "vision", "data_verification_receipt": verification,
            "data_verification_receipt_sha256": hashlib.sha256(canonical_record_bytes(verification)).hexdigest(),
            "execution_slice": execution_slice,
            "execution_slice_sha256": hashlib.sha256(canonical_record_bytes(execution_slice)).hexdigest(),
            "scene_split_selection": scene_split_selection,
            "scene_split_selection_sha256": hashlib.sha256(canonical_record_bytes(scene_split_selection)).hexdigest(),
        }
        parameter_counter._validate_legacy_specialist_counter_episode(episode, active_expert="vision")

    def test_execute_counter_routes_p2b_lineage_through_stream_authority(self) -> None:
        """The production counter reaches P2B reopening before issuing its measured receipt."""
        config = {
            "architecture_revision": "ember-sparse-3b-v2",
            "model": {"hidden_size": 32, "layers": 2, "attention_heads": 4, "vocab_size": 64,
                      "tied_embeddings": True, "image_projection": {"input_shape": [48, 48, 3], "output_size": 32},
                      "audio_projection": {"frame_samples": 640, "output_size": 32},
                      "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]}},
        }
        genesis = {name: (str(index + 1) * 64) for index, name in enumerate(("vision", "audio", "reasoning", "tool"))}
        parent_parameters = dict(genesis)
        candidate_parameters = {**genesis, "vision": "a" * 64}
        parent_files = dict(genesis)
        canonical_manifest_path = _STREAM_MANIFEST_AUTHORITY.path
        canonical_build_path = _STREAM_RECEIPT_AUTHORITY.path
        manifest_bytes, build_bytes = canonical_manifest_path.read_bytes(), canonical_build_path.read_bytes()
        runtime_bundle = importlib.import_module("tokenizer_runtime_bundle")
        runtime_root, runtime_manifest, _ = runtime_bundle.materialize_tokenizer_runtime_bundle(
            bundle_parent=self.bundle_test_root,
        )
        self.addCleanup(shutil.rmtree, runtime_root, ignore_errors=True)
        runtime_authority = runtime_bundle.validate_tokenizer_runtime_bundle(
            bundle_root=runtime_root, manifest_path=runtime_manifest,
        )
        stream = open_specialist_stream(
            repo_root=ROOT, manifest_path=canonical_manifest_path,
            expected_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            expected_corpus_root_sha256="c2edce94125d9b7d88676ebbfa5aca3c447aa2d264ac6b74d7dfae5cf94e7178",
        )
        selection = stream.prepare_execution_selection(
            capability="image", selection_rule_id="image_scene_split_train_v1",
            build_receipt_path=canonical_build_path, expected_build_receipt_sha256=hashlib.sha256(build_bytes).hexdigest(),
        )
        record, end = next(selection.iter_from())
        receipt = selection.receipt
        receipt_sha256 = hashlib.sha256(canonical_record_bytes(receipt)).hexdigest()
        start = {**end, "selected_ordinal": 0, "next_source_index": 0}
        stream_episode = {
            "schema_version": "ember-specialist-stream-episode-v1", "active_expert": "vision",
            "selection_receipt": receipt, "selection_receipt_sha256": receipt_sha256,
            "start_selection_cursor": start, "end_selection_cursor": end,
            "completed_updates": 1, "training_token_delta": len(record["token_ids"]),
            "stream_manifest_sha256": receipt["stream_manifest_sha256"],
            "stream_build_receipt_sha256": receipt["stream_build_receipt_sha256"],
            "corpus_root_sha256": receipt["corpus_root_sha256"], "family_root_sha256": receipt["family_root_sha256"],
        }
        candidate = {
            "schema_version": "ember-sparse-checkpoint-v4", "active_expert_ids": ["vision"],
            "lineage": {"parent_checkpoint_sha256": "b" * 64, "root_genesis_checkpoint_sha256": "b" * 64,
                        "trained_expert_ids": ["vision"],
                        "episode": stream_episode},
            "expert_genesis_sha256": genesis, "expert_parameter_sha256": candidate_parameters,
            "expert_checkpoint_sha256": parent_files, "model_config_sha256": "c" * 64,
            "data_cursor": {"schema_version": "ember-specialist-stream-training-cursor-v1", "selection_cursor": end, "global_step": 8, "tokens_seen": 42 + len(record["token_ids"])},
        }
        parent = {
            "schema_version": "ember-sparse-checkpoint-v3", "active_expert_ids": ["shared"],
            "expert_genesis_sha256": genesis, "expert_parameter_sha256": parent_parameters,
            "expert_checkpoint_sha256": parent_files,
            "data_cursor": {"shard": "legacy", "record_index": 0, "global_step": 7, "tokens_seen": 42},
        }
        manifest_path = _STREAM_MANIFEST_AUTHORITY.path
        build_path = _STREAM_RECEIPT_AUTHORITY.path
        original_bytes_snapshot = parameter_counter._read_bytes_snapshot

        def run_counter(
            *, supplied_manifest: bytes = manifest_bytes, supplied_build: bytes = build_bytes,
            supplied_manifest_path: Path | None = manifest_path,
            supplied_build_path: Path | None = build_path,
            candidate_snapshot: dict[str, object] | None = None,
        ) -> dict[str, object]:
            snapshots = iter(((config, "c" * 64), (candidate_snapshot or candidate, "d" * 64), (parent, "b" * 64), (parent, "b" * 64)))

            def bytes_snapshot(path: Path, *, label: str) -> tuple[bytes, str]:
                if Path(path) == manifest_path:
                    return supplied_manifest, hashlib.sha256(supplied_manifest).hexdigest()
                if Path(path) == build_path:
                    return supplied_build, hashlib.sha256(supplied_build).hexdigest()
                return original_bytes_snapshot(path, label=label)

            with patch.object(parameter_counter, "_read_json_snapshot", side_effect=lambda *_args, **_kwargs: next(snapshots)), \
                 patch.object(parameter_counter, "_inspect_realization", side_effect=lambda _path, snapshot, **_kwargs: snapshot), \
                 patch.object(parameter_counter, "_read_bytes_snapshot", side_effect=bytes_snapshot), \
                 patch.object(parameter_counter, "_lease_p2b_tokenizer_runtime", return_value=nullcontext(runtime_authority)):
                return parameter_counter.execute_counter(
                    model_config=Path("config.json"), checkpoint_manifest=Path("candidate.json"), active_expert="vision",
                    parent_manifest=Path("parent.json"), root_manifest=Path("root.json"),
                    p2b_repo_root=ROOT, p2b_stream_manifest=supplied_manifest_path,
                    p2b_stream_build_receipt=supplied_build_path,
                    p2b_tokenizer_runtime_root=runtime_root,
                    p2b_tokenizer_runtime_manifest=runtime_manifest,
                )

        receipt = run_counter()
        self.assertEqual(receipt["result"], "MEASURED")
        for label, kwargs, message in (
            ("missing_p2b_build_input", {"supplied_build_path": None}, "requires explicit stream authority"),
            ("wrong_stream_manifest_bytes", {"supplied_manifest": b"wrong"}, "manifest authority mismatch"),
            ("wrong_stream_build_receipt_bytes", {"supplied_build": b"wrong"}, "build receipt authority mismatch"),
            ("synthetic_receipt_only", {"supplied_manifest_path": None, "supplied_build_path": None}, "requires explicit stream authority"),
        ):
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, message):
                run_counter(**kwargs)

        def rebind_episode(candidate_snapshot: dict[str, object]) -> None:
            lineage = candidate_snapshot["lineage"]
            assert isinstance(lineage, dict)
            episode = lineage["episode"]
            assert isinstance(episode, dict)
            selection_receipt = episode["selection_receipt"]
            assert isinstance(selection_receipt, dict)
            receipt_digest = hashlib.sha256(canonical_record_bytes(selection_receipt)).hexdigest()
            episode["selection_receipt_sha256"] = receipt_digest
            for cursor_name in ("start_selection_cursor", "end_selection_cursor"):
                cursor = episode[cursor_name]
                assert isinstance(cursor, dict)
                cursor["selection_receipt_sha256"] = receipt_digest
            data_cursor = candidate_snapshot["data_cursor"]
            assert isinstance(data_cursor, dict)
            data_cursor["selection_cursor"] = episode["end_selection_cursor"]

        wrong_family = copy.deepcopy(candidate)
        family_episode = wrong_family["lineage"]["episode"]
        family_episode["selection_receipt"]["family_root_sha256"] = "0" * 64
        family_episode["family_root_sha256"] = "0" * 64
        rebind_episode(wrong_family)
        with self.assertRaisesRegex(ValueError, "P2B stream family authority mismatch"):
            run_counter(candidate_snapshot=wrong_family)

        wrong_build = copy.deepcopy(candidate)
        changed_build = json.loads(build_bytes)
        changed_build["corpus_root_sha256"] = "0" * 64
        changed_build_bytes = json.dumps(changed_build, sort_keys=True, separators=(",", ":")).encode("utf-8")
        build_episode = wrong_build["lineage"]["episode"]
        changed_build_digest = hashlib.sha256(changed_build_bytes).hexdigest()
        build_episode["selection_receipt"]["stream_build_receipt_sha256"] = changed_build_digest
        build_episode["stream_build_receipt_sha256"] = changed_build_digest
        rebind_episode(wrong_build)
        with self.assertRaisesRegex(ValueError, "does not bind the canonical stream authorities"):
            run_counter(supplied_build=changed_build_bytes, candidate_snapshot=wrong_build)

    def test_counter_binds_p2b_episode_end_to_candidate_and_parent_training_cursors(self) -> None:
        """Counter revalidation rejects a checkpoint cursor that diverges from the admitted P2B episode."""
        end = {
            "schema_version": SELECTION_CURSOR_SCHEMA_VERSION, "selection_receipt_sha256": "a" * 64,
            "selection_rule_id": "image_scene_split_train_v1", "selected_ordinal": 3, "next_source_index": 5,
        }
        episode = {"end_selection_cursor": end, "completed_updates": 2, "training_token_delta": 12}
        parent = {"global_step": 7, "tokens_seen": 42}
        candidate = {
            "schema_version": "ember-specialist-stream-training-cursor-v1", "selection_cursor": end,
            "global_step": 9, "tokens_seen": 54,
        }
        validate = getattr(parameter_counter, "validate_p2b_counter_checkpoint_progress")
        self.assertEqual(validate(episode, candidate, parent), candidate)
        for label, forged in (
            ("end_cursor", {**candidate, "selection_cursor": {**end, "selected_ordinal": 2}}),
            ("global_delta", {**candidate, "global_step": 8}),
            ("token_delta", {**candidate, "tokens_seen": 53}),
        ):
            with self.subTest(label=label), self.assertRaises(ValueError):
                validate(episode, forged, parent)


if __name__ == "__main__":
    unittest.main()
