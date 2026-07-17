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

from checkpoint_artifacts import _default_optimizer_contract, _optimizer_realization, _select_detached_state, _validate_runtime_optimizer_realization, _write_checkpoint_artifacts_test_only, admit_quarantined_checkpoint, checkpoint_commit_preflight, configured_maximum_available_commit_bytes, load_checkpoint_artifacts, load_checkpoint_model_only_transition, write_checkpoint_artifacts as _write_checkpoint_artifacts_public
from model import RestartDecoderConfig, UnifiedDecoder
from parameter_counter import measure_parameter_counts
from run_vertical_slice import load_optimizer_contract

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
        "active_expert_ids": manifest_receipt["active_expert_ids"],
    }
    for field in ("allocated_parameters", "unique_parameters", "trainable_parameters", "served_parameters", "active_parameters", "episode_trainable_parameters"):
        payload[field] = architecture[field]
    (candidate / "parameter-counter-receipt.json").write_text(json.dumps(payload, sort_keys=True) + chr(10), encoding="utf-8")
    return payload


def write_checkpoint_artifacts(*args, **kwargs):
    if "test_only_allow_unverified" in kwargs:
        return _write_checkpoint_artifacts_test_only(*args, **kwargs)
    return _write_checkpoint_artifacts_public(*args, **kwargs)



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
                write_checkpoint_artifacts(
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
            def fail_manifest(root: Path, filename: str, payload: dict[str, object]) -> Path:
                if filename == "checkpoint-manifest.json":
                    raise RuntimeError("manifest write failed")
                return real_write_json(root, filename, payload)
            with patch("checkpoint_artifacts._write_json_atomic", side_effect=fail_manifest):
                with self.assertRaisesRegex(RuntimeError, "manifest write failed"):
                    write_checkpoint_artifacts(model, optimizer, target, **arguments)
            self.assertFalse(target.exists())
            self.assertEqual(list(parent.glob(".*.staging")), [])
            candidates = [path for path in (parent / ".checkpoint-quarantine").iterdir() if path.is_dir() and path.name.startswith("candidate-")]
            self.assertEqual(len(candidates), 1)
            self.assertTrue(candidates[0].joinpath("shared.pt").is_file())
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
            candidates = [path for path in (parent / ".checkpoint-quarantine").iterdir() if path.is_dir() and path.name.startswith("candidate-write-failed-")]
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
            self.assertTrue(candidate.joinpath("shared.pt").is_file())
            self.assertTrue(candidate.joinpath("checkpoint-manifest.json").is_file())
            self.assertFalse(candidate.joinpath(".writer-lease.json").exists())
            shared_sha256 = __import__("hashlib").sha256(candidate.joinpath("shared.pt").read_bytes()).hexdigest()
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
            self.assertEqual(__import__("hashlib").sha256(target.joinpath("shared.pt").read_bytes()).hexdigest(), shared_sha256)
            self.assertEqual(admitted["checkpoint_manifest_sha256"], __import__("hashlib").sha256(target.joinpath("checkpoint-manifest.json").read_bytes()).hexdigest())
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
            self.assertEqual(receipt["contract_version"], 3)
            self.assertEqual(receipt["architecture_revision"], "ember-sparse-3b-v2")
            restored = UnifiedDecoder(config, genesis_seed=99)
            restore_optimizer = torch.optim.AdamW((parameter for parameter in restored.parameters() if parameter.requires_grad), lr=1e-4)
            load_checkpoint_artifacts(restored, restore_optimizer, Path(directory) / "checkpoint-0001", receipt)
            self.assertEqual(restored.active_expert, "reasoning")
        self.assertEqual(set(receipt["expert_checkpoint_sha256"]), {"vision", "audio", "reasoning", "tool"})
        self.assertEqual(len(receipt["shards"]), 6)
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
                data_cursor={"shard": "TOKEN-SHARDS-V0:receipt", "record_index": 2, "global_step": 2, "tokens_seen": 2048},
                model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                test_only_allow_unverified=True,
            )
            restored = UnifiedDecoder(config, genesis_seed=18)
            restore_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-4)
            load_checkpoint_artifacts(restored, restore_optimizer, root, receipt)
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
if __name__ == "__main__":
    unittest.main()
