# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

class OwnedTextTransformTests(unittest.TestCase):
    def test_pre_admission_builder_requires_and_enforces_per_source_record_bound(self):
        from text_lab_corpus import build_pre_admission_text_tranche, record_source_custody_file
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            train = root / "train.txt"; heldout = root / "heldout.txt"
            train.write_text("one\ntwo\nthree\n", encoding="utf-8")
            heldout.write_text("four\nfive\nsix\n", encoding="utf-8")
            def descriptor(source_id, split, path):
                raw = path.read_bytes()
                return {
                    "source_id": source_id, "domain": "application_worlds", "split": split,
                    "source_url": f"https://example.invalid/{source_id}", "license_spdx": "PDDL-1.0",
                    "provenance_origin_id": f"origin:{source_id}", "human_provenance_basis": "human public record",
                    "fetched_ts": "2026-07-07T00:00:00Z", "selection_rule": "utf8_nonblank_lines_v1",
                    "expected_source_sha256": sha(raw), "expected_source_bytes": len(raw),
                }
            receipts = {
                "train": record_source_custody_file(descriptor=descriptor("train", "train", train), raw_path=train, license_evidence_bytes=b"pd", policy_bytes=b"policy", verifier_bytes=b"verifier"),
                "heldout": record_source_custody_file(descriptor=descriptor("heldout", "heldout", heldout), raw_path=heldout, license_evidence_bytes=b"pd", policy_bytes=b"policy", verifier_bytes=b"verifier"),
            }
            manifest = build_pre_admission_text_tranche(
                sources=[
                    {"source_id": "train", "split": "train", "transform_id": "utf8_nonblank_lines_v1"},
                    {"source_id": "heldout", "split": "heldout", "transform_id": "utf8_nonblank_lines_v1"},
                ],
                raw_paths={"train": train, "heldout": heldout}, source_custody_receipts=receipts,
                output_root=root / "out", build_id="bounded", max_records_per_source=1,
            )
            self.assertEqual(manifest["train_record_count"], 1)
            self.assertEqual(manifest["heldout_record_count"], 1)

if __name__ == "__main__":
    unittest.main()
