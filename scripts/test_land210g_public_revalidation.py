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
SCRIPT = ROOT / "scripts" / "land210g_public_revalidation.py"
HISTORICAL = (
    ROOT
    / "receipts"
    / "ember-c-scale"
    / "land210g-experiment-runners-receipt.json"
)
SUBJECT = "e8ca7191fd5ac29594868894ced6e5b5efafa9f8"


def load_revalidator():
    if not SCRIPT.is_file():
        raise AssertionError("production land210g revalidator is missing")
    spec = importlib.util.spec_from_file_location("land210g_revalidation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Land210gPublicRevalidationTests(unittest.TestCase):
    def test_exact_public_history_revalidates_and_corrects_exclusion_count(self) -> None:
        revalidation = load_revalidator()
        receipt = revalidation.build_receipt(
            ROOT,
            HISTORICAL,
            subject_commit=SUBJECT,
            timestamp="2026-07-29T12:20:00Z",
        )
        result = receipt["public_lineage_revalidation"]
        self.assertEqual(result["historical_landed_file_count"], 26)
        self.assertEqual(result["historical_exclusion_count"], 8)
        self.assertEqual(result["historical_candidate_count"], 34)
        self.assertTrue(result["recorded_verdict_exclusion_count_incorrect"])
        self.assertEqual(result["direct_landing_blob_matches"], 24)
        self.assertEqual(result["historical_landing_hashes_not_rehashed"], 2)
        self.assertEqual(result["subject_tracked_candidate_count"], 34)
        self.assertEqual(result["subject_original_bytes_unchanged"], 24)
        self.assertEqual(
            [row["path"] for row in result["traceable_later_changes"]],
            [
                "scripts/conv_c03_muon_ns3_live.py",
                "scripts/ember_cbase_mixture.py",
            ],
        )
        self.assertEqual(
            receipt["verdict"],
            "HISTORICAL_24_BYTES_DIRECTLY_VERIFIED_8_EXCLUSIONS_CORRECTED_ALL_34_TRACKED",
        )
        boundary = receipt["claim_boundary"]
        self.assertFalse(boundary["historical_runtime_checks_replayed"])
        self.assertFalse(boundary["preexisting_runtime_defects_cured"])
        self.assertFalse(boundary["training_claim"])
        self.assertFalse(boundary["model_capability_claim"])

    def test_historical_structure_rejects_count_or_path_tamper(self) -> None:
        revalidation = load_revalidator()
        historical = revalidation.load_json(HISTORICAL)

        wrong_count = copy.deepcopy(historical)
        wrong_count["candidates_total"] = 33
        with self.assertRaisesRegex(ValueError, "candidate arithmetic"):
            revalidation.validate_historical_structure(wrong_count)

        duplicate = copy.deepcopy(historical)
        duplicate["excluded_forward_dependency_on_later_families"][0]["path"] = (
            duplicate["files"][0]["path"]
        )
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
                    timestamp="2026-07-29T12:20:00Z",
                )

    def test_subject_commit_drift_is_rejected_before_lineage_credit(self) -> None:
        revalidation = load_revalidator()
        with self.assertRaisesRegex(
            ValueError, "subject commit is not the reviewed public base"
        ):
            revalidation.build_receipt(
                ROOT,
                HISTORICAL,
                subject_commit="0" * 40,
                timestamp="2026-07-29T12:20:00Z",
            )

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
