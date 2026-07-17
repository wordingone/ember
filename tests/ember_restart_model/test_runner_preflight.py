# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute runner preflight helpers without allocating the production model."""

from __future__ import annotations

import inspect
from contextlib import ExitStack
import hashlib
import json
import os
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
    def test_specialist_execution_slice_binds_exact_contiguous_records_and_tokens(self) -> None:
        records = [
            {"active_expert": "vision", "token_ids": [1, 2], "row_id": "zero"},
            {"active_expert": "vision", "token_ids": [3, 4, 5], "row_id": "one"},
            {"active_expert": "vision", "token_ids": [6], "row_id": "two"},
        ]
        selected, receipt = run_vertical_slice.bind_specialist_execution_slice(
            records, start_record=1, max_records=1,
        )
        self.assertEqual(selected, [records[1]])
        self.assertEqual(
            receipt,
            {
                "schema_version": "ember-specialist-execution-slice-v1",
                "start_record": 1,
                "record_count": 1,
                "token_count": 3,
                "records_sha256": hashlib.sha256(
                    json.dumps([records[1]], sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
                "tokens_sha256": hashlib.sha256(
                    json.dumps([[3, 4, 5]], separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
            },
        )
        with self.assertRaisesRegex(ValueError, "start record"):
            run_vertical_slice.bind_specialist_execution_slice(records, start_record=3, max_records=1)
        with self.assertRaisesRegex(ValueError, "max records"):
            run_vertical_slice.bind_specialist_execution_slice(records, start_record=0, max_records=0)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            run_vertical_slice.bind_specialist_execution_slice(records, start_record=2, max_records=2)

    def test_training_telemetry_is_bounded_path_free_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            channel = Path(directory) / "ember-telemetry.jsonl"
            run_vertical_slice.append_training_telemetry(
                channel,
                kind="train_step",
                payload={"run_id": "vision-v4", "step": 3, "total_steps": 10, "loss": 4.0, "step_ms": 125.0},
            )
            event = json.loads(channel.read_text(encoding="utf-8"))
            self.assertEqual(event["kind"], "train_step")
            self.assertEqual(event["source"], "ember-restart-3b")
            self.assertEqual(event["payload"]["step"], 3)
            self.assertLess(channel.stat().st_size, 4096)
            with self.assertRaisesRegex(ValueError, "filesystem paths"):
                run_vertical_slice.append_training_telemetry(
                    channel,
                    kind="checkpoint",
                    payload={"run_id": "vision-v4", "checkpoint_path": "C:/secret"},
                )

    def test_specialist_loader_ignores_ambient_pythonpath_and_prioritizes_canonical_verifier(self) -> None:
        """The independent verifier must never import ambient generator/tokenizer modules."""
        from build_specialist_bundle import emit_bundle
        from tokenizers import Tokenizer, models, pre_tokenizers

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            tokenizer = root / "tokenizer.json"
            vocabulary = {
                "<unk>": 0, "reasoning": 1, "sum": 2, "plus": 3, "equals": 4,
                "tool": 5, "calculator": 6,
                **{f"filler-{index}": index for index in range(7, 32_000)},
            }
            frozen = Tokenizer(models.WordLevel(vocabulary, unk_token="<unk>"))
            frozen.pre_tokenizer = pre_tokenizers.Whitespace()
            frozen.save(str(tokenizer))
            config = root / "config.json"
            config.write_bytes((ROOT / "configs" / "ember-restart-3b.json").read_bytes())
            manifest = emit_bundle(repo_root=ROOT, output_root=root / "bundle", tokenizer_path=tokenizer, model_config_path=config, count=4_096)["reasoning"]
            poison = root / "ambient-poison"
            poison.mkdir()
            marker = root / "ambient-imported.txt"
            poison_module = "from pathlib import Path; Path(" + repr(str(marker)) + ").write_text('poison', encoding='utf-8'); raise RuntimeError('ambient poison imported')\n"
            (poison / "build_owned_reasoning_tool_trajectories.py").write_text(poison_module, encoding="utf-8")
            (poison / "tokenizers.py").write_text(poison_module, encoding="utf-8")
            (poison / "sitecustomize.py").write_text(poison_module, encoding="utf-8")
            with patch.dict(os.environ, {"PYTHONPATH": str(poison)}, clear=False):
                records, receipt = run_vertical_slice.load_verified_specialist_records(
                    root=ROOT, data_manifest=manifest, tokenizer_path=tokenizer, capability="reasoning",
                )
            self.assertFalse(marker.exists(), "the isolated verifier imported an ambient PYTHONPATH candidate")
            self.assertGreaterEqual(len(records), 4_096)
            self.assertEqual(receipt["result"], "VERIFIED")
        wrapper = inspect.getsource(run_vertical_slice.load_verified_specialist_records)
        self.assertIn("sys.path[:0]=[sys.argv[1],sys.argv[2]]", wrapper)
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
            config.write_bytes((ROOT / "configs" / "ember-restart-3b.json").read_bytes())
            manifest = emit_bundle(repo_root=ROOT, output_root=root / "bundle", tokenizer_path=tokenizer, model_config_path=config, count=4_096)["reasoning"]
            records_out, verification = run_vertical_slice.load_verified_specialist_records(root=ROOT, data_manifest=manifest, tokenizer_path=tokenizer, capability="reasoning")
        self.assertGreaterEqual(len(records_out), 4_096)
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
            config_path = root / "configs" / "ember-restart-3b.json"
            config_path.parent.mkdir()
            config_path.write_bytes((ROOT / "configs" / "ember-restart-3b.json").read_bytes())
            records_path.write_text(json.dumps({"records": [{"active_expert": "reasoning"}]}), encoding="utf-8")
            source_path.write_text("{}", encoding="utf-8")
            sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps({"records_artifact": {"path": "records.json", "sha256": sha(records_path)}, "source_manifest": {"path": "source.json", "sha256": sha(source_path)}}), encoding="utf-8")
            from semantic_contract import semantic_model_contract_sha256
            verification = {"result": "VERIFIED", "capability": "reasoning", "generator_replay_verified": True, "admission": "ADMISSIBLE_SEMANTIC_CONTRACT", "semantic_model_contract_sha256": semantic_model_contract_sha256(json.loads(config_path.read_bytes())), "data_manifest_sha256": sha(manifest_path), "source_manifest_sha256": sha(source_path), "records_artifact_sha256": sha(records_path)}
            def verified_then_mutated(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
                records_path.write_text(json.dumps({"records": [{"active_expert": "reasoning", "mutated": True}]}), encoding="utf-8")
                return subprocess.CompletedProcess([], 0, json.dumps(verification), "")
            with patch.object(run_vertical_slice.subprocess, "run", side_effect=verified_then_mutated):
                with self.assertRaisesRegex(RuntimeError, "changed after verification"):
                    run_vertical_slice.load_verified_specialist_records(root=root, data_manifest=manifest_path, tokenizer_path=root / "tokenizer.json", capability="reasoning")

    def test_specialist_loader_rejects_verified_data_for_a_different_runtime_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "configs" / "ember-restart-3b.json"
            config_path.parent.mkdir()
            config_path.write_bytes((ROOT / "configs" / "ember-restart-3b.json").read_bytes())
            manifest = root / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            verification = {
                "result": "VERIFIED",
                "capability": "image",
                "generator_replay_verified": True,
                "admission": "ADMISSIBLE_SEMANTIC_CONTRACT",
                "semantic_model_contract_sha256": "0" * 64,
            }
            with patch.object(run_vertical_slice.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(verification), "")):
                with self.assertRaisesRegex(RuntimeError, "does not match the runtime model contract"):
                    run_vertical_slice.load_verified_specialist_records(
                        root=root,
                        data_manifest=manifest,
                        tokenizer_path=root / "tokenizer.json",
                        capability="image",
                    )
    def test_production_optimizer_uses_declared_device_resident_8bit_adamw_state(self) -> None:
        calls: dict[str, object] = {}

        class Subject:
            def parameters(self) -> list[str]:
                return ["parameter"]

        def make_adamw(parameters: object, **kwargs: object) -> object:
            calls["parameters"] = parameters
            calls.update(kwargs)
            return "optimizer"

        fake = SimpleNamespace(optim=SimpleNamespace(AdamW8bit=make_adamw))
        with patch.dict(sys.modules, {"bitsandbytes": fake}):
            contract = run_vertical_slice.load_optimizer_contract(ROOT / "configs" / "ember-restart-3b.json")
            optimizer = run_vertical_slice.build_production_optimizer(Subject(), optimizer_contract=contract)
        self.assertEqual(optimizer, "optimizer")
        self.assertEqual(contract["name"], "device_resident_8bit_adamw")
        self.assertEqual(contract["implementation"], "bitsandbytes.optim.AdamW8bit")
        self.assertEqual(contract["state_format"], "bitsandbytes-device-resident-8bit-adamw-state-dict-v1")
        self.assertEqual(contract["hyperparameters"]["learning_rate"], 1e-5)
        self.assertEqual(calls["parameters"], ["parameter"])
        self.assertEqual(calls["percentile_clipping"], 100)
        self.assertEqual(calls["lr"], 1e-5)

    def test_production_optimizer_rejects_the_previous_paged_contract(self) -> None:
        contract = run_vertical_slice.load_optimizer_contract(ROOT / "configs" / "ember-restart-3b.json")
        previous = {
            **contract,
            "name": "paged_8bit_adamw",
            "implementation": "bitsandbytes.optim.PagedAdamW8bit",
            "state_format": "bitsandbytes-paged-8bit-adamw-state-dict-v1",
        }
        with self.assertRaisesRegex(ValueError, "device-resident AdamW8bit"):
            run_vertical_slice.build_production_optimizer(SimpleNamespace(parameters=lambda: []), optimizer_contract=previous)
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
    def test_v4_specialist_preflight_reserves_the_full_copy_fallback(self) -> None:
        active = 1_725_232_640
        full = run_vertical_slice.checkpoint_serialization_byte_bound(
            ROOT / "configs" / "ember-restart-3b.json", active_parameters=active,
        )
        self.assertEqual(full, 3_839_161_856 * 2 + active * 2 + 1024**3)

    def test_checkpoint_host_commit_reserve_is_contract_bound(self) -> None:
        self.assertEqual(
            run_vertical_slice.checkpoint_host_commit_reserve_bytes(
                ROOT / "configs" / "ember-restart-3b.json"
            ),
            8 * 1024**3,
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
        writer.side_effect = lambda *args, **kwargs: (kwargs["pre_publish_verifier"](args[2], {}), {"published": True})[-1]
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
            stack.enter_context(patch.object(run_vertical_slice, "production_artifact_root", side_effect=lambda path, **_kwargs: path))
            stack.enter_context(patch.object(run_vertical_slice.ManifestBoundTokenStream, "from_receipt", return_value=stream))
            stack.enter_context(patch.object(run_vertical_slice, "UnifiedDecoder", return_value=model))
            stack.enter_context(patch.object(run_vertical_slice, "measure_parameter_counts", return_value=counts))
            stack.enter_context(patch.object(run_vertical_slice, "build_production_optimizer", return_value=optimizer))
            stack.enter_context(patch.object(run_vertical_slice, "_rng_state_hash", return_value={"cpu": "c" * 64, "cuda": "d" * 64}))
            stack.enter_context(patch.object(run_vertical_slice, "_rng_state", return_value={"cpu": torch.tensor([1]), "cuda": torch.tensor([2])}))
            stack.enter_context(patch.object(run_vertical_slice, "run_manifest_bound_semantic_segment", side_effect=segment))
            stack.enter_context(patch.object(run_vertical_slice, "_retain_after_success", side_effect=retain))
            stack.enter_context(patch.object(run_vertical_slice, "write_checkpoint_artifacts", writer))
            stack.enter_context(patch.object(run_vertical_slice, "_atomic_json"))
            stack.enter_context(patch.object(run_vertical_slice, "_execute_realization_counter", return_value={"counter": "ok"}))
            stack.enter_context(patch.object(run_vertical_slice, "publish_counter_verified_checkpoint", side_effect=lambda *, write_candidate, execute_counter, **_kwargs: (write_candidate(), execute_counter())))
            stack.enter_context(patch.object(run_vertical_slice, "require_counter_success_receipt", return_value={"verified": True, "counter_sha256": "h" * 64}))
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
        self.assertEqual(writer.call_args.kwargs["host_commit_reserve_bytes"], 8 * 1024**3)

    def test_semantic_run_resume_uses_parent_step_and_final_publication(self) -> None:
        result, segment_kwargs, writer, _retention_bounds = self._run_semantic_with_mocks(resume=True)
        bound = run_vertical_slice.checkpoint_serialization_byte_bound(ROOT / "configs" / "ember-restart-3b.json", active_parameters=1_020_589_568)
        self.assertEqual(segment_kwargs["initial_global_step"], 31)
        self.assertEqual(segment_kwargs["initial_tokens_seen"], 31 * 1024)
        self.assertEqual(result["publication_plan"], {"publication_count": 2, "checkpoint_byte_bound": bound, "projected_write_bytes": 2 * bound})
        self.assertEqual(writer.call_count, 2)
        self.assertTrue(all(call.kwargs["max_serialized_bytes"] == bound for call in writer.call_args_list))
        self.assertTrue(all(call.kwargs["host_commit_reserve_bytes"] == 8 * 1024**3 for call in writer.call_args_list))
    def _run_vertical_resume_with_mocks(
        self, *, specialist: bool, callback_steps: tuple[int, ...] = (),
    ) -> tuple[dict[str, object], dict[str, object], MagicMock]:
        model = SimpleNamespace(active_expert="reasoning")
        model.train = lambda: None
        model.activation_calls = []
        def activate(expert: str) -> None:
            model.active_expert = expert
            model.activation_calls.append(expert)
        model._activate_expert = activate
        model.expert_bank_genesis_hashes = lambda: {name: name * 64 for name in ("vision", "audio", "reasoning", "tool")}
        optimizer = SimpleNamespace(param_groups=[{"lr": 1e-5}])
        counts = {"unique_parameters": 3_839_161_856, "active_parameters": 1_725_232_640}
        segment_kwargs: dict[str, object] = {}
        writer = MagicMock(return_value={"published": True})
        writer.side_effect = lambda *args, **kwargs: (kwargs["pre_publish_verifier"](args[2], {}), {"published": True})[-1]
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
            published_steps = callback_steps or (20,)
            result = {"losses": [0.1], "data_cursor": {"shard": str(kwargs["data_shard_id"]), "record_index": len(published_steps), "global_step": published_steps[-1], "tokens_seen": 20_480}}
            for record_index, step in enumerate(published_steps, start=1):
                callback_result = {
                    **result,
                    "data_cursor": {**result["data_cursor"], "record_index": record_index, "global_step": step},
                }
                kwargs["checkpoint_callback"](step, callback_result)
            return result

        with ExitStack() as stack:
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "is_available", return_value=True))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "mem_get_info", return_value=(32 * 1024**3, 32 * 1024**3)))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "manual_seed_all"))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "reset_peak_memory_stats"))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "max_memory_allocated", return_value=0))
            stack.enter_context(patch.object(run_vertical_slice.torch, "manual_seed"))
            stack.enter_context(patch.object(run_vertical_slice.torch, "get_default_dtype", return_value=torch.float32))
            stack.enter_context(patch.object(run_vertical_slice.torch, "set_default_dtype"))
            stack.enter_context(patch.object(run_vertical_slice, "production_artifact_root", side_effect=lambda path, **_kwargs: path))
            stack.enter_context(patch.object(run_vertical_slice, "UnifiedDecoder", return_value=model))
            def measure(_model: object) -> dict[str, int]:
                if specialist:
                    segment_kwargs["count_active_expert"] = model.active_expert
                return counts
            def build(_model: object, **_kwargs: object) -> object:
                if specialist:
                    segment_kwargs["optimizer_active_expert"] = model.active_expert
                return optimizer
            stack.enter_context(patch.object(run_vertical_slice, "measure_parameter_counts", side_effect=measure))
            stack.enter_context(patch.object(run_vertical_slice, "build_production_optimizer", side_effect=build))
            stack.enter_context(patch.object(run_vertical_slice, "_rng_state_hash", return_value={"cpu": "c" * 64, "cuda": "d" * 64}))
            stack.enter_context(patch.object(run_vertical_slice, "_rng_state", return_value={"cpu": torch.tensor([1]), "cuda": torch.tensor([2])}))
            stack.enter_context(patch.object(run_vertical_slice, "run_pretraining_segment", side_effect=segment))
            stack.enter_context(patch.object(run_vertical_slice, "_retain_after_success", side_effect=lambda _parent, *, operation, **_kwargs: operation()))
            stack.enter_context(patch.object(run_vertical_slice, "write_checkpoint_artifacts", writer))
            stack.enter_context(patch.object(run_vertical_slice, "_atomic_json"))
            stack.enter_context(patch.object(run_vertical_slice, "_execute_realization_counter", return_value={"counter": "ok"}))
            stack.enter_context(patch.object(run_vertical_slice, "publish_counter_verified_checkpoint", side_effect=lambda *, write_candidate, execute_counter, **_kwargs: (write_candidate(), execute_counter())))
            stack.enter_context(patch.object(run_vertical_slice, "require_counter_success_receipt", return_value={"verified": True, "counter_sha256": "h" * 64}))
            stack.enter_context(patch.object(run_vertical_slice, "load_checkpoint_artifacts", return_value={"data_cursor": {"shard": "TOKEN-SHARDS-V0:prior", "record_index": 37, "global_step": 19, "tokens_seen": 19_456}}))
            stack.enter_context(patch.object(run_vertical_slice, "load_authorized_records", return_value=([{"active_expert": "shared"}], {"input_identity": {"shard_path": "TOKEN-SHARDS-V0:prior"}}, {"receipt": "bound"})))
            stack.enter_context(patch.object(Path, "is_dir", autospec=True, side_effect=lambda path: path.drive.upper() == "B:"))
            stack.enter_context(patch.object(Path, "read_text", autospec=True, side_effect=read_text))
            stack.enter_context(patch.object(run_vertical_slice, "_sha256", return_value="h" * 64))
            result = run_vertical_slice.run(
                seed=84, artifact_root=Path("B:/vertical-artifacts"), resume_checkpoint=parent,
                records_override=([{"active_expert": "vision", "token_ids": [index + 1]} for index in range(len(callback_steps or (20,)))] if specialist else None),
                specialist_verification={"capability": "image", "data_manifest_sha256": "a" * 64} if specialist else None,
                specialist_lineage={"parent_manifest": str(parent_manifest), "root_manifest": str(parent_manifest), "execution_slice": {"start_record": 0, "records_sha256": "1" * 64}} if specialist else None,
                checkpoint_interval=8_192 if specialist else None,
                write_budget_bytes=100 * 1024**3 if specialist else None,
            )
        return result, segment_kwargs, writer

    def test_verified_specialist_episode_binds_requested_expert_before_setup(self) -> None:
        verification = {"capability": "image"}
        self.assertEqual(
            run_vertical_slice.verified_specialist_episode_expert(
                [{"active_expert": "vision"}], verification,
            ),
            "vision",
        )
        with self.assertRaisesRegex(ValueError, "verified image episode must route to vision"):
            run_vertical_slice.verified_specialist_episode_expert(
                [{"active_expert": "reasoning"}], verification,
            )
    def test_verified_specialist_expert_is_active_before_counts_and_optimizer(self) -> None:
        _result, segment_kwargs, _writer = self._run_vertical_resume_with_mocks(specialist=True)
        self.assertEqual(segment_kwargs["count_active_expert"], "vision")
        self.assertEqual(segment_kwargs["optimizer_active_expert"], "vision")
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
    def test_specialist_run_requests_periodic_checkpoint_interval(self) -> None:
        _result, specialist_kwargs, _writer = self._run_vertical_resume_with_mocks(specialist=True)
        self.assertEqual(specialist_kwargs["checkpoint_every"], 8_192)
    def test_specialist_publication_plan_counts_interval_and_mandatory_final_bundle(self) -> None:
        self.assertEqual(
            run_vertical_slice.specialist_publication_plan(
                records=65_536,
                checkpoint_interval=8_192,
                checkpoint_byte_bound=10,
                write_budget_bytes=90,
                initial_global_step=2,
            ),
            {"publication_count": 9, "checkpoint_byte_bound": 10, "projected_write_bytes": 90},
        )

    def test_specialist_periodic_checkpoints_chain_the_previous_published_manifest(self) -> None:
        _result, _kwargs, writer = self._run_vertical_resume_with_mocks(
            specialist=True, callback_steps=(8_192, 16_384),
        )
        self.assertEqual(writer.call_count, 2)
        first, second = writer.call_args_list
        self.assertEqual(
            Path(first.kwargs["specialist_lineage"]["parent_manifest"]),
            Path("B:/vertical-parent/checkpoint-manifest.json"),
        )
        self.assertEqual(
            Path(second.kwargs["specialist_lineage"]["parent_manifest"]),
            Path(first.args[2]) / "checkpoint-manifest.json",
        )
        self.assertEqual(first.kwargs["specialist_lineage"]["execution_slice"]["start_record"], 0)
        self.assertEqual(first.kwargs["specialist_lineage"]["execution_slice"]["record_count"], 1)
        self.assertEqual(second.kwargs["specialist_lineage"]["execution_slice"]["start_record"], 1)
        self.assertEqual(second.kwargs["specialist_lineage"]["execution_slice"]["record_count"], 1)
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
            resume_counter_receipt=None,
            resume_realization_registry=None,
        )

    def test_specialist_lineage_request_binds_parent_to_exact_resume_bundle(self) -> None:
        verification = {"result": "VERIFIED", "capability": "image", "record_count": 20}
        execution_slice = {
            "schema_version": "ember-specialist-execution-slice-v1", "start_record": 0,
            "record_count": 20, "token_count": 40, "records_sha256": "a" * 64,
            "tokens_sha256": "b" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "parent"
            parent.mkdir()
            manifest = parent / "checkpoint-manifest.json"
            manifest.write_text(json.dumps({"schema_version": "ember-sparse-checkpoint-v3"}), encoding="utf-8")
            with patch.object(run_vertical_slice, "preflight_specialist_lineage_sources") as preflight:
                lineage = run_vertical_slice.specialist_lineage_request(
                    capability="image", verification=verification, resume_checkpoint=parent,
                    parent_manifest=manifest, root_manifest=manifest, execution_slice=execution_slice,
                )
                self.assertEqual(lineage["trained_expert_ids"], ["vision"])
                self.assertEqual(lineage["execution_slice"], execution_slice)
                preflight.assert_called_once_with(parent_manifest=manifest.resolve(), root_manifest=manifest.resolve())
                with self.assertRaisesRegex(ValueError, "exact resumed"):
                    run_vertical_slice.specialist_lineage_request(
                        capability="image", verification=verification, resume_checkpoint=Path(directory) / "other",
                        parent_manifest=manifest, root_manifest=manifest, execution_slice=execution_slice,
                    )
    def test_specialist_dispatch_does_not_enter_cuda_runner_when_lineage_preflight_fails(self) -> None:
        verification = {"result": "VERIFIED", "capability": "image"}
        with patch.object(run_vertical_slice, "load_verified_specialist_records", return_value=([{"active_expert": "vision", "token_ids": [1]}], verification)):
            with patch.object(run_vertical_slice, "specialist_lineage_request", side_effect=ValueError("parent shard hash mismatch")):
                with patch.object(run_vertical_slice, "run") as cuda_runner:
                    with self.assertRaisesRegex(ValueError, "hash mismatch"):
                        run_vertical_slice.run_specialist(
                            seed=84, artifact_root=Path("B:/ember-artifacts"), data_manifest=Path("data/vision.json"),
                            tokenizer_path=Path("tokenizer.json"), capability="image", resume_checkpoint=Path("B:/parent"),
                            parent_manifest=Path("B:/parent/checkpoint-manifest.json"), root_manifest=Path("B:/root/checkpoint-manifest.json"), checkpoint_interval=8_192, write_budget_bytes=120 * 1024**3,
                        )
        cuda_runner.assert_not_called()
    def test_specialist_forwards_counter_success_receipt_to_cuda_runner(self) -> None:
        verification = {"result": "VERIFIED", "capability": "image"}
        with patch.object(run_vertical_slice, "load_verified_specialist_records", return_value=([{"active_expert": "vision", "token_ids": [1]}], verification)):
            with patch.object(run_vertical_slice, "specialist_lineage_request", side_effect=lambda **kwargs: {"parent_manifest": "parent", "root_manifest": "root", "execution_slice": kwargs["execution_slice"]}):
                with patch.object(run_vertical_slice, "run", return_value={"steps": 1}) as cuda_runner:
                    run_vertical_slice.run_specialist(
                        seed=84,
                        artifact_root=Path("B:/ember-artifacts"),
                        data_manifest=Path("data/vision.json"),
                        tokenizer_path=Path("tokenizer.json"),
                        capability="image",
                        resume_checkpoint=Path("B:/parent"),
                        resume_counter_receipt=Path("B:/parent/parameter-counter-receipt.json"),
                        parent_manifest=Path("B:/parent/checkpoint-manifest.json"),
                        root_manifest=Path("B:/root/checkpoint-manifest.json"),
                        checkpoint_interval=8_192,
                        write_budget_bytes=120 * 1024**3,
                        start_record=0,
                        max_records=1,
                    )
        self.assertEqual(cuda_runner.call_args.kwargs["resume_counter_receipt"], Path("B:/parent/parameter-counter-receipt.json"))
        self.assertEqual(cuda_runner.call_args.kwargs["records_override"], [{"active_expert": "vision", "token_ids": [1]}])
        self.assertIn("execution_slice", cuda_runner.call_args.kwargs["specialist_lineage"])
    def test_specialist_cli_dispatches_one_verified_route(self) -> None:
        with patch.object(run_vertical_slice, "run_specialist", return_value={"steps": 1}) as specialist:
            with patch.object(sys, "argv", ["run_vertical_slice.py", "specialist", "--seed", "84", "--artifact-root", "B:/ember-artifacts", "--data-manifest", "data/vision.json", "--tokenizer", "tokenizer.json", "--capability", "image", "--resume-checkpoint", "B:/parent", "--resume-counter-receipt", "B:/parent/parameter-counter-receipt.json", "--parent-manifest", "B:/parent/checkpoint-manifest.json", "--root-manifest", "B:/root/checkpoint-manifest.json", "--start-record", "7", "--max-records", "20", "--checkpoint-interval", "8192", "--write-budget-gib", "120", "--telemetry-path", "state/ember-telemetry.jsonl", "--telemetry-run-id", "vision-v4", "--model-chat-restore-not-before", "2026-07-18T11:00:00-07:00"]):
                run_vertical_slice.main()
        specialist.assert_called_once_with(seed=84, artifact_root=Path("B:/ember-artifacts"), data_manifest=Path("data/vision.json"), tokenizer_path=Path("tokenizer.json"), capability="image", resume_checkpoint=Path("B:/parent"), resume_counter_receipt=Path("B:/parent/parameter-counter-receipt.json"), resume_realization_registry=None, parent_manifest=Path("B:/parent/checkpoint-manifest.json"), root_manifest=Path("B:/root/checkpoint-manifest.json"), start_record=7, max_records=20, checkpoint_interval=8_192, write_budget_bytes=120 * 1024**3, c_relocated_under_disk_budget_runner=False, relocation_custody_root=None, telemetry_path=Path("state/ember-telemetry.jsonl"), telemetry_run_id="vision-v4", model_chat_restore_not_before="2026-07-18T11:00:00-07:00")
    def test_specialist_cli_forwards_explicit_c_relocation_custody(self) -> None:
        with patch.object(run_vertical_slice, "run_specialist", return_value={"steps": 1}) as specialist:
            with patch.object(sys, "argv", ["run_vertical_slice.py", "specialist", "--seed", "84", "--artifact-root", "C:/tmp/ember-restart-niko-3b/production-artifacts/vision", "--data-manifest", "data/vision.json", "--tokenizer", "tokenizer.json", "--capability", "image", "--resume-checkpoint", "B:/parent", "--resume-counter-receipt", "B:/parent/parameter-counter-receipt.json", "--parent-manifest", "B:/parent/checkpoint-manifest.json", "--root-manifest", "B:/root/checkpoint-manifest.json", "--max-records", "20", "--c-relocated-under-disk-budget-runner", "--relocation-custody-root", "C:/tmp/ember-restart-niko-3b/production-artifacts", "--checkpoint-interval", "8192", "--write-budget-gib", "120", "--telemetry-path", "state/ember-telemetry.jsonl", "--telemetry-run-id", "vision-v4", "--model-chat-restore-not-before", "2026-07-18T11:00:00-07:00"]):
                run_vertical_slice.main()
        self.assertIs(specialist.call_args.kwargs["c_relocated_under_disk_budget_runner"], True)
        self.assertEqual(specialist.call_args.kwargs["artifact_root"], Path("C:/tmp/ember-restart-niko-3b/production-artifacts/vision"))
        self.assertEqual(specialist.call_args.kwargs["relocation_custody_root"], Path("C:/tmp/ember-restart-niko-3b/production-artifacts"))
        self.assertEqual(specialist.call_args.kwargs["checkpoint_interval"], 8_192)
        self.assertEqual(specialist.call_args.kwargs["write_budget_bytes"], 120 * 1024**3)
        self.assertEqual(specialist.call_args.kwargs["resume_counter_receipt"], Path("B:/parent/parameter-counter-receipt.json"))
        self.assertEqual(specialist.call_args.kwargs["start_record"], 0)
        self.assertEqual(specialist.call_args.kwargs["max_records"], 20)

    def test_specialist_cli_accepts_exactly_one_historical_registry(self) -> None:
        with patch.object(run_vertical_slice, "run_specialist", return_value={"steps": 1}) as specialist:
            with patch.object(sys, "argv", ["run_vertical_slice.py", "specialist", "--seed", "84", "--artifact-root", "C:/custody/vision", "--data-manifest", "data/vision.json", "--tokenizer", "tokenizer.json", "--capability", "image", "--resume-checkpoint", "B:/parent", "--resume-realization-registry", "B:/registry/trusted-verifiers.json", "--parent-manifest", "B:/parent/checkpoint-manifest.json", "--root-manifest", "B:/parent/checkpoint-manifest.json", "--max-records", "20", "--c-relocated-under-disk-budget-runner", "--relocation-custody-root", "C:/custody", "--checkpoint-interval", "20", "--write-budget-gib", "24", "--telemetry-path", "C:/custody/telemetry.jsonl", "--telemetry-run-id", "vision-smoke", "--model-chat-restore-not-before", "2026-07-18T01:00:00-07:00"]):
                run_vertical_slice.main()
        self.assertIsNone(specialist.call_args.kwargs["resume_counter_receipt"])
        self.assertEqual(specialist.call_args.kwargs["resume_realization_registry"], Path("B:/registry/trusted-verifiers.json"))

    def test_c_custody_resume_bundle_requires_the_declared_disk_runner_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            custody = Path(directory)
            checkpoint = custody / "checkpoint"
            checkpoint.mkdir()
            manifest = {
                "schema_version": "ember-sparse-checkpoint-v4",
                "model_config_sha256": "a" * 64,
                "architecture_revision": "ember-sparse-3b-v2",
                "active_expert_ids": ["vision"],
                "architecture": {
                    "allocated_parameters": 3_839_161_856,
                    "unique_parameters": 3_839_161_856,
                    "trainable_parameters": 3_839_161_856,
                    "served_parameters": 3_839_161_856,
                    "active_parameters": 1_725_232_640,
                    "episode_trainable_parameters": 1_725_232_640,
                },
            }
            manifest_path = checkpoint / "checkpoint-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            checkpoint.joinpath("parameter-counter-receipt.json").write_text(
                json.dumps({
                    "schema_version": "ember-sparse-realization-receipt-v1",
                    "verification_boundary": "VERIFIED_MEASURED",
                    "result": "MEASURED",
                    "subject_checkpoint_sha256": manifest_sha256,
                    "model_config_sha256": manifest["model_config_sha256"],
                    "architecture_revision": manifest["architecture_revision"],
                    "active_expert_ids": manifest["active_expert_ids"],
                    "counter_sha256": run_vertical_slice._sha256(ROOT / "tools" / "ember-restart-3b" / "parameter_counter.py"),
                    **manifest["architecture"],
                }),
                encoding="utf-8",
            )
            self.assertEqual(
                run_vertical_slice.production_resume_checkpoint(
                    checkpoint,
                    c_relocated_under_disk_budget_runner=True,
                    relocation_custody_root=custody,
                ),
                checkpoint.resolve(),
            )
            with self.assertRaisesRegex(ValueError, "published B: bundle"):
                run_vertical_slice.production_resume_checkpoint(checkpoint)

    def test_published_bundle_without_counter_success_receipt_is_unresumable(self) -> None:
        """A manifest alone is not a durable checkpoint-selection capability."""

        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint"
            checkpoint.mkdir()
            checkpoint.joinpath("checkpoint-manifest.json").write_text(
                json.dumps({
                    "schema_version": "ember-sparse-checkpoint-v4",
                    "model_config_sha256": "a" * 64,
                    "architecture_revision": "ember-sparse-3b-v2",
                    "active_expert_ids": ["vision"],
                    "architecture": {
                        "allocated_parameters": 3_839_161_856,
                        "unique_parameters": 3_839_161_856,
                        "trainable_parameters": 3_839_161_856,
                        "served_parameters": 3_839_161_856,
                        "active_parameters": 1_725_232_640,
                        "episode_trainable_parameters": 1_725_232_640,
                    },
                }),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "counter-success receipt"):
                run_vertical_slice.production_resume_checkpoint(
                    checkpoint,
                    c_relocated_under_disk_budget_runner=True,
                    relocation_custody_root=checkpoint.parent,
                )

    def test_historical_resume_uses_one_exact_registry_instead_of_current_counter(self) -> None:
        """The portable historical counter bundle is an explicit, mutually exclusive path."""

        with tempfile.TemporaryDirectory() as directory:
            custody = Path(directory)
            checkpoint = custody / "checkpoint"
            checkpoint.mkdir()
            manifest_path = checkpoint / "checkpoint-manifest.json"
            manifest_path.write_text("{}", encoding="utf-8")
            registry = custody / "registry" / "trusted-verifiers.json"
            registry.parent.mkdir()
            registry.write_text("{}", encoding="utf-8")
            registry_sha256 = hashlib.sha256(registry.read_bytes()).hexdigest()
            semantic_sha256 = "s" * 64
            with patch.object(run_vertical_slice, "validate_step2_realization_registry_bundle", return_value={"result": "MEASURED", "counter_sha256": "c" * 64, "receipt_sha256": "r" * 64, "historical_model_config_sha256": "h" * 64, "current_model_config_sha256": "n" * 64, "semantic_model_contract_sha256": semantic_sha256}) as validate:
                admitted, authority = run_vertical_slice.authorize_production_resume_checkpoint(
                    checkpoint,
                    realization_registry=registry,
                    c_relocated_under_disk_budget_runner=True,
                    relocation_custody_root=custody,
                )
            self.assertEqual(admitted, checkpoint.resolve())
            self.assertEqual(authority["mode"], "TRUSTED_HISTORICAL_REALIZATION_REGISTRY")
            self.assertEqual(authority["registry_sha256"], registry_sha256)
            self.assertEqual(authority["counter_sha256"], "c" * 64)
            self.assertEqual(authority["receipt_sha256"], "r" * 64)
            self.assertEqual(authority["semantic_model_contract_sha256"], semantic_sha256)
            validate.assert_called_once_with(
                registry.resolve(),
                manifest_path.resolve(),
                ROOT / "configs" / "ember-restart-3b.json",
            )
            with self.assertRaisesRegex(ValueError, "mutually exclusive"):
                run_vertical_slice.production_resume_checkpoint(
                    checkpoint,
                    counter_success_receipt=checkpoint / "parameter-counter-receipt.json",
                    realization_registry=registry,
                    c_relocated_under_disk_budget_runner=True,
                    relocation_custody_root=custody,
                )

    def test_counter_failure_quarantines_new_candidate_and_preserves_prior_bundle(self) -> None:
        """A counter failure cannot leave the just-published bundle selectable."""

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            previous = parent / "checkpoint-known-good"
            previous.mkdir()
            candidate = parent / "checkpoint-candidate"

            def write_candidate() -> dict[str, object]:
                candidate.mkdir()
                candidate.joinpath("checkpoint-manifest.json").write_text("{}", encoding="utf-8")
                return {"published": True}

            with self.assertRaisesRegex(RuntimeError, "counter failed"):
                run_vertical_slice.publish_counter_verified_checkpoint(
                    checkpoint_target=candidate,
                    write_candidate=write_candidate,
                    execute_counter=lambda: (_ for _ in ()).throw(RuntimeError("counter failed")),
                )
            self.assertTrue(previous.is_dir())
            self.assertFalse(candidate.exists())
            evidence = parent / ".checkpoint-quarantine" / "counter-failed-checkpoint-candidate.json"
            self.assertTrue(evidence.is_file())
            self.assertEqual(json.loads(evidence.read_text(encoding="utf-8"))["result"], "COUNTER_FAILED")
            self.assertEqual(list(parent.glob(".counter-failed-checkpoint-candidate-*")), [])

    def test_preexisting_target_is_refused_before_writer_and_bytes_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "checkpoint-existing"
            target.mkdir()
            original = target.joinpath("sentinel"); original.write_bytes(b"known-good")
            called = False

            def writer() -> dict[str, object]:
                nonlocal called
                called = True
                original.write_bytes(b"corrupted")
                return {"published": True}

            with self.assertRaisesRegex(FileExistsError, "already exists"):
                run_vertical_slice.publish_counter_verified_checkpoint(
                    checkpoint_target=target, write_candidate=writer, execute_counter=lambda: {"unexpected": True},
                )
            self.assertFalse(called)
            self.assertEqual(original.read_bytes(), b"known-good")
    def test_partial_writer_failure_deletes_candidate_and_preserves_bounded_evidence(self) -> None:
        """A writer exception cannot strand a partial checkpoint in the resumable namespace."""

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            previous = parent / "checkpoint-known-good"
            previous.mkdir()
            candidate = parent / "checkpoint-partial"

            def partial_writer() -> dict[str, object]:
                candidate.mkdir()
                candidate.joinpath("partial-shard.pt").write_bytes(b"partial")
                raise RuntimeError("writer failed")

            with self.assertRaisesRegex(RuntimeError, "writer failed"):
                run_vertical_slice.publish_counter_verified_checkpoint(
                    checkpoint_target=candidate,
                    write_candidate=partial_writer,
                    execute_counter=lambda: {"unexpected": True},
                )
            self.assertTrue(previous.is_dir())
            self.assertFalse(candidate.exists())
            evidence = parent / ".checkpoint-quarantine" / "counter-failed-checkpoint-partial.json"
            self.assertTrue(evidence.is_file())
            self.assertEqual(json.loads(evidence.read_text(encoding="utf-8"))["result"], "COUNTER_FAILED")
            self.assertEqual(list(parent.glob(".counter-failed-checkpoint-partial-*")), [])
            self.assertFalse(candidate.exists())
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
