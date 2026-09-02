# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deletion-testable v4 specialist accretion checkpoint lineage."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch
import torch

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))
sys.path.insert(0, str(ROOT / "tests" / "ember_restart_model" / "domain-governance"))

from checkpoint_artifacts import load_checkpoint_artifacts, preflight_specialist_lineage_sources, published_checkpoint_receipt
from model import RestartDecoderConfig, UnifiedDecoder
from checkpoint_fixture import write_checkpoint_artifacts





from parameter_counter import execute_counter


def _rng_state() -> dict[str, torch.Tensor]:
    return {"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))}


def _verification(capability: str = "image") -> dict[str, object]:
    return {
        "schema_version": "ember-training-data-verification-v1",
        "result": "VERIFIED",
        "capability": capability,
        "data_manifest_sha256": "a" * 64,
        "tokenizer_sha256": "b" * 64,
        "verifier_sha256": "c" * 64,
        "data_class": "SEMANTIC_PRETRAINING",
        "generator_replay_verified": True,
        "record_count": 4,
        "token_count": 64,
        "source_manifest_sha256": "d" * 64,
        "records_artifact_sha256": "e" * 64,
        "semantic_checks": {"image": ["token_roundtrip", "source_target_pair", "raw_image_text_pair"], "audio": ["token_roundtrip", "source_target_pair", "raw_audio_text_pair"], "reasoning": ["token_roundtrip", "source_target_pair", "local_answer_execution"], "tool": ["token_roundtrip", "source_target_pair", "typed_tool_execution"]}[capability],
        "admission": "ADMISSIBLE_SEMANTIC_CONTRACT",
        "semantic_model_contract_sha256": "f" * 64,
        "runtime_semantic_model_contract_sha256": "f" * 64,
    }


def _execution_slice(*, start_record: int = 0, record_count: int = 2, scene: bool = False) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "ember-specialist-execution-slice-v1",
        "start_record": start_record,
        "record_count": record_count,
        "token_count": record_count * 16,
        "records_sha256": "1" * 64,
        "tokens_sha256": "2" * 64,
    }
    if scene:
        receipt["scene_split_record_count"] = 2
    return receipt

def _scene_selection() -> dict[str, object]:
    return {
        "schema_version": "ember-specialist-scene-split-selection-v1",
        "capability": "image", "scene_split": "train",
        "full_records_artifact_sha256": "e" * 64,
        "selected_record_count": 2, "selected_token_count": 32,
        "selected_records_sha256": "1" * 64, "selected_tokens_sha256": "2" * 64,
    }

def _write_root(model: UnifiedDecoder, optimizer: torch.optim.Optimizer, root: Path) -> dict[str, object]:
    model._activate_expert("shared")
    return write_checkpoint_artifacts(
        model, optimizer, root, launch_seed=83, rng_state=_rng_state(),
        data_cursor={"shard": "TOKEN-SHARDS-V0:test", "record_index": 1, "global_step": 1, "tokens_seen": 16},
        model_config_sha256="c" * 64, contract_sha256="d" * 64,
        expert_genesis_sha256=model.expert_bank_genesis_hashes(),
    )


class SpecialistLineageTests(unittest.TestCase):
    def test_legacy_shared_v3_bridge_helper_is_absent(self) -> None:
        """First accretion starts from one immutable v3 parent/root, not an inferred bridge."""
        import checkpoint_artifacts

        self.assertFalse(hasattr(checkpoint_artifacts, "_v3_shared_continuation_history"))

    def _root_and_candidate(self, base: Path) -> tuple[dict[str, object], Path, UnifiedDecoder, torch.optim.Optimizer]:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        manifest_path = base / "root" / "checkpoint-manifest.json"
        if not manifest_path.is_file():
            root_model = UnifiedDecoder(config, genesis_seed=83)
            root_optimizer = torch.optim.AdamW(root_model.parameters(), lr=1e-4)
            _write_root(root_model, root_optimizer, base / "root")
        parent = published_checkpoint_receipt(base / "root")
        candidate = UnifiedDecoder(config, genesis_seed=991)
        optimizer = torch.optim.AdamW(candidate.parameters(), lr=1e-4)
        load_checkpoint_artifacts(candidate, optimizer, base / "root", {**parent, "checkpoint_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()})
        candidate._activate_expert("vision")
        return parent, manifest_path, candidate, optimizer

    def _write_vision_successor(self, base: Path, *, parent_manifest: Path | None = None, root_manifest: Path | None = None, trained: list[str] | None = None, max_serialized_bytes: int | None = None, verification: dict[str, object] | None = None, execution_slice: dict[str, object] | None = None) -> dict[str, object]:
        parent, default_manifest, candidate, optimizer = self._root_and_candidate(base)
        parent_manifest = parent_manifest or default_manifest
        root_manifest = root_manifest or default_manifest
        next(parameter for name, parameter in candidate.named_parameters() if ".experts.vision." in name).data.add_(1)
        return write_checkpoint_artifacts(
            candidate, optimizer, base / "candidate", launch_seed=999, rng_state=_rng_state(),
            data_cursor={"shard": "verified-vision", "record_index": 2, "global_step": 2, "tokens_seen": 32},
            model_config_sha256="c" * 64, contract_sha256="d" * 64,
            expert_genesis_sha256=parent["expert_genesis_sha256"],
            specialist_lineage={
                "parent_manifest": parent_manifest,
                "root_manifest": root_manifest,
                "trained_expert_ids": trained if trained is not None else ["vision"],
                "data_verification_receipt": _verification() if verification is None else verification,
                "execution_slice": _execution_slice(scene=True) if execution_slice is None else execution_slice,
                "scene_split_selection": _scene_selection(),
            },
            max_serialized_bytes=max_serialized_bytes,
        )

    def test_first_v4_successor_binds_external_parent_root_exact_history_and_closed_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            parent, parent_manifest, _candidate, _optimizer = self._root_and_candidate(base)
            receipt = self._write_vision_successor(base, parent_manifest=parent_manifest, root_manifest=parent_manifest)
            parent_sha256 = hashlib.sha256(parent_manifest.read_bytes()).hexdigest()
        self.assertEqual(receipt["schema_version"], "ember-sparse-checkpoint-v5")
        self.assertEqual(receipt["contract_version"], 5)
        self.assertEqual(receipt["lineage"]["parent_checkpoint_sha256"], parent_sha256)
        self.assertEqual(receipt["lineage"]["root_genesis_checkpoint_sha256"], parent_sha256)
        self.assertEqual(receipt["lineage"]["trained_expert_ids"], ["vision"])
        self.assertEqual(receipt["lineage"]["episode"]["active_expert"], "vision")
        self.assertEqual(receipt["lineage"]["episode"]["data_verification_receipt"], _verification())
        self.assertEqual(receipt["lineage"]["episode"]["execution_slice"], _execution_slice(scene=True))
        self.assertEqual(receipt["lineage"]["episode"]["scene_split_selection"], _scene_selection())
        self.assertNotIn("parent_manifest", json.dumps(receipt))
        self.assertNotIn("root_manifest", json.dumps(receipt))
        self.assertEqual(parent["active_expert_ids"], ["shared"])

    def test_vision_episode_slice_from_runner_builder_publishes_and_sceneless_is_refused(self) -> None:
        """#1457: the publication callback rebuilds the execution slice per episode with
        run_vertical_slice.specialist_execution_slice_receipt. For a vision lineage the
        rebuild must thread the planned slice's scene_split_record_count through — the
        first certified image canary trained its full 200 records and then failed every
        publication because the episode rebuild dropped the key while the lineage spread
        kept scene_split_selection. This test binds the runner's builder to this writer's
        vision shape requirement so the two cannot silently disagree again."""
        from run_vertical_slice import specialist_execution_slice_receipt

        records = [
            {"token_ids": list(range(16)), "scene_split": "train", "active_expert": "vision"},
            {"token_ids": list(range(16)), "scene_split": "train", "active_expert": "vision"},
        ]
        planned = specialist_execution_slice_receipt(records, source_start_record=0, scene_split_record_count=2)
        episode = specialist_execution_slice_receipt(
            records[0:2],
            source_start_record=int(planned["start_record"]) + 0,
            scene_split_record_count=planned.get("scene_split_record_count"),
        )
        sceneless_episode = specialist_execution_slice_receipt(records[0:2], source_start_record=0)

        with tempfile.TemporaryDirectory() as directory:
            receipt = self._write_vision_successor(Path(directory), execution_slice=episode)
            self.assertEqual(receipt["lineage"]["episode"]["execution_slice"]["scene_split_record_count"], 2)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "execution slice has an invalid shape"):
                self._write_vision_successor(Path(directory), execution_slice=sceneless_episode)

    def test_specialist_successor_rejects_semantic_admission_or_runtime_contract_drift(self) -> None:
        for name, mutate, expected in [
            (
                "admission",
                lambda receipt: receipt.update(admission="NON_ADMISSIBLE_LEGACY"),
                "lacks semantic-contract admission",
            ),
            (
                "runtime-contract",
                lambda receipt: receipt.update(runtime_semantic_model_contract_sha256="0" * 64),
                "semantic contract differs from runtime",
            ),
        ]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                verification = _verification()
                mutate(verification)
                with self.assertRaisesRegex(ValueError, expected):
                    self._write_vision_successor(
                        Path(directory), verification=verification
                    )

    def test_first_successor_rejects_unreceipted_shared_v3_continuation(self) -> None:
        """Equal specialist bytes cannot launder an arbitrary shared-core v3 mutation."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, root_manifest, _candidate, _optimizer = self._root_and_candidate(base)
            config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
            shared = UnifiedDecoder(config, genesis_seed=101)
            shared_optimizer = torch.optim.AdamW(shared.parameters(), lr=1e-4)
            load_checkpoint_artifacts(shared, shared_optimizer, base / "root", {**root, "checkpoint_manifest_sha256": hashlib.sha256(root_manifest.read_bytes()).hexdigest()})
            shared._activate_expert("shared")
            next(parameter for name, parameter in shared.named_parameters() if ".experts." not in name).data.add_(1)
            step2 = write_checkpoint_artifacts(
                shared, shared_optimizer, base / "step2", launch_seed=83, rng_state=_rng_state(),
                data_cursor={"shard": "TOKEN-SHARDS-V0:test", "record_index": 2, "global_step": 2, "tokens_seen": 32},
                model_config_sha256="c" * 64, contract_sha256="d" * 64,
                expert_genesis_sha256=root["expert_genesis_sha256"],
            )
            step2_manifest = base / "step2" / "checkpoint-manifest.json"
            step2_sha256 = hashlib.sha256(step2_manifest.read_bytes()).hexdigest()
            root_sha256 = hashlib.sha256(root_manifest.read_bytes()).hexdigest()
            candidate = UnifiedDecoder(config, genesis_seed=202)
            candidate_optimizer = torch.optim.AdamW(candidate.parameters(), lr=1e-4)
            load_checkpoint_artifacts(candidate, candidate_optimizer, base / "step2", {**step2, "checkpoint_manifest_sha256": step2_sha256})
            candidate._activate_expert("vision")
            next(parameter for name, parameter in candidate.named_parameters() if ".experts.vision." in name).data.add_(1)
            with self.assertRaisesRegex(ValueError, "exact parent and root"):
                write_checkpoint_artifacts(
                    candidate, candidate_optimizer, base / "vision", launch_seed=84, rng_state=_rng_state(),
                    data_cursor={"shard": "VERIFIED_SPECIALIST:test", "record_index": 1, "global_step": 3, "tokens_seen": 48},
                    model_config_sha256="c" * 64, contract_sha256="d" * 64,
                    expert_genesis_sha256=root["expert_genesis_sha256"],
                    specialist_lineage={
                        "parent_manifest": step2_manifest, "root_manifest": root_manifest,
                        "trained_expert_ids": ["vision"], "data_verification_receipt": _verification(), "execution_slice": _execution_slice(scene=True),
                "scene_split_selection": _scene_selection(),
                    },
                )
    def test_first_successor_requires_parent_and_root_to_be_the_same_genesis_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self._root_and_candidate(base)
            second_root = base / "other-root"
            model = UnifiedDecoder(RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64), genesis_seed=99)
            _write_root(model, torch.optim.AdamW(model.parameters(), lr=1e-4), second_root)
            with self.assertRaisesRegex(ValueError, "parent and root"):
                self._write_vision_successor(base, root_manifest=second_root / "checkpoint-manifest.json")

    def test_specialist_writer_rejects_missing_or_non_content_addressed_parent_or_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            missing = base / "missing" / "checkpoint-manifest.json"
            with self.assertRaisesRegex(ValueError, "parent manifest"):
                self._write_vision_successor(base, parent_manifest=missing)
            with self.assertRaisesRegex(ValueError, "root genesis manifest"):
                self._write_vision_successor(base, root_manifest=missing)
            self.assertFalse(list(base.glob(".candidate.*.staging")))

    def test_external_manifest_hashes_and_parses_one_byte_snapshot(self) -> None:
        """Authority binding cannot hash one manifest revision and parse another."""
        import checkpoint_artifacts
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self._root_and_candidate(base)
            manifest_path = base / "root" / "checkpoint-manifest.json"
            original_bytes = Path.read_bytes
            original_text = Path.read_text
            reads = 0

            def read_bytes_once(path: Path, *args: object, **kwargs: object) -> bytes:
                nonlocal reads
                if path.resolve() == manifest_path.resolve():
                    reads += 1
                return original_bytes(path, *args, **kwargs)

            def reject_manifest_text(path: Path, *args: object, **kwargs: object) -> str:
                if path.resolve() == manifest_path.resolve():
                    raise AssertionError("manifest must be parsed from its authority bytes")
                return original_text(path, *args, **kwargs)

            with patch.object(Path, "read_bytes", new=read_bytes_once), patch.object(Path, "read_text", new=reject_manifest_text):
                _manifest, digest = checkpoint_artifacts._external_checkpoint_manifest(manifest_path, label="parent")
            self.assertEqual(reads, 1)
            self.assertEqual(digest, hashlib.sha256(original_bytes(manifest_path)).hexdigest())
    def test_lineage_source_preflight_rejects_missing_root_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self._root_and_candidate(base)
            parent_manifest = base / "root" / "checkpoint-manifest.json"
            with self.assertRaisesRegex(ValueError, "root genesis manifest"):
                preflight_specialist_lineage_sources(
                    parent_manifest=parent_manifest,
                    root_manifest=base / "missing" / "checkpoint-manifest.json",
                )
    def test_lineage_source_preflight_rejects_tampered_parent_before_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self._root_and_candidate(base)
            manifest = base / "root" / "checkpoint-manifest.json"
            (base / "root" / "expert-tool.pt").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                preflight_specialist_lineage_sources(parent_manifest=manifest, root_manifest=manifest)
            self.assertFalse(list(base.glob(".candidate.*.staging")))
    def test_specialist_writer_rejects_tampered_parent_shard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self._root_and_candidate(base)
            parent_manifest = base / "root" / "checkpoint-manifest.json"
            (base / "root" / "expert-audio.pt").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                self._write_vision_successor(base, parent_manifest=parent_manifest, root_manifest=parent_manifest)

    def test_specialist_writer_rejects_active_unchanged_and_inactive_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            parent, parent_manifest, candidate, optimizer = self._root_and_candidate(base)
            with self.assertRaisesRegex(ValueError, "active expert parameter content"):
                write_checkpoint_artifacts(candidate, optimizer, base / "same", launch_seed=999, rng_state=_rng_state(), data_cursor={"shard": "verified-vision", "record_index": 2, "global_step": 2, "tokens_seen": 32}, model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=parent["expert_genesis_sha256"], specialist_lineage={"parent_manifest": parent_manifest, "root_manifest": parent_manifest, "trained_expert_ids": ["vision"], "data_verification_receipt": _verification(), "execution_slice": _execution_slice(scene=True), "scene_split_selection": _scene_selection()})
            next(parameter for name, parameter in candidate.named_parameters() if ".experts.vision." in name).data.add_(1)
            next(parameter for name, parameter in candidate.named_parameters() if ".experts.audio." in name).data.add_(1)
            with self.assertRaisesRegex(ValueError, "inactive expert.*parent"):
                write_checkpoint_artifacts(candidate, optimizer, base / "drift", launch_seed=999, rng_state=_rng_state(), data_cursor={"shard": "verified-vision", "record_index": 2, "global_step": 2, "tokens_seen": 32}, model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=parent["expert_genesis_sha256"], specialist_lineage={"parent_manifest": parent_manifest, "root_manifest": parent_manifest, "trained_expert_ids": ["vision"], "data_verification_receipt": _verification(), "execution_slice": _execution_slice(scene=True), "scene_split_selection": _scene_selection()})

    def test_specialist_writer_rejects_wrong_history_or_capability_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with self.assertRaisesRegex(ValueError, "history union"):
                self._write_vision_successor(base, trained=[])
            base = Path(directory) / "capability"
            parent, parent_manifest, candidate, optimizer = self._root_and_candidate(base)
            next(parameter for name, parameter in candidate.named_parameters() if ".experts.vision." in name).data.add_(1)
            with self.assertRaisesRegex(ValueError, "capability"):
                write_checkpoint_artifacts(candidate, optimizer, base / "candidate", launch_seed=999, rng_state=_rng_state(), data_cursor={"shard": "verified-vision", "record_index": 2, "global_step": 2, "tokens_seen": 32}, model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=parent["expert_genesis_sha256"], specialist_lineage={"parent_manifest": parent_manifest, "root_manifest": parent_manifest, "trained_expert_ids": ["vision"], "data_verification_receipt": _verification("audio"), "execution_slice": _execution_slice(scene=True), "scene_split_selection": _scene_selection()})



    def test_v4_requires_parameter_content_digests_and_canonical_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            parent, parent_manifest, candidate, optimizer = self._root_and_candidate(base)
            next(parameter for name, parameter in candidate.named_parameters() if ".experts.vision." in name).data.add_(1)
            receipt = write_checkpoint_artifacts(candidate, optimizer, base / "candidate", launch_seed=999, rng_state=_rng_state(), data_cursor={"shard": "verified-vision", "record_index": 2, "global_step": 2, "tokens_seen": 32}, model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=parent["expert_genesis_sha256"], specialist_lineage={"parent_manifest": parent_manifest, "root_manifest": parent_manifest, "trained_expert_ids": ["vision"], "data_verification_receipt": _verification(), "execution_slice": _execution_slice(scene=True), "scene_split_selection": _scene_selection()})
        self.assertEqual(set(receipt["expert_parameter_sha256"]), {"vision", "audio", "reasoning", "tool"})
        self.assertNotEqual(receipt["expert_parameter_sha256"]["vision"], parent["expert_genesis_sha256"]["vision"])

    def test_specialist_hardlink_reuse_charges_zero_incremental_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            receipt = self._write_vision_successor(base)
            parent = base / "root"
            candidate = base / "candidate"
            records = {record["role"]: record for record in receipt["shards"]}
            for name in ("audio", "reasoning", "tool"):
                source = parent / f"expert-{name}.pt"
                reused = candidate / f"expert-{name}.pt"
                self.assertEqual(source.stat().st_dev, reused.stat().st_dev)
                self.assertEqual(source.stat().st_ino, reused.stat().st_ino)
                self.assertGreater(reused.stat().st_nlink, 1)
                self.assertEqual(records[f"expert_{name}"]["publication_mode"], "hardlink")
                self.assertEqual(records[f"expert_{name}"]["incremental_bytes"], 0)
        self.assertLess(receipt["incremental_publication_bytes"], receipt["serialized_bytes"])

    def test_writer_applies_the_cap_to_incremental_publication_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            probe = self._write_vision_successor(base / "probe")
            cap = int(probe["incremental_publication_bytes"]) + 1024
            linked = self._write_vision_successor(base / "linked", max_serialized_bytes=cap)
            self.assertLessEqual(linked["incremental_publication_bytes"], cap)
            self.assertGreater(linked["serialized_bytes"], cap)
            import checkpoint_artifacts
            with patch.object(checkpoint_artifacts.os, "link", side_effect=OSError("forced copy fallback")):
                with self.assertRaisesRegex(RuntimeError, "serialized checkpoint exceeds"):
                    self._write_vision_successor(base / "copied", max_serialized_bytes=cap)
            self.assertFalse((base / "copied" / "candidate").exists())
    def test_specialist_copy_fallback_charges_full_reused_shard_bytes(self) -> None:
        import checkpoint_artifacts

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with patch.object(checkpoint_artifacts.os, "link", side_effect=OSError("forced copy fallback")):
                receipt = self._write_vision_successor(base)
            records = {record["role"]: record for record in receipt["shards"]}
            for name in ("audio", "reasoning", "tool"):
                record = records[f"expert_{name}"]
                self.assertEqual(record["publication_mode"], "copy")
                self.assertEqual(record["incremental_bytes"], record["bytes"])
        self.assertEqual(receipt["incremental_publication_bytes"], receipt["serialized_bytes"])
    def test_specialist_writer_rejects_noncanonical_semantic_checks_and_boolean_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            parent, parent_manifest, candidate, optimizer = self._root_and_candidate(base)
            next(parameter for name, parameter in candidate.named_parameters() if ".experts.vision." in name).data.add_(1)
            bad = _verification()
            bad["semantic_checks"] = ["locally_derived"]
            with self.assertRaisesRegex(ValueError, "semantic checks"):
                write_checkpoint_artifacts(candidate, optimizer, base / "bad-checks", launch_seed=999, rng_state=_rng_state(), data_cursor={"shard": "verified-vision", "record_index": 2, "global_step": 2, "tokens_seen": 32}, model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=parent["expert_genesis_sha256"], specialist_lineage={"parent_manifest": parent_manifest, "root_manifest": parent_manifest, "trained_expert_ids": ["vision"], "data_verification_receipt": bad, "execution_slice": _execution_slice(scene=True), "scene_split_selection": _scene_selection()})
            bad = _verification()
            bad["record_count"] = True
            with self.assertRaisesRegex(ValueError, "training evidence"):
                write_checkpoint_artifacts(candidate, optimizer, base / "bad-count", launch_seed=999, rng_state=_rng_state(), data_cursor={"shard": "verified-vision", "record_index": 2, "global_step": 2, "tokens_seen": 32}, model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=parent["expert_genesis_sha256"], specialist_lineage={"parent_manifest": parent_manifest, "root_manifest": parent_manifest, "trained_expert_ids": ["vision"], "data_verification_receipt": bad, "execution_slice": _execution_slice(scene=True), "scene_split_selection": _scene_selection()})


    def test_writer_refuses_unrecorded_staging_files_before_promotion(self) -> None:
        import checkpoint_artifacts

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
            model = UnifiedDecoder(config, genesis_seed=83)
            optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
            original = checkpoint_artifacts._write_json_atomic

            def write_manifest_then_plant_unrecorded(root: Path, filename: str, payload: object, **kwargs: object) -> Path:
                manifest_path = original(root, filename, payload, **kwargs)
                (root / "unrecorded.bin").write_bytes(b"unaccounted")
                return manifest_path

            with patch.object(checkpoint_artifacts, "_write_json_atomic", side_effect=write_manifest_then_plant_unrecorded):
                with self.assertRaisesRegex(ValueError, "unrecorded files"):
                    write_checkpoint_artifacts(
                        model, optimizer, base / "candidate", launch_seed=83, rng_state=_rng_state(),
                        data_cursor={"shard": "test", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                        model_config_sha256="c" * 64, contract_sha256="d" * 64,
                        expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                    )
            self.assertFalse((base / "candidate").exists())
            self.assertFalse(list(base.glob(".candidate.*.staging")))
    def test_writer_cleans_only_generated_staging_directory_after_write_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
            model = UnifiedDecoder(config, genesis_seed=83)
            optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
            import checkpoint_artifacts
            original = checkpoint_artifacts._write_atomic
            def fail_replay(root: Path, filename: str, writer: object, **kwargs: object) -> Path:
                if filename == "replay-state.pt":
                    raise RuntimeError("injected write failure")
                return original(root, filename, writer, **kwargs)
            with patch.object(checkpoint_artifacts, "_write_atomic", side_effect=fail_replay):
                with self.assertRaisesRegex(RuntimeError, "injected write failure"):
                    write_checkpoint_artifacts(model, optimizer, base / "failed", launch_seed=83, rng_state=_rng_state(), data_cursor={"shard": "test", "record_index": 0, "global_step": 0, "tokens_seen": 0}, model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes())
            self.assertFalse((base / "failed").exists())
            self.assertFalse(list(base.glob(".failed.*.staging")))


    def test_later_successor_keeps_immutable_root_and_exact_union_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first = self._write_vision_successor(base)
            first_manifest_path = base / "candidate" / "checkpoint-manifest.json"
            root_manifest_path = base / "root" / "checkpoint-manifest.json"
            root_sha256 = hashlib.sha256(root_manifest_path.read_bytes()).hexdigest()
            config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
            model = UnifiedDecoder(config, genesis_seed=7)
            optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
            load_checkpoint_artifacts(model, optimizer, base / "candidate", {**first, "checkpoint_manifest_sha256": hashlib.sha256(first_manifest_path.read_bytes()).hexdigest()})
            model._activate_expert("audio")
            next(parameter for name, parameter in model.named_parameters() if ".experts.audio." in name).data.add_(1)
            second = write_checkpoint_artifacts(model, optimizer, base / "second", launch_seed=1001, rng_state=_rng_state(), data_cursor={"shard": "verified-audio", "record_index": 3, "global_step": 3, "tokens_seen": 48}, model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256={"vision": "0" * 64, "audio": "0" * 64, "reasoning": "0" * 64, "tool": "0" * 64}, specialist_lineage={"parent_manifest": first_manifest_path, "root_manifest": root_manifest_path, "trained_expert_ids": ["vision", "audio"], "data_verification_receipt": _verification("audio"), "execution_slice": _execution_slice(start_record=2)})
        self.assertEqual(second["lineage"]["root_genesis_checkpoint_sha256"], root_sha256)
        self.assertEqual(second["lineage"]["trained_expert_ids"], ["vision", "audio"])
        self.assertEqual(second["expert_checkpoint_sha256"]["vision"], first["expert_checkpoint_sha256"]["vision"])
        self.assertEqual(second["expert_parameter_sha256"]["tool"], first["expert_parameter_sha256"]["tool"])

    def test_writer_refuses_actual_bundle_above_derived_byte_bound_before_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
            model = UnifiedDecoder(config, genesis_seed=83)
            optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
            with self.assertRaisesRegex(RuntimeError, "serialized checkpoint exceeds"):
                write_checkpoint_artifacts(
                    model, optimizer, base / "too-large", launch_seed=83, rng_state=_rng_state(),
                    data_cursor={"shard": "test", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                    model_config_sha256="c" * 64, contract_sha256="d" * 64,
                    expert_genesis_sha256=model.expert_bank_genesis_hashes(), max_serialized_bytes=1,
                )
            self.assertFalse((base / "too-large").exists())
            self.assertFalse(list(base.glob(".too-large.*.staging")))


class SpecialistInheritedOptimizerRouteTests(unittest.TestCase):
    """#1473: the first R2 specialist entry exact-resumed the full-coverage r1
    root, inherited its four-route post-update optimizer state verbatim through
    load_checkpoint_artifacts' optimizer.load_state_dict, trained one routed
    family, and lost its whole trained segment when
    _derive_checkpoint_storage_projection admitted only [active] for a lineage
    episode. These bind the cured admission end to end: a parent whose
    digest-bound storage projection attests all four initialized routes makes
    the inherited state publishable, while a parent that attests nothing keeps
    the strict single-route refusal."""

    def _full_coverage_root(self, base: Path, *, with_projection: bool) -> tuple[dict[str, object], Path]:
        from checkpoint_artifacts import EXPERT_NAMES

        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=83)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        for expert in EXPERT_NAMES:
            optimizer.zero_grad(set_to_none=True)
            model(torch.tensor([[1, 2, 3]], dtype=torch.long), active_expert=expert).float().square().mean().backward()
            optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        caps = (
            {
                "optimizer_state_layout": "owner-sharded-v1",
                "max_transient_scratch_bytes": 1024**3,
                "max_serialized_bytes": 1024**3,
            }
            if with_projection
            else {}
        )
        receipt = write_checkpoint_artifacts(
            model, optimizer, base / "root", launch_seed=83, rng_state=_rng_state(),
            data_cursor={"shard": "TOKEN-SHARDS-V0:test", "record_index": 4, "global_step": 4, "tokens_seen": 12},
            model_config_sha256="c" * 64, contract_sha256="d" * 64,
            expert_genesis_sha256=model.expert_bank_genesis_hashes(),
            **caps,
        )
        return receipt, base / "root" / "checkpoint-manifest.json"

    def _resumed_vision_candidate(self, base: Path, root_receipt: dict[str, object], manifest_path: Path) -> tuple[UnifiedDecoder, torch.optim.Optimizer]:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        candidate = UnifiedDecoder(config, genesis_seed=991)
        optimizer = torch.optim.AdamW(candidate.parameters(), lr=1e-4)
        load_checkpoint_artifacts(candidate, optimizer, base / "root", {**root_receipt, "checkpoint_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()})
        candidate._activate_expert("vision")
        optimizer.zero_grad(set_to_none=True)
        candidate(torch.tensor([[1, 2, 3]], dtype=torch.long), active_expert="vision").float().square().mean().backward()
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        return candidate, optimizer

    def _publish_vision_successor(self, base: Path, candidate: UnifiedDecoder, optimizer: torch.optim.Optimizer, root_receipt: dict[str, object], manifest_path: Path) -> dict[str, object]:
        return write_checkpoint_artifacts(
            candidate, optimizer, base / "candidate", launch_seed=999, rng_state=_rng_state(),
            data_cursor={"shard": "verified-vision", "record_index": 2, "global_step": 6, "tokens_seen": 44},
            model_config_sha256="c" * 64, contract_sha256="d" * 64,
            expert_genesis_sha256=root_receipt["expert_genesis_sha256"],
            specialist_lineage={
                "parent_manifest": manifest_path, "root_manifest": manifest_path,
                "trained_expert_ids": ["vision"], "data_verification_receipt": _verification(),
                "execution_slice": _execution_slice(scene=True), "scene_split_selection": _scene_selection(),
            },
            max_transient_scratch_bytes=1024**3, max_serialized_bytes=1024**3,
        )

    def test_root_resumed_specialist_episode_publishes_inherited_four_route_state(self) -> None:
        import checkpoint_artifacts

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root_receipt, manifest_path = self._full_coverage_root(base, with_projection=True)
            self.assertEqual(
                root_receipt["storage_projection"]["optimizer_state_active_expert_ids"],
                list(checkpoint_artifacts.EXPERT_NAMES),
            )
            candidate, optimizer = self._resumed_vision_candidate(base, root_receipt, manifest_path)
            receipt = self._publish_vision_successor(base, candidate, optimizer, root_receipt, manifest_path)
            projection = receipt["storage_projection"]
            self.assertEqual(projection["active_expert"], "vision")
            self.assertEqual(
                projection["optimizer_state_active_expert_ids"],
                list(checkpoint_artifacts.EXPERT_NAMES),
            )
            for route in ("shared", *checkpoint_artifacts.EXPERT_NAMES):
                self.assertGreater(projection["optimizer_state_tensor_storage_by_route_bytes"][route], 0)
            # Inherited full realization projects at factor 1: the state itself
            # is already the all-expert floor.
            self.assertEqual(
                projection["projected_all_expert_optimizer_state_tensor_storage_lower_bound_bytes"],
                projection["optimizer_state_tensor_storage_lower_bound_bytes"],
            )
            self.assertEqual(receipt["lineage"]["trained_expert_ids"], ["vision"])
            checkpoint_artifacts._validate_checkpoint_storage_projection(projection)
            checkpoint_artifacts._measure_candidate_storage_projection(base / "candidate", projection)

    def test_unattested_parent_keeps_strict_single_route_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root_receipt, manifest_path = self._full_coverage_root(base, with_projection=False)
            self.assertNotIn("storage_projection", root_receipt)
            candidate, optimizer = self._resumed_vision_candidate(base, root_receipt, manifest_path)
            with self.assertRaisesRegex(ValueError, "requires one post-update optimizer state"):
                self._publish_vision_successor(base, candidate, optimizer, root_receipt, manifest_path)
            self.assertFalse((base / "candidate").exists())
            self.assertFalse(list(base.glob(".candidate.*.staging")))


if __name__ == "__main__":
    unittest.main()
