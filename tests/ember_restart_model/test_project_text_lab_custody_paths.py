# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import copy
import importlib.util
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
MODULE_PATH = (
    ROOT
    / "tools"
    / "ember-restart-3b"
    / "project_text_lab_custody_paths.py"
)

PARTITION_IDS = (
    "candidate-statistics-heldout-1",
    "candidate-training_infrastructure-train-1",
    "candidate-software_engineering-train-0",
    "candidate-software_engineering-train-1",
    "candidate-software_engineering-heldout-0",
    "candidate-software_engineering-heldout-1",
    "candidate-application_worlds-train-0",
    "candidate-application_worlds-train-1",
    "candidate-application_worlds-heldout-1",
)
PDF_IDS = (
    "candidate-physics-heldout-0",
    "candidate-computer_science-train-0",
    "candidate-scientific_method-heldout-0",
)


def load_module():
    sys.path.insert(0, str(MODULE_PATH.parent))
    try:
        spec = importlib.util.spec_from_file_location(
            "project_text_lab_custody_paths",
            MODULE_PATH,
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def projection_fixture(root: pathlib.Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source_id in PARTITION_IDS:
        receipt = root / source_id / "partition-receipt.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_bytes(b"partition\n")
        rows.append(
            {
                "source_id": source_id,
                "content_sha256": source_id.ljust(64, "0")[:64],
                "license_partition_receipt": str(receipt.resolve()),
                "license_partition_sha256": "a" * 64,
                "sentinel": source_id,
            }
        )
    for source_id in PDF_IDS:
        connector = root / source_id / "connector.json"
        transform = root / source_id / "transform.json"
        connector.parent.mkdir(parents=True)
        connector.write_bytes(b"connector\n")
        transform.write_bytes(b"transform\n")
        rows.append(
            {
                "source_id": source_id,
                "content_sha256": source_id.ljust(64, "0")[:64],
                "license_evidence": {
                    "kind": "publisher_terms",
                    "connector_receipt_path": str(connector.resolve()),
                    "connector_receipt_sha256": "b" * 64,
                    "transform_receipt_path": str(transform.resolve()),
                    "transform_receipt_sha256": "c" * 64,
                },
                "sentinel": source_id,
            }
        )
    return rows


class CustodyPathProjectionTests(unittest.TestCase):
    def test_projects_exact_twelve_paths_and_preserves_every_other_row_byte_value(self):
        """Catches path projection changing payload identity or skipping one class member."""
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            custody_root = pathlib.Path(directory) / "corpus"
            rows = projection_fixture(custody_root)
            before = copy.deepcopy(rows)
            projected = module.project_rows(
                rows,
                receipt_custody_root=custody_root,
            )

            self.assertEqual(len(projected), 12)
            for original, result in zip(before, projected, strict=True):
                self.assertEqual(result["source_id"], original["source_id"])
                self.assertEqual(result["content_sha256"], original["content_sha256"])
                self.assertEqual(result["sentinel"], original["sentinel"])
                if result["source_id"] in PARTITION_IDS:
                    self.assertNotIn(":", result["license_partition_receipt"])
                    self.assertNotIn("\\", result["license_partition_receipt"])
                else:
                    evidence = result["license_evidence"]
                    self.assertNotIn(":", evidence["connector_receipt_path"])
                    self.assertNotIn("\\", evidence["connector_receipt_path"])
                    self.assertNotIn(":", evidence["transform_receipt_path"])
                    self.assertNotIn("\\", evidence["transform_receipt_path"])

    def test_refuses_missing_extra_and_outside_projection_class(self):
        """Catches a partial, widened, or cross-root authority-row projection."""
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            custody_root = pathlib.Path(directory) / "corpus"
            rows = projection_fixture(custody_root)
            outside = pathlib.Path(directory) / "outside.json"
            outside.write_bytes(b"outside\n")
            for candidate in (
                rows[:-1],
                rows + [{"source_id": "candidate-extra-train-0"}],
                [
                    {
                        **row,
                        "license_partition_receipt": str(outside.resolve()),
                    }
                    if row["source_id"] == PARTITION_IDS[0]
                    else row
                    for row in rows
                ],
            ):
                with self.subTest(count=len(candidate)), self.assertRaises(ValueError):
                    module.project_rows(
                        candidate,
                        receipt_custody_root=custody_root,
                    )


if __name__ == "__main__":
    unittest.main()
