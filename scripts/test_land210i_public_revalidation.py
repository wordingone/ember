# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "land210i_public_revalidation.py"
HISTORICAL = (
    ROOT
    / "receipts"
    / "ember-c-scale"
    / "land210i-harness-entry-receipt.json"
)
SUBJECT = "090d92b72e131df65048e62553c253b694f13d00"


def load_revalidator():
    if not SCRIPT.is_file():
        raise AssertionError("production land210i revalidator is missing")
    spec = importlib.util.spec_from_file_location("land210i_revalidation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Land210iPublicRevalidationTests(unittest.TestCase):
    def test_harness_selftest_exercises_real_session_selection_and_passes(self) -> None:
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-B", "scripts/ember_avir_harness.py", "--selftest"],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("T15/find_session_jsonl/session_id pinning", result.stdout)
        self.assertIn("T15/find_session_jsonl/mtime fallback", result.stdout)
        self.assertIn("Result: 38/38 passed", result.stdout)

    def test_exact_public_history_and_current_cpu_replay(self) -> None:
        revalidation = load_revalidator()
        receipt = revalidation.build_receipt(
            ROOT,
            HISTORICAL,
            subject_commit=SUBJECT,
            timestamp="2026-07-29T14:00:00Z",
        )
        lineage = receipt["public_lineage_revalidation"]
        self.assertEqual(lineage["historical_candidate_count"], 6)
        self.assertEqual(lineage["subject_landing_blob_matches"], 6)
        self.assertEqual(lineage["current_unchanged_landing_files"], 5)
        self.assertEqual(lineage["current_repaired_files"], 1)
        replay = receipt["current_cpu_replay"]
        self.assertEqual(replay["harness_selftest"], "38/38 PASS")
        self.assertEqual(replay["tasks_train"], 24)
        self.assertEqual(replay["tasks_heldout"], 20)
        self.assertEqual(replay["tasks_total"], 44)
        self.assertTrue(replay["all_pass"])
        boundary = receipt["claim_boundary"]
        self.assertTrue(boundary["historical_six_file_landing_revalidated"])
        self.assertTrue(boundary["current_cpu_only_selftests_replayed"])
        self.assertFalse(boundary["external_executable_invoked"])
        self.assertFalse(boundary["owned_model_credit_claim"])
        self.assertFalse(boundary["issue_210_whole_closure_revalidated"])
        self.assertFalse(boundary["issue_700_completion_claim"])

    def test_historical_structure_rejects_count_duplicate_and_bad_companion(self) -> None:
        revalidation = load_revalidator()
        historical = revalidation.load_json(HISTORICAL)

        wrong_count = copy.deepcopy(historical)
        wrong_count["candidates_total"] = 5
        with self.assertRaisesRegex(ValueError, "candidate arithmetic"):
            revalidation.validate_historical_structure(wrong_count)

        duplicate = copy.deepcopy(historical)
        duplicate["files"][1]["path"] = duplicate["files"][0]["path"]
        with self.assertRaisesRegex(ValueError, "candidate paths must be unique"):
            revalidation.validate_historical_structure(duplicate)

        bad_companion = copy.deepcopy(historical)
        bad_companion["companion_data_included"]["files"].pop()
        with self.assertRaisesRegex(ValueError, "companion data"):
            revalidation.validate_historical_structure(bad_companion)

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

    def test_subject_historical_hash_and_current_harness_drift_are_rejected(self) -> None:
        revalidation = load_revalidator()
        with self.assertRaisesRegex(
            ValueError, "subject commit is not the reviewed public base"
        ):
            revalidation.build_receipt(
                ROOT,
                HISTORICAL,
                subject_commit="0" * 40,
                timestamp="2026-07-29T14:00:00Z",
            )
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "ember_avir_harness.py"
            fake.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "current harness SHA-256"):
                revalidation.validate_current_harness(fake)

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
