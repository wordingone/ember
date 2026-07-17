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

from checkpoint_artifacts import _default_optimizer_contract, _optimizer_realization, _select_detached_state, _validate_runtime_optimizer_realization, admit_quarantined_checkpoint, checkpoint_commit_preflight, configured_maximum_available_commit_bytes, load_checkpoint_artifacts, load_checkpoint_model_only_transition, write_checkpoint_artifacts
from model import RestartDecoderConfig, UnifiedDecoder
from parameter_counter import measure_parameter_counts
from run_vertical_slice import load_optimizer_contract


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

    def test_test_only_verifier_opt_out_is_closed_and_boolean(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=14)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        arguments = {
            "launch_seed": 14,
            "rng_state": {"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
            "data_cursor": {"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
            "model_config_sha256": "c" * 64,
            "contract_sha256": "d" * 64,
            "expert_genesis_sha256": model.expert_bank_genesis_hashes(),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "must be a boolean"):
                write_checkpoint_artifacts(model, optimizer, root / "non-bool", test_only_allow_unverified=1, **arguments)
            with self.assertRaisesRegex(ValueError, "cannot accompany"):
                write_checkpoint_artifacts(
                    model, optimizer, root / "ambiguous", test_only_allow_unverified=True,
                    pre_publish_verifier=lambda _root, _receipt: None, **arguments,
                )

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

            def verify(candidate: Path, _receipt: dict[str, object]) -> None:
                observations.append((candidate.is_dir(), target.exists(), (candidate / "checkpoint-manifest.json").is_file(), candidate.parent.name == ".checkpoint-quarantine", (candidate / ".writer-lease.json").is_file()))
                (candidate / "parameter-counter-receipt.json").write_text('{"result":"MEASURED"}' + chr(10), encoding="utf-8")

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

    def test_counter_failure_preserves_full_candidate_for_rejudging_without_retraining(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=13)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "checkpoint-failed"
            with self.assertRaisesRegex(RuntimeError, "counter failed"):
                write_checkpoint_artifacts(
                    model, optimizer, target, launch_seed=13,
                    rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                    data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                    model_config_sha256="c" * 64, contract_sha256="d" * 64,
                    expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                    pre_publish_verifier=lambda _staging, _receipt: (_ for _ in ()).throw(RuntimeError("counter failed")),
                )
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
                verifier=lambda root, _receipt: root.joinpath("parameter-counter-receipt.json").write_text('{"result":"MEASURED"}' + chr(10), encoding="utf-8"),
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
