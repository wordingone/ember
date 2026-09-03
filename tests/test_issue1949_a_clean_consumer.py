# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import inspect
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "runtime" / "ember-lab" / "scripts" / "issue1949_a_clean_consumer.py"
SPEC = importlib.util.spec_from_file_location("issue1949_a_clean_consumer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_data(root: Path) -> Path:
    path = root / "deterministic-data.json"
    builder = MODULE._load_module(ROOT, "build_owned_curriculum")
    payload = {
        "schema_version": "ember-owned-pretraining-shard-v1",
        "generator": "src/ember/infrastructure/tools/ember-restart-3b/build_owned_curriculum.py",
        "records": builder.records(2),
    }
    path.write_bytes(MODULE.canonical_json(payload) + b"\n")
    return path


class ACleanConsumerTests(unittest.TestCase):
    def test_tool_root_prefers_canonical_then_accepts_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "tools" / "ember-restart-3b"
            legacy.mkdir(parents=True)
            (legacy / "build_owned_curriculum.py").touch()
            self.assertEqual(MODULE._tool_root(root), legacy)
            canonical = root / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"
            canonical.mkdir(parents=True)
            (canonical / "build_owned_curriculum.py").touch()
            self.assertEqual(MODULE._tool_root(root), canonical)

    def test_tool_root_refuses_when_both_locations_are_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "PRODUCTION_TOOL_ROOT_ABSENT:canonical-and-legacy"):
                MODULE._tool_root(Path(directory))

    def test_command_contract_is_exact(self) -> None:
        self.assertEqual(MODULE.COMMAND_EXITS, {
            "direct": 0,
            "lab": 0,
            "external-present": 0,
            "external-absent": 3,
            "topology": 0,
        })

    def test_real_chain_calls_production_training_evaluation_and_runtime(self) -> None:
        source = inspect.getsource(MODULE._run_real_model_chain)
        self.assertIn("run_pretraining_segment", source)
        self.assertIn("evaluate_teacher_forced", source)
        self.assertIn("greedy_generate", source)

    def test_training_selection_requires_two_steps_and_topology_covers_all_experts(self) -> None:
        rows = [{"active_expert": expert} for expert in ("vision", "audio", "reasoning", "tool")]
        self.assertEqual(len(MODULE._select_training_records(rows, topology=False)), 2)
        selected = MODULE._select_training_records(rows, topology=True)
        self.assertEqual(
            {row["active_expert"] for row in selected},
            {"vision", "audio", "reasoning", "tool"},
        )
        with self.assertRaisesRegex(ValueError, "TRAINING_RECORDS_INSUFFICIENT"):
            MODULE._select_training_records(rows[:1], topology=False)

    def test_receipt_path_is_below_artifact_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(
                MODULE.receipt_path(root, "direct"),
                root / "issue1949-a-clean-consumer-direct.json",
            )

    def test_receipt_is_canonical_self_hashed_and_reopened(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = MODULE.publish_receipt(root, "direct", {"result": "PASS"})
            path = MODULE.receipt_path(root, "direct")
            self.assertEqual(path.read_bytes(), MODULE.canonical_json(receipt) + b"\n")
            self.assertEqual(MODULE.reopen_receipt(path), receipt)

    def test_receipt_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            MODULE.publish_receipt(root, "direct", {"result": "PASS"})
            with self.assertRaises(FileExistsError):
                MODULE.publish_receipt(root, "direct", {"result": "PASS"})

    def test_receipt_reopen_refuses_noncanonical_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_text('{"result": "PASS"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "RECEIPT_RAW_REFUSED"):
                MODULE.reopen_receipt(path)

    def test_receipt_reopen_refuses_bad_self_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_bytes(MODULE.canonical_json({"result": "PASS", "self_sha256": "0" * 64}) + b"\n")
            with self.assertRaisesRegex(ValueError, "RECEIPT_SELF_REFUSED"):
                MODULE.reopen_receipt(path)

    def test_external_absent_maps_only_exact_root_absence(self) -> None:
        exact = ValueError("external authority root is absent")
        path = ValueError("external authority path is absent")
        other = ValueError("authority bytes do not match the bound hash")
        self.assertEqual(MODULE.external_absent_exit(exact), 3)
        self.assertEqual(MODULE.external_absent_exit(path), 3)
        with self.assertRaisesRegex(ValueError, "bound hash"):
            MODULE.external_absent_exit(other)

    def test_lab_timing_constants_derive_from_the_producer_contract_cap(self) -> None:
        self.assertEqual(MODULE.LAB_PRODUCER_CONTRACT_CAP_MS, 60_000)
        self.assertEqual(
            MODULE.LAB_DISPATCH_TTL_MS,
            10 * MODULE.LAB_PRODUCER_CONTRACT_CAP_MS,
        )

    def test_main_direct_returns_zero_and_writes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = write_data(root)
            self.assertEqual(MODULE.main(["direct", "--repo-root", str(ROOT), "--artifact-root", str(root), "--data-path", str(data)]), 0)
            self.assertEqual(MODULE.reopen_receipt(MODULE.receipt_path(root, "direct"))["result"], "PASS")

    def test_main_direct_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = write_data(root)
            argv = ["direct", "--repo-root", str(ROOT), "--artifact-root", str(root), "--data-path", str(data)]
            self.assertEqual(MODULE.main(argv), 0)
            self.assertEqual(MODULE.main(argv), 2)

    def test_main_lab_returns_zero_and_writes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = write_data(root)
            self.assertEqual(MODULE.main(["lab", "--repo-root", str(ROOT), "--artifact-root", str(root), "--data-path", str(data), "--cargo", "cargo"]), 0)
            self.assertEqual(MODULE.reopen_receipt(MODULE.receipt_path(root, "lab"))["result"], "PASS")

    def test_main_external_present_mints_verified_all_local_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            custody = root / "external-custody"
            self.assertEqual(MODULE.main(["external-present", "--repo-root", str(ROOT), "--artifact-root", str(root), "--receipt-custody-root", str(custody)]), 0)
            receipt = MODULE.reopen_receipt(MODULE.receipt_path(root, "external-present"))
            self.assertEqual(receipt["result"], "PASS")
            self.assertEqual(receipt["validator"]["result"], "VERIFIED")
            self.assertEqual(receipt["minted_authority"]["source_count"], 44)
            self.assertIn("NOT_CANONICAL_V4", receipt["claim_boundary"])

    def test_main_external_absent_returns_three_and_writes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            absent = root / "external-custody-absent"
            self.assertEqual(MODULE.main(["external-absent", "--repo-root", str(ROOT), "--artifact-root", str(root), "--receipt-custody-root", str(absent)]), 3)
            receipt = MODULE.reopen_receipt(MODULE.receipt_path(root, "external-absent"))
            self.assertEqual(receipt["result"], "EXPECTED_REFUSAL")
            self.assertEqual(receipt["exit_code"], 3)

    def test_main_unknown_failure_is_not_exit_three(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing-repository"
            root = Path(directory) / "artifacts"
            absent = root / "external-custody-absent"
            self.assertEqual(MODULE.main(["external-absent", "--repo-root", str(missing), "--artifact-root", str(root), "--receipt-custody-root", str(absent)]), 2)

    def test_every_success_receipt_binds_production_modules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = write_data(root)
            self.assertEqual(MODULE.main(["direct", "--repo-root", str(ROOT), "--artifact-root", str(root), "--data-path", str(data)]), 0)
            receipt = MODULE.reopen_receipt(MODULE.receipt_path(root, "direct"))
            self.assertTrue(receipt["production_modules"])
            self.assertTrue(all(len(row["sha256"]) == 64 for row in receipt["production_modules"]))

    def test_receipt_claim_boundary_forbids_capability_credit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = write_data(root)
            self.assertEqual(MODULE.main(["direct", "--repo-root", str(ROOT), "--artifact-root", str(root), "--data-path", str(data)]), 0)
            receipt = MODULE.reopen_receipt(MODULE.receipt_path(root, "direct"))
            self.assertIn("NO_CORPUS_CAPABILITY", receipt["claim_boundary"])


if __name__ == "__main__":
    unittest.main()
