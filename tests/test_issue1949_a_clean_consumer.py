# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "issue1949_a_clean_consumer.py"
SPEC = importlib.util.spec_from_file_location("issue1949_a_clean_consumer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


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
            "external-present": 4,
            "external-absent": 3,
        })

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

    def test_external_projection_names_are_exact(self) -> None:
        self.assertEqual(set(MODULE.EXTERNAL_ARTIFACTS), {
            "text-lab-source-receipt-bundle-v4.json",
            "owned-text-lab-corpus-v4.json",
            "owned-text-lab-input-identity-v4.json",
            "text-lab-authority-index-v2.json",
        })

    def test_main_direct_returns_zero_and_writes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(MODULE.main(["direct", "--repo-root", str(ROOT), "--artifact-root", str(root)]), 0)
            self.assertEqual(MODULE.reopen_receipt(MODULE.receipt_path(root, "direct"))["result"], "PASS")

    def test_main_direct_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(MODULE.main(["direct", "--repo-root", str(ROOT), "--artifact-root", str(root)]), 0)
            self.assertEqual(MODULE.main(["direct", "--repo-root", str(ROOT), "--artifact-root", str(root)]), 2)

    def test_main_lab_returns_zero_and_writes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(MODULE.main(["lab", "--repo-root", str(ROOT), "--artifact-root", str(root), "--cargo", "cargo"]), 0)
            self.assertEqual(MODULE.reopen_receipt(MODULE.receipt_path(root, "lab"))["result"], "PASS")

    def test_main_external_present_returns_named_four_and_writes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            custody = root / "external-custody"
            self.assertEqual(MODULE.main(["external-present", "--repo-root", str(ROOT), "--artifact-root", str(root), "--receipt-custody-root", str(custody)]), 4)
            receipt = MODULE.reopen_receipt(MODULE.receipt_path(root, "external-present"))
            self.assertEqual(receipt["result"], "REFUSED_EXTERNAL_CUSTODY_INSUFFICIENT")
            self.assertTrue(Path(receipt["producer_receipt"]["path"]).is_file())

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
            self.assertEqual(MODULE.main(["direct", "--repo-root", str(ROOT), "--artifact-root", str(root)]), 0)
            receipt = MODULE.reopen_receipt(MODULE.receipt_path(root, "direct"))
            self.assertTrue(receipt["production_modules"])
            self.assertTrue(all(len(row["sha256"]) == 64 for row in receipt["production_modules"]))

    def test_receipt_claim_boundary_forbids_capability_credit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(MODULE.main(["direct", "--repo-root", str(ROOT), "--artifact-root", str(root)]), 0)
            receipt = MODULE.reopen_receipt(MODULE.receipt_path(root, "direct"))
            self.assertIn("NO_CORPUS_CAPABILITY", receipt["claim_boundary"])


if __name__ == "__main__":
    unittest.main()
