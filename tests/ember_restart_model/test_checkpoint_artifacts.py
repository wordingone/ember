# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD checkpoint artifacts for the sparse vertical slice."""

from __future__ import annotations

import os
import hashlib
import json
import sys
import tempfile
import warnings
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

import checkpoint_artifacts
import durable_io

from checkpoint_artifacts import _default_optimizer_contract, _optimizer_realization, _select_detached_state, _validate_runtime_optimizer_realization, admit_quarantined_checkpoint, checkpoint_commit_preflight, configured_maximum_available_commit_bytes, load_checkpoint_artifacts, load_checkpoint_model_only_transition, write_checkpoint_artifacts as _write_checkpoint_artifacts_public
from model import RestartDecoderConfig, UnifiedDecoder
from parameter_counter import measure_parameter_counts
from run_vertical_slice import load_optimizer_contract
from specialist_stream import SELECTION_CURSOR_SCHEMA_VERSION, TRAINING_CURSOR_SCHEMA_VERSION

def _counter_receipt(candidate: Path, manifest_receipt: dict[str, object]) -> dict[str, object]:
    architecture = manifest_receipt["architecture"]
    payload = {
        "schema_version": "ember-sparse-realization-receipt-v1",
        "verification_boundary": "VERIFIED_MEASURED",
        "result": "MEASURED",
        "subject_checkpoint_sha256": manifest_receipt["checkpoint_manifest_sha256"],
        "model_config_sha256": manifest_receipt["model_config_sha256"],
        "architecture_revision": manifest_receipt["architecture_revision"],
        "counter_sha256": hashlib.sha256((ROOT / "tools" / "ember-restart-3b" / "parameter_counter.py").read_bytes()).hexdigest(),
        "runtime_authority": {
            "schema_version": "ember-counter-runtime-authority-v1",
            "kind": "NONE",
        },
        "active_expert_ids": manifest_receipt["active_expert_ids"],
        "expert_genesis_sha256": manifest_receipt["expert_genesis_sha256"],
        "expert_parameter_sha256": manifest_receipt["expert_parameter_sha256"],
    }
    for field in ("allocated_parameters", "unique_parameters", "trainable_parameters", "served_parameters", "active_parameters", "episode_trainable_parameters"):
        payload[field] = architecture[field]
    (candidate / "parameter-counter-receipt.json").write_text(json.dumps(payload, sort_keys=True) + chr(10), encoding="utf-8")
    return payload


def write_checkpoint_artifacts(*args, **kwargs):
    kwargs.pop("test_only_allow_unverified", None)
    kwargs.setdefault("pre_publish_verifier", _counter_receipt)
    return _write_checkpoint_artifacts_public(*args, **kwargs)


def _valid_rng_state() -> dict[str, torch.Tensor]:
    return {
        "cpu": torch.get_rng_state().clone(),
        "cuda": (
            torch.cuda.get_rng_state().clone()
            if torch.cuda.is_available()
            else torch.tensor([1, 2, 3], dtype=torch.uint8)
        ),
    }



class CheckpointArtifactTests(unittest.TestCase):
    def test_model_only_transition_streams_model_shards_and_discards_optimizer_payload(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        source = UnifiedDecoder(config, genesis_seed=11)
        source._activate_expert("shared")
        target = UnifiedDecoder(config, genesis_seed=12)
        source_state = source.state_dict()
        old_contract = {
            "name": "paged_8bit_adamw",
            "implementation": "bitsandbytes.optim.PagedAdamW8bit",
            "hyperparameters": {"learning_rate": 1e-5, "weight_decay": 0.01, "percentile_clipping": 100, "block_wise": True},
            "state_format": "bitsandbytes-paged-8bit-adamw-state-dict-v1",
        }
        old_realization = {
            "implementation": old_contract["implementation"],
            "implementation_source_sha256": "a" * 64,
            "state_format": old_contract["state_format"],
            "optimizer_contract_sha256": hashlib.sha256(json.dumps(old_contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            torch.save({
                "model": _select_detached_state(source_state, lambda name: ".experts." not in name),
                "optimizer": {"state": {0: {"step": torch.tensor(2), "state1": torch.ones(4)}}, "param_groups": [{"params": [0]}]},
                "optimizer_contract": old_contract,
                "optimizer_realization": old_realization,
            }, root / "shared.pt")
            cuda_rng_state = torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8)
            torch.save({"rng_state": {"cpu": torch.get_rng_state().clone(), "cuda": cuda_rng_state}, "data_cursor": {"global_step": 2, "record_index": 2, "tokens_seen": 2048}}, root / "replay-state.pt")
            expert_hashes = {}
            for name in ("vision", "audio", "reasoning", "tool"):
                path = root / f"expert-{name}.pt"
                torch.save({"expert": name, "model": _select_detached_state(source_state, lambda key, selected=name: f".experts.{selected}." in key)}, path)
                expert_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            shard_paths = ["shared.pt", "replay-state.pt", "expert-vision.pt", "expert-audio.pt", "expert-reasoning.pt", "expert-tool.pt"]
            shards = [{"path": name, "bytes": (root / name).stat().st_size, "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest()} for name in shard_paths]
            manifest = {
                "schema_version": "ember-sparse-checkpoint-v3",
                "optimizer_contract": old_contract,
                "optimizer_realization": old_realization,
                "expert_checkpoint_sha256": expert_hashes,
                "expert_genesis_sha256": source.expert_bank_genesis_hashes(),
                "active_expert_ids": ["shared"],
                "data_cursor": {"global_step": 2, "record_index": 2, "tokens_seen": 2048},
                "shards": shards,
            }
            manifest_path = root / "checkpoint-manifest.json"
            manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
            real_torch_load = torch.load
            load_calls = []
            def recorded_load(*args, **kwargs):
                load_calls.append((Path(args[0]).name, dict(kwargs)))
                return real_torch_load(*args, **kwargs)
            with patch("checkpoint_artifacts.torch.load", side_effect=recorded_load):
                loaded = load_checkpoint_model_only_transition(target, root, {**manifest, "checkpoint_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()})
        self.assertEqual(loaded["data_cursor"]["global_step"], 2)
        self.assertEqual([name for name, _ in load_calls], ["replay-state.pt", "shared.pt", "expert-vision.pt", "expert-audio.pt", "expert-reasoning.pt", "expert-tool.pt"])
        self.assertTrue(all(kwargs.get("mmap") is True for _, kwargs in load_calls))
        for key, tensor in source.state_dict().items():
            self.assertTrue(torch.equal(tensor, target.state_dict()[key]), key)

    def test_model_only_transition_reads_v5_split_model_without_loading_optimizer_shard(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        source = UnifiedDecoder(config, genesis_seed=21)
        source._activate_expert("shared")
        target = UnifiedDecoder(config, genesis_seed=22)
        source_state = source.state_dict()
        old_contract = {
            "name": "paged_8bit_adamw",
            "implementation": "bitsandbytes.optim.PagedAdamW8bit",
            "hyperparameters": {"learning_rate": 1e-5, "weight_decay": 0.01, "percentile_clipping": 100, "block_wise": True},
            "state_format": "bitsandbytes-paged-8bit-adamw-state-dict-v1",
        }
        old_realization = {
            "implementation": old_contract["implementation"],
            "implementation_source_sha256": "a" * 64,
            "state_format": old_contract["state_format"],
            "optimizer_contract_sha256": hashlib.sha256(json.dumps(old_contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        }
        cursor = {"global_step": 2, "record_index": 2, "tokens_seen": 2048}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            torch.save(
                {"model": _select_detached_state(source_state, lambda name: ".experts." not in name)},
                root / "shared-model.pt",
            )
            torch.save(
                {
                    "optimizer": {"state": {0: {"step": torch.tensor(2), "state1": torch.ones(4)}}, "param_groups": [{"params": [0]}]},
                    "optimizer_contract": old_contract,
                    "optimizer_realization": old_realization,
                },
                root / "optimizer-state.pt",
            )
            torch.save({"rng_state": _valid_rng_state(), "data_cursor": cursor}, root / "replay-state.pt")
            expert_hashes = {}
            for name in ("vision", "audio", "reasoning", "tool"):
                path = root / f"expert-{name}.pt"
                torch.save(
                    {"expert": name, "model": _select_detached_state(source_state, lambda key, selected=name: f".experts.{selected}." in key)},
                    path,
                )
                expert_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            shard_paths = [
                "shared-model.pt",
                "optimizer-state.pt",
                "replay-state.pt",
                "expert-vision.pt",
                "expert-audio.pt",
                "expert-reasoning.pt",
                "expert-tool.pt",
            ]
            shards = [
                {"path": name, "bytes": (root / name).stat().st_size, "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest()}
                for name in shard_paths
            ]
            manifest = {
                "schema_version": "ember-sparse-checkpoint-v5",
                "optimizer_contract": old_contract,
                "optimizer_realization": old_realization,
                "expert_checkpoint_sha256": expert_hashes,
                "expert_genesis_sha256": source.expert_bank_genesis_hashes(),
                "active_expert_ids": ["shared"],
                "data_cursor": cursor,
                "shared_model_shard_sha256": hashlib.sha256((root / "shared-model.pt").read_bytes()).hexdigest(),
                "optimizer_state_shard_sha256": hashlib.sha256((root / "optimizer-state.pt").read_bytes()).hexdigest(),
                "shards": shards,
            }
            manifest_path = root / "checkpoint-manifest.json"
            manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
            manifest["checkpoint_manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            real_torch_load = torch.load
            load_calls = []

            def recorded_load(*args, **kwargs):
                load_calls.append((Path(args[0]).name, dict(kwargs)))
                return real_torch_load(*args, **kwargs)

            with patch("checkpoint_artifacts.torch.load", side_effect=recorded_load):
                loaded = load_checkpoint_model_only_transition(target, root, manifest)
        self.assertEqual(loaded["data_cursor"]["global_step"], 2)
        self.assertEqual(
            [name for name, _ in load_calls],
            ["replay-state.pt", "shared-model.pt", "expert-vision.pt", "expert-audio.pt", "expert-reasoning.pt", "expert-tool.pt"],
        )
        self.assertNotIn("optimizer-state.pt", [name for name, _ in load_calls])
        for key, tensor in source.state_dict().items():
            self.assertTrue(torch.equal(tensor, target.state_dict()[key]), key)

    def test_model_only_transition_rejects_quarantined_bundle_before_receipt_validation(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=11)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".checkpoint-quarantine" / "candidate-valid"
            root.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "quarantined checkpoint"):
                load_checkpoint_model_only_transition(model, root, {"schema_version": "ember-sparse-checkpoint-v3"})

    def test_test_only_verifier_opt_out_cannot_leak_into_production_call_sites(self) -> None:
        tools_root = ROOT / "tools"
        offenders = []
        for path in tools_root.rglob("*.py"):
            if path.name == "checkpoint_artifacts.py":
                continue
            if "test_only_allow_unverified" in path.read_text(encoding="utf-8"):
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])

    def test_test_only_verifier_opt_out_is_private(self) -> None:
        import inspect
        self.assertNotIn("test_only_allow_unverified", inspect.signature(_write_checkpoint_artifacts_public).parameters)

    def test_noop_counter_callback_is_not_an_admission_verdict(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=15)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "checkpoint-noop-verifier"
            with self.assertRaisesRegex(ValueError, "counter receipt"):
                write_checkpoint_artifacts(
                    model, optimizer, target, launch_seed=15,
                    rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                    data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                    model_config_sha256="c" * 64, contract_sha256="d" * 64,
                    expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                    pre_publish_verifier=lambda _candidate, _receipt: None,
                )
            self.assertFalse(target.exists())
            self.assertTrue(any(path.is_dir() for path in (parent / ".checkpoint-quarantine").iterdir()))

    def test_checkpoint_publication_requires_realization_verifier_by_default(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=14)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "checkpoint-unverified"
            with self.assertRaisesRegex(ValueError, "pre-publish verifier is required"):
                _write_checkpoint_artifacts_public(
                    model, optimizer, target, launch_seed=14,
                    rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                    data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                    model_config_sha256="c" * 64, contract_sha256="d" * 64,
                    expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                )
            self.assertFalse(target.exists())

    def test_commit_preflight_requires_streaming_peak_plus_reserve(self) -> None:
        plan = checkpoint_commit_preflight(
            available_commit_bytes=10_000,
            streaming_peak_bytes=4_000,
            reserve_bytes=6_000,
        )
        self.assertEqual(plan["required_commit_bytes"], 10_000)
        with self.assertRaisesRegex(RuntimeError, "host commit reserve"):
            checkpoint_commit_preflight(
                available_commit_bytes=9_999,
                streaming_peak_bytes=4_000,
                reserve_bytes=6_000,
            )

    def test_checkpoint_capacity_uses_fixed_pagefile_maximum_not_current_limit(self) -> None:
        gib = 1024**3
        available = configured_maximum_available_commit_bytes(
            physical_ram_bytes=64 * gib,
            commit_total_bytes=60 * gib,
            current_commit_limit_bytes=80 * gib,
            paging_files=[r"C:\pagefile.sys 16384 32768"],
        )
        self.assertEqual(available, 36 * gib)
        for paging_files in (
            [r"C:\pagefile.sys 0 0"],
            [r"C:\pagefile.sys 16384 automatic"],
            [],
        ):
            with self.subTest(paging_files=paging_files), self.assertRaisesRegex(
                RuntimeError, "fixed positive maximum"
            ):
                configured_maximum_available_commit_bytes(
                    physical_ram_bytes=64 * gib,
                    commit_total_bytes=60 * gib,
                    current_commit_limit_bytes=80 * gib,
                    paging_files=paging_files,
                )
        with self.assertRaisesRegex(RuntimeError, "below the live Windows commit limit"):
            configured_maximum_available_commit_bytes(
                physical_ram_bytes=64 * gib,
                commit_total_bytes=60 * gib,
                current_commit_limit_bytes=100 * gib,
                paging_files=[r"C:\pagefile.sys 16384 32768"],
            )
        with self.assertRaisesRegex(RuntimeError, "live committed bytes exceed"):
            configured_maximum_available_commit_bytes(
                physical_ram_bytes=64 * gib,
                commit_total_bytes=100 * gib,
                current_commit_limit_bytes=80 * gib,
                paging_files=[r"C:\pagefile.sys 16384 32768"],
            )

    def test_serialization_state_views_reuse_tensor_storage_without_cpu_clones(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=10)
        source = model.state_dict()
        shared = _select_detached_state(source, lambda name: ".experts." not in name)
        vision = _select_detached_state(source, lambda name: ".experts.vision." in name)
        self.assertTrue(shared)
        self.assertTrue(vision)
        for selected in (shared, vision):
            for name, tensor in selected.items():
                self.assertEqual(tensor.device, source[name].device)
                self.assertEqual(tensor.data_ptr(), source[name].data_ptr())

    def test_checkpoint_atomic_write_fsyncs_parent_after_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls: list[int] = []
            def recording_fsync(descriptor: int) -> None:
                calls.append(descriptor)
            with patch.object(checkpoint_artifacts.os, "name", "posix"), \
                 patch.object(durable_io.os, "open", return_value=919) as open_directory, \
                 patch.object(durable_io.os, "close") as close_directory, \
                 patch.object(durable_io.os, "fsync", recording_fsync):
                checkpoint_artifacts._write_atomic(root, "receipt.json", lambda handle: handle.write(b"{}\n"))
            open_directory.assert_called_once_with(str(root), os.O_RDONLY)
            close_directory.assert_called_once_with(919)
            self.assertIn(919, calls)
    def test_preexisting_target_is_refused_before_staging_or_verifier(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=11)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "checkpoint-existing"
            target.mkdir()
            sentinel = target / "sentinel"
            sentinel.write_bytes(b"known-good")
            verifier = Mock()
            with self.assertRaisesRegex(FileExistsError, "already exists"):
                write_checkpoint_artifacts(
                    model, optimizer, target, launch_seed=11,
                    rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                    data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                    model_config_sha256="c" * 64, contract_sha256="d" * 64,
                    expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                    pre_publish_verifier=verifier,
                )
            self.assertEqual(sentinel.read_bytes(), b"known-good")
            self.assertFalse(verifier.called)
            self.assertEqual(list(Path(directory).glob(".*.staging")), [])
    def test_counter_verifier_runs_on_durable_quarantine_before_atomic_promotion(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=12)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "checkpoint-atomic"
            observations: list[tuple[bool, bool, bool, bool, bool]] = []

            def verify(candidate: Path, _receipt: dict[str, object]) -> dict[str, object]:
                observations.append((candidate.is_dir(), target.exists(), (candidate / "checkpoint-manifest.json").is_file(), candidate.parent.name == ".checkpoint-quarantine", (candidate / ".writer-lease.json").is_file()))
                return _counter_receipt(candidate, _receipt)

            with patch("checkpoint_artifacts.available_host_commit_bytes", return_value=1024**3):
                receipt = write_checkpoint_artifacts(
                    model, optimizer, target, launch_seed=12,
                    rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                    data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                    model_config_sha256="c" * 64, contract_sha256="d" * 64,
                    expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                    host_commit_reserve_bytes=128 * 1024**2,
                    pre_publish_verifier=verify,
                )
            self.assertEqual(observations, [(True, False, True, True, False)])
            self.assertTrue(target.joinpath("parameter-counter-receipt.json").is_file())
            self.assertFalse(target.joinpath(".writer-lease.json").exists())
            self.assertEqual(receipt["checkpoint_manifest_sha256"], __import__("hashlib").sha256(target.joinpath("checkpoint-manifest.json").read_bytes()).hexdigest())
            self.assertEqual(receipt["host_commit_preflight"]["available_commit_bytes"], 1024**3)
            self.assertEqual(receipt["host_commit_preflight"]["reserve_bytes"], 128 * 1024**2)

    def test_staging_failure_preserves_raw_bytes_in_durable_quarantine(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=13)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "checkpoint-staging-failed"
            arguments = {
                "launch_seed": 13,
                "rng_state": {"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                "data_cursor": {"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                "model_config_sha256": "c" * 64,
                "contract_sha256": "d" * 64,
                "expert_genesis_sha256": model.expert_bank_genesis_hashes(),
                "test_only_allow_unverified": True,
            }
            real_write_json = checkpoint_artifacts._write_json_atomic
            def fail_manifest(
                root: Path,
                filename: str,
                payload: dict[str, object],
                **kwargs: object,
            ) -> Path:
                if filename == "checkpoint-manifest.json":
                    raise RuntimeError("manifest write failed")
                return real_write_json(root, filename, payload, **kwargs)
            with patch("checkpoint_artifacts._write_json_atomic", side_effect=fail_manifest):
                with self.assertRaisesRegex(RuntimeError, "manifest write failed"):
                    write_checkpoint_artifacts(model, optimizer, target, **arguments)
            self.assertFalse(target.exists())
            self.assertEqual(list(parent.glob(".*.staging")), [])
            candidates = [path for path in (parent / ".checkpoint-quarantine").iterdir() if path.is_dir() and path.name.startswith("candidate-")]
            self.assertEqual(len(candidates), 1)
            self.assertTrue(candidates[0].joinpath("shared-model.pt").is_file())
            self.assertTrue(candidates[0].joinpath("optimizer-state.pt").is_file())
            self.assertTrue(candidates[0].joinpath("replay-state.pt").is_file())
            self.assertTrue(any(path.name.startswith("checkpoint-write-failed-") for path in (parent / ".checkpoint-quarantine").glob("*.json")))

    def test_verifier_mutation_of_existing_shard_is_rejected_before_promotion(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=21)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "checkpoint-shard-mutated"
            arguments = {
                "launch_seed": 21,
                "rng_state": {"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                "data_cursor": {"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                "model_config_sha256": "c" * 64,
                "contract_sha256": "d" * 64,
                "expert_genesis_sha256": model.expert_bank_genesis_hashes(),
            }
            def mutate(candidate: Path, _receipt: dict[str, object]) -> None:
                candidate.joinpath("expert-vision.pt").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "changed after verifier"):
                write_checkpoint_artifacts(model, optimizer, target, pre_publish_verifier=mutate, **arguments)
            self.assertFalse(target.exists())
            candidates = [path for path in (parent / ".checkpoint-quarantine").iterdir() if path.is_dir() and path.name.startswith("candidate-")]
            self.assertEqual(len(candidates), 1)
            self.assertEqual((candidates[0] / "expert-vision.pt").read_bytes(), b"tampered")

    def test_verifier_manifest_mutation_is_rejected_before_promotion(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=22)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "checkpoint-manifest-mutated"
            arguments = {
                "launch_seed": 22,
                "rng_state": {"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                "data_cursor": {"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                "model_config_sha256": "c" * 64,
                "contract_sha256": "d" * 64,
                "expert_genesis_sha256": model.expert_bank_genesis_hashes(),
            }
            def mutate(candidate: Path, _receipt: dict[str, object]) -> None:
                manifest_path = candidate / "checkpoint-manifest.json"
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                payload["late_mutation"] = True
                manifest_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed after verifier"):
                write_checkpoint_artifacts(model, optimizer, target, pre_publish_verifier=mutate, **arguments)
            self.assertFalse(target.exists())
            candidates = [path for path in (parent / ".checkpoint-quarantine").iterdir() if path.is_dir() and path.name.startswith("candidate-")]
            self.assertEqual(len(candidates), 1)

    def test_atomic_publish_no_replace_moves_directory_and_preserves_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = parent / "source"
            target = parent / "target"
            source.mkdir()
            source.joinpath("shared.pt").write_bytes(b"owned-bytes")
            checkpoint_artifacts._atomic_publish_no_replace(source, target)
            self.assertFalse(source.exists())
            self.assertEqual(target.joinpath("shared.pt").read_bytes(), b"owned-bytes")

    def test_atomic_publish_no_replace_rejects_dangling_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = parent / "source"
            target = parent / "target"
            referent = parent / "absent-referent"
            source.mkdir()
            source.joinpath("shared.pt").write_bytes(b"owned-bytes")
            try:
                target.symlink_to(referent, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation is unavailable on this host")
            with self.assertRaises(FileExistsError):
                checkpoint_artifacts._atomic_publish_no_replace(source, target)
            self.assertTrue(source.joinpath("shared.pt").is_file())
            self.assertTrue(target.is_symlink())
            self.assertFalse(referent.exists())

    def test_atomic_publish_no_replace_rejects_existing_empty_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = parent / "source"
            target = parent / "target"
            source.mkdir()
            source.joinpath("shared.pt").write_bytes(b"owned-bytes")
            target.mkdir()
            with self.assertRaises(FileExistsError):
                checkpoint_artifacts._atomic_publish_no_replace(source, target)
            self.assertEqual(source.joinpath("shared.pt").read_bytes(), b"owned-bytes")
            self.assertEqual(list(target.iterdir()), [])

    def test_empty_late_target_at_rename_boundary_is_not_replaced(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=24)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "checkpoint-empty-late-target"
            arguments = {
                "launch_seed": 24,
                "rng_state": {"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                "data_cursor": {"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                "model_config_sha256": "c" * 64,
                "contract_sha256": "d" * 64,
                "expert_genesis_sha256": model.expert_bank_genesis_hashes(),
            }
            real_publish = checkpoint_artifacts._atomic_publish_no_replace

            def appear_at_boundary(source: Path, destination: Path) -> None:
                if destination == target:
                    destination.mkdir()
                    raise FileExistsError(17, "target appeared", str(destination))
                real_publish(source, destination)
            with patch("checkpoint_artifacts._atomic_publish_no_replace", side_effect=appear_at_boundary):
                with self.assertRaisesRegex(FileExistsError, "appeared during admission"):
                    write_checkpoint_artifacts(model, optimizer, target, pre_publish_verifier=lambda candidate, receipt: _counter_receipt(candidate, receipt), **arguments)
            self.assertTrue(target.is_dir())
            candidates = [path for path in (parent / ".checkpoint-quarantine").iterdir() if path.is_dir() and path.name.startswith("candidate-")]
            self.assertEqual(len(candidates), 1)
            self.assertTrue(candidates[0].joinpath("checkpoint-manifest.json").is_file())

    def test_deterministic_quarantine_candidate_collision_preserves_existing_bytes(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=26)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "checkpoint-deterministic-collision"
            arguments = {
                "launch_seed": 26,
                "rng_state": {"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                "data_cursor": {"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                "model_config_sha256": "c" * 64,
                "contract_sha256": "d" * 64,
                "expert_genesis_sha256": model.expert_bank_genesis_hashes(),
            }
            real_publish = checkpoint_artifacts._atomic_publish_no_replace

            def collide(source: Path, destination: Path) -> None:
                if destination.name.startswith("candidate-") and not destination.name.startswith("candidate-write-failed-"):
                    destination.mkdir()
                    destination.joinpath("existing-sentinel").write_bytes(b"preserved")
                real_publish(source, destination)

            with patch("checkpoint_artifacts._atomic_publish_no_replace", side_effect=collide):
                with self.assertRaises(FileExistsError):
                    write_checkpoint_artifacts(
                        model,
                        optimizer,
                        target,
                        pre_publish_verifier=lambda candidate, receipt: _counter_receipt(candidate, receipt),
                        **arguments,
                    )
            quarantine = parent / ".checkpoint-quarantine"
            existing = [path for path in quarantine.iterdir() if path.is_dir() and path.name.startswith("candidate-checkpoint-deterministic-collision-")]
            self.assertEqual(len(existing), 1)
            self.assertEqual(existing[0].joinpath("existing-sentinel").read_bytes(), b"preserved")
            failures = [path for path in quarantine.iterdir() if path.is_dir() and path.name.startswith("candidate-write-failed-")]
            self.assertEqual(len(failures), 1)
            self.assertTrue(failures[0].joinpath("checkpoint-manifest.json").is_file())

    def test_unverified_writer_uses_no_replace_for_empty_late_target(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=25)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "checkpoint-unverified-empty-late-target"
            arguments = {
                "launch_seed": 25,
                "rng_state": {"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                "data_cursor": {"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                "model_config_sha256": "c" * 64,
                "contract_sha256": "d" * 64,
                "expert_genesis_sha256": model.expert_bank_genesis_hashes(),
            }

            real_publish = checkpoint_artifacts._atomic_publish_no_replace

            def appear_at_boundary(source: Path, destination: Path) -> None:
                if destination == target:
                    destination.mkdir()
                    raise FileExistsError(17, "target appeared", str(destination))
                real_publish(source, destination)

            with patch("checkpoint_artifacts._atomic_publish_no_replace", side_effect=appear_at_boundary):
                with self.assertRaises(FileExistsError):
                    write_checkpoint_artifacts(
                        model,
                        optimizer,
                        target,
                        test_only_allow_unverified=True,
                        **arguments,
                    )
            self.assertTrue(target.is_dir())
            self.assertEqual(list(target.iterdir()), [])
            candidates = [path for path in (parent / ".checkpoint-quarantine").iterdir() if path.is_dir() and path.name.startswith("candidate-")]
            self.assertEqual(len(candidates), 1)
            self.assertTrue(candidates[0].joinpath("checkpoint-manifest.json").is_file())

    def test_late_published_target_is_never_overwritten(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=23)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "checkpoint-late-target"
            arguments = {
                "launch_seed": 23,
                "rng_state": {"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                "data_cursor": {"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                "model_config_sha256": "c" * 64,
                "contract_sha256": "d" * 64,
                "expert_genesis_sha256": model.expert_bank_genesis_hashes(),
            }
            def create_target(_candidate: Path, _receipt: dict[str, object]) -> dict[str, object]:
                target.mkdir()
                target.joinpath("sentinel").write_bytes(b"late-owner")
                return _counter_receipt(_candidate, _receipt)
            with self.assertRaisesRegex(FileExistsError, "appeared during admission"):
                write_checkpoint_artifacts(model, optimizer, target, pre_publish_verifier=create_target, **arguments)
            self.assertEqual(target.joinpath("sentinel").read_bytes(), b"late-owner")
            candidates = [path for path in (parent / ".checkpoint-quarantine").iterdir() if path.is_dir() and path.name.startswith("candidate-")]
            self.assertEqual(len(candidates), 1)

    def test_counter_failure_preserves_full_candidate_for_rejudging_without_retraining(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=13)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "checkpoint-failed"
            observed_target_states: list[bool] = []

            def counter_verifier(_candidate: Path, _receipt: dict[str, object]) -> None:
                observed_target_states.append(target.exists())
                raise RuntimeError("counter failed")

            with self.assertRaisesRegex(RuntimeError, "counter failed"):
                write_checkpoint_artifacts(
                    model, optimizer, target, launch_seed=13,
                    rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                    data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                    model_config_sha256="c" * 64, contract_sha256="d" * 64,
                    expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                    pre_publish_verifier=counter_verifier,
                )
            self.assertEqual(observed_target_states, [False])
            self.assertFalse(target.exists())
            self.assertEqual(list(parent.glob(".*.staging")), [])
            candidates = [path for path in (parent / ".checkpoint-quarantine").iterdir() if path.is_dir()]
            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            self.assertTrue(candidate.joinpath("shared-model.pt").is_file())
            self.assertTrue(candidate.joinpath("optimizer-state.pt").is_file())
            self.assertTrue(candidate.joinpath("checkpoint-manifest.json").is_file())
            self.assertFalse(candidate.joinpath(".writer-lease.json").exists())
            shared_sha256 = __import__("hashlib").sha256(candidate.joinpath("shared-model.pt").read_bytes()).hexdigest()
            optimizer_sha256 = __import__("hashlib").sha256(candidate.joinpath("optimizer-state.pt").read_bytes()).hexdigest()
            candidate_manifest = __import__("json").loads(candidate.joinpath("checkpoint-manifest.json").read_text(encoding="utf-8"))
            candidate_receipt = {**candidate_manifest, "checkpoint_manifest_sha256": __import__("hashlib").sha256(candidate.joinpath("checkpoint-manifest.json").read_bytes()).hexdigest()}
            restored = UnifiedDecoder(config, genesis_seed=99)
            restored_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-4)
            with self.assertRaisesRegex(ValueError, "quarantined checkpoint"):
                load_checkpoint_artifacts(restored, restored_optimizer, candidate, candidate_receipt)
            evidence = list((parent / ".checkpoint-quarantine").glob("checkpoint-write-failed-*.json"))
            self.assertEqual(len(evidence), 1)
            payload = __import__("json").loads(evidence[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["error_type"], "RuntimeError")
            self.assertEqual(payload["error_message"], "counter failed")
            self.assertEqual(payload["target"], "checkpoint-failed")
            self.assertRegex(payload["checkpoint_manifest_sha256"], r"^[0-9a-f]{64}$")
            self.assertLess(evidence[0].stat().st_size, 64 * 1024)
            self.assertEqual(
                evidence[0].stem.removeprefix("checkpoint-write-failed-"),
                __import__("hashlib").sha256(evidence[0].read_bytes()).hexdigest(),
            )
            admitted = admit_quarantined_checkpoint(
                candidate,
                target,
                verifier=lambda root, receipt: _counter_receipt(root, receipt),
            )
            self.assertTrue(target.is_dir())
            self.assertFalse(candidate.exists())
            self.assertEqual(__import__("hashlib").sha256(target.joinpath("shared-model.pt").read_bytes()).hexdigest(), shared_sha256)
            self.assertEqual(__import__("hashlib").sha256(target.joinpath("optimizer-state.pt").read_bytes()).hexdigest(), optimizer_sha256)
            self.assertEqual(admitted["checkpoint_manifest_sha256"], __import__("hashlib").sha256(target.joinpath("checkpoint-manifest.json").read_bytes()).hexdigest())
    def test_admission_rejects_counter_mapping_that_mutates_shard_after_verifier_returns(self) -> None:
        """The final immutable closure snapshot must follow every Mapping-controlled access."""
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=94)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "checkpoint-mapping-mutation"

            class MutatingReceipt(dict[str, object]):
                def __init__(self, payload: dict[str, object], shard: Path) -> None:
                    super().__init__(payload)
                    self._shard = shard
                    self._mutated = False

                def items(self):  # type: ignore[override]
                    if not self._mutated:
                        self._mutated = True
                        self._shard.write_bytes(b"mutated-after-final-snapshot")
                    return super().items()

            def verifier(candidate: Path, receipt: dict[str, object]) -> dict[str, object]:
                payload = _counter_receipt(candidate, receipt)
                return MutatingReceipt(payload, candidate / "expert-vision.pt")

            with self.assertRaises(ValueError):
                write_checkpoint_artifacts(
                    model, optimizer, target, launch_seed=94,
                    rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                    data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                    model_config_sha256="c" * 64, contract_sha256="d" * 64,
                    expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                    pre_publish_verifier=verifier,
                )
            self.assertFalse(target.exists())
            candidates = [path for path in (parent / ".checkpoint-quarantine").iterdir() if path.is_dir() and path.name.startswith("candidate-")]
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].joinpath("expert-vision.pt").read_bytes(), b"mutated-after-final-snapshot")

    def test_refuses_checkpoint_receipt_without_optimizer_contract(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=11)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkpoint-0001"
            receipt = write_checkpoint_artifacts(model, optimizer, root, launch_seed=11, rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))}, data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0}, model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes(), test_only_allow_unverified=True)
            receipt.pop("optimizer_contract")
            restored = UnifiedDecoder(config, genesis_seed=12)
            with self.assertRaisesRegex(ValueError, "optimizer contract"):
                load_checkpoint_artifacts(restored, optimizer, root, receipt)
    def test_writes_and_restores_hashed_shared_and_four_expert_shards(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=11)
        optimizer = torch.optim.AdamW((parameter for parameter in model.parameters() if parameter.requires_grad), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            receipt = write_checkpoint_artifacts(model, optimizer, Path(directory) / "checkpoint-0001", launch_seed=11, rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))}, data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0}, model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes(), test_only_allow_unverified=True)
            self.assertEqual(receipt["contract_version"], 5)
            self.assertEqual(receipt["architecture_revision"], "ember-sparse-3b-v2")
            restored = UnifiedDecoder(config, genesis_seed=99)
            restore_optimizer = torch.optim.AdamW((parameter for parameter in restored.parameters() if parameter.requires_grad), lr=1e-4)
            load_checkpoint_artifacts(restored, restore_optimizer, Path(directory) / "checkpoint-0001", receipt)
            self.assertEqual(restored.active_expert, "reasoning")
        self.assertEqual(set(receipt["expert_checkpoint_sha256"]), {"vision", "audio", "reasoning", "tool"})
        self.assertEqual(len(receipt["shards"]), 7)
        self.assertEqual(receipt["launch_seed"], 11)
        self.assertIn("optimizer_contract", receipt)
        self.assertRegex(receipt["optimizer_realization"]["optimizer_contract_sha256"], r"^[0-9a-f]{64}$")


    def test_device_resident_8bit_realization_reads_live_args_not_receipt_fields(self) -> None:
        with warnings.catch_warnings():

            warnings.simplefilter("ignore", DeprecationWarning)

            import bitsandbytes as bnb
        model = UnifiedDecoder(RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64), genesis_seed=11)
        optimizer = bnb.optim.AdamW8bit(model.parameters(), lr=1e-5, weight_decay=0.01, percentile_clipping=100, block_wise=True)
        contract = load_optimizer_contract(ROOT / "configs" / "ember-restart-3b.json")
        realization = _optimizer_realization(optimizer, contract)
        self.assertEqual(realization["implementation"], "bitsandbytes.optim.AdamW8bit")
        self.assertEqual(realization["placement"], "cuda_non_paged")
        self.assertEqual(realization["state_format"], "bitsandbytes-device-resident-8bit-adamw-state-dict-v1")

    def test_device_resident_contract_rejects_adamw8bit_forced_into_paged_mode(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import bitsandbytes as bnb
        model = UnifiedDecoder(RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64), genesis_seed=11)
        optimizer = bnb.optim.AdamW8bit(model.parameters(), lr=1e-5, weight_decay=0.01, percentile_clipping=100, block_wise=True, is_paged=True)
        contract = load_optimizer_contract(ROOT / "configs" / "ember-restart-3b.json")
        with self.assertRaisesRegex(ValueError, "not device-resident"):
            _optimizer_realization(optimizer, contract)
    def test_writes_and_restores_shared_semantic_checkpoint(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=17)
        model._activate_expert("shared")
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "semantic-checkpoint"
            receipt = write_checkpoint_artifacts(
                model, optimizer, root, launch_seed=17,
                rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))},
                data_cursor={"shard": "TOKEN-SHARDS-V0:receipt", "record_index": 2, "global_step": 2, "tokens_seen": 2048, "governor": {"free_gb": 32.0, "governor_source_sha256": "a" * 64}},
                model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                test_only_allow_unverified=True,
            )
            restored = UnifiedDecoder(config, genesis_seed=18)
            restore_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-4)
            restored_state = load_checkpoint_artifacts(restored, restore_optimizer, root, receipt)
        self.assertEqual(restored_state["data_cursor"]["governor"], {"free_gb": 32.0, "governor_source_sha256": "a" * 64})
        self.assertEqual(receipt["active_expert_ids"], ["shared"])
        self.assertEqual(restored.active_expert, "shared")
    def test_optimizer_realization_recomputes_runtime_class_source_hyperparameters_and_state_format(self) -> None:
        model = UnifiedDecoder(RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64), genesis_seed=11)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4, weight_decay=0.02)
        contract = _default_optimizer_contract(optimizer)
        self.assertEqual(contract["hyperparameters"], {"param_group_count": 1, "learning_rate": 1e-4, "weight_decay": 0.02})
        realization = _optimizer_realization(optimizer, contract)
        for field, value in (("implementation", "torch.optim.SGD"), ("state_format", "forged-state")):
            tampered = dict(contract); tampered[field] = value
            with self.assertRaisesRegex(ValueError, "runtime optimizer realization"):
                _optimizer_realization(optimizer, tampered)
        tampered = {**contract, "hyperparameters": {**contract["hyperparameters"], "learning_rate": 2e-4}}
        with self.assertRaisesRegex(ValueError, "runtime optimizer realization"):
            _optimizer_realization(optimizer, tampered)
        forged_source = {**realization, "implementation_source_sha256": "0" * 64}
        with self.assertRaisesRegex(ValueError, "runtime optimizer realization"):
            _validate_runtime_optimizer_realization(optimizer, contract, forged_source)
    def test_restore_rejects_a_runtime_optimizer_that_does_not_realize_the_receipt(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=11)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkpoint-0001"
            receipt = write_checkpoint_artifacts(model, optimizer, root, launch_seed=11, rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))}, data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0}, model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes(), test_only_allow_unverified=True)
            restored = UnifiedDecoder(config, genesis_seed=12)
            wrong_optimizer = torch.optim.SGD(restored.parameters(), lr=1e-4)
            with self.assertRaisesRegex(ValueError, "runtime optimizer realization"):
                load_checkpoint_artifacts(restored, wrong_optimizer, root, receipt)
    def test_architecture_receipt_uses_measured_active_shared_route(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=23)
        model._activate_expert("shared")
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            receipt = write_checkpoint_artifacts(
                model, optimizer, Path(directory) / "checkpoint-architecture", launch_seed=23,
                rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))},
                data_cursor={"shard": "TOKEN-SHARDS-V0:test", "record_index": 1, "global_step": 1, "tokens_seen": 16},
                model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                test_only_allow_unverified=True,
            )
        expected = measure_parameter_counts(model)
        architecture = receipt["architecture"]
        self.assertEqual(architecture["revision"], "ember-sparse-3b-v2")
        for field in ("allocated_parameters", "unique_parameters", "trainable_parameters", "served_parameters", "active_parameters", "episode_trainable_parameters"):
            self.assertEqual(architecture[field], expected[field])
        self.assertEqual(architecture["shared_text_ffn"], "always_active_SwiGLU_4H")
    def test_admission_preserves_dangling_published_root_symlink(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=91)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "checkpoint-dangling"
            referent = parent / "referent"
            def verifier(candidate: Path, receipt: dict[str, object]) -> dict[str, object]:
                try:
                    target.symlink_to(referent, target_is_directory=True)
                except (OSError, NotImplementedError):
                    self.skipTest("directory symlink creation unavailable")
                return _counter_receipt(candidate, receipt)
            with self.assertRaises(FileExistsError):
                write_checkpoint_artifacts(
                    model, optimizer, target, launch_seed=91,
                    rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                    data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                    model_config_sha256="c" * 64, contract_sha256="d" * 64,
                    expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                    pre_publish_verifier=verifier,
                )
            self.assertTrue(target.is_symlink())
            self.assertFalse(referent.exists())
            self.assertFalse(target.is_dir())

    def test_declared_shard_symlink_to_external_bytes_is_rejected(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=92)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "checkpoint-external"
            outside = parent / "outside.pt"
            outside.write_bytes(b"external")
            def verifier(candidate: Path, receipt: dict[str, object]) -> dict[str, object]:
                shard = candidate / "expert-vision.pt"
                shard.unlink()
                try:
                    shard.symlink_to(outside)
                except (OSError, NotImplementedError):
                    self.skipTest("file symlink creation unavailable")
                return _counter_receipt(candidate, receipt)
            with self.assertRaisesRegex(ValueError, "symlink or reparse"):
                write_checkpoint_artifacts(
                    model, optimizer, target, launch_seed=92,
                    rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                    data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                    model_config_sha256="c" * 64, contract_sha256="d" * 64,
                    expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                    pre_publish_verifier=verifier,
                )
            self.assertEqual(outside.read_bytes(), b"external")
            self.assertFalse(target.exists())

    def test_p2b_training_cursor_is_closed_and_disjoint_from_legacy_replay_cursor(self) -> None:
        selection_cursor = {"schema_version": SELECTION_CURSOR_SCHEMA_VERSION, "selection_receipt_sha256": "a" * 64, "selection_rule_id": "image_scene_split_train_v1", "selected_ordinal": 2, "next_source_index": 5}
        cursor = {"schema_version": TRAINING_CURSOR_SCHEMA_VERSION, "selection_cursor": selection_cursor, "global_step": 7, "tokens_seen": 42}
        kwargs = {"launch_seed": 1, "rng_state": {"cpu": torch.tensor([1], dtype=torch.uint8), "cuda": torch.tensor([2], dtype=torch.uint8)}, "data_cursor": cursor, "model_config_sha256": "c" * 64, "contract_sha256": "d" * 64, "expert_genesis_sha256": {name: "e" * 64 for name in ("vision", "audio", "reasoning", "tool")}}
        checkpoint_artifacts._validate_replay_bindings(**kwargs)
        for label, forged in (("legacy_mixed", {**cursor, "shard": "legacy", "record_index": 0}), ("missing_selection", {key: value for key, value in cursor.items() if key != "selection_cursor"}), ("negative_step", {**cursor, "global_step": -1}), ("negative_tokens", {**cursor, "tokens_seen": -1})):
            with self.subTest(label=label), self.assertRaises(ValueError):
                checkpoint_artifacts._validate_replay_bindings(**{**kwargs, "data_cursor": forged})

        for label, forged in (("wrong_training_schema", {**cursor, "schema_version": "wrong"}), ("outer_extra", {**cursor, "extra": 1}), ("selection_not_mapping", {**cursor, "selection_cursor": []}), ("wrong_selection_schema", {**cursor, "selection_cursor": {**selection_cursor, "schema_version": "wrong"}}), ("selection_missing", {**cursor, "selection_cursor": {key: value for key, value in selection_cursor.items() if key != "next_source_index"}}), ("selection_extra", {**cursor, "selection_cursor": {**selection_cursor, "extra": 1}}), ("negative_ordinal", {**cursor, "selection_cursor": {**selection_cursor, "selected_ordinal": -1}}), ("negative_source", {**cursor, "selection_cursor": {**selection_cursor, "next_source_index": -1}})):
            with self.subTest(label=label), self.assertRaises(ValueError):
                checkpoint_artifacts._validate_replay_bindings(**{**kwargs, "data_cursor": forged})

        for label, forged in (("step_bool", {**cursor, "global_step": True}), ("tokens_bool", {**cursor, "tokens_seen": True}), ("ordinal_bool", {**cursor, "selection_cursor": {**selection_cursor, "selected_ordinal": True}}), ("source_bool", {**cursor, "selection_cursor": {**selection_cursor, "next_source_index": True}}), ("hash_empty", {**cursor, "selection_cursor": {**selection_cursor, "selection_receipt_sha256": ""}}), ("hash_nonstring", {**cursor, "selection_cursor": {**selection_cursor, "selection_receipt_sha256": 1}}), ("hash_upper", {**cursor, "selection_cursor": {**selection_cursor, "selection_receipt_sha256": "A" * 64}}), ("hash_short", {**cursor, "selection_cursor": {**selection_cursor, "selection_receipt_sha256": "a" * 63}}), ("rule_empty", {**cursor, "selection_cursor": {**selection_cursor, "selection_rule_id": ""}}), ("rule_nonstring", {**cursor, "selection_cursor": {**selection_cursor, "selection_rule_id": 1}})):
            with self.subTest(label=label), self.assertRaises(ValueError):
                checkpoint_artifacts._validate_replay_bindings(**{**kwargs, "data_cursor": forged})

    def test_p2b_checkpoint_progress_binds_episode_end_to_outer_training_cursor(self) -> None:
        end = {"schema_version": SELECTION_CURSOR_SCHEMA_VERSION, "selection_receipt_sha256": "a" * 64, "selection_rule_id": "image_scene_split_train_v1", "selected_ordinal": 2, "next_source_index": 5}
        episode = {"end_selection_cursor": end, "completed_updates": 2, "training_token_delta": 12}
        parent = {"global_step": 3, "tokens_seen": 18}
        candidate = {"schema_version": TRAINING_CURSOR_SCHEMA_VERSION, "selection_cursor": end, "global_step": 5, "tokens_seen": 30}
        validate = getattr(checkpoint_artifacts, "_validate_p2b_checkpoint_progress")
        self.assertEqual(validate(episode, candidate, parent), candidate)
        for label, forged in (("end_mismatch", {**candidate, "selection_cursor": {**end, "selected_ordinal": 1}}), ("global_regression", {**candidate, "global_step": 2}), ("global_delta", {**candidate, "global_step": 4}), ("token_regression", {**candidate, "tokens_seen": 17}), ("token_delta", {**candidate, "tokens_seen": 29}), ("legacy_mixed", {**candidate, "shard": "legacy"}), ("wrong_schema", {**candidate, "schema_version": "wrong"})):
            with self.subTest(label=label), self.assertRaises(ValueError):
                validate(episode, forged, parent)
        for malformed_parent in ({"global_step": -1, "tokens_seen": 0}, {"global_step": 3}, {"global_step": "3", "tokens_seen": 18}):
            with self.assertRaises(ValueError):
                validate(episode, candidate, malformed_parent)

        for forged_episode in ({**episode, "completed_updates": 0}, {**episode, "completed_updates": "2"}, {**episode, "training_token_delta": 0}, {**episode, "training_token_delta": "12"}):
            with self.assertRaises(ValueError):
                validate(forged_episode, candidate, parent)

        for bad_episode, bad_candidate, bad_parent in (({**episode, "completed_updates": True}, candidate, parent), ({**episode, "training_token_delta": True}, candidate, parent), (episode, {**candidate, "global_step": True}, parent), (episode, {**candidate, "tokens_seen": True}, parent), (episode, candidate, {"global_step": True, "tokens_seen": 18}), (episode, candidate, {"global_step": 3, "tokens_seen": True})):
            with self.assertRaises(ValueError):
                validate(bad_episode, bad_candidate, bad_parent)

    def test_specialist_lineage_binds_p2b_episode_to_candidate_and_parent_cursor(self) -> None:
        genesis = {"vision": "a" * 64, "audio": "b" * 64, "reasoning": "c" * 64, "tool": "d" * 64}
        receipt = {
            "schema_version": "ember-owned-specialist-stream-selection-receipt-v1",
            "stream_manifest_sha256": "857835d9722e5d6410f4c6c34c537ad2af12bfb98c4d3eb242b3a2c99e591427",
            "stream_build_receipt_sha256": "2e68402c914e842fe23c6ef69f1f8e957d858f7ad2de4d5467dfc65c949ead1e",
            "corpus_root_sha256": "42d1aac14c1e59563d348b7a53ce83dcce499a48217569d7d00a3966199141ab",
            "family_root_sha256": "e" * 64, "capability": "image", "selection_rule_id": "image_scene_split_train_v1",
            "selected_record_count": 3, "selected_token_count": 12, "selected_records_sha256": "f" * 64,
            "selection_commitment_sha256": "0" * 64,
        }
        receipt_sha256 = checkpoint_artifacts._canonical_sha256(receipt)
        start = {"schema_version": SELECTION_CURSOR_SCHEMA_VERSION, "selection_receipt_sha256": receipt_sha256, "selection_rule_id": "image_scene_split_train_v1", "selected_ordinal": 0, "next_source_index": 0}
        end = {**start, "selected_ordinal": 2, "next_source_index": 5}
        episode = {
            "schema_version": "ember-specialist-stream-episode-v1", "active_expert": "vision", "selection_receipt": receipt,
            "selection_receipt_sha256": receipt_sha256, "start_selection_cursor": start, "end_selection_cursor": end,
            "completed_updates": 2, "training_token_delta": 12,
            "stream_manifest_sha256": receipt["stream_manifest_sha256"], "stream_build_receipt_sha256": receipt["stream_build_receipt_sha256"],
            "corpus_root_sha256": receipt["corpus_root_sha256"], "family_root_sha256": receipt["family_root_sha256"],
        }
        candidate_cursor = {"schema_version": TRAINING_CURSOR_SCHEMA_VERSION, "selection_cursor": end, "global_step": 5, "tokens_seen": 30}
        parent = {"schema_version": "ember-sparse-checkpoint-v3", "expert_checkpoint_sha256": genesis, "expert_genesis_sha256": genesis, "data_cursor": {"shard": "legacy-parent", "record_index": 7, "global_step": 3, "tokens_seen": 18}}
        lineage = {"parent_manifest": "parent/checkpoint-manifest.json", "root_manifest": "root/checkpoint-manifest.json", "trained_expert_ids": ["vision"], "episode": episode}
        candidate_parameters = {**genesis, "vision": "1" * 64}
        with patch.object(checkpoint_artifacts, "_external_checkpoint_manifest", side_effect=((parent, "9" * 64), (parent, "9" * 64))):
            normalized, _, _, _ = checkpoint_artifacts._specialist_lineage(
                lineage, active_expert="vision", candidate_parameter_sha256=candidate_parameters,
                data_cursor=candidate_cursor,
            )
        self.assertEqual(normalized["episode"], episode)
        root_parent = {"schema_version": "ember-sparse-checkpoint-v3", "expert_checkpoint_sha256": genesis, "expert_genesis_sha256": genesis, "data_cursor": {"shard": "root-parent", "record_index": 0, "global_step": 3, "tokens_seen": 18}}
        p2b_receipt = {**receipt, "selected_record_count": 4, "selected_token_count": 24}
        p2b_receipt_sha256 = checkpoint_artifacts._canonical_sha256(p2b_receipt)
        p2b_start = {"schema_version": SELECTION_CURSOR_SCHEMA_VERSION, "selection_receipt_sha256": p2b_receipt_sha256, "selection_rule_id": "image_scene_split_train_v1", "selected_ordinal": 0, "next_source_index": 0}
        p2b_end = {**p2b_start, "selected_ordinal": 2, "next_source_index": 5}
        p2b_parent_episode = {**episode, "selection_receipt": p2b_receipt, "selection_receipt_sha256": p2b_receipt_sha256, "start_selection_cursor": p2b_start, "end_selection_cursor": p2b_end}
        chained_start = p2b_end
        chained_end = {**p2b_end, "selected_ordinal": 3, "next_source_index": 6}
        chained_episode = {**p2b_parent_episode, "start_selection_cursor": chained_start, "end_selection_cursor": chained_end, "completed_updates": 1, "training_token_delta": 12}
        chained_cursor = {"schema_version": TRAINING_CURSOR_SCHEMA_VERSION, "selection_cursor": chained_end, "global_step": 6, "tokens_seen": 42}
        chained_lineage = {"parent_manifest": "parent/checkpoint-manifest.json", "root_manifest": "root/checkpoint-manifest.json", "trained_expert_ids": ["vision"], "episode": chained_episode}
        p2b_parent = {
            "schema_version": "ember-sparse-checkpoint-v4", "expert_checkpoint_sha256": {**genesis, "vision": "0" * 64},
            "expert_parameter_sha256": {**genesis, "vision": "0" * 64}, "expert_genesis_sha256": genesis,
            "lineage": {"parent_checkpoint_sha256": "7" * 64, "root_genesis_checkpoint_sha256": "8" * 64, "trained_expert_ids": ["vision"], "episode": p2b_parent_episode},
            "data_cursor": {"schema_version": TRAINING_CURSOR_SCHEMA_VERSION, "selection_cursor": p2b_end, "global_step": 5, "tokens_seen": 30},
        }
        with patch.object(checkpoint_artifacts, "_external_checkpoint_manifest", side_effect=((p2b_parent, "9" * 64), (root_parent, "8" * 64))):
            normalized, _, _, _ = checkpoint_artifacts._specialist_lineage(
                chained_lineage, active_expert="vision", candidate_parameter_sha256=candidate_parameters,
                data_cursor=chained_cursor,
            )
        self.assertEqual(normalized["episode"], chained_episode)
        legacy_lineage = {"parent_manifest": "parent/checkpoint-manifest.json", "root_manifest": "root/checkpoint-manifest.json", "trained_expert_ids": ["vision"], "data_verification_receipt": {}, "execution_slice": {}, "scene_split_selection": {}}
        with patch.object(checkpoint_artifacts, "_external_checkpoint_manifest", side_effect=((parent, "9" * 64), (parent, "9" * 64))), self.assertRaisesRegex(ValueError, "P2B training cursor requires P2B specialist lineage"):
            checkpoint_artifacts._specialist_lineage(legacy_lineage, active_expert="vision", candidate_parameter_sha256=candidate_parameters, data_cursor=candidate_cursor)
        for label, forged_lineage, forged_cursor in (
            ("mixed_shape", {**lineage, "execution_slice": {}}, candidate_cursor),
            ("legacy_cursor", lineage, {"shard": "legacy", "record_index": 0, "global_step": 5, "tokens_seen": 30}),
            ("end_mismatch", lineage, {**candidate_cursor, "selection_cursor": {**end, "selected_ordinal": 1}}),
            ("global_delta", lineage, {**candidate_cursor, "global_step": 4}),
            ("token_delta", lineage, {**candidate_cursor, "tokens_seen": 29}),
            ("forged_nested", lineage, {**candidate_cursor, "selection_cursor": {**end, "selection_receipt_sha256": "1" * 64}}),
        ):
            with self.subTest(label=label), patch.object(checkpoint_artifacts, "_external_checkpoint_manifest", side_effect=((parent, "9" * 64), (parent, "9" * 64))), self.assertRaises(ValueError):
                checkpoint_artifacts._specialist_lineage(forged_lineage, active_expert="vision", candidate_parameter_sha256=candidate_parameters, data_cursor=forged_cursor)
        for label, forged_parameters in (
            ("active_unchanged", {**genesis}),
            ("inactive_changed", {**candidate_parameters, "audio": "2" * 64}),
        ):
            with self.subTest(label=label), patch.object(checkpoint_artifacts, "_external_checkpoint_manifest", side_effect=((parent, "9" * 64), (parent, "9" * 64))), self.assertRaises(ValueError):
                checkpoint_artifacts._specialist_lineage(lineage, active_expert="vision", candidate_parameter_sha256=forged_parameters, data_cursor=candidate_cursor)

    def test_published_checkpoint_receipt_reopens_exact_manifest_identity(self) -> None:
        """A reopening consumer derives the out-of-band identity from frozen bytes."""

        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint"
            checkpoint.mkdir()
            manifest_bytes = b'{"schema_version":"ember-sparse-checkpoint-v4","step":17}\n'
            checkpoint.joinpath("checkpoint-manifest.json").write_bytes(manifest_bytes)

            receipt = checkpoint_artifacts.published_checkpoint_receipt(checkpoint)

        expected = __import__("hashlib").sha256(manifest_bytes).hexdigest()
        self.assertEqual(receipt["checkpoint_manifest_sha256"], expected)
        self.assertEqual(receipt["checkpoint"], {"byte_sha256": expected})

    def test_published_checkpoint_receipt_refuses_reparse_malformed_and_invalid_utf8_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint"
            checkpoint.mkdir()
            manifest = checkpoint / "checkpoint-manifest.json"
            manifest.write_bytes(b'{"schema_version":"ember-sparse-checkpoint-v4"}\n')
            with patch.object(checkpoint_artifacts, "_is_link_or_reparse", return_value=True):
                with self.assertRaisesRegex(checkpoint_artifacts.CheckpointIdentityMismatch, "symlink or reparse"):
                    checkpoint_artifacts.published_checkpoint_receipt(checkpoint)

            manifest.write_bytes(b"{not-json\n")
            with self.assertRaisesRegex(checkpoint_artifacts.CheckpointIdentityMismatch, "not valid published JSON"):
                checkpoint_artifacts.published_checkpoint_receipt(checkpoint)

            manifest.write_bytes(b"\xff\xfe")
            with self.assertRaisesRegex(checkpoint_artifacts.CheckpointIdentityMismatch, "not valid published JSON"):
                checkpoint_artifacts.published_checkpoint_receipt(checkpoint)

    def test_published_checkpoint_receipt_refuses_non_object_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint"
            checkpoint.mkdir()
            checkpoint.joinpath("checkpoint-manifest.json").write_bytes(b"[]\n")
            with self.assertRaisesRegex(checkpoint_artifacts.CheckpointIdentityMismatch, "JSON object"):
                checkpoint_artifacts.published_checkpoint_receipt(checkpoint)

    def test_v5_writer_requires_closed_split_shards_and_round_trips(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=81)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "v5"
            receipt = write_checkpoint_artifacts(model, optimizer, root, launch_seed=81, rng_state=_valid_rng_state(), data_cursor={"shard": "owned", "record_index": 1, "global_step": 1, "tokens_seen": 2}, model_config_sha256="a" * 64, contract_sha256="b" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes())
            self.assertEqual(receipt["schema_version"], "ember-sparse-checkpoint-v5")
            self.assertEqual({entry["path"] for entry in receipt["shards"]}, {"shared-model.pt", "optimizer-state.pt", "replay-state.pt", "expert-vision.pt", "expert-audio.pt", "expert-reasoning.pt", "expert-tool.pt"})
            restored = UnifiedDecoder(config, genesis_seed=82)
            restore_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-4)
            restored_state = load_checkpoint_artifacts(restored, restore_optimizer, root, receipt)
        self.assertEqual(restored_state["data_cursor"]["record_index"], 1)

    def test_v5_writer_rejects_single_temp_shard_above_transient_scratch_cap(self) -> None:
        import inspect

        self.assertIn(
            "max_transient_scratch_bytes",
            inspect.signature(_write_checkpoint_artifacts_public).parameters,
        )
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=83)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(checkpoint_artifacts.torch, "save", wraps=torch.save) as save:
                with self.assertRaisesRegex(RuntimeError, "tensor-storage lower bound"):
                    write_checkpoint_artifacts(model, optimizer, Path(directory) / "v5", launch_seed=83, rng_state=_valid_rng_state(), data_cursor={"shard": "owned", "record_index": 0, "global_step": 0, "tokens_seen": 0}, model_config_sha256="a" * 64, contract_sha256="b" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes(), max_transient_scratch_bytes=1)
            save.assert_not_called()

    def test_v5_storage_projection_binds_post_update_optimizer_and_all_experts(self) -> None:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=2, attention_heads=4, vocab_size=64
        )
        model = UnifiedDecoder(config, genesis_seed=183)
        model._activate_expert("vision")
        optimizer = torch.optim.AdamW(
            (parameter for parameter in model.parameters() if parameter.requires_grad),
            lr=1e-4,
        )
        loss = model(
            torch.tensor([[1, 2, 3]], dtype=torch.long),
            active_expert="vision",
        ).float().square().mean()
        loss.backward()
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "v5"
            receipt = write_checkpoint_artifacts(
                model,
                optimizer,
                root,
                launch_seed=183,
                rng_state=_valid_rng_state(),
                data_cursor={
                    "shard": "owned",
                    "record_index": 1,
                    "global_step": 1,
                    "tokens_seen": 3,
                },
                model_config_sha256="a" * 64,
                contract_sha256="b" * 64,
                expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                max_transient_scratch_bytes=1024**3,
                max_serialized_bytes=1024**3,
            )
            manifest = json.loads(
                (root / "checkpoint-manifest.json").read_text(encoding="utf-8")
            )

        projection = receipt["storage_projection"]
        self.assertEqual(projection, manifest["storage_projection"])
        self.assertEqual(projection["optimizer_state_after_global_step"], 1)
        self.assertEqual(
            projection["optimizer_state_active_expert_ids"], ["vision"]
        )
        self.assertGreater(
            projection["optimizer_state_tensor_storage_lower_bound_bytes"], 0
        )
        self.assertGreaterEqual(
            projection[
                "projected_all_expert_optimizer_state_tensor_storage_lower_bound_bytes"
            ],
            projection["optimizer_state_tensor_storage_lower_bound_bytes"],
        )
        self.assertGreaterEqual(
            projection[
                "all_expert_projected_tensor_storage_lower_bound_bytes"
            ],
            projection[
                "projected_all_expert_optimizer_state_tensor_storage_lower_bound_bytes"
            ],
        )
        self.assertTrue(projection["manifest_written_last"])
        self.assertRegex(projection["projection_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            projection["per_shard_sha256"],
            {
                record["path"]: record["sha256"]
                for record in receipt["shards"]
            },
        )

    def test_v5_storage_projection_rejects_empty_post_update_optimizer(self) -> None:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=2, attention_heads=4, vocab_size=64
        )
        model = UnifiedDecoder(config, genesis_seed=184)
        model._activate_expert("vision")
        optimizer = torch.optim.AdamW(
            (parameter for parameter in model.parameters() if parameter.requires_grad),
            lr=1e-4,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                ValueError, "post-update optimizer state"
            ):
                write_checkpoint_artifacts(
                    model,
                    optimizer,
                    Path(directory) / "v5",
                    launch_seed=184,
                    rng_state=_valid_rng_state(),
                    data_cursor={
                        "shard": "owned",
                        "record_index": 1,
                        "global_step": 1,
                        "tokens_seen": 3,
                    },
                    model_config_sha256="a" * 64,
                    contract_sha256="b" * 64,
                    expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                    max_transient_scratch_bytes=1024**3,
                    max_serialized_bytes=1024**3,
                )

    def test_v5_storage_projection_counts_retained_hardlink_only_in_logical_floor(self) -> None:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=2, attention_heads=4, vocab_size=64
        )
        model = UnifiedDecoder(config, genesis_seed=185)
        model._activate_expert("vision")
        optimizer = torch.optim.AdamW(
            (parameter for parameter in model.parameters() if parameter.requires_grad),
            lr=1e-4,
        )
        model(
            torch.tensor([[1, 2, 3]], dtype=torch.long),
            active_expert="vision",
        ).float().square().mean().backward()
        optimizer.step()
        optimizer_payload = {"optimizer": optimizer.state_dict()}
        optimizer_floor = checkpoint_artifacts._unique_tensor_storage_bytes(
            optimizer_payload
        )
        bounds = {
            "shared-model.pt": 100,
            "optimizer-state.pt": optimizer_floor,
            "replay-state.pt": 100,
            "expert-vision.pt": 100,
            "expert-audio.pt": optimizer_floor + 1000,
            "expert-reasoning.pt": 100,
            "expert-tool.pt": 100,
        }
        modes = {path: "written" for path in bounds}
        modes["expert-audio.pt"] = "hardlink"

        projection = checkpoint_artifacts._derive_checkpoint_storage_projection(
            model=model,
            optimizer=optimizer,
            optimizer_file_payload=optimizer_payload,
            shard_storage_lower_bounds=bounds,
            shard_sha256={path: "a" * 64 for path in bounds},
            publication_modes=modes,
            global_step=1,
            max_transient_scratch_bytes=optimizer_floor + 100,
            max_serialized_bytes=1024**3,
        )

        self.assertEqual(
            projection["retained_shard_paths"], ["expert-audio.pt"]
        )
        self.assertEqual(
            projection["transient_new_write_peak_lower_bound_bytes"],
            optimizer_floor,
        )
        self.assertGreater(
            projection["all_expert_projected_tensor_storage_lower_bound_bytes"],
            bounds["expert-audio.pt"],
        )

    def test_v5_storage_projection_rejects_all_expert_aggregate_over_serialized_gate(self) -> None:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=2, attention_heads=4, vocab_size=64
        )
        model = UnifiedDecoder(config, genesis_seed=186)
        model._activate_expert("vision")
        optimizer = torch.optim.AdamW(
            (parameter for parameter in model.parameters() if parameter.requires_grad),
            lr=1e-4,
        )
        model(
            torch.tensor([[1, 2, 3]], dtype=torch.long),
            active_expert="vision",
        ).float().square().mean().backward()
        optimizer.step()
        optimizer_payload = {"optimizer": optimizer.state_dict()}
        optimizer_floor = checkpoint_artifacts._unique_tensor_storage_bytes(
            optimizer_payload
        )
        bounds = {
            "shared-model.pt": 100,
            "optimizer-state.pt": optimizer_floor,
            "replay-state.pt": 100,
            **{
                f"expert-{name}.pt": 100
                for name in checkpoint_artifacts.EXPERT_NAMES
            },
        }
        per_shard_ceiling = max(bounds.values()) + 1
        with self.assertRaisesRegex(
            RuntimeError, "all-expert projected tensor-storage"
        ):
            checkpoint_artifacts._derive_checkpoint_storage_projection(
                model=model,
                optimizer=optimizer,
                optimizer_file_payload=optimizer_payload,
                shard_storage_lower_bounds=bounds,
                shard_sha256={path: "a" * 64 for path in bounds},
                publication_modes={path: "written" for path in bounds},
                global_step=1,
                max_transient_scratch_bytes=per_shard_ceiling,
                max_serialized_bytes=per_shard_ceiling,
            )

    def test_v5_storage_projection_rejects_rehashed_route_tamper(self) -> None:
        projection = {
            "schema_version": "ember-checkpoint-storage-projection-v1",
            "active_expert": "vision",
            "optimizer_state_after_global_step": 1,
            "optimizer_state_active_expert_ids": ["vision"],
            "optimizer_state_tensor_storage_lower_bound_bytes": 10,
            "optimizer_state_tensor_storage_by_route_bytes": {
                "shared": 2,
                "vision": 8,
                "audio": 0,
                "reasoning": 0,
                "tool": 0,
            },
            "projected_all_expert_optimizer_state_tensor_storage_lower_bound_bytes": 34,
            "per_shard_tensor_storage_lower_bound_bytes": {
                "shared-model.pt": 10,
                "optimizer-state.pt": 10,
                "replay-state.pt": 10,
                "expert-vision.pt": 10,
                "expert-audio.pt": 10,
                "expert-reasoning.pt": 10,
                "expert-tool.pt": 10,
            },
            "per_shard_sha256": {
                "shared-model.pt": "a" * 64,
                "optimizer-state.pt": "b" * 64,
                "replay-state.pt": "c" * 64,
                "expert-vision.pt": "d" * 64,
                "expert-audio.pt": "e" * 64,
                "expert-reasoning.pt": "f" * 64,
                "expert-tool.pt": "0" * 64,
            },
            "transient_new_write_peak_lower_bound_bytes": 10,
            "retained_shard_paths": [],
            "all_expert_projected_tensor_storage_lower_bound_bytes": 94,
            "max_transient_scratch_bytes": 100,
            "max_serialized_bytes": 100,
            "manifest_written_last": True,
        }
        projection["projection_sha256"] = checkpoint_artifacts._canonical_sha256(
            projection
        )
        projection["optimizer_state_tensor_storage_by_route_bytes"]["audio"] = 1
        projection["projection_sha256"] = checkpoint_artifacts._canonical_sha256(
            {
                key: value
                for key, value in projection.items()
                if key != "projection_sha256"
            }
        )
        with self.assertRaisesRegex(
            ValueError, "optimizer route projection"
        ):
            checkpoint_artifacts._validate_checkpoint_storage_projection(
                projection
            )

    def test_v5_storage_projection_rejects_rehashed_shard_binding_tamper(self) -> None:
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=2, attention_heads=4, vocab_size=64
        )
        model = UnifiedDecoder(config, genesis_seed=187)
        model._activate_expert("vision")
        optimizer = torch.optim.AdamW(
            (parameter for parameter in model.parameters() if parameter.requires_grad),
            lr=1e-4,
        )
        model(
            torch.tensor([[1, 2, 3]], dtype=torch.long),
            active_expert="vision",
        ).float().square().mean().backward()
        optimizer.step()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "v5"
            write_checkpoint_artifacts(
                model,
                optimizer,
                root,
                launch_seed=187,
                rng_state=_valid_rng_state(),
                data_cursor={
                    "shard": "owned",
                    "record_index": 1,
                    "global_step": 1,
                    "tokens_seen": 3,
                },
                model_config_sha256="a" * 64,
                contract_sha256="b" * 64,
                expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                max_transient_scratch_bytes=1024**3,
                max_serialized_bytes=1024**3,
            )
            manifest_path = root / "checkpoint-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            projection = manifest["storage_projection"]
            projection["per_shard_sha256"]["shared-model.pt"] = "0" * 64
            projection["projection_sha256"] = checkpoint_artifacts._canonical_sha256(
                {
                    key: value
                    for key, value in projection.items()
                    if key != "projection_sha256"
                }
            )
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError, "shard-byte projection"
            ):
                checkpoint_artifacts._checkpoint_candidate_receipt(root)

    def test_v5_copy_fallback_cannot_bypass_transient_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pt"
            target = root / "target.pt"
            source.write_bytes(b"owned-checkpoint-shard")
            with (
                patch.object(checkpoint_artifacts.os, "link", side_effect=OSError),
                patch.object(
                    checkpoint_artifacts.shutil,
                    "copyfile",
                    wraps=checkpoint_artifacts.shutil.copyfile,
                ) as copyfile,
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "copy fallback is forbidden"
                ):
                    checkpoint_artifacts._link_or_copy_verified(
                        source,
                        target,
                        checkpoint_artifacts._sha256(source),
                        max_transient_scratch_bytes=1024,
                    )
            copyfile.assert_not_called()
            self.assertFalse(target.exists())

    def test_v5_transient_cap_breach_cleans_temps_and_retains_failure_evidence(self) -> None:
        import inspect

        self.assertIn(
            "max_transient_scratch_bytes",
            inspect.signature(_write_checkpoint_artifacts_public).parameters,
        )
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=84)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "transient scratch"):
                write_checkpoint_artifacts(model, optimizer, parent / "v5", launch_seed=84, rng_state=_valid_rng_state(), data_cursor={"shard": "owned", "record_index": 0, "global_step": 0, "tokens_seen": 0}, model_config_sha256="a" * 64, contract_sha256="b" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes(), max_transient_scratch_bytes=1)
            self.assertEqual(list(parent.rglob("*.tmp")), [])
            self.assertEqual(list(parent.glob(".*.staging")), [])
            evidence = list((parent / ".checkpoint-quarantine").glob("checkpoint-write-failed-*.json"))
            self.assertEqual(len(evidence), 1)
            self.assertLess(evidence[0].stat().st_size, checkpoint_artifacts._FAILURE_EVIDENCE_LIMIT)

    def test_explicit_v3_shared_fixture_still_loads_model_optimizer_and_cursor(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=85)
        model._activate_expert("reasoning")
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "legacy-v3"
            root.mkdir()
            rng_state = _valid_rng_state()
            data_cursor = {
                "shard": "legacy",
                "record_index": 2,
                "global_step": 2,
                "tokens_seen": 4,
            }
            optimizer_contract = _default_optimizer_contract(optimizer)
            optimizer_realization = _optimizer_realization(optimizer, optimizer_contract)
            state = model.state_dict()
            torch.save(
                {
                    "model": _select_detached_state(state, lambda name: ".experts." not in name),
                    "optimizer": optimizer.state_dict(),
                    "optimizer_contract": optimizer_contract,
                    "optimizer_realization": optimizer_realization,
                },
                root / "shared.pt",
            )
            torch.save({"rng_state": rng_state, "data_cursor": data_cursor}, root / "replay-state.pt")
            expert_hashes = {}
            for name in ("vision", "audio", "reasoning", "tool"):
                path = root / f"expert-{name}.pt"
                torch.save(
                    {
                        "expert": name,
                        "model": _select_detached_state(
                            state,
                            lambda key, selected=name: f".experts.{selected}." in key,
                        ),
                    },
                    path,
                )
                expert_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            roles = {
                "shared.pt": "shared_model_and_optimizer",
                "replay-state.pt": "replay_state",
                **{
                    f"expert-{name}.pt": f"expert_{name}"
                    for name in ("vision", "audio", "reasoning", "tool")
                },
            }
            shards = []
            for name, role in roles.items():
                path = root / name
                size = path.stat().st_size
                shards.append(
                    {
                        "path": name,
                        "role": role,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "bytes": size,
                        "publication_mode": "written",
                        "incremental_bytes": size,
                    }
                )
            manifest = {
                "schema_version": "ember-sparse-checkpoint-v3",
                "contract_version": 3,
                "architecture_revision": "ember-sparse-3b-v2",
                "data_cursor": data_cursor,
                "model_config_sha256": "a" * 64,
                "contract_sha256": "b" * 64,
                "active_expert_ids": ["reasoning"],
                "expert_genesis_sha256": model.expert_bank_genesis_hashes(),
                "expert_checkpoint_sha256": expert_hashes,
                "expert_parameter_sha256": model.expert_bank_genesis_hashes(),
                "shared_optimizer_shard_sha256": hashlib.sha256(
                    (root / "shared.pt").read_bytes()
                ).hexdigest(),
                "optimizer_contract": optimizer_contract,
                "optimizer_realization": optimizer_realization,
                "shards": shards,
            }
            manifest_path = root / "checkpoint-manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            receipt = {
                **manifest,
                "checkpoint_manifest_sha256": manifest_sha256,
                "checkpoint": {"byte_sha256": manifest_sha256},
            }
            restored = UnifiedDecoder(config, genesis_seed=86)
            restored_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-4)
            loaded = load_checkpoint_artifacts(restored, restored_optimizer, root, receipt)
        self.assertEqual(loaded["data_cursor"], data_cursor)
        for key, tensor in model.state_dict().items():
            self.assertTrue(torch.equal(tensor, restored.state_dict()[key]), key)

if __name__ == "__main__":
    unittest.main()
