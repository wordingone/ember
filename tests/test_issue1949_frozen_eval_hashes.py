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
SCRIPT = ROOT / "scripts" / "issue1949_frozen_eval_hashes.py"
SPEC = importlib.util.spec_from_file_location("issue1949_frozen_eval_hashes", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FrozenEvalHashesTests(unittest.TestCase):
    def test_committed_file_is_exact_deterministic_derivation(self) -> None:
        expected = MODULE.canonical_json(MODULE.derive(ROOT)) + b"\n"
        self.assertEqual((ROOT / MODULE.OUTPUT).read_bytes(), expected)
        self.assertEqual(MODULE.main(["--repo-root", str(ROOT), "--verify"]), 0)

    def test_absent_committed_file_exercises_the_fail_closed_validator_path(self) -> None:
        consumer_path = (
            ROOT / "runtime" / "ember-lab" / "scripts" / "issue1949_a_clean_consumer.py"
        )
        consumer_spec = importlib.util.spec_from_file_location("issue1949_consumer_frozen_test", consumer_path)
        assert consumer_spec is not None and consumer_spec.loader is not None
        consumer = importlib.util.module_from_spec(consumer_spec)
        consumer_spec.loader.exec_module(consumer)
        text_lab = consumer._load_module(ROOT, "text_lab_corpus")
        with tempfile.TemporaryDirectory() as directory:
            artifact_root = Path(directory)
            external_root = artifact_root / "external-authority"
            custody_root = artifact_root / "external-custody"
            consumer._mint_all_local_external_authority(
                ROOT, external_root, custody_root,
            )
            original = text_lab._FROZEN_EVAL_HASHES_PATH
            text_lab._FROZEN_EVAL_HASHES_PATH = (
                "data/ember-restart-3b/absent-frozen-eval-hashes.json"
            )
            try:
                with self.assertRaisesRegex(
                    ValueError,
                    "frozen eval hash registry is required for VERIFIED and is absent",
                ):
                    text_lab.validate_authority_index(
                        ROOT,
                        external_authority_root=external_root,
                        receipt_custody_root=custody_root,
                    )
            finally:
                text_lab._FROZEN_EVAL_HASHES_PATH = original

    def test_derivation_refuses_a_registry_without_content_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / MODULE.REGISTRY
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "schema_version": "ember-protected-eval-registry-v2",
                "protected": [{"protected_identifiers": []}],
            }))
            with self.assertRaisesRegex(ValueError, "PROTECTED_EVAL_CONTENT_HASHES_REFUSED"):
                MODULE.derive(root)


if __name__ == "__main__":
    unittest.main()
