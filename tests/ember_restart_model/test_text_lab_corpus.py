# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green charter gate for non-acquired shared-text corpus manifests."""
from __future__ import annotations
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

DOMAINS = ("mathematics", "statistics", "physics", "computer_science", "ml_ai", "training_infrastructure", "formal_logic", "software_engineering", "data_evaluation", "scientific_method", "application_worlds")

def sha(value: bytes) -> str: return hashlib.sha256(value).hexdigest()
def source(domain: str, n: int) -> dict[str, object]:
    content = f"human authored {domain} source {n}".encode()
    return {"source_id": f"{domain}-{n}", "domain": domain, "license_spdx": "CC-BY-4.0", "content_sha256": sha(content), "l4_receipt": {"schema_version":"ember-text-source-receipt-v1","result":"VERIFIED","source_sha256":sha(content),"generator":"local-normalizer-v1","verifier":"local-license-provenance-v1","model_mediated":False,"borrowed_labels":False}, "split":"train" if n == 0 else "heldout"}

class TextLabCorpusTests(unittest.TestCase):
    def test_manifest_requires_two_sources_all_domains_and_deterministic_splits(self):
        from text_lab_corpus import build_manifest, validate_manifest
        entries=[source(d,n) for d in DOMAINS for n in range(2)]
        manifest=build_manifest(entries, frozen_eval_hashes={sha(b"frozen eval")})
        self.assertEqual(tuple(manifest["domains"]), DOMAINS)
        self.assertEqual(validate_manifest(manifest, frozen_eval_hashes={sha(b"frozen eval")})["result"], "PREFLIGHT_ONLY")
        self.assertNotEqual(manifest["train_root_sha256"], manifest["heldout_root_sha256"])
    def test_rejects_single_source_bad_l4_duplicate_or_eval_contamination(self):
        from text_lab_corpus import build_manifest
        entries=[source(d,n) for d in DOMAINS for n in range(2)]
        with self.assertRaisesRegex(ValueError,"two independent"): build_manifest(entries[:-1], frozen_eval_hashes=set())
        bad=[dict(x) for x in entries]; bad[0]["license_spdx"]="Proprietary"
        with self.assertRaisesRegex(ValueError,"license"): build_manifest(bad, frozen_eval_hashes=set())
        duplicate=[dict(x) for x in entries]; duplicate[1]["content_sha256"]=duplicate[0]["content_sha256"]
        with self.assertRaisesRegex(ValueError,"duplicate"): build_manifest(duplicate, frozen_eval_hashes=set())
        with self.assertRaisesRegex(ValueError,"frozen eval"): build_manifest(entries, frozen_eval_hashes={entries[0]["content_sha256"]})
if __name__ == "__main__": unittest.main()