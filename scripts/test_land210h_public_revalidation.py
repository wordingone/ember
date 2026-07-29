# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "land210h_public_revalidation.py"
HISTORICAL = (
    ROOT
    / "receipts"
    / "ember-c-scale"
    / "land210h-ops-tools-receipt.json"
)
SUBJECT = "801cd32723734697eab58e19b7a22aef7b28f0a8"


def load_revalidator():
    if not SCRIPT.is_file():
        raise AssertionError("production land210h revalidator is missing")
    spec = importlib.util.spec_from_file_location("land210h_revalidation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Land210hPublicRevalidationTests(unittest.TestCase):
    def test_exact_public_history_and_current_tokenizer_revalidate(self) -> None:
        revalidation = load_revalidator()
        receipt = revalidation.build_receipt(
            ROOT,
            HISTORICAL,
            subject_commit=SUBJECT,
            timestamp="2026-07-29T13:00:00Z",
        )
        result = receipt["public_lineage_revalidation"]
        self.assertEqual(result["historical_candidate_count"], 5)
        self.assertEqual(result["direct_landing_blob_matches"], 5)
        self.assertEqual(result["subject_original_bytes_unchanged"], 5)
        self.assertEqual(result["import_closure_path_count"], 4)
        self.assertEqual(
            result["current_tokenizer"]["sha256"],
            "2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97",
        )
        self.assertEqual(result["current_tokenizer"]["tokenizers_version"], "0.22.2")
        self.assertEqual(result["current_tokenizer"]["vocab_size"], 32000)
        self.assertTrue(result["current_tokenizer"]["load_pass"])
        self.assertTrue(result["historical_pipeline_execution_policy"]["denied"])
        self.assertEqual(
            receipt["verdict"],
            "HISTORICAL_5_LANDING_BYTES_VERIFIED_CURRENT_TOKENIZER_LOADS_"
            "HISTORICAL_PIPELINE_EXECUTION_DENIED",
        )
        boundary = receipt["claim_boundary"]
        self.assertTrue(boundary["five_historical_landing_hashes_revalidated"])
        self.assertTrue(boundary["current_tokenizer_load_replayed"])
        self.assertFalse(boundary["historical_full_pipeline_replayed"])
        self.assertFalse(boundary["historical_stage_source_revalidated"])
        self.assertFalse(boundary["issue_210_whole_closure_revalidated"])
        self.assertFalse(boundary["training_claim"])
        self.assertFalse(boundary["model_capability_claim"])

    def test_historical_structure_rejects_count_or_path_tamper(self) -> None:
        revalidation = load_revalidator()
        historical = revalidation.load_json(HISTORICAL)

        wrong_count = copy.deepcopy(historical)
        wrong_count["candidates_total"] = 4
        with self.assertRaisesRegex(ValueError, "candidate arithmetic"):
            revalidation.validate_historical_structure(wrong_count)

        duplicate = copy.deepcopy(historical)
        duplicate["files"][1]["path"] = duplicate["files"][0]["path"]
        with self.assertRaisesRegex(ValueError, "candidate paths must be unique"):
            revalidation.validate_historical_structure(duplicate)

    def test_landing_blob_substitution_is_rejected(self) -> None:
        revalidation = load_revalidator()
        historical = revalidation.load_json(HISTORICAL)

        def substituted_oid(commit: str, path: str) -> str:
            if (
                commit == revalidation.LANDING_COMMIT
                and path == historical["files"][0]["path"]
            ):
                return "0" * 40
            return revalidation.git_blob_oid(ROOT, commit, path)

        with self.assertRaisesRegex(ValueError, "landing tree/object mismatch"):
            revalidation.validate_landing_blobs(
                historical,
                substituted_oid,
                lambda commit, path: revalidation.git_blob(ROOT, commit, path),
            )

    def test_exact_historical_receipt_hash_is_required(self) -> None:
        revalidation = load_revalidator()
        with tempfile.TemporaryDirectory() as td:
            copied = Path(td) / HISTORICAL.name
            copied.write_bytes(HISTORICAL.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "historical receipt SHA-256"):
                revalidation.build_receipt(
                    ROOT,
                    copied,
                    subject_commit=SUBJECT,
                    timestamp="2026-07-29T13:00:00Z",
                )

    def test_subject_commit_and_tokenizer_byte_drift_are_rejected(self) -> None:
        revalidation = load_revalidator()
        with self.assertRaisesRegex(
            ValueError, "subject commit is not the reviewed public base"
        ):
            revalidation.build_receipt(
                ROOT,
                HISTORICAL,
                subject_commit="0" * 40,
                timestamp="2026-07-29T13:00:00Z",
            )

        with self.assertRaisesRegex(ValueError, "current tokenizer SHA-256"):
            revalidation.validate_current_tokenizer(b"{}")

    def test_publish_is_exclusive_lf_only_and_confined(self) -> None:
        revalidation = load_revalidator()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target_dir = root / "receipts" / "ember-c-scale"
            target_dir.mkdir(parents=True)
            target = target_dir / "successor.json"
            revalidation.publish({"ticket": "x"}, target, root)
            self.assertNotIn(b"\r\n", target.read_bytes())
            with self.assertRaises(FileExistsError):
                revalidation.publish({"ticket": "x"}, target, root)
            with self.assertRaisesRegex(ValueError, "output must be under"):
                revalidation.publish({"ticket": "x"}, root / "outside.json", root)


if __name__ == "__main__":
    unittest.main()
