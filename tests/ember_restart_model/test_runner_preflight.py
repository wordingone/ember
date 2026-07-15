# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute runner preflight helpers without allocating the production model."""

from __future__ import annotations

import inspect
from contextlib import ExitStack
import hashlib
import json
import tempfile

import sys
import subprocess
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    def test_specialist_loader_rejects_manifest_or_artifact_mutation_after_verifier_receipt(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            records_path = root / "records.json"
            source_path = root / "source.json"
            manifest_path = root / "manifest.json"
            records_path.write_text(json.dumps({"records": [{"active_expert": "reasoning"}]}), encoding="utf-8")
            source_path.write_text("{}", encoding="utf-8")
            sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps({"records_artifact": {"path": "records.json", "sha256": sha(records_path)}, "source_manifest": {"path": "source.json", "sha256": sha(source_path)}}), encoding="utf-8")
            verification = {"result": "VERIFIED", "capability": "reasoning", "generator_replay_verified": True, "data_manifest_sha256": sha(manifest_path), "source_manifest_sha256": sha(source_path), "records_artifact_sha256": sha(records_path)}
            def verified_then_mutated(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
                records_path.write_text(json.dumps({"records": [{"active_expert": "reasoning", "mutated": True}]}), encoding="utf-8")
                return subprocess.CompletedProcess([], 0, json.dumps(verification), "")
            with patch.object(run_vertical_slice.subprocess, "run", side_effect=verified_then_mutated):
                with self.assertRaisesRegex(RuntimeError, "changed after verification"):
                    run_vertical_slice.load_verified_specialist_records(root=root, data_manifest=manifest_path, tokenizer_path=root / "tokenizer.json", capability="reasoning")
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

    def _run_semantic_with_mocks(self, *, resume: bool) -> tuple[dict[str, object], dict[str, object], MagicMock, list[int]]:
        model = SimpleNamespace(active_expert="reasoning")
        model._activate_expert = lambda expert: setattr(model, "active_expert", expert)
        model.expert_bank_genesis_hashes = lambda: {name: name * 64 for name in ("vision", "audio", "reasoning", "tool")}
        optimizer = SimpleNamespace(param_groups=[{"lr": 1e-5}])
        stream = SimpleNamespace(vocab_size=32_000, receipt_sha256="r" * 64, tokenizer_sha256="t" * 64)
        counts = {"unique_parameters": 3_839_161_856, "active_parameters": 1_020_589_568}
        segment_kwargs: dict[str, object] = {}
        retention_bounds: list[int] = []
        writer = MagicMock(return_value={"published": True})
        parent = Path("B:/semantic-parent")
        parent_manifest = parent / "checkpoint-manifest.json"
        real_read_text = Path.read_text
        genesis = {name: (index.to_bytes(1, "little") * 32).hex() for index, name in enumerate(("vision", "audio", "reasoning", "tool"), start=1)}

        def read_text(path: Path, *args: object, **kwargs: object) -> str:
            if path.resolve() == parent_manifest.resolve():
                return json.dumps({"expert_genesis_sha256": genesis})
            return real_read_text(path, *args, **kwargs)

        def retain(_parent: Path, *, max_serialized_bytes: int, operation: object, **_kwargs: object) -> object:
            retention_bounds.append(max_serialized_bytes)
            return operation()

        def segment(**kwargs: object) -> dict[str, object]:
            segment_kwargs.update(kwargs)
            initial = int(kwargs["initial_global_step"])
            steps = int(kwargs["steps"])
            interval = int(kwargs["checkpoint_every"])
            callback = kwargs["checkpoint_callback"]
            for step in range(initial + 1, initial + steps + 1):
                if step % interval == 0 or step == initial + steps:
                    callback(step, {"data_cursor": {"shard": "TOKEN-SHARDS-V0:current", "record_index": step, "global_step": step, "tokens_seen": step * 1024}})
            return {"global_step": initial + steps, "tokens_seen": (initial + steps) * 1024, "data_cursor": {"shard": "TOKEN-SHARDS-V0:current", "record_index": initial + steps, "global_step": initial + steps, "tokens_seen": (initial + steps) * 1024}}

        with ExitStack() as stack:
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "is_available", return_value=True))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "mem_get_info", return_value=(32 * 1024**3, 32 * 1024**3)))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "manual_seed_all"))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "reset_peak_memory_stats"))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "max_memory_allocated", return_value=0))
            stack.enter_context(patch.object(run_vertical_slice.torch, "manual_seed"))
            stack.enter_context(patch.object(run_vertical_slice.torch, "get_default_dtype", return_value=torch.float32))
            stack.enter_context(patch.object(run_vertical_slice.torch, "set_default_dtype"))
            stack.enter_context(patch.object(run_vertical_slice, "production_artifact_root", side_effect=lambda path: path))
            stack.enter_context(patch.object(run_vertical_slice.ManifestBoundTokenStream, "from_receipt", return_value=stream))
            stack.enter_context(patch.object(run_vertical_slice, "UnifiedDecoder", return_value=model))
            stack.enter_context(patch.object(run_vertical_slice, "measure_parameter_counts", return_value=counts))
            stack.enter_context(patch.object(run_vertical_slice, "build_production_optimizer", return_value=optimizer))
            stack.enter_context(patch.object(run_vertical_slice, "_rng_state_hash", return_value={"cpu": "c" * 64, "cuda": "d" * 64}))
            stack.enter_context(patch.object(run_vertical_slice, "_rng_state", return_value={"cpu": torch.tensor([1]), "cuda": torch.tensor([2])}))
            stack.enter_context(patch.object(run_vertical_slice, "run_manifest_bound_semantic_segment", side_effect=segment))
            stack.enter_context(patch.object(run_vertical_slice, "_retain_after_success", side_effect=retain))
            stack.enter_context(patch.object(run_vertical_slice, "write_checkpoint_artifacts", writer))
            stack.enter_context(patch.object(run_vertical_slice, "_execute_realization_counter", return_value={"counter": "ok"}))
            stack.enter_context(patch.object(run_vertical_slice, "load_checkpoint_artifacts", return_value={"data_cursor": {"shard": "TOKEN-SHARDS-V0:prior", "record_index": 7, "global_step": 31, "tokens_seen": 31 * 1024}}))
            stack.enter_context(patch.object(Path, "is_dir", autospec=True, side_effect=lambda path: path.drive.upper() == "B:"))
            stack.enter_context(patch.object(Path, "read_text", autospec=True, side_effect=read_text))
            stack.enter_context(patch.object(run_vertical_slice, "_sha256", return_value="h" * 64))
            result = run_vertical_slice.run_semantic(
                seed=83, artifact_root=Path("B:/semantic-artifacts"), receipt_path=Path("receipt.json"),
                shards_root=Path("shards"), tokenizer_path=Path("tokenizer.json"), steps=2,
                sequence_length=1024, checkpoint_interval=32, write_budget_bytes=24 * 1024**3,
                resume_checkpoint=parent if resume else None,
            )
        return result, segment_kwargs, writer, retention_bounds

    def test_semantic_run_fresh_binds_publication_plan_and_writer_limit(self) -> None:
        result, segment_kwargs, writer, retention_bounds = self._run_semantic_with_mocks(resume=False)
        bound = run_vertical_slice.checkpoint_serialization_byte_bound(ROOT / "configs" / "ember-restart-3b.json", active_parameters=1_020_589_568)
        self.assertEqual(segment_kwargs["initial_global_step"], 0)
        self.assertEqual(segment_kwargs["initial_tokens_seen"], 0)
        self.assertEqual(result["publication_plan"], {"publication_count": 1, "checkpoint_byte_bound": bound, "projected_write_bytes": bound})
        self.assertEqual(retention_bounds, [run_vertical_slice.checkpoint_retention_budget_bytes(ROOT / "configs" / "ember-restart-3b.json")])
        self.assertEqual(writer.call_count, 1)
        self.assertEqual(writer.call_args.kwargs["max_serialized_bytes"], bound)

    def test_semantic_run_resume_uses_parent_step_and_final_publication(self) -> None:
        result, segment_kwargs, writer, _retention_bounds = self._run_semantic_with_mocks(resume=True)
        bound = run_vertical_slice.checkpoint_serialization_byte_bound(ROOT / "configs" / "ember-restart-3b.json", active_parameters=1_020_589_568)
        self.assertEqual(segment_kwargs["initial_global_step"], 31)
        self.assertEqual(segment_kwargs["initial_tokens_seen"], 31 * 1024)
        self.assertEqual(result["publication_plan"], {"publication_count": 2, "checkpoint_byte_bound": bound, "projected_write_bytes": 2 * bound})
        self.assertEqual(writer.call_count, 2)
        self.assertTrue(all(call.kwargs["max_serialized_bytes"] == bound for call in writer.call_args_list))
    def _run_vertical_resume_with_mocks(self, *, specialist: bool) -> tuple[dict[str, object], dict[str, object], MagicMock]:
        model = SimpleNamespace(active_expert="reasoning")
        model.train = lambda: None
        model.expert_bank_genesis_hashes = lambda: {name: name * 64 for name in ("vision", "audio", "reasoning", "tool")}
        optimizer = SimpleNamespace(param_groups=[{"lr": 1e-5}])
        counts = {"unique_parameters": 3_839_161_856, "active_parameters": 1_725_232_640}
        segment_kwargs: dict[str, object] = {}
        writer = MagicMock(return_value={"published": True})
        parent = Path("B:/vertical-parent")
        parent_manifest = parent / "checkpoint-manifest.json"
        real_read_text = Path.read_text
        genesis = {name: (index.to_bytes(1, "little") * 32).hex() for index, name in enumerate(("vision", "audio", "reasoning", "tool"), start=1)}

        def read_text(path: Path, *args: object, **kwargs: object) -> str:
            if path.resolve() == parent_manifest.resolve():
                return json.dumps({"expert_genesis_sha256": genesis})
            return real_read_text(path, *args, **kwargs)

        def segment(**kwargs: object) -> dict[str, object]:
            segment_kwargs.update(kwargs)
            return {"losses": [0.1], "data_cursor": {"shard": str(kwargs["data_shard_id"]), "record_index": 1, "global_step": 20, "tokens_seen": 20_480}}

        with ExitStack() as stack:
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "is_available", return_value=True))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "mem_get_info", return_value=(32 * 1024**3, 32 * 1024**3)))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "manual_seed_all"))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "reset_peak_memory_stats"))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "max_memory_allocated", return_value=0))
            stack.enter_context(patch.object(run_vertical_slice.torch, "manual_seed"))
            stack.enter_context(patch.object(run_vertical_slice.torch, "get_default_dtype", return_value=torch.float32))
            stack.enter_context(patch.object(run_vertical_slice.torch, "set_default_dtype"))
            stack.enter_context(patch.object(run_vertical_slice, "production_artifact_root", side_effect=lambda path: path))
            stack.enter_context(patch.object(run_vertical_slice, "UnifiedDecoder", return_value=model))
            stack.enter_context(patch.object(run_vertical_slice, "measure_parameter_counts", return_value=counts))
            stack.enter_context(patch.object(run_vertical_slice, "build_production_optimizer", return_value=optimizer))
            stack.enter_context(patch.object(run_vertical_slice, "_rng_state_hash", return_value={"cpu": "c" * 64, "cuda": "d" * 64}))
            stack.enter_context(patch.object(run_vertical_slice, "_rng_state", return_value={"cpu": torch.tensor([1]), "cuda": torch.tensor([2])}))
            stack.enter_context(patch.object(run_vertical_slice, "run_pretraining_segment", side_effect=segment))
            stack.enter_context(patch.object(run_vertical_slice, "_retain_after_success", side_effect=lambda _parent, *, operation, **_kwargs: operation()))
            stack.enter_context(patch.object(run_vertical_slice, "write_checkpoint_artifacts", writer))
            stack.enter_context(patch.object(run_vertical_slice, "_execute_realization_counter", return_value={"counter": "ok"}))
            stack.enter_context(patch.object(run_vertical_slice, "load_checkpoint_artifacts", return_value={"data_cursor": {"shard": "TOKEN-SHARDS-V0:prior", "record_index": 37, "global_step": 19, "tokens_seen": 19_456}}))
            stack.enter_context(patch.object(run_vertical_slice, "load_authorized_records", return_value=([{"active_expert": "shared"}], {"input_identity": {"shard_path": "TOKEN-SHARDS-V0:prior"}}, {"receipt": "bound"})))
            stack.enter_context(patch.object(Path, "is_dir", autospec=True, side_effect=lambda path: path.drive.upper() == "B:"))
            stack.enter_context(patch.object(Path, "read_text", autospec=True, side_effect=read_text))
            stack.enter_context(patch.object(run_vertical_slice, "_sha256", return_value="h" * 64))
            result = run_vertical_slice.run(
                seed=84, artifact_root=Path("B:/vertical-artifacts"), resume_checkpoint=parent,
                records_override=[{"active_expert": "vision"}] if specialist else None,
                specialist_verification={"data_manifest_sha256": "a" * 64} if specialist else None,
                specialist_lineage={"parent_manifest": str(parent_manifest), "root_manifest": str(parent_manifest)} if specialist else None,
            )
        return result, segment_kwargs, writer

    def test_vertical_resume_preserves_owned_cursor_but_resets_only_specialist_cursor(self) -> None:
        _ordinary_result, ordinary_kwargs, ordinary_writer = self._run_vertical_resume_with_mocks(specialist=False)
        _specialist_result, specialist_kwargs, specialist_writer = self._run_vertical_resume_with_mocks(specialist=True)
        bound = run_vertical_slice.checkpoint_serialization_byte_bound(ROOT / "configs" / "ember-restart-3b.json", active_parameters=1_725_232_640)
        self.assertEqual(ordinary_kwargs["initial_data_cursor"], 37)
        self.assertEqual(ordinary_kwargs["initial_global_step"], 19)
        self.assertEqual(specialist_kwargs["initial_data_cursor"], 0)
        self.assertEqual(specialist_kwargs["initial_global_step"], 19)
        self.assertTrue(str(specialist_kwargs["data_shard_id"]).startswith("VERIFIED_SPECIALIST:"))
        self.assertEqual(ordinary_writer.call_args.kwargs["max_serialized_bytes"], bound)
        self.assertEqual(specialist_writer.call_args.kwargs["max_serialized_bytes"], bound)
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
        self.assertIn("checkpoint_serialization_byte_bound", source)
        self.assertNotIn("semantic_publication_plan", source)
    def test_runner_has_one_retention_implementation(self) -> None:
        self.assertEqual(inspect.getsource(run_vertical_slice).count("def _retain_after_success("), 1)
    def test_bf16_contract_disables_unsupported_percentile_clipping(self) -> None:
        contract = run_vertical_slice.load_optimizer_contract(ROOT / "configs" / "ember-restart-3b.json")
        self.assertEqual(contract["hyperparameters"]["percentile_clipping"], 100)
if __name__ == "__main__":
    unittest.main()
