# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Executable semantic-training-data verifier regressions."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "tools" / "ember-restart-3b" / "verify_training_data.py"


def _write_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TrainingDataVerifierTests(unittest.TestCase):
    def test_text_semantic_manifest_is_recomputed_from_bound_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tokenizer = root / "tokenizer.json"
            tokenizer_hash = _write_json(
                tokenizer,
                {"model": {"vocab": {f"token-{index}": index for index in range(8, 32)}}},
            )
            source = root / "sources" / "text.json"
            source_hash = _write_json(
                source,
                {
                    "schema_version": "ember-owned-source-v1",
                    "capability": "text",
                    "model_mediated": False,
                    "borrowed_labels": False,
                },
            )
            records = root / "records" / "text.json"
            records_hash = _write_json(
                records,
                {
                    "schema_version": "ember-owned-semantic-records-v1",
                    "records": [{"token_ids": [8, 9, 10], "target_ids": [9, 10, 11]}],
                },
            )
            data = root / "data" / "text.json"
            _write_json(
                data,
                {
                    "schema_version": "ember-owned-training-data-v1",
                    "capability": "text",
                    "data_class": "SEMANTIC_PRETRAINING",
                    "tokenizer_sha256": tokenizer_hash,
                    "model_mediated": False,
                    "borrowed_labels": False,
                    "record_count": 1,
                    "token_count": 3,
                    "source_manifest": {"path": "sources/text.json", "sha256": source_hash},
                    "records_artifact": {"path": "records/text.json", "sha256": records_hash},
                },
            )
            completed = subprocess.run(
                [sys.executable, "-I", str(VERIFIER), "--data-manifest", str(data), "--tokenizer", str(tokenizer), "--capability", "text"],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        receipt = json.loads(completed.stdout)
        self.assertEqual(receipt["result"], "VERIFIED")
        self.assertEqual(receipt["capability"], "text")
        self.assertEqual(receipt["semantic_checks"], ["token_roundtrip", "source_target_pair"])
        self.assertEqual(receipt["record_count"], 1)
        self.assertEqual(receipt["token_count"], 3)


if __name__ == "__main__":
    unittest.main()

