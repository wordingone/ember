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
import shutil
import tempfile

import sys
import subprocess
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import torch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

import run_vertical_slice
from build_owned_reasoning_tool_trajectories import build_records
from train import run_launch as live_run_launch
from verify_capability_record import expected_receipt


class RunnerPreflightTests(unittest.TestCase):
    def test_training_acceleration_config_is_closed_and_stage1_disabled(self) -> None:
        policy = run_vertical_slice.load_training_acceleration_policy()
        self.assertFalse(policy.enabled)
        self.assertFalse(policy.fp8_enabled)
        self.assertFalse(policy.cuda_graph_enabled)
        self.assertIsNone(policy.signature_census_sha256)

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

    def test_vision_scene_split_selection_keeps_train_out_of_evaluation(self) -> None:
        records = [
            {"active_expert": "vision", "scene_split": "train", "token_ids": [1], "row_id": "train"},
            {"active_expert": "vision", "scene_split": "validation", "token_ids": [2], "row_id": "validation"},
            {"active_expert": "vision", "scene_split": "test", "token_ids": [3], "row_id": "test"},
        ]
        train, train_receipt = run_vertical_slice.select_verified_scene_split(
            records, capability="image", scene_split="train", full_records_artifact_sha256="a" * 64,
        )
        validation, validation_receipt = run_vertical_slice.select_verified_scene_split(
            records, capability="image", scene_split="validation", full_records_artifact_sha256="a" * 64,
        )
        test, test_receipt = run_vertical_slice.select_verified_scene_split(
            records, capability="image", scene_split="test", full_records_artifact_sha256="a" * 64,
        )
        self.assertEqual([record["row_id"] for record in train], ["train"])
        self.assertEqual([record["row_id"] for record in validation], ["validation"])
        self.assertEqual([record["row_id"] for record in test], ["test"])
        self.assertEqual(train_receipt["scene_split"], "train")
        self.assertNotEqual(train_receipt["selected_records_sha256"], validation_receipt["selected_records_sha256"])
        self.assertNotEqual(validation_receipt["selected_records_sha256"], test_receipt["selected_records_sha256"])
        with self.assertRaisesRegex(ValueError, "declare a scene split"):
            run_vertical_slice.select_verified_scene_split(
                [{"active_expert": "vision", "token_ids": [1]}], capability="image", scene_split="train", full_records_artifact_sha256="a" * 64,
            )
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

    def test_training_telemetry_separates_a_killed_writer_partial_before_terminal_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            channel = Path(directory) / "ember-telemetry.jsonl"
            channel.write_bytes(b'{"ts":"truncated"')

            run_vertical_slice.append_training_telemetry(
                channel,
                kind="run_status",
                payload={
                    "run_id": "vision-v4",
                    "phase": "FAILED",
                    "model_chat": "OFFLINE",
                    "last_completed_step": 7,
                    "failure_class": "TRAINER_ERROR",
                },
            )

            lines = channel.read_bytes().splitlines()
            self.assertEqual(lines[0], b'{"ts":"truncated"')
            terminal = json.loads(lines[1])
            self.assertEqual(terminal["payload"]["phase"], "FAILED")
            self.assertEqual(terminal["payload"]["last_completed_step"], 7)

    def test_e4_receipt_write_failure_emits_one_path_free_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            channel = Path(directory) / "ember-telemetry.jsonl"
            accumulator: dict[str, object] = {"write_failures": 0}

            run_vertical_slice._record_e4_measurement_write_failure(
                accumulator,
                telemetry_path=channel,
                telemetry_run_id="vision-v4",
                error=PermissionError("refused at C:/private/run/e4-measurement-receipt.json"),
            )
            run_vertical_slice._record_e4_measurement_write_failure(
                accumulator,
                telemetry_path=channel,
                telemetry_run_id="vision-v4",
                error=RuntimeError("deterministic writer bug"),
            )

            self.assertEqual(accumulator["write_failures"], 2)
            events = [json.loads(line) for line in channel.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["kind"], "e4_receipt_write_failure")
            self.assertEqual(events[0]["payload"], {
                "error_type": "PermissionError",
                "failure_class": "IO_ERROR",
                "run_id": "vision-v4",
                "write_failures": 1,
            })
            self.assertNotIn("private", json.dumps(events[0]))

            blocked: dict[str, object] = {"write_failures": 0}
            with patch.object(
                run_vertical_slice,
                "append_training_telemetry",
                side_effect=OSError("primary telemetry unavailable"),
            ), self.assertRaisesRegex(OSError, "primary telemetry unavailable"):
                run_vertical_slice._record_e4_measurement_write_failure(
                    blocked,
                    telemetry_path=channel,
                    telemetry_run_id="vision-v5",
                    error=RuntimeError("receipt writer bug"),
                )
            self.assertEqual(blocked["write_failures"], 1)

    def test_specialist_failure_emits_path_free_failed_status_with_last_completed_step(self) -> None:
        records = [
            {"active_expert": "vision", "scene_split": "train", "token_ids": [1], "row_id": "train"},
            {"active_expert": "vision", "scene_split": "validation", "token_ids": [2], "row_id": "validation"},
            {"active_expert": "vision", "scene_split": "test", "token_ids": [3], "row_id": "test"},
        ]
        verification = {
            "result": "VERIFIED",
            "capability": "image",
            "records_artifact_sha256": "a" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            channel = Path(directory) / "ember-telemetry.jsonl"
            channel.write_text(json.dumps({
                "ts": "2026-07-17T05:00:00",
                "kind": "train_step",
                "source": "ember-restart-3b",
                "payload": {"run_id": "vision-v4", "step": 99},
            }) + "\n", encoding="utf-8")

            def fail_after_progress(**_kwargs: object) -> dict[str, object]:
                run_vertical_slice.append_training_telemetry(
                    channel,
                    kind="train_step",
                    payload={"run_id": "vision-v4", "step": 7, "loss": 4.0},
                )
                raise RuntimeError("trainer failed at C:/private/checkpoint")

            with patch.object(
                run_vertical_slice,
                "load_verified_specialist_records",
                return_value=(records, verification, b"{}"),
            ), patch.object(
                run_vertical_slice,
                "specialist_lineage_request",
                side_effect=lambda **kwargs: {
                    "parent_manifest": "parent",
                    "root_manifest": "root",
                    "execution_slice": kwargs["execution_slice"],
                    "scene_split_selection": kwargs["scene_split_selection"],
                },
            ), patch.object(run_vertical_slice, "run", side_effect=fail_after_progress):
                with self.assertRaisesRegex(RuntimeError, "private/checkpoint"):
                    run_vertical_slice.run_specialist(
                        seed=84,
                        artifact_root=Path("B:/ember-artifacts"),
                        data_manifest=Path("data/vision.json"),
                        tokenizer_path=Path("tokenizer.json"),
                        capability="image",
                        resume_checkpoint=Path("B:/parent"),
                        parent_manifest=Path("B:/parent/checkpoint-manifest.json"),
                        root_manifest=Path("B:/root/checkpoint-manifest.json"),
                        checkpoint_interval=8_192,
                        write_budget_bytes=120 * 1024**3,
                        start_record=0,
                        max_records=1,
                        telemetry_path=channel,
                        telemetry_run_id="vision-v4",
                        model_chat_restore_not_before="2026-07-18T11:00:00-07:00",
                    )

            events = [
                json.loads(line)
                for line in channel.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(events[-1]["kind"], "run_status")
            self.assertEqual(events[-1]["payload"], {
                "failure_class": "TRAINER_ERROR",
                "last_completed_step": 7,
                "model_chat": "OFFLINE",
                "phase": "FAILED",
                "restore_not_before": "2026-07-18T11:00:00-07:00",
                "run_id": "vision-v4",
            })
            self.assertNotIn("private", json.dumps(events[-1]))

    def test_post_publication_housekeeping_failure_emits_safe_checkpoint_locator(self) -> None:
        records = [
            {"active_expert": "vision", "scene_split": "train", "token_ids": [1], "row_id": "train"},
            {"active_expert": "vision", "scene_split": "validation", "token_ids": [2], "row_id": "validation"},
            {"active_expert": "vision", "scene_split": "test", "token_ids": [3], "row_id": "test"},
        ]
        verification = {"result": "VERIFIED", "capability": "image", "records_artifact_sha256": "a" * 64}
        with tempfile.TemporaryDirectory() as directory:
            channel = Path(directory) / "ember-telemetry.jsonl"
            error = run_vertical_slice.PublishedHousekeepingError(
                published_checkpoint_id="checkpoint-continue-seed-830001-from-step-204",
                cause=RuntimeError("retention failed at B:/private/custody"),
            )
            with patch.object(run_vertical_slice, "load_verified_specialist_records", return_value=(records, verification, b"{}")), patch.object(
                run_vertical_slice,
                "specialist_lineage_request",
                side_effect=lambda **kwargs: {"parent_manifest": "parent", "root_manifest": "root", "execution_slice": kwargs["execution_slice"], "scene_split_selection": kwargs["scene_split_selection"]},
            ), patch.object(run_vertical_slice, "run", side_effect=error), self.assertRaises(run_vertical_slice.PublishedHousekeepingError):
                run_vertical_slice.run_specialist(
                    seed=84, artifact_root=Path("B:/ember-artifacts"), data_manifest=Path("data/vision.json"),
                    tokenizer_path=Path("tokenizer.json"), capability="image", resume_checkpoint=Path("B:/parent"),
                    parent_manifest=Path("B:/parent/checkpoint-manifest.json"), root_manifest=Path("B:/root/checkpoint-manifest.json"),
                    checkpoint_interval=8192, write_budget_bytes=120 * 1024**3, start_record=0, max_records=1,
                    telemetry_path=channel, telemetry_run_id="vision-v4", model_chat_restore_not_before="2026-07-18T11:00:00-07:00",
                )
            terminal = json.loads(channel.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(terminal["payload"], {
                "failure_class": "PUBLISHED_HOUSEKEEPING_FAILED",
                "last_completed_step": 0,
                "model_chat": "OFFLINE",
                "phase": "PUBLISHED_HOUSEKEEPING_FAILED",
                "published_checkpoint_id": "checkpoint-continue-seed-830001-from-step-204",
                "restore_not_before": "2026-07-18T11:00:00-07:00",
                "run_id": "vision-v4",
            })
            self.assertNotIn("B:/", json.dumps(terminal))

        with self.assertRaisesRegex(ValueError, "locator"):
            run_vertical_slice.PublishedHousekeepingError(
                published_checkpoint_id="B:/private/checkpoint-204", cause=RuntimeError("retention"),
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
                records, receipt, _artifact_bytes = run_vertical_slice.load_verified_specialist_records(
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
            records_out, verification, _artifact_bytes = run_vertical_slice.load_verified_specialist_records(root=ROOT, data_manifest=manifest, tokenizer_path=tokenizer, capability="reasoning")
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
        self.assertEqual(contract["placement"], "cuda_non_paged")
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

    def test_production_optimizer_rejects_declared_placement_drift(self) -> None:
        contract = run_vertical_slice.load_optimizer_contract(ROOT / "configs" / "ember-restart-3b.json")
        contract["placement"] = "host_paged"
        with self.assertRaisesRegex(ValueError, "cuda_non_paged"):
            run_vertical_slice.build_production_optimizer(SimpleNamespace(parameters=lambda: []), optimizer_contract=contract)
    def test_contract_retention_limit_is_used_as_the_runner_limit(self) -> None:
        contract = ROOT / "configs" / "ember-restart-3b.json"
        self.assertTrue(hasattr(run_vertical_slice, "checkpoint_retention_budget_bytes"))
        self.assertEqual(run_vertical_slice.checkpoint_retention_budget_bytes(contract), 24 * 1024**3)
        self.assertEqual(run_vertical_slice.checkpoint_quarantine_budget_bytes(contract), 24 * 1024**3)
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

    def _run_semantic_with_mocks(self, *, resume: bool, telemetry_path: Path | None = None, telemetry_run_id: str | None = None, atomic_json_mock: MagicMock | None = None) -> tuple[dict[str, object], dict[str, object], MagicMock, list[int]]:
        model = SimpleNamespace(active_expert="reasoning")
        model._activate_expert = lambda expert: setattr(model, "active_expert", expert)
        model.expert_bank_genesis_hashes = lambda: {name: name * 64 for name in ("vision", "audio", "reasoning", "tool")}
        optimizer = SimpleNamespace(param_groups=[{"lr": 1e-5}])
        resume_receipt = {"expert_genesis_sha256": {name: (index.to_bytes(1, "little") * 32).hex() for index, name in enumerate(("vision", "audio", "reasoning", "tool"), start=1)}, "checkpoint_manifest_sha256": "a" * 64, "checkpoint": {"byte_sha256": "a" * 64}}
        restore_loader = MagicMock(return_value={"data_cursor": {"shard": "TOKEN-SHARDS-V0:prior", "record_index": 7, "global_step": 31, "tokens_seen": 31 * 1024}})
        call_order: list[str] = []
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
            progress = kwargs.get("progress_callback")
            for step in range(initial + 1, initial + steps + 1):
                if progress is not None:
                    progress({"step": step, "total_steps": initial + steps, "loss": 1.0 / step, "step_ms": 10.0, "tokens_consumed": step * 1024, "grad_norm": 2.0 / step})
                if step % interval == 0 or step == initial + steps:
                    callback(step, {"data_cursor": {"shard": "TOKEN-SHARDS-V0:current", "record_index": step, "global_step": step, "tokens_seen": step * 1024}})
            return {"global_step": initial + steps, "tokens_seen": (initial + steps) * 1024, "data_cursor": {"shard": "TOKEN-SHARDS-V0:current", "record_index": initial + steps, "global_step": initial + steps, "tokens_seen": (initial + steps) * 1024}}

        with ExitStack() as stack:
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "is_available", return_value=True))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "mem_get_info", return_value=(32 * 1024**3, 32 * 1024**3)))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "manual_seed_all"))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "reset_peak_memory_stats"))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "max_memory_allocated", return_value=0))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "max_memory_reserved", return_value=0))
            stack.enter_context(patch.object(run_vertical_slice.torch, "manual_seed"))
            stack.enter_context(patch.object(run_vertical_slice.torch, "get_default_dtype", return_value=torch.float32))
            stack.enter_context(patch.object(run_vertical_slice.torch, "set_default_dtype"))
            stack.enter_context(patch.object(run_vertical_slice, "production_artifact_root", side_effect=lambda path, **_kwargs: path))
            stack.enter_context(patch.object(run_vertical_slice.ManifestBoundTokenStream, "from_receipt", return_value=stream))
            stack.enter_context(patch.object(run_vertical_slice, "UnifiedDecoder", side_effect=lambda *args, **kwargs: (call_order.append("model"), model)[1]))
            stack.enter_context(patch.object(run_vertical_slice, "measure_parameter_counts", return_value=counts))
            stack.enter_context(patch.object(run_vertical_slice, "build_production_optimizer", return_value=optimizer))
            stack.enter_context(patch.object(run_vertical_slice, "_rng_state_hash", return_value={"cpu": "c" * 64, "cuda": "d" * 64}))
            stack.enter_context(patch.object(run_vertical_slice, "_rng_state", return_value={"cpu": torch.tensor([1]), "cuda": torch.tensor([2])}))
            stack.enter_context(patch.object(run_vertical_slice, "run_manifest_bound_semantic_segment", side_effect=segment))
            stack.enter_context(patch.object(run_vertical_slice, "run_text_lab_preflight", return_value={"result": "VERIFIED"}))
            stack.enter_context(patch.object(run_vertical_slice, "governed_resource_preflight", return_value={"free_gb": 32.0}))
            stack.enter_context(patch.object(run_vertical_slice, "_retain_after_success", side_effect=retain))
            stack.enter_context(patch.object(run_vertical_slice, "write_checkpoint_artifacts", writer))
            stack.enter_context(patch.object(run_vertical_slice, "_atomic_json", atomic_json_mock if atomic_json_mock is not None else MagicMock()))
            stack.enter_context(patch.object(run_vertical_slice, "_execute_realization_counter", return_value={"counter": "ok"}))
            stack.enter_context(patch.object(run_vertical_slice, "require_counter_success_receipt", return_value={"verified": True, "counter_sha256": "h" * 64}))
            stack.enter_context(patch.object(run_vertical_slice, "published_checkpoint_receipt", side_effect=lambda _path: (call_order.append("receipt"), resume_receipt)[1]))
            stack.enter_context(patch.object(run_vertical_slice, "load_checkpoint_artifacts", restore_loader))
            stack.enter_context(patch.object(Path, "is_dir", autospec=True, side_effect=lambda path: path.drive.upper() == "B:" or os.path.isdir(str(path))))
            stack.enter_context(patch.object(Path, "read_text", autospec=True, side_effect=read_text))
            stack.enter_context(patch.object(run_vertical_slice, "_sha256", return_value="a" * 64))
            result = run_vertical_slice.run_semantic(
                seed=83, artifact_root=Path("B:/semantic-artifacts"), receipt_path=Path("receipt.json"),
                shards_root=Path("shards"), tokenizer_path=Path("tokenizer.json"),
                expected_receipt_sha256="r" * 64, expected_tokenizer_sha256="t" * 64,
                expected_architecture_sha256="a" * 64,
                steps=2,
                sequence_length=1024, checkpoint_interval=32, write_budget_bytes=24 * 1024**3,
                resume_checkpoint=parent if resume else None,
                telemetry_path=telemetry_path, telemetry_run_id=telemetry_run_id,
            )
        self._semantic_restore_loader = restore_loader
        self._semantic_resume_receipt = resume_receipt
        self._semantic_call_order = call_order
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
        self.assertEqual(writer.call_args.kwargs["max_transient_scratch_bytes"], 4 * 1024**3)
        self.assertEqual(writer.call_args.kwargs["host_commit_reserve_bytes"], 8 * 1024**3)
        self.assertEqual(writer.call_args.kwargs["data_cursor"]["governor"], {"free_gb": 32.0})
        self.assertEqual(result["governor"], {"free_gb": 32.0})

    def test_semantic_run_resume_uses_parent_step_and_final_publication(self) -> None:
        result, segment_kwargs, writer, _retention_bounds = self._run_semantic_with_mocks(resume=True)
        bound = run_vertical_slice.checkpoint_serialization_byte_bound(ROOT / "configs" / "ember-restart-3b.json", active_parameters=1_020_589_568)
        self.assertEqual(segment_kwargs["initial_global_step"], 31)
        self.assertEqual(segment_kwargs["initial_tokens_seen"], 31 * 1024)
        self.assertEqual(result["publication_plan"], {"publication_count": 2, "checkpoint_byte_bound": bound, "projected_write_bytes": 2 * bound})
        self.assertEqual(writer.call_count, 2)
        self.assertTrue(all(call.kwargs["max_serialized_bytes"] == bound for call in writer.call_args_list))
        self.assertTrue(all(call.kwargs["max_transient_scratch_bytes"] == 4 * 1024**3 for call in writer.call_args_list))
        self.assertTrue(all(call.kwargs["host_commit_reserve_bytes"] == 8 * 1024**3 for call in writer.call_args_list))
        receipt = self._semantic_restore_loader.call_args.args[3]
        self.assertIs(receipt, self._semantic_resume_receipt)
        self.assertEqual(receipt["checkpoint"], {"byte_sha256": "a" * 64})
        self.assertLess(self._semantic_call_order.index("receipt"), self._semantic_call_order.index("model"))

    def test_semantic_run_forwards_per_step_telemetry_when_telemetry_path_is_set(self) -> None:
        """Issue #1719 blocker 1: semantic is the only >=100-contiguous-step-capable CLI
        mode, but run_semantic accepted no telemetry_path/telemetry_run_id at all, so
        R1-E1/R1-E2 per-step loss/grad-norm telemetry was architecturally unreachable from
        the only path that can actually run 100 contiguous steps.
        """
        with tempfile.TemporaryDirectory() as directory:
            telemetry_path = Path(directory) / "telemetry" / "telemetry.jsonl"
            self._run_semantic_with_mocks(resume=False, telemetry_path=telemetry_path, telemetry_run_id="semantic-run-1719")
            events = [json.loads(line) for line in telemetry_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        train_steps = [event for event in events if event["kind"] == "train_step"]
        self.assertEqual([event["payload"]["step"] for event in train_steps], [1, 2])
        self.assertTrue(all(event["payload"]["run_id"] == "semantic-run-1719" for event in train_steps))
        self.assertTrue(all(isinstance(event["payload"]["loss"], float) for event in train_steps))
        self.assertTrue(all(isinstance(event["payload"]["grad_norm"], float) and event["payload"]["grad_norm"] > 0.0 for event in train_steps))

    def test_semantic_run_writes_e4_measurement_receipt_when_telemetry_path_is_set(self) -> None:
        """Issue #1464 (R1-E4 cascade review, 2026-08-21): run_semantic's progress_callback
        appended train_step telemetry but never touched the e4 accumulator/writer that run()
        already carried, so a fully certified semantic warm-100 run -- the only CLI route that
        can complete >=100 contiguous steps -- produced zero e4-measurement-receipt.json and
        check_r1_e4 returned EVIDENCE_MISSING after the compute was spent. The receipt must now
        exist, upsert every step, and reflect this run's own accumulated counters.
        """
        atomic_json = MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            telemetry_path = Path(directory) / "telemetry" / "telemetry.jsonl"
            self._run_semantic_with_mocks(
                resume=False, telemetry_path=telemetry_path, telemetry_run_id="semantic-run-1464",
                atomic_json_mock=atomic_json,
            )
            receipt_calls = [
                call for call in atomic_json.call_args_list
                if call.args[0] == Path(directory) / "e4-measurement-receipt.json"
            ]
            self.assertEqual(len(receipt_calls), 2, "one running upsert per training step")
            for _path, payload in (call.args for call in receipt_calls):
                self.assertEqual(payload["schema_version"], "ember02-r1-e4-measurement/v1")
                self.assertEqual(payload["run_id"], "semantic-run-1464")
                self.assertEqual(payload["write_failures"], 0)
            last_payload = receipt_calls[-1].args[1]
            self.assertEqual(last_payload["steps"], 2)
            self.assertEqual(last_payload["tokens_missing_steps"], 0)
            self.assertEqual(last_payload["tokens_total"], 1024 + 2048)
            self.assertIsInstance(last_payload["tokens_per_second"], float)
            self.assertIsNotNone(last_payload["mfu"]["value"])
            self.assertEqual(last_payload["peak_vram"], {"allocated_bytes": 0, "reserved_bytes": 0})

    def test_semantic_run_omits_e4_measurement_receipt_without_telemetry_path(self) -> None:
        """The e4 recorder is constructed unconditionally (issue #1464 wiring), but its
        progress_callback guard -- unchanged by the wiring -- must still keep a telemetry-less
        semantic run from writing any receipt, matching run()'s existing None-telemetry
        behavior."""
        atomic_json = MagicMock()
        self._run_semantic_with_mocks(resume=False, atomic_json_mock=atomic_json)
        receipt_calls = [call for call in atomic_json.call_args_list if call.args[0].name == "e4-measurement-receipt.json"]
        self.assertEqual(receipt_calls, [])

    def test_disk_reopen_resume_receipt_binds_exact_frozen_manifest_bytes(self) -> None:
        """A disk-reopened resume receipt carries the manifest's out-of-band identity."""

        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint"
            checkpoint.mkdir()
            manifest_path = checkpoint / "checkpoint-manifest.json"
            manifest_bytes = b'{"schema_version":"ember-sparse-checkpoint-v4","step":17}\n'
            manifest_path.write_bytes(manifest_bytes)

            receipt = run_vertical_slice.published_checkpoint_receipt(checkpoint)

        self.assertEqual(receipt["checkpoint_manifest_sha256"], hashlib.sha256(manifest_bytes).hexdigest())
        self.assertEqual(receipt["checkpoint"], {"byte_sha256": hashlib.sha256(manifest_bytes).hexdigest()})

    def test_semantic_runner_refuses_cuda_before_governor_admission(self) -> None:
        with patch.object(run_vertical_slice, "run_text_lab_preflight", return_value={"result": "VERIFIED"}):
            with patch.object(run_vertical_slice, "governed_resource_preflight", return_value={"free_gb": 32.0}) as governor:
                with patch.object(run_vertical_slice.torch.cuda, "is_available", side_effect=RuntimeError("CUDA probe")) as cuda_probe:
                    with self.assertRaisesRegex(RuntimeError, "CUDA probe"):
                        run_vertical_slice.run_semantic(
                            seed=83, artifact_root=Path("B:/semantic-artifacts"), receipt_path=Path("receipt.json"),
                            shards_root=Path("shards"), tokenizer_path=Path("tokenizer.json"),
                            expected_receipt_sha256="r" * 64, expected_tokenizer_sha256="t" * 64,
                            expected_architecture_sha256="a" * 64, steps=1,
                            sequence_length=1024, checkpoint_interval=1, write_budget_bytes=8 * 1024**3,
                        )
        governor.assert_called_once_with()
        cuda_probe.assert_called_once_with()

    def test_semantic_runner_rejects_invalid_pure_arguments_before_governor(self) -> None:
        with patch.object(run_vertical_slice, "run_text_lab_preflight", return_value={"result": "VERIFIED"}):
            with patch.object(run_vertical_slice, "governed_resource_preflight", side_effect=AssertionError("governor")) as governor:
                with patch.object(run_vertical_slice.torch.cuda, "is_available", side_effect=AssertionError("CUDA probe")) as cuda_probe:
                    with self.assertRaisesRegex(ValueError, "semantic launch requires"):
                        run_vertical_slice.run_semantic(
                            seed=83, artifact_root=Path("B:/semantic-artifacts"), receipt_path=Path("receipt.json"),
                            shards_root=Path("shards"), tokenizer_path=Path("tokenizer.json"),
                            expected_receipt_sha256="r" * 64, expected_tokenizer_sha256="t" * 64,
                            expected_architecture_sha256="a" * 64, steps=0,
                            sequence_length=1024, checkpoint_interval=1, write_budget_bytes=8 * 1024**3,
                        )
        governor.assert_not_called()
        cuda_probe.assert_not_called()

    def test_governed_resource_preflight_loads_the_repository_governor(self) -> None:
        with patch.object(run_vertical_slice.torch.cuda, "set_per_process_memory_fraction") as fraction:
            with patch.object(run_vertical_slice.torch.cuda, "mem_get_info", return_value=(8 * 10**9, 24 * 10**9)) as memory:
                receipt = run_vertical_slice.governed_resource_preflight()
        fraction.assert_called_once()
        memory.assert_called_once_with(device=None)
        self.assertEqual(receipt["free_gb"], 8.0)
        self.assertEqual(receipt["total_gb"], 24.0)
        self.assertIn("vram_fraction", receipt)
        self.assertIn("margin_gb", receipt)
        self.assertEqual(
            receipt["governor_source_sha256"],
            hashlib.sha256(
                (ROOT / "src" / "ember" / "governance" / "scripts" / "governor.py").read_bytes()
            ).hexdigest(),
        )
        self.assertRegex(receipt["governor_source_sha256"], r"^[0-9a-f]{64}$")

    def test_semantic_runner_resource_refusal_prevents_cuda_probe(self) -> None:
        with patch.object(run_vertical_slice, "run_text_lab_preflight", return_value={"result": "VERIFIED"}):
            with patch.object(run_vertical_slice, "governed_resource_preflight", side_effect=RuntimeError("resource refusal")) as governor:
                with patch.object(run_vertical_slice.torch.cuda, "is_available", side_effect=AssertionError("CUDA probe")) as cuda_probe:
                    with self.assertRaisesRegex(RuntimeError, "resource refusal"):
                        run_vertical_slice.run_semantic(
                            seed=83, artifact_root=Path("B:/semantic-artifacts"), receipt_path=Path("receipt.json"),
                            shards_root=Path("shards"), tokenizer_path=Path("tokenizer.json"),
                            expected_receipt_sha256="r" * 64, expected_tokenizer_sha256="t" * 64,
                            expected_architecture_sha256="a" * 64, steps=1,
                            sequence_length=1024, checkpoint_interval=1, write_budget_bytes=8 * 1024**3,
                        )
        governor.assert_called_once_with()
        cuda_probe.assert_not_called()

    def test_vertical_run_rejects_forged_canonical_runner_authority_before_governor(self) -> None:
        with patch.object(run_vertical_slice, "canonical_disk_budget_runner_authority", return_value={"live": "authority"}):
            with patch.object(run_vertical_slice, "governed_resource_preflight", side_effect=AssertionError("governor")) as governor:
                with patch.object(run_vertical_slice.torch.cuda, "is_available", side_effect=AssertionError("CUDA probe")) as cuda_probe:
                    with self.assertRaisesRegex(RuntimeError, "canonical runner authority"):
                        run_vertical_slice.run(
                            seed=83, artifact_root=Path("B:/vertical-artifacts"),
                            canonical_runner_authority={"forged": "authority"},
                        )
        governor.assert_not_called()
        cuda_probe.assert_not_called()

    def test_vertical_runner_resource_refusal_prevents_cuda_probe(self) -> None:
        with patch.object(run_vertical_slice, "governed_resource_preflight", side_effect=RuntimeError("resource refusal")) as governor:
            with patch.object(run_vertical_slice.torch.cuda, "is_available", side_effect=AssertionError("CUDA probe")) as cuda_probe:
                with self.assertRaisesRegex(RuntimeError, "resource refusal"):
                    run_vertical_slice.run(
                        seed=83,
                        artifact_root=Path("B:/vertical-artifacts"),
                    )
        governor.assert_called_once_with()
        cuda_probe.assert_not_called()

    def test_vertical_runner_rejects_missing_integration_contract_before_governor(self) -> None:
        with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
            module_path = Path(directory) / "tools" / "ember-restart-3b" / "run_vertical_slice.py"
            module_path.parent.mkdir(parents=True)
            module_path.write_text("# synthetic module location\n", encoding="utf-8")
            with patch.object(run_vertical_slice, "__file__", str(module_path)):
                with patch.object(run_vertical_slice, "governed_resource_preflight", side_effect=AssertionError("governor")) as governor:
                    with patch.object(run_vertical_slice.torch.cuda, "is_available", side_effect=AssertionError("CUDA probe")) as cuda_probe:
                        with self.assertRaisesRegex(RuntimeError, "merged Ember integration contract"):
                            run_vertical_slice.run(seed=83, artifact_root=Path("B:/vertical-artifacts"))
            governor.assert_not_called()
            cuda_probe.assert_not_called()

    def test_semantic_runner_rejects_missing_integration_contract_before_governor(self) -> None:
        with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
            module_path = Path(directory) / "tools" / "ember-restart-3b" / "run_vertical_slice.py"
            module_path.parent.mkdir(parents=True)
            module_path.write_text("# synthetic module location\n", encoding="utf-8")
            with patch.object(run_vertical_slice, "__file__", str(module_path)):
                with patch.object(run_vertical_slice, "run_text_lab_preflight", return_value={"result": "VERIFIED"}):
                    with patch.object(run_vertical_slice, "governed_resource_preflight", side_effect=AssertionError("governor")) as governor:
                        with patch.object(run_vertical_slice.torch.cuda, "is_available", side_effect=AssertionError("CUDA probe")) as cuda_probe:
                            with self.assertRaisesRegex(RuntimeError, "merged Ember integration contract"):
                                run_vertical_slice.run_semantic(seed=83, artifact_root=Path("B:/semantic-artifacts"), receipt_path=Path("receipt.json"), shards_root=Path("shards"), tokenizer_path=Path("tokenizer.json"), expected_receipt_sha256="r" * 64, expected_tokenizer_sha256="t" * 64, expected_architecture_sha256="a" * 64, steps=1, sequence_length=8, checkpoint_interval=1, write_budget_bytes=1)
            governor.assert_not_called()
            cuda_probe.assert_not_called()

    def _run_vertical_resume_with_mocks(
        self, *, specialist: bool, callback_steps: tuple[int, ...] = (),
        restored_receipts: list[dict[str, object]] | None = None,
        call_order: list[str] | None = None,
        ordinary_rows: list[dict[str, object]] | None = None,
        parent_data_cursor: dict[str, object] | None = None,
        max_records: int | None = None,
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
        real_read_bytes = Path.read_bytes
        genesis = {name: (index.to_bytes(1, "little") * 32).hex() for index, name in enumerate(("vision", "audio", "reasoning", "tool"), start=1)}
        ordinary_rows = ordinary_rows if ordinary_rows is not None else [{"active_expert": "shared", "row_id": index} for index in range(38)]
        parent_data_cursor = parent_data_cursor if parent_data_cursor is not None else {"shard": "TOKEN-SHARDS-V0:prior", "record_index": 37, "global_step": 19, "tokens_seen": 19_456}
        parent_data_cursor.setdefault("input_identity_receipt_sha256", run_vertical_slice._json_sha256({"receipt": "bound"}))
        specialist_rows = [{"active_expert": "vision", "scene_split": "train", "token_ids": [index + 1]} for index in range(len(callback_steps or (20,))) ]
        specialist_artifact_bytes = json.dumps({"records": specialist_rows}, sort_keys=True, separators=(",", ":")).encode("utf-8")
        specialist_artifact_sha256 = hashlib.sha256(specialist_artifact_bytes).hexdigest()
        _specialist_selected, specialist_selection = run_vertical_slice.select_verified_scene_split(
            specialist_rows, capability="image", scene_split="train", full_records_artifact_sha256=specialist_artifact_sha256,
        )
        _specialist_slice_rows, specialist_execution_slice = run_vertical_slice.bind_specialist_execution_slice(
            specialist_rows, start_record=0, max_records=len(specialist_rows), scene_split_record_count=len(specialist_rows),
        )

        def read_text(path: Path, *args: object, **kwargs: object) -> str:
            if path.resolve() == parent_manifest.resolve():
                return json.dumps({"expert_genesis_sha256": genesis})
            return real_read_text(path, *args, **kwargs)

        def read_bytes(path: Path, *args: object, **kwargs: object) -> bytes:
            if path.resolve() == parent_manifest.resolve():
                return json.dumps({"expert_genesis_sha256": genesis}).encode("utf-8")
            return real_read_bytes(path, *args, **kwargs)
        def sha256(path: Path) -> str:
            if path.resolve() == parent_manifest.resolve():
                return hashlib.sha256(read_bytes(parent_manifest)).hexdigest()
            return "h" * 64


        def segment(**kwargs: object) -> dict[str, object]:
            segment_kwargs.update(kwargs)
            published_steps = callback_steps or (20,)
            initial_record_index = int(kwargs["initial_data_cursor"])
            result = {"losses": [0.1], "data_cursor": {"shard": str(kwargs["data_shard_id"]), "record_index": initial_record_index + len(published_steps), "global_step": published_steps[-1], "tokens_seen": 20_480}}
            for record_index, step in enumerate(published_steps, start=initial_record_index + 1):
                callback_result = {
                    **result,
                    "data_cursor": {**result["data_cursor"], "record_index": record_index, "global_step": step},
                }
                kwargs["checkpoint_callback"](step, callback_result)
            return result

        with ExitStack() as stack:
            stack.enter_context(patch("checkpoint_artifacts._is_link_or_reparse", return_value=False))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "is_available", return_value=True))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "mem_get_info", return_value=(32 * 1024**3, 32 * 1024**3)))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "manual_seed_all"))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "reset_peak_memory_stats"))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "max_memory_allocated", return_value=0))
            stack.enter_context(patch.object(run_vertical_slice.torch, "manual_seed"))
            stack.enter_context(patch.object(run_vertical_slice.torch, "get_default_dtype", return_value=torch.float32))
            stack.enter_context(patch.object(run_vertical_slice.torch, "set_default_dtype"))
            stack.enter_context(patch.object(run_vertical_slice, "production_artifact_root", side_effect=lambda path, **_kwargs: path))
            def build_model(*_args: object, **_kwargs: object) -> object:
                if call_order is not None:
                    call_order.append("model")
                return model
            stack.enter_context(patch.object(run_vertical_slice, "UnifiedDecoder", side_effect=build_model))
            # #1483: the byte-bound coverage decision measures the live optimizer;
            # this fixture's model/optimizer are fakes with no routes to measure, so
            # pin single-route coverage and keep the pre-#1483 bound these tests pin.
            stack.enter_context(patch.object(run_vertical_slice, "optimizer_covers_every_expert_route", return_value=False))
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
            def published_receipt(_checkpoint: Path) -> dict[str, object]:
                if call_order is not None:
                    call_order.append("receipt")
                manifest_sha256 = hashlib.sha256(read_bytes(parent_manifest)).hexdigest()
                return {
                    "checkpoint_manifest_sha256": manifest_sha256,
                    "checkpoint": {"byte_sha256": manifest_sha256},
                    "expert_genesis_sha256": genesis,
                    "data_cursor": dict(parent_data_cursor),
                }
            stack.enter_context(patch.object(run_vertical_slice, "published_checkpoint_receipt", side_effect=published_receipt))
            stack.enter_context(patch.object(run_vertical_slice, "_rng_state_hash", return_value={"cpu": "c" * 64, "cuda": "d" * 64}))
            stack.enter_context(patch.object(run_vertical_slice, "_rng_state", return_value={"cpu": torch.tensor([1]), "cuda": torch.tensor([2])}))
            stack.enter_context(patch.object(run_vertical_slice, "run_pretraining_segment", side_effect=segment))
            stack.enter_context(patch.object(run_vertical_slice, "_retain_after_success", side_effect=lambda _parent, *, operation, **_kwargs: operation()))
            stack.enter_context(patch.object(run_vertical_slice, "write_checkpoint_artifacts", writer))
            stack.enter_context(patch.object(run_vertical_slice, "_atomic_json"))
            stack.enter_context(patch.object(run_vertical_slice, "_execute_realization_counter", return_value={"counter": "ok"}))
            stack.enter_context(patch.object(run_vertical_slice, "require_counter_success_receipt", return_value={"verified": True, "counter_sha256": "h" * 64}))
            def load_checkpoint(_model: object, _optimizer: object, _root: Path, receipt: dict[str, object]) -> dict[str, object]:
                if restored_receipts is not None:
                    restored_receipts.append(dict(receipt))
                return {"data_cursor": dict(parent_data_cursor)}

            stack.enter_context(patch.object(run_vertical_slice, "load_checkpoint_artifacts", side_effect=load_checkpoint))
            stack.enter_context(patch.object(run_vertical_slice, "load_authorized_records", return_value=(ordinary_rows, {"input_identity": {"shard_path": "TOKEN-SHARDS-V0:prior"}}, {"receipt": "bound"})))
            stack.enter_context(patch.object(Path, "is_dir", autospec=True, side_effect=lambda path: path.drive.upper() == "B:"))
            stack.enter_context(patch.object(Path, "read_text", autospec=True, side_effect=read_text))
            stack.enter_context(patch.object(Path, "read_bytes", autospec=True, side_effect=read_bytes))
            stack.enter_context(patch.object(run_vertical_slice, "_sha256", side_effect=sha256))
            result = run_vertical_slice.run(
                seed=84, artifact_root=Path("B:/vertical-artifacts"), resume_checkpoint=parent,
                records_override=specialist_rows if specialist else None,
                scene_split_records=specialist_rows if specialist else None,
                full_records_artifact_bytes=specialist_artifact_bytes if specialist else None,
                specialist_verification={"capability": "image", "data_manifest_sha256": "a" * 64, "records_artifact_sha256": specialist_artifact_sha256} if specialist else None,
                specialist_lineage={"parent_manifest": str(parent_manifest), "root_manifest": str(parent_manifest), "execution_slice": specialist_execution_slice, "scene_split_selection": specialist_selection} if specialist else None,
                checkpoint_interval=8_192 if specialist else None,
                write_budget_bytes=100 * 1024**3 if specialist else None,
                max_records=max_records,
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
        full_rows = [{"active_expert": "shared", "row_id": index} for index in range(38)]
        _ordinary_result, ordinary_kwargs, ordinary_writer = self._run_vertical_resume_with_mocks(
            specialist=False, ordinary_rows=full_rows,
        )
        _specialist_result, specialist_kwargs, specialist_writer = self._run_vertical_resume_with_mocks(specialist=True)
        specialist_bound = run_vertical_slice.checkpoint_serialization_byte_bound(ROOT / "configs" / "ember-restart-3b.json", active_parameters=1_725_232_640)
        # Non-specialist episodes realize every expert, so their checkpoint
        # bound must admit full-coverage optimizer state (#1320); specialist
        # lineage episodes keep the tighter shared-plus-one-expert bound.
        full_coverage_bound = run_vertical_slice.checkpoint_serialization_byte_bound(ROOT / "configs" / "ember-restart-3b.json", active_parameters=3_839_161_856)
        self.assertEqual(ordinary_kwargs["initial_data_cursor"], 37)
        self.assertEqual(ordinary_kwargs["initial_global_step"], 19)
        self.assertEqual(specialist_kwargs["initial_data_cursor"], 0)
        self.assertEqual(specialist_kwargs["initial_global_step"], 19)
        self.assertTrue(str(specialist_kwargs["data_shard_id"]).startswith("VERIFIED_SPECIALIST:"))
        self.assertEqual(ordinary_writer.call_args.kwargs["max_serialized_bytes"], full_coverage_bound)
        self.assertEqual(specialist_writer.call_args.kwargs["max_serialized_bytes"], specialist_bound)
        self.assertEqual(ordinary_writer.call_args.kwargs["max_transient_scratch_bytes"], 4 * 1024**3)
        self.assertEqual(specialist_writer.call_args.kwargs["max_transient_scratch_bytes"], 4 * 1024**3)
    def test_vertical_resume_passes_frozen_manifest_identity_to_checkpoint_loader(self) -> None:
        """The full runner resume handoff retains the disk manifest's identity receipt."""

        receipts: list[dict[str, object]] = []
        _result, _segment_kwargs, writer = self._run_vertical_resume_with_mocks(specialist=False, restored_receipts=receipts)
        manifest_bytes = json.dumps({"expert_genesis_sha256": {
            name: (index.to_bytes(1, "little") * 32).hex()
            for index, name in enumerate(("vision", "audio", "reasoning", "tool"), start=1)
        }}).encode("utf-8")
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["checkpoint_manifest_sha256"], hashlib.sha256(manifest_bytes).hexdigest())
        self.assertIn("governor", writer.call_args.kwargs["data_cursor"])
        self.assertEqual(receipts[0]["checkpoint"], {"byte_sha256": hashlib.sha256(manifest_bytes).hexdigest()})

    def test_vertical_resume_freezes_manifest_receipt_before_cuda_allocation(self) -> None:
        call_order: list[str] = []
        self._run_vertical_resume_with_mocks(specialist=False, call_order=call_order)
        self.assertLess(call_order.index("receipt"), call_order.index("model"))

    def test_vertical_canary_resume_uses_bounded_cursor_for_checkpoint_target(self) -> None:
        rows = [{"active_expert": "shared", "row_id": index} for index in range(4)]
        parent_cursor = {"shard": "TOKEN-SHARDS-V0:prior", "record_index": 3, "global_step": 3, "tokens_seen": 3_072}
        _result, kwargs, writer = self._run_vertical_resume_with_mocks(
            specialist=False, callback_steps=(4,), ordinary_rows=rows,
            parent_data_cursor=parent_cursor, max_records=1,
        )
        self.assertEqual(kwargs["initial_data_cursor"], 3)
        self.assertEqual(kwargs["max_records"], 1)
        self.assertEqual(Path(writer.call_args.args[2]).name, "checkpoint-continue-seed-84-from-step-4")

    def test_vertical_resume_rejects_exhausted_frozen_cursor_before_model_construction(self) -> None:
        rows = [{"active_expert": "shared", "row_id": index} for index in range(4)]
        for exhausted_index in (4, 5):
            call_order: list[str] = []
            with self.assertRaisesRegex(RuntimeError, "no remaining authorized records"):
                self._run_vertical_resume_with_mocks(
                    specialist=False, ordinary_rows=rows,
                    parent_data_cursor={"shard": "TOKEN-SHARDS-V0:prior", "record_index": exhausted_index, "global_step": 3, "tokens_seen": 3_072},
                    max_records=1, call_order=call_order,
                )
            self.assertNotIn("model", call_order)

    def test_vertical_resume_rejects_frozen_cursor_from_another_admitted_input_before_model(self) -> None:
        rows = [{"active_expert": "shared", "row_id": index} for index in range(4)]
        valid_hash = run_vertical_slice._json_sha256({"receipt": "bound"})
        for field, value, message in (
            ("shard", "TOKEN-SHARDS-V0:other", "input shard"),
            ("input_identity_receipt_sha256", "a" * 64, "input receipt"),
        ):
            cursor = {"shard": "TOKEN-SHARDS-V0:prior", "record_index": 3, "global_step": 3, "tokens_seen": 3_072, "input_identity_receipt_sha256": valid_hash}
            cursor[field] = value
            call_order: list[str] = []
            with self.assertRaisesRegex(RuntimeError, message):
                self._run_vertical_resume_with_mocks(
                    specialist=False, ordinary_rows=rows, parent_data_cursor=cursor,
                    max_records=1, call_order=call_order,
                )
            self.assertNotIn("model", call_order)

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
                    "--tokenizer", "semantic/tokenizer.json",
                    "--expected-receipt-sha256", "r" * 64, "--expected-tokenizer-sha256", "t" * 64,
                    "--expected-architecture-sha256", "a" * 64,
                    "--steps", "1", "--sequence-length", "1024", "--checkpoint-interval", "32", "--write-budget-gib", "24",
                ],
            ):
                run_vertical_slice.main()
        semantic.assert_called_once_with(
            seed=83,
            artifact_root=Path("B:/ember-artifacts"),
            receipt_path=Path("semantic/receipt.json"),
            shards_root=Path("semantic/shards"),
            tokenizer_path=Path("semantic/tokenizer.json"),
            expected_receipt_sha256="r" * 64,
            expected_tokenizer_sha256="t" * 64,
            expected_architecture_sha256="a" * 64,
            admitted_row_set_sha256=None,
            receipt_custody_root=None,
            steps=1,
            sequence_length=1024,
            checkpoint_interval=32,
            write_budget_bytes=24 * 1024**3,
            resume_checkpoint=None,
            resume_counter_receipt=None,
            resume_realization_registry=None,
            resume_optimizer_transition_registry=None,
            resume_optimizer_transition_registry_sha256=None,
            telemetry_path=None,
            telemetry_run_id=None,
        )

    def test_semantic_cli_forwards_telemetry_flags_when_supplied(self) -> None:
        """Issue #1719 blocker 1: the semantic subparser had zero telemetry wiring --
        --telemetry-path/--telemetry-run-id must reach run_semantic when the operator
        supplies them, the same way the specialist subparser already forwards its
        (required) telemetry flags.
        """
        with patch.object(run_vertical_slice, "run_semantic", return_value={"steps": 1}) as semantic:
            with patch.object(
                sys,
                "argv",
                [
                    "run_vertical_slice.py", "semantic", "--seed", "83", "--artifact-root", "B:/ember-artifacts",
                    "--receipt", "semantic/receipt.json", "--shards-root", "semantic/shards",
                    "--tokenizer", "semantic/tokenizer.json",
                    "--expected-receipt-sha256", "r" * 64, "--expected-tokenizer-sha256", "t" * 64,
                    "--expected-architecture-sha256", "a" * 64,
                    "--steps", "1", "--sequence-length", "1024", "--checkpoint-interval", "32", "--write-budget-gib", "24",
                    "--telemetry-path", "semantic/telemetry.jsonl", "--telemetry-run-id", "semantic-run-1719",
                ],
            ):
                run_vertical_slice.main()
        self.assertEqual(semantic.call_args.kwargs["telemetry_path"], Path("semantic/telemetry.jsonl"))
        self.assertEqual(semantic.call_args.kwargs["telemetry_run_id"], "semantic-run-1719")

    def test_vertical_cli_refuses_direct_launch_without_disk_budget_runner(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(
                sys,
                "argv",
                [
                    "run_vertical_slice.py", "vertical", "--seed", "83",
                    "--artifact-root", "B:/ember-artifacts",
                ],
            ):
                with patch.object(run_vertical_slice, "run", return_value={}) as vertical_run:
                    with self.assertRaisesRegex(RuntimeError, "disk budget runner"):
                        run_vertical_slice.main()
        vertical_run.assert_not_called()

    def test_governed_vertical_cli_validates_canonical_startup_assertion_and_budget_before_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            custody = Path(directory) / "custody"
            artifact_root = custody / "artifacts"
            artifact_root.mkdir(parents=True)
            cache = custody / "tmp"
            cache.mkdir(parents=True)
            bindings = {
                "TEMP": str(cache.resolve()), "TMP": str(cache.resolve()),
                "TORCH_HOME": str((custody / "torch").resolve()),
                "TRITON_CACHE_DIR": str((custody / "triton").resolve()),
                "CUDA_CACHE_PATH": str((custody / "cuda").resolve()),
                "HF_HOME": str((custody / "hf").resolve()),
                "XDG_CACHE_HOME": str((custody / "xdg-cache").resolve()),
            }
            for value in set(bindings.values()):
                Path(value).mkdir(parents=True, exist_ok=True)
            nonce = "a" * 32
            assertion = custody / "child-env-startup.json"
            assertion_bytes = json.dumps(
                {"schema_version": 1, "nonce": nonce, "bindings": bindings},
                sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
            assertion.write_bytes(assertion_bytes)
            environment = {
                **bindings, "EMBER_DISK_BUDGET_ENV_ASSERTION": str(assertion),
                "EMBER_DISK_BUDGET_ENV_NONCE": nonce,
            }
            census_output = artifact_root / "signature-census.json"
            with patch.dict(os.environ, environment, clear=True):
                with patch.object(sys, "argv", [
                    "run_vertical_slice.py", "governed-vertical", "--seed", "83",
                    "--artifact-root", str(artifact_root), "--write-budget-bytes", "4096", "--max-records", "3",
                    "--signature-census-output", str(census_output),
                    "--signature-census-source-commit", "1" * 40,
                ]):
                    with patch.object(run_vertical_slice, "checkpoint_serialization_byte_bound", return_value=4096):
                        with patch.object(run_vertical_slice, "run", return_value={"steps": 1}) as vertical_run:
                            run_vertical_slice.main()
            assertion_authority = {
                "schema_version": "ember-canonical-disk-budget-startup-v1",
                "assertion_sha256": hashlib.sha256(assertion_bytes).hexdigest(),
                "cache_bindings_sha256": hashlib.sha256(
                    json.dumps(bindings, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
                "config_sha256": hashlib.sha256((ROOT / "configs" / "ember-restart-3b.json").read_bytes()).hexdigest(),
                "runner_source_sha256": hashlib.sha256((ROOT / "tools" / "ember-restart-3b" / "run_vertical_slice.py").read_bytes()).hexdigest(),
                "checkpoint_byte_bound": 4096,
                "write_budget_bytes": 4096,
            }
            vertical_run.assert_called_once_with(
                seed=83, artifact_root=artifact_root, resume_checkpoint=None,
                resume_counter_receipt=None, resume_realization_registry=None,
                resume_optimizer_transition_registry=None,
                resume_optimizer_transition_registry_sha256=None,
                write_budget_bytes=4096, max_records=3, canonical_runner_authority=assertion_authority,
                c_relocated_under_disk_budget_runner=False,
                relocation_custody_root=None,
                signature_census_output=census_output,
                signature_census_source_commit="1" * 40,
                stage2_acceleration=False,
                stage2_diagnostic_bf16_down=False,
                stage2_diagnostic_eager_workspace=False,
                stage2_diagnostic_pre_optimizer_sync=False,
                stage2_arm_receipt_output=None,
            )

    def test_signature_census_request_is_paired_and_refuses_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "census.json"
            self.assertEqual(
                run_vertical_slice.validate_signature_census_request(output, "1" * 40),
                (output.resolve(), "1" * 40),
            )
            with self.assertRaisesRegex(ValueError, "together"):
                run_vertical_slice.validate_signature_census_request(output, None)
            with self.assertRaisesRegex(ValueError, "40hex"):
                run_vertical_slice.validate_signature_census_request(output, "bad")
            output.write_text("occupied", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                run_vertical_slice.validate_signature_census_request(output, "1" * 40)

    def test_stage2_activation_request_is_explicit_canonical_and_non_minting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact_root = Path(directory)
            output = artifact_root / "stage2-arm.json"
            self.assertEqual(
                run_vertical_slice.validate_stage2_activation_request(
                    enabled=True,
                    artifact_root=artifact_root,
                    receipt_output=output,
                    signature_census_output=None,
                    resume_checkpoint=None,
                ),
                output.resolve(),
            )
            with self.assertRaisesRegex(ValueError, "cannot mint"):
                run_vertical_slice.validate_stage2_activation_request(
                    enabled=True, artifact_root=artifact_root, receipt_output=output,
                    signature_census_output=artifact_root / "census.json", resume_checkpoint=None,
                )
            with self.assertRaisesRegex(ValueError, "resume"):
                run_vertical_slice.validate_stage2_activation_request(
                    enabled=True, artifact_root=artifact_root, receipt_output=output,
                    signature_census_output=None, resume_checkpoint=artifact_root / "checkpoint",
                )
            with self.assertRaisesRegex(ValueError, "receipt output"):
                run_vertical_slice.validate_stage2_activation_request(
                    enabled=True, artifact_root=artifact_root, receipt_output=None,
                    signature_census_output=None, resume_checkpoint=None,
                )
            outside = artifact_root.parent / "outside-stage2.json"
            with self.assertRaisesRegex(ValueError, "custody"):
                run_vertical_slice.validate_stage2_activation_request(
                    enabled=False, artifact_root=artifact_root, receipt_output=outside,
                    signature_census_output=None, resume_checkpoint=None,
                )

    def test_stage2_graph_only_diagnostic_is_explicit_and_requires_closed_custody(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact_root = Path(directory)
            output = artifact_root / "graph-only-diagnostic.json"
            self.assertEqual(
                run_vertical_slice.validate_stage2_activation_request(
                    enabled=False,
                    diagnostic_bf16_down=True,
                    artifact_root=artifact_root,
                    receipt_output=output,
                    signature_census_output=None,
                    resume_checkpoint=None,
                ),
                output.resolve(),
            )
            with self.assertRaisesRegex(ValueError, "mutually exclusive"):
                run_vertical_slice.validate_stage2_activation_request(
                    enabled=True,
                    diagnostic_bf16_down=True,
                    artifact_root=artifact_root,
                    receipt_output=output,
                    signature_census_output=None,
                    resume_checkpoint=None,
                )

    def test_stage2_eager_workspace_diagnostic_is_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact_root = Path(directory)
            output = artifact_root / "eager-workspace.json"
            self.assertEqual(
                run_vertical_slice.validate_stage2_activation_request(
                    enabled=False,
                    diagnostic_eager_workspace=True,
                    artifact_root=artifact_root,
                    receipt_output=output,
                    signature_census_output=None,
                    resume_checkpoint=None,
                ),
                output.resolve(),
            )
            with self.assertRaisesRegex(ValueError, "mutually exclusive"):
                run_vertical_slice.validate_stage2_activation_request(
                    enabled=False,
                    diagnostic_bf16_down=True,
                    diagnostic_eager_workspace=True,
                    artifact_root=artifact_root,
                    receipt_output=output,
                    signature_census_output=None,
                    resume_checkpoint=None,
                )

    def test_pre_optimizer_sync_is_admitted_only_for_graph_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact_root = Path(directory)
            output = artifact_root / "sync.json"
            self.assertEqual(
                run_vertical_slice.validate_stage2_activation_request(
                    enabled=False,
                    diagnostic_bf16_down=True,
                    diagnostic_pre_optimizer_sync=True,
                    artifact_root=artifact_root,
                    receipt_output=output,
                    signature_census_output=None,
                    resume_checkpoint=None,
                ),
                output.resolve(),
            )
            with self.assertRaisesRegex(ValueError, "sync requires"):
                run_vertical_slice.validate_stage2_activation_request(
                    enabled=False,
                    diagnostic_pre_optimizer_sync=True,
                    artifact_root=artifact_root,
                    receipt_output=output,
                    signature_census_output=None,
                    resume_checkpoint=None,
                )
            with self.assertRaisesRegex(ValueError, "receipt output"):
                run_vertical_slice.validate_stage2_activation_request(
                    enabled=False,
                    diagnostic_bf16_down=True,
                    artifact_root=artifact_root,
                    receipt_output=None,
                    signature_census_output=None,
                    resume_checkpoint=None,
                )

    def test_governed_vertical_forwards_relocation_to_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            custody = Path(directory) / "custody"
            artifact_root = custody / "artifacts"
            cache = custody / "tmp"
            cache.mkdir(parents=True)
            artifact_root.mkdir(parents=True)
            bindings = {name: str((custody / name.lower()).resolve()) for name in (
                "TEMP", "TMP", "TORCH_HOME", "TRITON_CACHE_DIR", "CUDA_CACHE_PATH", "HF_HOME", "XDG_CACHE_HOME",
            )}
            bindings["TEMP"] = str(cache.resolve())
            bindings["TMP"] = str(cache.resolve())
            for value in set(bindings.values()):
                Path(value).mkdir(parents=True, exist_ok=True)
            nonce = "f" * 32
            assertion = custody / "child-env-startup.json"
            assertion.write_text(json.dumps({"schema_version": 1, "nonce": nonce, "bindings": bindings}), encoding="utf-8")
            relocation = custody / "relocated"
            relocation.mkdir()
            with patch.dict(os.environ, {**bindings, "EMBER_DISK_BUDGET_ENV_ASSERTION": str(assertion), "EMBER_DISK_BUDGET_ENV_NONCE": nonce}, clear=True):
                with patch.object(run_vertical_slice, "checkpoint_serialization_byte_bound", return_value=4096):
                    with patch.object(run_vertical_slice, "run", return_value={}) as vertical_run:
                        run_vertical_slice.run_governed_vertical(
                            seed=83,
                            artifact_root=artifact_root,
                            write_budget_bytes=4096,
                            c_relocated_under_disk_budget_runner=True,
                            relocation_custody_root=relocation,
                        )
            self.assertIs(vertical_run.call_args.kwargs["c_relocated_under_disk_budget_runner"], True)
            self.assertEqual(vertical_run.call_args.kwargs["relocation_custody_root"], relocation)

    def test_governed_vertical_wrapper_reaches_real_run_authority_equality(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            custody = Path(directory) / "custody"
            artifact_root = custody / "artifacts"
            cache = custody / "tmp"
            cache.mkdir(parents=True)
            artifact_root.mkdir(parents=True)
            bindings = {name: str((custody / name.lower()).resolve()) for name in (
                "TEMP", "TMP", "TORCH_HOME", "TRITON_CACHE_DIR", "CUDA_CACHE_PATH", "HF_HOME", "XDG_CACHE_HOME",
            )}
            bindings["TEMP"] = str(cache.resolve())
            bindings["TMP"] = str(cache.resolve())
            for value in set(bindings.values()):
                Path(value).mkdir(parents=True, exist_ok=True)
            nonce = "e" * 32
            assertion = custody / "child-env-startup.json"
            assertion.write_text(json.dumps({"schema_version": 1, "nonce": nonce, "bindings": bindings}), encoding="utf-8")
            with patch.dict(os.environ, {**bindings, "EMBER_DISK_BUDGET_ENV_ASSERTION": str(assertion), "EMBER_DISK_BUDGET_ENV_NONCE": nonce}, clear=True):
                with patch.object(run_vertical_slice, "production_artifact_root", side_effect=lambda path, **_kwargs: path):
                    with patch.object(run_vertical_slice, "governed_resource_preflight", side_effect=RuntimeError("governor reached")) as governor:
                        with self.assertRaisesRegex(RuntimeError, "governor reached"):
                            run_vertical_slice.run_governed_vertical(
                                seed=83, artifact_root=artifact_root, write_budget_bytes=16_430_389_248,
                            )
            governor.assert_called_once_with()

    def test_governed_vertical_rejects_artifact_root_outside_custody_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            custody = Path(directory) / "custody"
            cache = custody / "tmp"
            cache.mkdir(parents=True)
            bindings = {name: str((custody / name.lower()).resolve()) for name in (
                "TEMP", "TMP", "TORCH_HOME", "TRITON_CACHE_DIR", "CUDA_CACHE_PATH", "HF_HOME", "XDG_CACHE_HOME",
            )}
            bindings["TEMP"] = str(cache.resolve())
            bindings["TMP"] = str(cache.resolve())
            for value in set(bindings.values()):
                Path(value).mkdir(parents=True, exist_ok=True)
            nonce = "d" * 32
            assertion = custody / "child-env-startup.json"
            assertion.write_text(json.dumps({"schema_version": 1, "nonce": nonce, "bindings": bindings}), encoding="utf-8")
            outside_artifact_root = Path(directory) / "outside-artifacts"
            outside_artifact_root.mkdir()
            with patch.dict(os.environ, {**bindings, "EMBER_DISK_BUDGET_ENV_ASSERTION": str(assertion), "EMBER_DISK_BUDGET_ENV_NONCE": nonce}, clear=True):
                with patch.object(run_vertical_slice, "checkpoint_serialization_byte_bound", return_value=4096):
                    with patch.object(run_vertical_slice, "governed_resource_preflight", side_effect=AssertionError("governor")) as governor:
                        with patch.object(run_vertical_slice, "run", side_effect=AssertionError("run")) as vertical_run:
                            with self.assertRaisesRegex(ValueError, "artifact root escapes canonical runner custody"):
                                run_vertical_slice.run_governed_vertical(seed=83, artifact_root=outside_artifact_root, write_budget_bytes=4096)
            governor.assert_not_called()
            vertical_run.assert_not_called()

    def test_governed_checkpoint_bound_covers_every_expert(self) -> None:
        config_path = ROOT / "configs" / "ember-restart-3b.json"
        bound = run_vertical_slice.governed_vertical_checkpoint_byte_bound(config_path)
        self.assertEqual(bound, 3_839_161_856 * 2 + 3_839_161_856 * 2 + 1024**3)
        # The governed-vertical shard realizes all four experts, so the bound
        # must admit full-coverage optimizer state: model shards plus one
        # optimizer moment over every structural parameter (#1320).
        full_coverage_tensor_floor = 3_839_161_856 * 2 * 2
        self.assertGreater(bound, full_coverage_tensor_floor)

    def test_run_path_reserves_full_coverage_bound_for_nonspecialist_episodes(self) -> None:
        # #1483: the selection moved into specialist_checkpoint_bound_active_parameters,
        # whose own tests pin all four (lineage, coverage) combinations -- including
        # that nonspecialist episodes always reserve the full-coverage bound.
        # #1324 (reviewer nit): the prior version of this test pinned run()'s
        # delegation via inspect.getsource string matching, which is brittle to
        # reformatting and satisfiable by a stray comment. The real behavioral
        # coverage for run() delegating correctly lives in
        # test_vertical_resume_preserves_owned_cursor_but_resets_only_specialist_cursor
        # (asserts the actual max_serialized_bytes each episode shape publishes with).
        self.assertEqual(
            run_vertical_slice.specialist_checkpoint_bound_active_parameters(
                specialist_lineage=None,
                optimizer_full_route_coverage=False,
                active_parameters=1_725_232_640,
                total_parameters=3_839_161_856,
            ),
            3_839_161_856,
        )

    def test_run_early_write_budget_check_validates_against_the_episode_bound(self) -> None:
        # #1324: run()'s early write-budget sanity check validated against the
        # shared-only bound (10,793,244,672 here) regardless of episode shape,
        # so a budget well short of what a governed-vertical (specialist_lineage
        # is None) episode actually needs -- full-coverage optimizer state,
        # 16,430,389,248 -- silently passed this gate and only failed much later
        # (or, for a direct run() call bypassing run_governed_vertical, not at
        # all inside run() itself).
        config_path = ROOT / "configs" / "ember-restart-3b.json"
        shared_only_bound = run_vertical_slice.checkpoint_serialization_byte_bound(config_path)
        full_coverage_bound = run_vertical_slice.checkpoint_serialization_byte_bound(
            config_path, active_parameters=3_839_161_856,
        )
        specialist_bound = run_vertical_slice.checkpoint_serialization_byte_bound(
            config_path, active_parameters=1_725_232_640,
        )
        self.assertLess(shared_only_bound, specialist_bound)
        self.assertLess(specialist_bound, full_coverage_bound)
        under_full_coverage_budget = shared_only_bound + 1_000_000_000
        self.assertLess(under_full_coverage_budget, full_coverage_bound)
        # production_artifact_root requires an explicit B: path regardless of
        # where this test file itself resides (e.g. a linked worktree); a
        # nonexistent-but-lexically-valid B: path clears that unrelated
        # precondition without touching the filesystem, isolating the budget
        # gate under test. torch.cuda.is_available is forced False so this
        # unit test can never fall through into a real production launch on a
        # host that actually has a GPU (pre-training gate: no GPU/training work
        # from this test suite, ever).
        artifact_root = Path("B:/") / "ember-runner-preflight-test-1324-artifact-root"
        # Governed-vertical (specialist_lineage=None): the fixed check now uses
        # the full-coverage bound and refuses a budget the shared-only bound
        # would previously have waved through.
        with self.assertRaisesRegex(ValueError, "checkpoint publication bound exceeds"):
            run_vertical_slice.run(seed=83, artifact_root=artifact_root, write_budget_bytes=under_full_coverage_budget)
        # A budget that actually covers the full-coverage bound clears this
        # check and fails later, on an unrelated precondition -- proving the
        # ValueError above came from the budget gate, not from something else
        # run() validates first.
        with patch.object(run_vertical_slice.torch.cuda, "is_available", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "CUDA is required"):
                run_vertical_slice.run(seed=83, artifact_root=artifact_root, write_budget_bytes=full_coverage_bound)

    def test_governed_vertical_refuses_successor_four_gib_checkpoint_envelope(self) -> None:
        with self.assertRaisesRegex(ValueError, "checkpoint publication bound"):
            run_vertical_slice.preflight_governed_vertical(seed=83, artifact_root=ROOT, write_budget_bytes=4 * 1024**3)

    def test_canonical_runner_assertion_outside_custody_is_rejected_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            custody = Path(directory) / "custody"
            cache = custody / "tmp"
            cache.mkdir(parents=True)
            bindings = {name: str((custody / name.lower()).resolve()) for name in (
                "TEMP", "TMP", "TORCH_HOME", "TRITON_CACHE_DIR", "CUDA_CACHE_PATH", "HF_HOME", "XDG_CACHE_HOME",
            )}
            bindings["TEMP"] = str(cache.resolve())
            bindings["TMP"] = str(cache.resolve())
            for value in set(bindings.values()):
                Path(value).mkdir(parents=True, exist_ok=True)
            nonce = "b" * 32
            assertion = Path(directory) / "child-env-startup.json"
            assertion.write_text(json.dumps({"schema_version": 1, "nonce": nonce, "bindings": bindings}), encoding="utf-8")
            with patch.dict(os.environ, {**bindings, "EMBER_DISK_BUDGET_ENV_ASSERTION": str(assertion), "EMBER_DISK_BUDGET_ENV_NONCE": nonce}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "not the custody startup assertion"):
                    run_vertical_slice.canonical_disk_budget_runner_authority()

    def test_governed_vertical_rejects_one_byte_below_one_expert_bound_before_launch(self) -> None:
        with patch.object(run_vertical_slice, "_canonical_disk_budget_runner_authority", return_value=({}, ROOT)):
            with patch.object(run_vertical_slice, "governed_resource_preflight", side_effect=AssertionError("governor")) as governor:
                with patch.object(run_vertical_slice, "run", side_effect=AssertionError("run")) as vertical_run:
                    with self.assertRaisesRegex(ValueError, "checkpoint publication bound"):
                        run_vertical_slice.run_governed_vertical(seed=83, artifact_root=ROOT, write_budget_bytes=12_202_530_815)
        governor.assert_not_called()
        vertical_run.assert_not_called()
    def test_governed_vertical_budget_refusal_precedes_governor_and_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            custody = Path(directory) / "custody"
            bindings = {name: str((custody / name.lower()).resolve()) for name in (
                "TEMP", "TMP", "TORCH_HOME", "TRITON_CACHE_DIR", "CUDA_CACHE_PATH", "HF_HOME", "XDG_CACHE_HOME",
            )}
            bindings["TMP"] = bindings["TEMP"]
            for value in set(bindings.values()):
                Path(value).mkdir(parents=True, exist_ok=True)
            nonce = "c" * 32
            assertion = custody / "child-env-startup.json"
            assertion.write_text(json.dumps({"schema_version": 1, "nonce": nonce, "bindings": bindings}), encoding="utf-8")
            with patch.dict(os.environ, {**bindings, "EMBER_DISK_BUDGET_ENV_ASSERTION": str(assertion), "EMBER_DISK_BUDGET_ENV_NONCE": nonce}, clear=True):
                with patch.object(run_vertical_slice, "checkpoint_serialization_byte_bound", return_value=4097):
                    with patch.object(run_vertical_slice, "governed_resource_preflight", side_effect=AssertionError("governor")) as governor:
                        with patch.object(run_vertical_slice, "run", side_effect=AssertionError("run")) as vertical_run:
                            with self.assertRaisesRegex(ValueError, "checkpoint publication bound"):
                                run_vertical_slice.run_governed_vertical(seed=83, artifact_root=custody, write_budget_bytes=4096)
            governor.assert_not_called()
            vertical_run.assert_not_called()
    def test_canonical_runner_missing_nonce_is_rejected_before_launch(self) -> None:
        with patch.dict(os.environ, {"EMBER_DISK_BUDGET_ENV_ASSERTION": "B:/missing"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "canonical disk budget runner assertion"):
                run_vertical_slice.canonical_disk_budget_runner_authority()
    def test_specialist_lineage_request_binds_parent_to_exact_resume_bundle(self) -> None:
        verification = {"result": "VERIFIED", "capability": "image", "record_count": 20, "records_artifact_sha256": "e" * 64}
        execution_slice = {
            "schema_version": "ember-specialist-execution-slice-v1", "start_record": 0,
            "record_count": 20, "token_count": 40, "records_sha256": "a" * 64,
            "tokens_sha256": "b" * 64, "scene_split_record_count": 20,
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
                    scene_split_selection={"schema_version": "ember-specialist-scene-split-selection-v1", "capability": "image", "scene_split": "train", "full_records_artifact_sha256": "e" * 64, "selected_record_count": 20, "selected_token_count": 40, "selected_records_sha256": "a" * 64, "selected_tokens_sha256": "b" * 64},
                )
                self.assertEqual(lineage["trained_expert_ids"], ["vision"])
                self.assertEqual(lineage["execution_slice"], execution_slice)
                preflight.assert_called_once_with(parent_manifest=manifest.resolve(), root_manifest=manifest.resolve())
                with self.assertRaisesRegex(ValueError, "exact resumed"):
                    run_vertical_slice.specialist_lineage_request(
                        capability="image", verification=verification, resume_checkpoint=Path(directory) / "other",
                        parent_manifest=manifest, root_manifest=manifest, execution_slice=execution_slice,
                    scene_split_selection={"schema_version": "ember-specialist-scene-split-selection-v1", "capability": "image", "scene_split": "train", "full_records_artifact_sha256": "e" * 64, "selected_record_count": 20, "selected_token_count": 40, "selected_records_sha256": "a" * 64, "selected_tokens_sha256": "b" * 64},
                    )
    def test_scene_selection_is_separate_and_binds_full_verified_artifact(self) -> None:
        verification = {
            "result": "VERIFIED", "capability": "image", "records_artifact_sha256": "a" * 64,
        }
        original = dict(verification)
        records = [
            {"active_expert": "vision", "scene_split": "train", "token_ids": [1, 2]},
            {"active_expert": "vision", "scene_split": "validation", "token_ids": [3]},
            {"active_expert": "vision", "scene_split": "test", "token_ids": [4]},
        ]
        selected, selection = run_vertical_slice.select_verified_scene_split(
            records, capability="image", scene_split="train",
            full_records_artifact_sha256=verification["records_artifact_sha256"],
        )
        self.assertEqual(verification, original)
        self.assertEqual(selected, [records[0]])
        self.assertEqual(selection["full_records_artifact_sha256"], verification["records_artifact_sha256"])
        self.assertEqual(selection["selected_record_count"], 1)
        self.assertEqual(selection["selected_token_count"], 2)

    def test_image_run_rejects_unverifiable_selected_subset_before_cuda_probe(self) -> None:
        full_records = [
            {"active_expert": "vision", "scene_split": "train", "token_ids": [1]},
            {"active_expert": "vision", "scene_split": "train", "token_ids": [2]},
        ]
        artifact_bytes = json.dumps({"records": full_records}, sort_keys=True, separators=(",", ":")).encode("utf-8")
        artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
        _selected, selection = run_vertical_slice.select_verified_scene_split(
            full_records, capability="image", scene_split="train", full_records_artifact_sha256=artifact_sha256,
        )
        for label, mutate in {
            "records-hash": lambda receipt: receipt.__setitem__("selected_records_sha256", "b" * 64),
            "tokens-hash": lambda receipt: receipt.__setitem__("selected_tokens_sha256", "c" * 64),
            "record-count": lambda receipt: receipt.__setitem__("selected_record_count", 3),
            "token-count": lambda receipt: receipt.__setitem__("selected_token_count", 3),
        }.items():
            receipt = dict(selection)
            mutate(receipt)
            lineage = {"execution_slice": {**run_vertical_slice.specialist_execution_slice_receipt(full_records[:1], source_start_record=0, scene_split_record_count=receipt["selected_record_count"])}, "scene_split_selection": receipt}
            with self.subTest(label=label), patch.object(run_vertical_slice.torch.cuda, "is_available", side_effect=AssertionError("CUDA probe")) as cuda_probe:
                with self.assertRaisesRegex(ValueError, "image specialist"):
                    run_vertical_slice.run(seed=1, artifact_root=Path("B:/artifacts"), records_override=full_records[:1], scene_split_records=full_records, specialist_verification={"capability": "image", "records_artifact_sha256": artifact_sha256}, specialist_lineage=lineage, checkpoint_interval=1, write_budget_bytes=1, full_records_artifact_bytes=artifact_bytes)
                cuda_probe.assert_not_called()
        execution = run_vertical_slice.specialist_execution_slice_receipt(
            full_records[:1], source_start_record=2, scene_split_record_count=2,
        )
        with patch.object(run_vertical_slice.torch.cuda, "is_available", side_effect=AssertionError("CUDA probe")) as cuda_probe:
            with self.assertRaisesRegex(ValueError, "selected train records"):
                run_vertical_slice.run(seed=1, artifact_root=Path("B:/artifacts"), records_override=full_records[:1], scene_split_records=full_records, specialist_verification={"capability": "image", "records_artifact_sha256": artifact_sha256}, specialist_lineage={"execution_slice": execution, "scene_split_selection": selection}, checkpoint_interval=1, write_budget_bytes=1, full_records_artifact_bytes=artifact_bytes)
        cuda_probe.assert_not_called()
    def test_specialist_run_rejects_nontrain_or_unknown_image_rows_before_cuda_probe(self) -> None:
        selection = {
            "schema_version": "ember-specialist-scene-split-selection-v1",
            "capability": "image", "scene_split": "train", "full_records_artifact_sha256": "a" * 64,
            "selected_record_count": 1, "selected_token_count": 1,
            "selected_records_sha256": "b" * 64, "selected_tokens_sha256": "c" * 64,
        }
        lineage = {
            "parent_manifest": "parent", "root_manifest": "root", "trained_expert_ids": ["vision"],
            "execution_slice": {"schema_version": "ember-specialist-execution-slice-v1", "start_record": 0,
                "record_count": 1, "token_count": 1, "records_sha256": "b" * 64, "tokens_sha256": "c" * 64,
                "scene_split_record_count": 1},
            "scene_split_selection": selection,
        }
        verification = {"capability": "image", "records_artifact_sha256": "a" * 64}
        invalid_rows = {
            "validation": [{"active_expert": "vision", "scene_split": "validation", "token_ids": [1]}],
            "test": [{"active_expert": "vision", "scene_split": "test", "token_ids": [1]}],
            "missing": [{"active_expert": "vision", "token_ids": [1]}],
            "unknown": [{"active_expert": "vision", "scene_split": "other", "token_ids": [1]}],
            "mixed": [{"active_expert": "vision", "scene_split": "train", "token_ids": [1]}, {"active_expert": "vision", "scene_split": "validation", "token_ids": [2]}],
        }
        with patch.object(run_vertical_slice.torch.cuda, "is_available", side_effect=AssertionError("CUDA probe")) as cuda_probe:
            for label, rows in invalid_rows.items():
                with self.subTest(label=label), self.assertRaisesRegex(ValueError, "scene split"):
                    run_vertical_slice.run(
                        seed=1, artifact_root=Path("B:/artifacts"), records_override=rows, scene_split_records=rows,
                        specialist_verification=verification, specialist_lineage=lineage,
                        checkpoint_interval=1, write_budget_bytes=1,
                    )
        cuda_probe.assert_not_called()
    def test_specialist_dispatch_does_not_enter_cuda_runner_when_lineage_preflight_fails(self) -> None:
        verification = {"result": "VERIFIED", "capability": "image", "records_artifact_sha256": "a" * 64}
        with patch.object(run_vertical_slice, "load_verified_specialist_records", return_value=([{"active_expert": "vision", "scene_split": "train", "token_ids": [1]}, {"active_expert": "vision", "scene_split": "validation", "token_ids": [2]}, {"active_expert": "vision", "scene_split": "test", "token_ids": [3]}], verification, b"{}")):
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
        verification = {"result": "VERIFIED", "capability": "image", "records_artifact_sha256": "a" * 64}
        with patch.object(run_vertical_slice, "load_verified_specialist_records", return_value=([{"active_expert": "vision", "scene_split": "train", "token_ids": [1]}, {"active_expert": "vision", "scene_split": "validation", "token_ids": [2]}, {"active_expert": "vision", "scene_split": "test", "token_ids": [3]}], verification, b"{}")):
            with patch.object(run_vertical_slice, "specialist_lineage_request", side_effect=lambda **kwargs: {"parent_manifest": "parent", "root_manifest": "root", "execution_slice": kwargs["execution_slice"], "scene_split_selection": kwargs["scene_split_selection"]}):
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
        self.assertEqual(cuda_runner.call_args.kwargs["records_override"], [{"active_expert": "vision", "scene_split": "train", "token_ids": [1]}])
        self.assertEqual(cuda_runner.call_args.kwargs["scene_split_records"], [{"active_expert": "vision", "scene_split": "train", "token_ids": [1]}])
        self.assertEqual(cuda_runner.call_args.kwargs["specialist_verification"], verification)
        self.assertEqual(cuda_runner.call_args.kwargs["specialist_lineage"]["scene_split_selection"]["scene_split"], "train")
        self.assertIn("execution_slice", cuda_runner.call_args.kwargs["specialist_lineage"])
    def test_specialist_cli_dispatches_one_verified_route(self) -> None:
        with patch.object(run_vertical_slice, "run_specialist", return_value={"steps": 1}) as specialist:
            with patch.object(sys, "argv", ["run_vertical_slice.py", "specialist", "--seed", "84", "--artifact-root", "B:/ember-artifacts", "--data-manifest", "data/vision.json", "--tokenizer", "tokenizer.json", "--capability", "image", "--resume-checkpoint", "B:/parent", "--resume-counter-receipt", "B:/parent/parameter-counter-receipt.json", "--parent-manifest", "B:/parent/checkpoint-manifest.json", "--root-manifest", "B:/root/checkpoint-manifest.json", "--start-record", "7", "--max-records", "20", "--checkpoint-interval", "8192", "--write-budget-gib", "120", "--telemetry-path", "state/ember-telemetry.jsonl", "--telemetry-run-id", "vision-v4", "--model-chat-restore-not-before", "2026-07-18T11:00:00-07:00"]):
                run_vertical_slice.main()
        specialist.assert_called_once_with(seed=84, artifact_root=Path("B:/ember-artifacts"), data_manifest=Path("data/vision.json"), tokenizer_path=Path("tokenizer.json"), capability="image", resume_checkpoint=Path("B:/parent"), resume_counter_receipt=Path("B:/parent/parameter-counter-receipt.json"), resume_realization_registry=None, resume_optimizer_transition_registry=None, resume_optimizer_transition_registry_sha256=None, parent_manifest=Path("B:/parent/checkpoint-manifest.json"), root_manifest=Path("B:/root/checkpoint-manifest.json"), start_record=7, max_records=20, checkpoint_interval=8_192, write_budget_bytes=120 * 1024**3, c_relocated_under_disk_budget_runner=False, relocation_custody_root=None, telemetry_path=Path("state/ember-telemetry.jsonl"), telemetry_run_id="vision-v4", model_chat_restore_not_before="2026-07-18T11:00:00-07:00")
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

    def test_specialist_cli_forwards_expected_transition_registry_sha256(self) -> None:
        expected_sha256 = "7" * 64
        with patch.object(run_vertical_slice, "run_specialist", return_value={"steps": 1}) as specialist:
            with patch.object(sys, "argv", ["run_vertical_slice.py", "specialist", "--seed", "84", "--artifact-root", "C:/custody/vision", "--data-manifest", "data/vision.json", "--tokenizer", "tokenizer.json", "--capability", "image", "--resume-checkpoint", "B:/parent", "--resume-optimizer-transition-registry", "C:/transition/trusted-transitions.json", "--resume-optimizer-transition-registry-sha256", expected_sha256, "--parent-manifest", "B:/parent/checkpoint-manifest.json", "--root-manifest", "B:/parent/checkpoint-manifest.json", "--max-records", "20", "--c-relocated-under-disk-budget-runner", "--relocation-custody-root", "C:/custody", "--checkpoint-interval", "20", "--write-budget-gib", "24", "--telemetry-path", "C:/custody/telemetry.jsonl", "--telemetry-run-id", "vision-smoke", "--model-chat-restore-not-before", "2026-07-18T01:00:00-07:00"]):
                run_vertical_slice.main()
        self.assertEqual(specialist.call_args.kwargs["resume_optimizer_transition_registry"], Path("C:/transition/trusted-transitions.json"))
        self.assertEqual(specialist.call_args.kwargs["resume_optimizer_transition_registry_sha256"], expected_sha256)

    def test_c_custody_resume_bundle_requires_the_declared_disk_runner_root(self) -> None:
        with tempfile.TemporaryDirectory(dir="C:/tmp") as directory:
            custody = Path(directory)
            checkpoint = custody / "checkpoint"
            checkpoint.mkdir()
            manifest = {
                "schema_version": "ember-sparse-checkpoint-v4",
                "model_config_sha256": "a" * 64,
                "architecture_revision": "ember-sparse-3b-v2",
                "active_expert_ids": ["vision"],
                "expert_genesis_sha256": {name: "b" * 64 for name in ("vision", "audio", "reasoning", "tool")},
                "expert_parameter_sha256": {name: "c" * 64 for name in ("vision", "audio", "reasoning", "tool")},
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
                    "runtime_authority": {
                        "schema_version": "ember-counter-runtime-authority-v1",
                        "kind": "NONE",
                    },
                    "expert_genesis_sha256": manifest["expert_genesis_sha256"],
                    "expert_parameter_sha256": manifest["expert_parameter_sha256"],
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

    def test_planted_complete_published_but_unverified_bundle_is_not_resumable(self) -> None:
        """A complete-looking six-shard bundle without counter evidence is unselectable."""
        with tempfile.TemporaryDirectory() as directory:
            custody = Path(directory)
            checkpoint = custody / "checkpoint-complete-looking"
            checkpoint.mkdir()
            checkpoint.joinpath("checkpoint-manifest.json").write_text(json.dumps({"schema_version": "ember-sparse-checkpoint-v3", "shards": []}), encoding="utf-8")
            for name in ("shared.pt", "replay-state.pt", "expert-vision.pt", "expert-audio.pt", "expert-reasoning.pt", "expert-tool.pt"):
                checkpoint.joinpath(name).write_bytes(b"complete-looking checkpoint bytes")
            with self.assertRaisesRegex(ValueError, "counter-success receipt"):
                run_vertical_slice.production_resume_checkpoint(checkpoint, c_relocated_under_disk_budget_runner=True, relocation_custody_root=custody)
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

    def test_optimizer_transition_is_a_distinct_model_only_resume_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            custody = Path(directory)
            checkpoint = custody / "checkpoint"
            checkpoint.mkdir()
            (checkpoint / "checkpoint-manifest.json").write_text("{}", encoding="utf-8")
            registry = custody / "transition" / "trusted-transitions.json"
            registry.parent.mkdir()
            registry.write_text("{}", encoding="utf-8")
            admitted_transition = {
                "receipt_sha256": "r" * 64,
                "registry_sha256": hashlib.sha256(registry.read_bytes()).hexdigest(),
                "source": {"checkpoint_manifest_sha256": "m" * 64, "semantic_model_contract_sha256": "s" * 64},
                "target": {"model_config_sha256": "c" * 64, "semantic_model_contract_sha256": "t" * 64},
            }
            expected_registry_sha256 = hashlib.sha256(registry.read_bytes()).hexdigest()
            with patch.object(run_vertical_slice, "validate_optimizer_transition_registry", return_value=admitted_transition) as validate:
                with self.assertRaisesRegex(ValueError, "expected registry SHA-256"):
                    run_vertical_slice.authorize_production_resume_checkpoint(
                        checkpoint,
                        optimizer_transition_registry=registry,
                        c_relocated_under_disk_budget_runner=True,
                        relocation_custody_root=custody,
                    )
                with self.assertRaisesRegex(ValueError, "registry SHA-256 mismatch"):
                    run_vertical_slice.authorize_production_resume_checkpoint(
                        checkpoint,
                        optimizer_transition_registry=registry,
                        optimizer_transition_registry_sha256="0" * 64,
                        c_relocated_under_disk_budget_runner=True,
                        relocation_custody_root=custody,
                    )
                admitted, authority = run_vertical_slice.authorize_production_resume_checkpoint(
                    checkpoint,
                    optimizer_transition_registry=registry,
                    optimizer_transition_registry_sha256=expected_registry_sha256,
                    c_relocated_under_disk_budget_runner=True,
                    relocation_custody_root=custody,
                )
            self.assertEqual(admitted, checkpoint.resolve())
            self.assertEqual(authority["mode"], "MODEL_ONLY_OPTIMIZER_CONTRACT_TRANSITION")
            self.assertFalse(authority["optimizer_state_reused"])
            validate.assert_called_once_with(
                registry.resolve(),
                checkpoint_root=checkpoint.resolve(),
                current_target_config_path=ROOT / "configs" / "ember-restart-3b.json",
            )
            with self.assertRaisesRegex(ValueError, "mutually exclusive"):
                run_vertical_slice.authorize_production_resume_checkpoint(
                    checkpoint,
                    realization_registry=registry,
                    optimizer_transition_registry=registry,
                    c_relocated_under_disk_budget_runner=True,
                    relocation_custody_root=custody,
                )

    def test_quarantined_resume_is_rejected_before_counter_or_transition_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            custody = Path(directory)
            checkpoint = custody / ".checkpoint-quarantine" / "candidate-valid"
            checkpoint.mkdir(parents=True)
            (checkpoint / "checkpoint-manifest.json").write_text("{}", encoding="utf-8")
            counter = checkpoint / "parameter-counter-receipt.json"
            counter.write_text("{}", encoding="utf-8")
            registry = custody / "transition" / "trusted-transitions.json"
            registry.parent.mkdir()
            registry.write_text("{}", encoding="utf-8")
            registry_sha256 = hashlib.sha256(registry.read_bytes()).hexdigest()
            transition = {"receipt_sha256": "r" * 64, "registry_sha256": registry_sha256, "source": {"checkpoint_manifest_sha256": "m" * 64, "semantic_model_contract_sha256": "s" * 64}, "target": {"model_config_sha256": "c" * 64, "semantic_model_contract_sha256": "t" * 64}}
            with patch.object(run_vertical_slice, "production_artifact_root", return_value=checkpoint.resolve()):
                with patch.object(run_vertical_slice, "require_counter_success_receipt", return_value={}) as counter_validate:
                    with self.assertRaisesRegex(ValueError, "quarantined"):
                        run_vertical_slice.authorize_production_resume_checkpoint(checkpoint, counter_success_receipt=counter, c_relocated_under_disk_budget_runner=True, relocation_custody_root=custody)
                counter_validate.assert_not_called()
                with patch.object(run_vertical_slice, "validate_optimizer_transition_registry", return_value=transition) as transition_validate:
                    with self.assertRaisesRegex(ValueError, "quarantined"):
                        run_vertical_slice.authorize_production_resume_checkpoint(checkpoint, optimizer_transition_registry=registry, optimizer_transition_registry_sha256=registry_sha256, c_relocated_under_disk_budget_runner=True, relocation_custody_root=custody)
                transition_validate.assert_not_called()

    def test_model_only_transition_never_loads_parent_optimizer_state(self) -> None:
        model = object()
        optimizer = object()
        checkpoint = Path("checkpoint")
        receipt = {"checkpoint_manifest_sha256": "a" * 64}
        authority = {"mode": "MODEL_ONLY_OPTIMIZER_CONTRACT_TRANSITION", "checkpoint_manifest_sha256": "a" * 64}
        with patch.object(run_vertical_slice, "load_checkpoint_model_only_transition", return_value={"data_cursor": {"global_step": 2}}) as load:
            result = run_vertical_slice.restore_authorized_checkpoint(model, optimizer, checkpoint, receipt, authority)
        self.assertEqual(result["data_cursor"]["global_step"], 2)
        load.assert_called_once_with(model, checkpoint, receipt)

    def test_restore_authorized_checkpoint_refuses_manifest_changed_after_authorization(self) -> None:
        model = MagicMock()
        optimizer = MagicMock()
        checkpoint = Path("B:/published-checkpoint")
        receipt = {"checkpoint_manifest_sha256": "a" * 64, "checkpoint": {"byte_sha256": "a" * 64}}
        authority = {"mode": "CURRENT_COUNTER_SUCCESS_RECEIPT", "checkpoint_manifest_sha256": "b" * 64}
        with patch.object(run_vertical_slice, "load_checkpoint_artifacts") as load:
            with self.assertRaisesRegex(ValueError, "resume authority checkpoint manifest SHA-256 mismatch"):
                run_vertical_slice.restore_authorized_checkpoint(model, optimizer, checkpoint, receipt, authority)
        load.assert_not_called()

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

    def test_checked_in_four_domain_production_rung_is_receipted_and_admitted(self) -> None:
        records, packet, integration_receipt = run_vertical_slice.load_authorized_records(ROOT)
        identity = packet["input_identity"]
        self.assertEqual(identity["artifact_id"], "owned-four-domain-production-rung-v1")
        self.assertRegex(identity["admission_receipt_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual({record["active_expert"] for record in records}, {"vision", "audio", "reasoning", "tool"})
        self.assertEqual(len(records), 4)
        self.assertEqual(integration_receipt["launch_decision"], "ACCEPTED")
        self.assertEqual(integration_receipt["input_admission_receipt_sha256"], identity["admission_receipt_sha256"])

    def test_authorized_records_rejects_a_schema_valid_shard_swapped_after_admission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            for relative in ("configs", "domains/model/tokenizer", "data/ember-restart-3b"):
                shutil.copytree(ROOT / relative, root / relative)
            tools = root / "tools" / "ember-restart-3b"
            tools.mkdir(parents=True)
            for name in (
                "build_owned_audio_frames.py",
                "build_owned_reasoning_tool_trajectories.py",
                "build_owned_vision_scenes.py",
                "semantic_contract.py",
                "specialist_semantics.py",
                "verify_capability_record.py",
                "production_rung.py",
            ):
                shutil.copy2(ROOT / "tools" / "ember-restart-3b" / name, tools / name)
            shard = root / "data" / "ember-restart-3b" / "owned-four-domain-production-rung-v1.json"

            def admit_then_swap(*, repo_root: Path) -> tuple[dict[str, object], dict[str, str], dict[str, object]]:
                packet, validation, receipt = live_run_launch(repo_root=repo_root, code_commit="a" * 40)
                payload = json.loads(shard.read_bytes())
                payload["records"] = list(reversed(payload["records"]))
                shard.write_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
                return packet, validation, receipt

            with patch.object(run_vertical_slice, "run_launch", side_effect=admit_then_swap):
                with self.assertRaisesRegex(RuntimeError, "changed after admission"):
                    run_vertical_slice.load_authorized_records(root)
    def test_public_disk_budget_runner_creates_bound_assertion_and_invokes_child(self) -> None:
        runner = ROOT / "tools" / "ember-restart-3b" / "disk_budget_runner.py"
        self.assertTrue(runner.is_file(), "public disk budget runner is missing")
        with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
            custody = Path(directory) / "custody"
            artifact_root = custody / "artifacts"
            custody.mkdir()
            artifact_root.mkdir()
            child = Path(directory) / "child.py"
            capture = custody / "capture.json"
            child.write_text(
                "import json, os, pathlib\n"
                "assertion = pathlib.Path(os.environ['EMBER_DISK_BUDGET_ENV_ASSERTION'])\n"
                "payload = json.loads(assertion.read_text(encoding='utf-8'))\n"
                "pathlib.Path(os.environ['GOVERNED_LAUNCH_CAPTURE']).write_text(json.dumps({'payload': payload, 'env': {key: os.environ[key] for key in payload['bindings']}, 'dont_write_bytecode': os.environ.get('PYTHONDONTWRITEBYTECODE')}, sort_keys=True), encoding='utf-8')\n",
                encoding="utf-8",
            )
            receipt = custody / "runner-receipt.json"
            with patch.dict(os.environ, {"GOVERNED_LAUNCH_CAPTURE": str(capture)}, clear=False):
                completed = subprocess.run(
                    [
                        sys.executable, "-I", str(runner), "--max-c-write-gib", "0", "--max-b-write-gib", "0.01",
                        "--receipt", str(receipt), "--write-root", f"custody={custody}",
                        "--write-root", f"artifacts={artifact_root}", "--", sys.executable, str(child),
                    ],
                    text=True, capture_output=True, check=False,
                )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            observed = json.loads(capture.read_text(encoding="utf-8"))
            runner_receipt = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(observed["payload"]["schema_version"], 1)
        self.assertRegex(observed["payload"]["nonce"], r"^[0-9a-f]{32}$")
        self.assertEqual(observed["payload"]["bindings"], observed["env"])
        self.assertEqual(
            observed["dont_write_bytecode"],
            "1",
            "disk_budget_runner child spawn (argv is certificate-visible, "
            "so -B cannot ride argv) must suppress bytecode writes via env",
        )
        self.assertEqual(runner_receipt["outcome"], "COMPLETED")
        self.assertTrue(capture.is_relative_to(custody))
        self.assertEqual(runner_receipt["unredirected_cache_roots"], [])
        self.assertEqual(runner_receipt["child_cache_assertion"], observed["payload"])

    def test_public_disk_budget_runner_rejects_declared_write_that_crosses_reserve(self) -> None:
        runner = ROOT / "tools" / "ember-restart-3b" / "disk_budget_runner.py"
        self.assertTrue(runner.is_file(), "public disk budget runner is missing")
        with tempfile.TemporaryDirectory() as directory:
            custody = Path(directory) / "custody"
            custody.mkdir()
            receipt = custody / "runner-receipt.json"
            completed = subprocess.run(
                [sys.executable, str(runner), "--max-c-write-gib", "99999", "--max-b-write-gib", "0.001", "--receipt", str(receipt), "--write-root", f"custody={custody}", "--", sys.executable, "-c", "raise AssertionError('child')"],
                text=True, capture_output=True, check=False,
            )
            payload = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(completed.returncode, 125)
        self.assertEqual(payload["outcome"], "PRELAUNCH_REJECTED")
        self.assertIn("operating reserve", payload["stop_reason"])

    def test_public_runner_reaches_real_governed_vertical_cpu_preflight_child(self) -> None:
        runner = ROOT / "tools" / "ember-restart-3b" / "disk_budget_runner.py"
        child = ROOT / "tools" / "ember-restart-3b" / "run_vertical_slice.py"
        with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
            custody = Path(directory) / "custody"
            artifact_root = custody / "artifacts"
            custody.mkdir()
            artifact_root.mkdir()
            receipt = custody / "runner-receipt.json"
            completed = subprocess.run(
                [
                    sys.executable, "-I", str(runner), "--max-c-write-gib", "0", "--max-b-write-gib", "0.01",
                    "--receipt", str(receipt), "--write-root", f"custody={custody}", "--write-root", f"artifacts={artifact_root}", "--",
                    sys.executable, str(child), "governed-vertical-preflight", "--seed", "83", "--artifact-root", str(artifact_root),
                    "--write-budget-bytes", str(17 * 1024**3), "--max-records", "1",
                ], text=True, capture_output=True, check=False,
            )
            payload = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('"decision": "PREFLIGHT_ONLY"', completed.stdout)
        self.assertEqual(payload["outcome"], "COMPLETED")
        self.assertIsNotNone(payload["child_cache_assertion"])

    def test_public_runner_accounts_final_receipt_bytes_inside_custody_growth(self) -> None:
        runner = ROOT / "tools" / "ember-restart-3b" / "disk_budget_runner.py"
        with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
            custody = Path(directory) / "custody"
            custody.mkdir()
            receipt = custody / "runner-receipt.json"
            completed = subprocess.run(
                [sys.executable, "-I", str(runner), "--max-c-write-gib", "0", "--max-b-write-gib", "0.01", "--receipt", str(receipt), "--write-root", f"custody={custody}", "--", sys.executable, "-c", "pass"],
                text=True, capture_output=True, check=False,
            )
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            receipt_bytes = receipt.stat().st_size
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertGreaterEqual(payload["file_max_growth_bytes_by_root"]["custody"], receipt_bytes)

    def test_public_runner_refuses_budget_that_cannot_reserve_final_receipt_before_child(self) -> None:
        runner = ROOT / "tools" / "ember-restart-3b" / "disk_budget_runner.py"
        with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
            custody = Path(directory) / "custody"
            custody.mkdir()
            marker = custody / "child-ran"
            receipt = custody / "runner-receipt.json"
            completed = subprocess.run(
                [sys.executable, "-I", str(runner), "--max-c-write-gib", "0", "--max-b-write-gib", "0.00001", "--receipt", str(receipt), "--write-root", f"custody={custody}", "--", sys.executable, "-c", f"open(r'{marker}', 'w').write('ran')"],
                text=True, capture_output=True, check=False,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("cannot reserve the final runner receipt", completed.stderr)
        self.assertFalse(marker.exists())

    def test_public_runner_combines_child_growth_and_final_receipt_reservation(self) -> None:
        runner = ROOT / "tools" / "ember-restart-3b" / "disk_budget_runner.py"
        with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
            custody = Path(directory) / "custody"
            custody.mkdir()
            receipt = custody / "runner-receipt.json"
            child_file = custody / "child.bin"
            completed = subprocess.run(
                [sys.executable, "-I", str(runner), "--max-c-write-gib", "0", "--max-b-write-gib", "0.0001", "--receipt", str(receipt), "--write-root", f"custody={custody}", "--", sys.executable, "-c", f"open(r'{child_file}', 'wb').write(b'x' * 60000)"],
                text=True, capture_output=True, check=False,
            )
            payload = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(completed.returncode, 125, completed.stderr)
        self.assertEqual(payload["outcome"], "STOPPED_BY_BUDGET")
        self.assertIn("declared file write budget exceeded", payload["stop_reason"])

    def test_checkpoint_low_commit_deferral_policy_reads_its_own_module_local_file(self) -> None:
        policy_path = run_vertical_slice.default_checkpoint_low_commit_deferral_policy_path()
        self.assertEqual(policy_path.name, "checkpoint-low-commit-deferral-policy.json")
        self.assertTrue(policy_path.is_file())
        policy = run_vertical_slice.checkpoint_low_commit_deferral_policy(policy_path)
        self.assertEqual(policy, {"max_deferrals": 3, "max_uncheckpointed_step_distance": 2000})

    def test_publish_checkpoint_with_low_commit_deferral_defaults_to_the_module_local_policy(self) -> None:
        """Never touches the frozen ember-restart-3b.json production contract: that
        config's exact bytes are hash-bound into checked-in input-identity/
        production-rung/specialist-stream receipts, so any edit to it cascades into
        unrelated regenerated fixtures. The deferral policy is operational tuning
        and lives alongside this module instead, resolved with no config_path
        argument required."""
        from checkpoint_artifacts import CheckpointDeferredLowCommit
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            config_path = directory / "config.json"
            config_path.write_text(json.dumps({
                "checkpoints": {"retention": {"max_serialized_gib": 1, "preserve_last_known_good": True}},
            }), encoding="utf-8")
            checkpoint_parent = directory / "checkpoints"

            def publish() -> tuple[dict[str, object], dict[str, object]]:
                raise CheckpointDeferredLowCommit(
                    available_commit_bytes=1, required_commit_bytes=2,
                    streaming_peak_bytes=1, reserve_bytes=1,
                )

            state: dict[str, int] = {"count": 0}
            result = run_vertical_slice._publish_checkpoint_with_low_commit_deferral(
                checkpoint_parent=checkpoint_parent, config_path=config_path, global_step=1,
                last_checkpointed_step=0, deferral_state=state, publish=publish,
                telemetry_path=None, telemetry_run_id=None,
            )
            self.assertIsNone(result)
            self.assertEqual(state["count"], 1)

    def test_checkpoint_low_commit_deferral_policy_rejects_invalid_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            policy_path = Path(directory) / "policy.json"
            for policy_payload in (
                {},
                {"low_commit_deferral": "not-a-dict"},
                {"low_commit_deferral": {"max_deferrals": -1, "max_uncheckpointed_step_distance": 10}},
                {"low_commit_deferral": {"max_deferrals": 0, "max_uncheckpointed_step_distance": 0}},
                {"low_commit_deferral": {"max_deferrals": 0}},
            ):
                policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")
                with self.subTest(policy_payload=policy_payload), self.assertRaisesRegex(ValueError, "low-commit deferral"):
                    run_vertical_slice.checkpoint_low_commit_deferral_policy(policy_path)

    def test_checkpoint_low_commit_deferral_policy_fails_closed_when_the_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            policy_path = Path(directory) / "policy.json"
            with self.assertRaisesRegex(ValueError, "missing or unreadable"):
                run_vertical_slice.checkpoint_low_commit_deferral_policy(policy_path)

    def _low_commit_deferral_config(self, directory: Path, *, max_deferrals: int, max_distance: int) -> tuple[Path, Path]:
        config_path = directory / "config.json"
        config_path.write_text(json.dumps({
            "checkpoints": {"retention": {"max_serialized_gib": 1, "preserve_last_known_good": True}},
        }), encoding="utf-8")
        policy_path = directory / "policy.json"
        policy_path.write_text(json.dumps({
            "low_commit_deferral": {
                "max_deferrals": max_deferrals,
                "max_uncheckpointed_step_distance": max_distance,
            },
        }), encoding="utf-8")
        return config_path, policy_path

    def test_publish_checkpoint_with_low_commit_deferral_preserves_prior_and_receipts(self) -> None:
        from checkpoint_artifacts import CheckpointDeferredLowCommit, _empty_failure_comparison_operands
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            config_path, policy_path = self._low_commit_deferral_config(directory, max_deferrals=2, max_distance=100)
            checkpoint_parent = directory / "checkpoints"
            telemetry_path = directory / "telemetry.jsonl"
            comparison_operands = _empty_failure_comparison_operands()
            comparison_operands["derived_byte_bound_bytes"] = 4_096
            comparison_operands["derived_byte_bound_inputs"].update({
                "max_serialized_bytes": 4_096,
                "max_transient_scratch_bytes": 1_024,
                "active_parameters": 123,
                "model_config_sha256": "a" * 64,
                "contract_sha256": "b" * 64,
                "optimizer_state_layout": "owner-sharded-v1",
            })
            comparison_operands["projected_storage_floor_bytes"] = 8_192
            comparison_operands["projected_storage_floor_inputs"].update({
                "route_multiplier": 5,
                "active_expert": "vision",
                "optimizer_state_layout": "owner-sharded-v1",
                "optimizer_state_tensor_storage_lower_bound_bytes": 2_048,
                "projected_optimizer_state_tensor_storage_lower_bound_bytes": 10_240,
                "optimizer_state_tensor_storage_by_route_bytes": {
                    "shared": 512,
                    "vision": 1_536,
                    "audio": 0,
                    "reasoning": 0,
                    "tool": 0,
                },
                "per_shard_tensor_storage_lower_bound_bytes": {
                    "shared-model.pt": 1_024,
                },
                "retained_shard_paths": [],
            })

            def publish() -> tuple[dict[str, object], dict[str, object]]:
                raise CheckpointDeferredLowCommit(
                    available_commit_bytes=1_000, required_commit_bytes=5_000,
                    streaming_peak_bytes=4_000, reserve_bytes=1_000,
                )

            state: dict[str, int] = {"count": 0}
            result = run_vertical_slice._publish_checkpoint_with_low_commit_deferral(
                checkpoint_parent=checkpoint_parent, config_path=config_path, global_step=10,
                last_checkpointed_step=0, deferral_state=state, publish=publish,
                telemetry_path=telemetry_path, telemetry_run_id="run-1", policy_path=policy_path,
                comparison_operands=comparison_operands,
            )
            self.assertIsNone(result)
            self.assertEqual(state["count"], 1)
            # no checkpoint bundle, staging, or quarantine artifact was ever created --
            # the sole prior known-good checkpoint (if any) stays untouched/selectable.
            self.assertEqual(list(checkpoint_parent.glob("checkpoint-*")), [])
            receipts = list((checkpoint_parent / ".checkpoint-deferrals").glob("*.json"))
            self.assertEqual(len(receipts), 1)
            receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
            self.assertEqual(receipt["schema_version"], "ember-checkpoint-deferred-low-commit-v1")
            self.assertEqual(receipt["status"], "DEFERRED_LOW_COMMIT")
            self.assertEqual(receipt["global_step"], 10)
            self.assertEqual(receipt["deferral_count"], 1)
            self.assertEqual(receipt["uncheckpointed_step_distance"], 10)
            self.assertEqual(receipt["available_commit_bytes"], 1_000)
            self.assertEqual(receipt["required_commit_bytes"], 5_000)
            self.assertEqual(receipt["streaming_peak_bytes"], 4_000)
            self.assertEqual(receipt["reserve_bytes"], 1_000)
            self.assertEqual(
                set(receipt["comparison_operands"]),
                {
                    "derived_byte_bound_bytes",
                    "derived_byte_bound_inputs",
                    "projected_storage_floor_bytes",
                    "projected_storage_floor_inputs",
                    "staged_shard_bytes",
                    "available_commit_bytes",
                    "required_commit_bytes",
                },
            )
            self.assertEqual(
                receipt["comparison_operands"]["available_commit_bytes"],
                1_000,
            )
            self.assertEqual(
                receipt["comparison_operands"]["required_commit_bytes"],
                5_000,
            )
            bound_inputs = receipt["comparison_operands"]["derived_byte_bound_inputs"]
            self.assertIsNotNone(bound_inputs["active_parameters"])
            self.assertEqual(bound_inputs["model_config_sha256"], run_vertical_slice._sha256(config_path))
            self.assertEqual(bound_inputs["contract_sha256"], "b" * 64)
            self.assertEqual(bound_inputs["optimizer_state_layout"], "owner-sharded-v1")
            self.assertEqual(bound_inputs["max_transient_scratch_bytes"], 1_024)
            floor_inputs = receipt["comparison_operands"]["projected_storage_floor_inputs"]
            self.assertIsNotNone(floor_inputs["route_multiplier"])
            self.assertTrue(floor_inputs["optimizer_state_tensor_storage_by_route_bytes"])
            events = [json.loads(line) for line in telemetry_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["kind"], "checkpoint_deferred")
            self.assertEqual(events[0]["payload"]["status"], "DEFERRED_LOW_COMMIT")
            self.assertEqual(events[0]["payload"]["deferral_count"], 1)

    def test_publish_checkpoint_with_low_commit_deferral_fails_closed_past_max_deferrals(self) -> None:
        from checkpoint_artifacts import CheckpointDeferredLowCommit
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            config_path, policy_path = self._low_commit_deferral_config(directory, max_deferrals=1, max_distance=1000)
            checkpoint_parent = directory / "checkpoints"

            def publish() -> tuple[dict[str, object], dict[str, object]]:
                raise CheckpointDeferredLowCommit(
                    available_commit_bytes=1, required_commit_bytes=2,
                    streaming_peak_bytes=1, reserve_bytes=1,
                )

            state: dict[str, int] = {"count": 0}
            first = run_vertical_slice._publish_checkpoint_with_low_commit_deferral(
                checkpoint_parent=checkpoint_parent, config_path=config_path, global_step=5,
                last_checkpointed_step=0, deferral_state=state, publish=publish,
                telemetry_path=None, telemetry_run_id=None, policy_path=policy_path,
            )
            self.assertIsNone(first)
            with self.assertRaisesRegex(RuntimeError, "checkpoint low-commit deferral bound exceeded"):
                run_vertical_slice._publish_checkpoint_with_low_commit_deferral(
                    checkpoint_parent=checkpoint_parent, config_path=config_path, global_step=6,
                    last_checkpointed_step=0, deferral_state=state, publish=publish,
                    telemetry_path=None, telemetry_run_id=None, policy_path=policy_path,
                )
            self.assertEqual(state["count"], 2)
            self.assertEqual(len(list((checkpoint_parent / ".checkpoint-deferrals").glob("*.json"))), 2)

    def test_publish_checkpoint_with_low_commit_deferral_fails_closed_past_step_distance(self) -> None:
        from checkpoint_artifacts import CheckpointDeferredLowCommit
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            config_path, policy_path = self._low_commit_deferral_config(directory, max_deferrals=100, max_distance=5)
            checkpoint_parent = directory / "checkpoints"

            def publish() -> tuple[dict[str, object], dict[str, object]]:
                raise CheckpointDeferredLowCommit(
                    available_commit_bytes=1, required_commit_bytes=2,
                    streaming_peak_bytes=1, reserve_bytes=1,
                )

            state: dict[str, int] = {"count": 0}
            with self.assertRaisesRegex(RuntimeError, "uncheckpointed_step_distance"):
                run_vertical_slice._publish_checkpoint_with_low_commit_deferral(
                    checkpoint_parent=checkpoint_parent, config_path=config_path, global_step=50,
                    last_checkpointed_step=0, deferral_state=state, publish=publish,
                    telemetry_path=None, telemetry_run_id=None, policy_path=policy_path,
                )

    def test_publish_checkpoint_with_low_commit_deferral_publishes_normally_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            config_path, policy_path = self._low_commit_deferral_config(directory, max_deferrals=1, max_distance=10)
            checkpoint_parent = directory / "checkpoints"
            published = ({"checkpoint": "ok"}, {"receipt": "ok"})

            def publish() -> tuple[dict[str, object], dict[str, object]]:
                return published

            state: dict[str, int] = {"count": 0}
            result = run_vertical_slice._publish_checkpoint_with_low_commit_deferral(
                checkpoint_parent=checkpoint_parent, config_path=config_path, global_step=3,
                last_checkpointed_step=0, deferral_state=state, publish=publish,
                telemetry_path=None, telemetry_run_id=None, policy_path=policy_path,
            )
            self.assertEqual(result, ({
                "checkpoint": "ok",
                "retention_accounting": {
                    "schema_version": "ember-checkpoint-retention-accounting-v1",
                    "live_budget_bytes": 1024**3,
                    "live_charged_bytes": 0,
                    "quarantine_budget_bytes": 1024**3,
                    "quarantine_charged_bytes": 0,
                },
            }, published[1]))
            self.assertEqual(state["count"], 0)
            self.assertFalse((checkpoint_parent / ".checkpoint-deferrals").exists())

if __name__ == "__main__":
    unittest.main()
