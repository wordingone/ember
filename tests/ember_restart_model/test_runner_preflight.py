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
from verify_capability_record import expected_receipt


class RunnerPreflightTests(unittest.TestCase):
    def test_specialist_loader_executes_bound_verifier_and_returns_one_route(self) -> None:
        def write_json(path: Path, payload: object) -> str:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            return hashlib.sha256(path.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tokenizer = root / "tokenizer.json"
            tokenizer_hash = write_json(tokenizer, {"model": {"vocab": {str(index): index for index in range(8, 32)}}})
            source = root / "source.json"
            source_hash = write_json(source, {"schema_version": "ember-owned-source-v1", "capability": "reasoning", "model_mediated": False, "borrowed_labels": False})
            record = {"schema_version": "ember-owned-bootstrap-batch-v1", "active_expert": "reasoning", "token_ids": [8, 9, 10], "target_ids": [9, 10, 11], "image_coordinates": [], "multimodal_spans": [], "capability_evidence": {"reasoning": {"operands": [1, 2], "target": 3, "trace": [1, 2, 3]}}}
            record["capability_receipt"] = expected_receipt(record)
            records = root / "records.json"
            records_hash = write_json(records, {"schema_version": "ember-owned-semantic-records-v1", "records": [record]})
            manifest = root / "manifest.json"
            write_json(manifest, {"schema_version": "ember-owned-training-data-v1", "capability": "reasoning", "data_class": "SEMANTIC_PRETRAINING", "tokenizer_sha256": tokenizer_hash, "model_mediated": False, "borrowed_labels": False, "record_count": 1, "token_count": 3, "source_manifest": {"path": "source.json", "sha256": source_hash}, "records_artifact": {"path": "records.json", "sha256": records_hash}})
            records_out, verification = run_vertical_slice.load_verified_specialist_records(root=root, data_manifest=manifest, tokenizer_path=tokenizer, capability="reasoning")
        self.assertEqual(records_out, [record])
        self.assertEqual(verification["result"], "VERIFIED")
        self.assertEqual(verification["capability"], "reasoning")
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

    def test_semantic_cli_dispatches_only_manifest_bound_stream_inputs(self) -> None:
        with patch.object(run_vertical_slice, "run_semantic", return_value={"steps": 1}) as semantic:
            with patch.object(
                sys,
                "argv",
                [
                    "run_vertical_slice.py", "semantic", "--seed", "83", "--artifact-root", "B:/ember-artifacts",
                    "--receipt", "semantic/receipt.json", "--shards-root", "semantic/shards",
                    "--tokenizer", "semantic/tokenizer.json", "--steps", "1", "--sequence-length", "1024",
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
            resume_checkpoint=None,
        )

    def test_specialist_cli_dispatches_one_verified_route(self) -> None:
        with patch.object(run_vertical_slice, "run_specialist", return_value={"steps": 1}) as specialist:
            with patch.object(sys, "argv", ["run_vertical_slice.py", "specialist", "--seed", "84", "--artifact-root", "B:/ember-artifacts", "--data-manifest", "data/vision.json", "--tokenizer", "tokenizer.json", "--capability", "image"]):
                run_vertical_slice.main()
        specialist.assert_called_once_with(seed=84, artifact_root=Path("B:/ember-artifacts"), data_manifest=Path("data/vision.json"), tokenizer_path=Path("tokenizer.json"), capability="image", resume_checkpoint=None)
    def test_runner_file_exposes_the_semantic_cli_entrypoint(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "ember-restart-3b" / "run_vertical_slice.py"), "semantic", "--help"],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--receipt", completed.stdout)

    def test_runner_has_one_retention_implementation(self) -> None:
        self.assertEqual(inspect.getsource(run_vertical_slice).count("def _retain_after_success("), 1)
    def test_bf16_contract_disables_unsupported_percentile_clipping(self) -> None:
        contract = run_vertical_slice.load_optimizer_contract(ROOT / "configs" / "ember-restart-3b.json")
        self.assertEqual(contract["hyperparameters"]["percentile_clipping"], 100)
if __name__ == "__main__":
    unittest.main()