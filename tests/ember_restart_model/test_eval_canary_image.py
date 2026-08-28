# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import torch


ROOT = Path(__file__).resolve().parents[2]
CANARY = ROOT / "tools" / "ember-restart-3b" / "eval_canary_image.py"
FIXTURE = ROOT / "tests" / "ember_restart_model" / "fixtures" / "eval-canary-image-v1"
DISPOSITIONS = FIXTURE / "mechanics-only-dispositions.json"


class EvalCanaryImageContractTests(unittest.TestCase):
    """Break caught: a negative can be skipped, renamed, or accepted by the real CLI."""

    def test_full_negative_matrix_refuses_every_named_attack(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(CANARY),
                "--fixture-root",
                str(FIXTURE),
                "--run-negative-matrix",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        expected = {
            "LOADER_RECEIPT_MISSING",
            "CHECKPOINT_TENSOR_IDENTITY_MISMATCH",
            "CHECKPOINT_FILE_IDENTITY_MISMATCH_IDENTICAL_TENSORS",
            "CALLER_PREDICTION_FORBIDDEN:caller_supplied",
            "CALLER_PREDICTION_FORBIDDEN:cached",
            "CALLER_PREDICTION_FORBIDDEN:copied",
            "GOLD_SUBSTITUTION_FORBIDDEN",
            "IMAGE_PAYLOAD_MISSING",
            "IMAGE_PAYLOAD_IDENTITY_MISMATCH",
            "ITEM_SET_INCOMPLETE",
            "ITEM_ORDER_MISMATCH",
            "DUPLICATE_ITEM_ID",
            "DECLARED_DELETION_PATH_ACTIVE",
            "IMAGE_PATH_DISABLED",
            "ZERO_ITEMS",
            "SKIPPED_ALL",
        }
        observed = {
            row["row_class"] + (f":{row['subcase']}" if row.get("subcase") else "")
            for row in report["rows"]
            if row["result"] == "REFUSED"
        }
        self.assertEqual(observed, expected)
        for row in report["rows"]:
            self.assertIsNotNone(row.get("control_positive_sha256"), row)
            self.assertIsNotNone(row.get("mutated_input_sha256"), row)
            self.assertIsNotNone(row.get("observed_error"), row)
        control_hashes = {row["control_positive_sha256"] for row in report["rows"]}
        self.assertEqual(len(control_hashes), 1)
        self.assertEqual(len({row["mutated_input_sha256"] for row in report["rows"]}), len(expected))
        for row in report["rows"]:
            self.assertEqual(row["observed_error"], row["row_class"])
        self.assertEqual(report["result"], "PASS")

    def test_fixture_builder_is_byte_deterministic_and_scope_bound(self) -> None:
        """Break caught: generation drifts, omits an asset, or can claim evaluation authority."""
        builder = FIXTURE / "build_fixture.py"
        with tempfile.TemporaryDirectory() as left_dir, tempfile.TemporaryDirectory() as right_dir:
            outputs = []
            for output_dir in (left_dir, right_dir):
                completed = subprocess.run(
                    [sys.executable, str(builder), "--output-dir", output_dir],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                outputs.append(Path(output_dir))
            left_files = sorted(path.relative_to(outputs[0]) for path in outputs[0].rglob("*") if path.is_file())
            right_files = sorted(path.relative_to(outputs[1]) for path in outputs[1].rglob("*") if path.is_file())
            self.assertEqual(left_files, right_files)
            self.assertEqual(left_files, [Path("checkpoint.pt"), Path("config.json"), *[Path(f"image-{index:02d}.ppm") for index in range(8)], Path("manifest.json")])
            for relative in left_files:
                self.assertEqual((outputs[0] / relative).read_bytes(), (outputs[1] / relative).read_bytes(), relative)
            manifest = json.loads((outputs[0] / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["authority_scope"], "MECHANICS_CANARY_ONLY")
            self.assertEqual(manifest["canary_id"], "EVAL-CANARY-IMAGE-V1")
            self.assertEqual(len(manifest["items"]), 8)
            self.assertEqual(manifest["tokenizer"]["vocab_size"], manifest["config"]["vocab_size"])

    def test_tensor_identity_hashing_does_not_require_numpy(self) -> None:
        """Break caught: the pinned torch/tokenizers runtime implicitly needs NumPy."""

        def load_module(name: str, path: Path):
            spec = importlib.util.spec_from_file_location(name, path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

        builder = load_module("issue1948_fixture_builder", FIXTURE / "build_fixture.py")
        evaluator = load_module("issue1948_evaluator", CANARY)
        value = torch.tensor([[1.0, -2.0], [3.5, 0.0]], dtype=torch.float32)
        with mock.patch.object(torch.Tensor, "numpy", side_effect=RuntimeError("NumPy forbidden")):
            self.assertEqual(
                builder.canonical_tensor_hash(value),
                evaluator.canonical_tensor_hash(value),
            )

    def test_positive_run_binds_real_image_path_and_recomputable_scores(self) -> None:
        """Break caught: predictions bypass checkpoint, tokenizer, image adapter, or per-item scoring."""
        completed = subprocess.run(
            [sys.executable, str(CANARY), "--fixture-root", str(FIXTURE), "--run-positive"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        receipt = json.loads(completed.stdout)
        self.assertEqual(receipt["result"], "PASS")
        self.assertEqual(receipt["authority_scope"], "MECHANICS_CANARY_ONLY")
        self.assertEqual(receipt["canary_id"], "EVAL-CANARY-IMAGE-V1")
        self.assertEqual(receipt["loader"]["adapter_class"], "RawPatchProjector")
        self.assertEqual(receipt["loader"]["model_class"], "UnifiedDecoder")
        self.assertTrue(receipt["loader"]["checkpoint_file_identity_match"])
        self.assertTrue(receipt["loader"]["checkpoint_tensor_identity_match"])
        self.assertEqual(receipt["loader"]["checkpoint_sha256"], json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))["checkpoint"]["sha256"])
        self.assertEqual(receipt["loader"]["config_sha256"], json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))["config"]["sha256"])
        self.assertEqual(receipt["loader"]["fixture_seed"], 1948)
        self.assertEqual(receipt["loader"]["decoded_image_shapes"], [[1, 1, 48, 48, 3]] * 8)
        self.assertEqual(receipt["loader"]["exclusions"], ["capability_credit", "model_admission", "milestone_credit"])
        self.assertEqual(
            [row["item_id"] for row in receipt["items"]],
            [f"canary-image-{index:02d}" for index in range(8)],
        )
        self.assertEqual({row["pathway_event"] for row in receipt["items"]}, {"real_raw_image_adapter"})
        self.assertEqual(len({row["raw_logits_sha256"] for row in receipt["items"]}), 8)
        correct = sum(int(row["prediction"] == row["gold_label"]) for row in receipt["items"])
        self.assertEqual(receipt["score"], {"correct": correct, "item_count": 8, "accuracy": correct / 8})

    def test_existing_image_forward_fixtures_are_explicitly_mechanics_only(self) -> None:
        """Break caught: an old finite-forward fixture is silently promoted to evaluation evidence."""
        disposition = json.loads(DISPOSITIONS.read_text(encoding="utf-8"))
        expected_paths = {
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "tests" / "ember_restart_model").glob("test_*.py")
            if path.resolve() != Path(__file__).resolve()
            and (
                "image_patches" in path.read_text(encoding="utf-8")
                or "image_projector" in path.read_text(encoding="utf-8")
            )
        }
        self.assertEqual({row["path"] for row in disposition["rows"]}, expected_paths)
        self.assertEqual({row["disposition"] for row in disposition["rows"]}, {"MECHANICS_ONLY"})
        self.assertEqual(disposition["authority_scope"], "NO_EVALUATION_OR_CAPABILITY_CREDIT")

    def test_terminal_suite_receipt_is_self_hashed_and_dependency_bound(self) -> None:
        """Break caught: CI can pass without one immutable checkpoint-to-score suite receipt."""
        with tempfile.TemporaryDirectory() as output_dir:
            receipt_path = Path(output_dir) / "terminal.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(CANARY),
                    "--fixture-root",
                    str(FIXTURE),
                    "--run-suite",
                    "--torch-wheel-filename",
                    "torch-2.10.0+cpu-test.whl",
                    "--torch-wheel-sha256",
                    "a" * 64,
                    "--terminal-receipt",
                    str(receipt_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=45,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self_hash = receipt.pop("self_sha256")
            canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self.assertEqual(self_hash, hashlib.sha256(canonical).hexdigest())
            self.assertEqual(receipt["result"], "PASS")
            self.assertEqual(receipt["positive"]["result"], "PASS")
            self.assertEqual(receipt["negative_matrix"]["result"], "PASS")
            self.assertEqual(receipt["dependencies"]["torch_wheel_sha256"], "a" * 64)
            self.assertEqual(receipt["positive_sha256"], receipt["negative_control_positive_sha256"])
            self.assertEqual(
                set(receipt["source_hashes"]),
                {"build_fixture.py", "checkpoint.pt", "config.json", "eval_canary_image.py", "mechanics-only-dispositions.json", "model.py", "tokenizer.json"},
            )
            self.assertGreater(receipt["measured_wall_seconds"], 0)

if __name__ == "__main__":
    unittest.main()
