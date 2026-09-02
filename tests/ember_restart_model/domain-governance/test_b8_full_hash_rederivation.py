# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""B8 discriminating test: the pre-CUDA validator re-derives the full records artifact hash."""

import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "ember-restart-3b"))

import run_vertical_slice


def _artifact(records):
    return json.dumps({"records": records}, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _corpus(tag):
    return [
        {"active_expert": "vision", "scene_split": "train", "token_ids": [1, 2], "row_id": f"{tag}-t0"},
        {"active_expert": "vision", "scene_split": "train", "token_ids": [3, 4], "row_id": f"{tag}-t1"},
        {"active_expert": "vision", "scene_split": "validation", "token_ids": [5], "row_id": f"{tag}-v0"},
        {"active_expert": "vision", "scene_split": "test", "token_ids": [6], "row_id": f"{tag}-x0"},
    ]


class TestB8FullHashRederivation(unittest.TestCase):
    def _bundle(self, records, declared_sha256):
        train, selection = run_vertical_slice.select_verified_scene_split(
            records, capability="image", scene_split="train",
            full_records_artifact_sha256=declared_sha256,
        )
        _selected, execution_slice = run_vertical_slice.bind_specialist_execution_slice(
            train, start_record=0, max_records=len(train),
            scene_split_record_count=len(train),
        )
        verification = {"records_artifact_sha256": declared_sha256}
        return train, selection, execution_slice, verification

    def test_a_genuine_corpus_admitted(self) -> None:
        records = _corpus("genuine")
        artifact_bytes = _artifact(records)
        true_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
        train, selection, execution_slice, verification = self._bundle(records, true_sha256)
        run_vertical_slice.validate_image_scene_split_execution(
            train, verification=verification, selection=selection,
            execution_slice=execution_slice, full_records_artifact_bytes=artifact_bytes,
        )
        print("A: genuine corpus ADMITTED")

    def test_b_forged_corpus_with_true_hash_pasted_rejected(self) -> None:
        genuine_bytes = _artifact(_corpus("genuine"))
        true_sha256 = hashlib.sha256(genuine_bytes).hexdigest()
        forged = _corpus("forged")  # internally self-consistent, NOT a subset of the published corpus
        forged_bytes = _artifact(forged)
        train, selection, execution_slice, verification = self._bundle(forged, true_sha256)
        # Forgery shape 1: attacker supplies its own bytes; declared hash is the TRUE published one.
        with self.assertRaisesRegex(ValueError, "full records artifact hash mismatch"):
            run_vertical_slice.validate_image_scene_split_execution(
                train, verification=verification, selection=selection,
                execution_slice=execution_slice, full_records_artifact_bytes=forged_bytes,
            )
        # Forgery shape 2: attacker supplies the GENUINE bytes but forged train rows.
        with self.assertRaisesRegex(ValueError, "not the train subset"):
            run_vertical_slice.validate_image_scene_split_execution(
                train, verification=verification, selection=selection,
                execution_slice=execution_slice, full_records_artifact_bytes=genuine_bytes,
            )
        # Forgery shape 3: bytes omitted entirely (the pre-cure admission path) — fail closed.
        with self.assertRaisesRegex(ValueError, "requires the full verified records artifact bytes"):
            run_vertical_slice.validate_image_scene_split_execution(
                train, verification=verification, selection=selection,
                execution_slice=execution_slice,
            )
        print("B: forged corpus with true hash pasted REJECTED (all three shapes)")

    def test_c_honest_corpus_stale_declared_hash_rejected(self) -> None:
        records = _corpus("genuine")
        artifact_bytes = _artifact(records)
        stale_sha256 = "a" * 64
        train, selection, execution_slice, verification = self._bundle(records, stale_sha256)
        with self.assertRaisesRegex(ValueError, "full records artifact hash mismatch"):
            run_vertical_slice.validate_image_scene_split_execution(
                train, verification=verification, selection=selection,
                execution_slice=execution_slice, full_records_artifact_bytes=artifact_bytes,
            )
        print("C: honest corpus with stale declared hash REJECTED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
