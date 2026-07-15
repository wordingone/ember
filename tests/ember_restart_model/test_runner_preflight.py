# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute runner preflight helpers without allocating the production model."""

from __future__ import annotations

import inspect
import hashlib
import json
import tempfile

import sys
import subprocess
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

import run_vertical_slice
from build_owned_reasoning_tool_trajectories import build_records
from verify_capability_record import expected_receipt


class RunnerPreflightTests(unittest.TestCase):
    def test_specialist_loader_executes_bound_verifier_and_returns_one_route(self) -> None:
        from build_specialist_bundle import emit_bundle
        from tokenizers import Tokenizer, models, pre_tokenizers

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            tokenizer = root / "tokenizer.json"
            vocabulary = {"<unk>": 0, "image": 1, "scene": 2, "has": 3, "red": 4, "green": 5, "blue": 6, "squares": 7, "audio": 8, "signal": 9, "positive": 10, "negative": 11, "silent": 12, "frames": 13, "reasoning": 14, "sum": 15, "plus": 16, "equals": 17, "tool": 18, "calculator": 19, **{f"filler-{index}": index for index in range(20, 32_000)}}
            frozen = Tokenizer(models.WordLevel(vocabulary, unk_token="<unk>"))
            frozen.pre_tokenizer = pre_tokenizers.Whitespace()
            frozen.save(str(tokenizer))
            config = root / "config.json"
            config.write_text(json.dumps({"model": {"vocab_size": 32_000, "image_projection": {"input_shape": [48, 48, 3]}, "audio_projection": {"frame_samples": 640}}}), encoding="utf-8")
            manifest = emit_bundle(repo_root=ROOT, output_root=root / "bundle", tokenizer_path=tokenizer, model_config_path=config, count=512)["reasoning"]
            records_out, verification = run_vertical_slice.load_verified_specialist_records(root=ROOT, data_manifest=manifest, tokenizer_path=tokenizer, capability="reasoning")
        self.assertGreaterEqual(len(records_out), 512)
        self.assertEqual(verification["result"], "VERIFIED")
        self.assertEqual(verification["capability"], "reasoning")
        self.assertIs(verification["generator_replay_verified"], True)
    def test_specialist_loader_rejects_a_verified_receipt_without_generator_replay_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"records_artifact": {"path": "records.json"}}), encoding="utf-8")
            with patch.object(run_vertical_slice.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout=json.dumps({"result": "VERIFIED", "capability": "image", "generator_replay_verified": False}), stderr="")):
                with self.assertRaisesRegex(RuntimeError, "generator replay"):
                    run_vertical_slice.load_verified_specialist_records(
                        root=root, data_manifest=manifest, tokenizer_path=root / "tokenizer.json", capability="image",
                    )
    def test_production_optimizer_uses_declared_paged_8bit_adamw_state(self) -> None:
        calls: dict[str, object] = {}

        class Subject:
            def parameters(self) -> list[str]:
                return ["parameter"]

        def make_adamw(parameters: object, **kwargs: object) -> object:
            calls["parameters"] = parameters
            calls.update(kwargs)
            return "optimizer"

        fake = SimpleNamespace(optim=SimpleNamespace(PagedAdamW8bit=make_adamw))
        with patch.dict(sys.modules, {"bitsandbytes": fake}):
            contract = run_vertical_slice.load_optimizer_contract(ROOT / "configs" / "ember-restart-3b.json")
            optimizer = run_vertical_slice.build_production_optimizer(Subject(), optimizer_contract=contract)
        self.assertEqual(optimizer, "optimizer")
        self.assertEqual(contract["implementation"], "bitsandbytes.optim.PagedAdamW8bit")
        self.assertEqual(contract["hyperparameters"]["learning_rate"], 1e-5)
        self.assertEqual(calls["parameters"], ["parameter"])
        self.assertEqual(calls["percentile_clipping"], 100)
        self.assertEqual(calls["lr"], 1e-5)
    def test_contract_retention_limit_is_used_as_the_runner_limit(self) -> None:
        contract = ROOT / "configs" / "ember-restart-3b.json"
        self.assertTrue(hasattr(run_vertical_slice, "checkpoint_retention_budget_bytes"))
        self.assertEqual(run_vertical_slice.checkpoint_retention_budget_bytes(contract), 24 * 1024**3)
    def test_runtime_loads_the_exact_bf16_memory_contract(self) -> None:
        self.assertTrue(hasattr(run_vertical_slice, "load_memory_contract"))
        memory = run_vertical_slice.load_memory_contract(ROOT / "configs" / "ember-restart-3b.json")
        self.assertEqual(memory["parameter_dtype"], "bfloat16")

    def test_rng_preflight_hashes_cpu_and_cuda_without_allocation(self) -> None:
        with patch.object(run_vertical_slice.torch.cuda, "get_rng_state", return_value=torch.tensor([1, 2, 3], dtype=torch.uint8)):
            hashes = run_vertical_slice._rng_state_hash(torch.device("cuda"))
        self.assertEqual(set(hashes), {"cpu", "cuda"})
        self.assertTrue(all(len(value) == 64 for value in hashes.values()))


    def test_bf16_memory_plan_rejects_before_production_allocation(self) -> None:
        self.assertTrue(hasattr(run_vertical_slice, "production_memory_preflight"))
        plan = run_vertical_slice.production_memory_preflight(total_parameters=3_839_161_856, active_parameters=1_725_232_640, device_free_bytes=22 * 1024**3)
        self.assertEqual(plan["parameter_dtype"], "bfloat16")
        self.assertLessEqual(plan["required_bytes"], 22 * 1024**3)
        with self.assertRaisesRegex(MemoryError, "before allocation"):
            run_vertical_slice.production_memory_preflight(total_parameters=3_839_161_856, active_parameters=1_725_232_640, device_free_bytes=plan["required_bytes"] - 1)

    def test_production_runner_refuses_retired_bootstrap_curriculum(self) -> None:
        packet = {
            "input_identity": {
                "artifact_id": "owned-clean-curriculum-128-v1",
                "shard_path": "data/ember-restart-3b/owned-curriculum-128.json",
            }
        }
        with patch.object(run_vertical_slice, "run_launch", return_value=(packet, {"decision": "ACCEPTED"}, {})):
            with self.assertRaisesRegex(RuntimeError, "retired bootstrap"):
                run_vertical_slice.load_authorized_records(ROOT)


    def test_retention_prunes_after_success_with_the_serialized_budget(self) -> None:
        with patch.object(run_vertical_slice, "_enforce_retention") as retention:
            result = run_vertical_slice._retain_after_success(
                Path("B:/ember-artifacts/checkpoints"), max_serialized_bytes=24 * 1024**3, operation=lambda: "published"
            )
        self.assertEqual(result, "published")

    def test_publication_plan_is_exact_for_a_resumed_phase(self) -> None:
        plan = run_vertical_slice.semantic_publication_plan(steps=2, checkpoint_interval=32, checkpoint_byte_bound=10, write_budget_bytes=20, initial_global_step=31)
        self.assertEqual(plan, {"publication_count": 2, "checkpoint_byte_bound": 10, "projected_write_bytes": 20})
    def test_specialist_resume_preserves_global_counters_but_resets_new_source_cursor(self) -> None:
        cursor = {"shard": "TOKEN-SHARDS-V0:prior", "record_index": 37, "global_step": 19, "tokens_seen": 19_456}
        resumed = run_vertical_slice.specialist_resume_cursor(cursor, data_shard_id="VERIFIED_SPECIALIST:abc123")
        self.assertEqual(resumed, {"shard": "VERIFIED_SPECIALIST:abc123", "record_index": 0, "global_step": 19, "tokens_seen": 19_456})
    def test_checkpoint_byte_bound_is_derived_from_the_frozen_contract(self) -> None:
        bound = run_vertical_slice.checkpoint_serialization_byte_bound(ROOT / "configs" / "ember-restart-3b.json")
        self.assertEqual(
            bound,
            3_839_161_856 * 2 + 1_020_589_568 * 2 + 1024**3,
        )
    def test_semantic_publication_plan_bounds_write_budget_by_interval_and_final_checkpoint(self) -> None:
        plan = run_vertical_slice.semantic_publication_plan(steps=100, checkpoint_interval=32, checkpoint_byte_bound=10, write_budget_bytes=40)
        self.assertEqual(plan, {"publication_count": 4, "checkpoint_byte_bound": 10, "projected_write_bytes": 40})
        with self.assertRaisesRegex(ValueError, "write budget"):
            run_vertical_slice.semantic_publication_plan(steps=100, checkpoint_interval=32, checkpoint_byte_bound=10, write_budget_bytes=39)

    def test_semantic_cli_dispatches_only_manifest_bound_stream_inputs(self) -> None:
        with patch.object(run_vertical_slice, "run_semantic", return_value={"steps": 1}) as semantic:
            with patch.object(
                sys,
                "argv",
                [
                    "run_vertical_slice.py", "semantic", "--seed", "83", "--artifact-root", "B:/ember-artifacts",
                    "--receipt", "semantic/receipt.json", "--shards-root", "semantic/shards",
                    "--tokenizer", "semantic/tokenizer.json", "--steps", "1", "--sequence-length", "1024", "--checkpoint-interval", "32", "--write-budget-gib", "24",
                ],
            ):
                run_vertical_slice.main()
        semantic.assert_called_once_with(
            seed=83,
            artifact_root=Path("B:/ember-artifacts"),
            receipt_path=Path("semantic/receipt.json"),
            shards_root=Path("semantic/shards"),
            tokenizer_path=Path("semantic/tokenizer.json"),
            steps=1,
            sequence_length=1024,
            checkpoint_interval=32,
            write_budget_bytes=24 * 1024**3,
            resume_checkpoint=None,
        )

    def test_specialist_lineage_request_binds_parent_to_exact_resume_bundle(self) -> None:
        verification = {"result": "VERIFIED", "capability": "image"}
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "parent"
            parent.mkdir()
            manifest = parent / "checkpoint-manifest.json"
            manifest.write_text(json.dumps({"schema_version": "ember-sparse-checkpoint-v3"}), encoding="utf-8")
            with patch.object(run_vertical_slice, "preflight_specialist_lineage_sources") as preflight:
                lineage = run_vertical_slice.specialist_lineage_request(
                    capability="image", verification=verification, resume_checkpoint=parent,
                    parent_manifest=manifest, root_manifest=manifest,
                )
                self.assertEqual(lineage["trained_expert_ids"], ["vision"])
                preflight.assert_called_once_with(parent_manifest=manifest.resolve(), root_manifest=manifest.resolve())
                with self.assertRaisesRegex(ValueError, "exact resumed"):
                    run_vertical_slice.specialist_lineage_request(
                        capability="image", verification=verification, resume_checkpoint=Path(directory) / "other",
                        parent_manifest=manifest, root_manifest=manifest,
                    )
    def test_specialist_dispatch_does_not_enter_cuda_runner_when_lineage_preflight_fails(self) -> None:
        verification = {"result": "VERIFIED", "capability": "image"}
        with patch.object(run_vertical_slice, "load_verified_specialist_records", return_value=([], verification)):
            with patch.object(run_vertical_slice, "specialist_lineage_request", side_effect=ValueError("parent shard hash mismatch")):
                with patch.object(run_vertical_slice, "run") as cuda_runner:
                    with self.assertRaisesRegex(ValueError, "hash mismatch"):
                        run_vertical_slice.run_specialist(
                            seed=84, artifact_root=Path("B:/ember-artifacts"), data_manifest=Path("data/vision.json"),
                            tokenizer_path=Path("tokenizer.json"), capability="image", resume_checkpoint=Path("B:/parent"),
                            parent_manifest=Path("B:/parent/checkpoint-manifest.json"), root_manifest=Path("B:/root/checkpoint-manifest.json"),
                        )
        cuda_runner.assert_not_called()
    def test_specialist_cli_dispatches_one_verified_route(self) -> None:
        with patch.object(run_vertical_slice, "run_specialist", return_value={"steps": 1}) as specialist:
            with patch.object(sys, "argv", ["run_vertical_slice.py", "specialist", "--seed", "84", "--artifact-root", "B:/ember-artifacts", "--data-manifest", "data/vision.json", "--tokenizer", "tokenizer.json", "--capability", "image", "--resume-checkpoint", "B:/parent", "--parent-manifest", "B:/parent/checkpoint-manifest.json", "--root-manifest", "B:/root/checkpoint-manifest.json"]):
                run_vertical_slice.main()
        specialist.assert_called_once_with(seed=84, artifact_root=Path("B:/ember-artifacts"), data_manifest=Path("data/vision.json"), tokenizer_path=Path("tokenizer.json"), capability="image", resume_checkpoint=Path("B:/parent"), parent_manifest=Path("B:/parent/checkpoint-manifest.json"), root_manifest=Path("B:/root/checkpoint-manifest.json"))
    def test_resume_lineage_uses_verified_parent_genesis_not_requested_seed(self) -> None:
        genesis = {"vision": "a" * 64, "audio": "b" * 64, "reasoning": "c" * 64, "tool": "d" * 64}
        self.assertEqual(run_vertical_slice.resume_expert_genesis({"expert_genesis_sha256": genesis}, requested_seed=999), genesis)

    def test_runner_file_exposes_the_semantic_cli_entrypoint(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "ember-restart-3b" / "run_vertical_slice.py"), "semantic", "--help"],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--receipt", completed.stdout)

    def test_nonsemantic_vertical_runner_does_not_depend_on_semantic_publication_inputs(self) -> None:
        source = inspect.getsource(run_vertical_slice.run)
        self.assertNotIn("checkpoint_serialization_byte_bound", source)
        self.assertNotIn("semantic_publication_plan", source)
    def test_runner_has_one_retention_implementation(self) -> None:
        self.assertEqual(inspect.getsource(run_vertical_slice).count("def _retain_after_success("), 1)
    def test_bf16_contract_disables_unsupported_percentile_clipping(self) -> None:
        contract = run_vertical_slice.load_optimizer_contract(ROOT / "configs" / "ember-restart-3b.json")
        self.assertEqual(contract["hyperparameters"]["percentile_clipping"], 100)
if __name__ == "__main__":
    unittest.main()
