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

    def test_public_tranche_cli_reuses_existing_court_custody_receipt(self):
        import json
        import subprocess
        from text_lab_corpus import record_source_custody_file
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gutenberg = root / "gutenberg"; gutenberg.mkdir()
            text = b"one\ntwo\n"
            (gutenberg / "218.txt").write_bytes(text)
            inventory = {
                "source_url": "https://example.invalid/gutenberg", "sha256": sha(text), "bytes": len(text),
                "license": "Public Domain", "human_provenance_basis": "human-authored public literature",
                "fetched_ts": "2026-07-07T00:00:00Z", "selection_rule": "authorized-wave-rule",
            }
            (gutenberg / "manifest.jsonl").write_text(json.dumps(inventory, sort_keys=True) + "\n", encoding="utf-8")
            court = root / "court.csv"
            court.write_text("case_name,citations\nAlpha,1 U.S. 1\n", encoding="utf-8")
            court_raw = court.read_bytes()
            court_descriptor = {
                "source_id": "courtlistener-scotus-caption", "domain": "application_worlds", "split": "heldout",
                "source_url": "https://example.invalid/court", "license_spdx": "PDDL-1.0",
                "provenance_origin_id": "courtlistener:scotus-caption", "human_provenance_basis": "court-authored opinion",
                "fetched_ts": "2026-07-06T17:09:00Z", "selection_rule": "scotus_caption_csv_case_citation_v1",
                "expected_source_sha256": sha(court_raw), "expected_source_bytes": len(court_raw),
            }
            court_receipt = record_source_custody_file(
                descriptor=court_descriptor, raw_path=court, license_evidence_bytes=b"pd",
                policy_bytes=b"policy", verifier_bytes=b"verifier",
            )
            receipt_path = root / "court-custody.json"
            receipt_path.write_text(json.dumps(court_receipt, sort_keys=True), encoding="utf-8")
            result = subprocess.run([
                sys.executable, str(ROOT / "tools/ember-restart-3b/build_owned_text_tranche.py"),
                "--repo-root", str(ROOT), "--staging-root", str(root / "out"),
                "--gutenberg-root", str(gutenberg), "--gutenberg-limit", "1",
                "--court-csv", str(court), "--court-custody-receipt", str(receipt_path),
                "--max-records-per-source", "1",
            ], text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            tranche = root / "out" / summary["build_id"]
            self.assertEqual(summary["result"], "VERIFIED")
            self.assertTrue((tranche / "manifest.json").is_file())
            self.assertTrue((tranche / "l4-transform-receipt.json").is_file())
            l4 = json.loads((tranche / "l4-transform-receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(l4["source_custody_receipts"][-1]["source_id"], "gutenberg-218")
            self.assertIn({"source_id": "courtlistener-scotus-caption", "sha256": sha(json.dumps(court_receipt, sort_keys=True, separators=(",", ":")).encode("utf-8"))}, l4["source_custody_receipts"])

if __name__ == "__main__":
    unittest.main()
