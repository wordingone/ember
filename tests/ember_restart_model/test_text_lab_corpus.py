# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green charter gate for non-acquired shared-text corpus manifests."""
from __future__ import annotations
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

DOMAINS = ("mathematics", "statistics", "physics", "computer_science", "ml_ai", "training_infrastructure", "formal_logic", "software_engineering", "data_evaluation", "scientific_method", "application_worlds")

def sha(value: bytes) -> str: return hashlib.sha256(value).hexdigest()
def source(domain: str, n: int) -> dict[str, object]:
    content = f"human authored {domain} source {n}".encode()
    return {"source_id": f"{domain}-{n}", "domain": domain, "license_spdx": "CC-BY-4.0", "content_sha256": sha(content), "l4_receipt": {"schema_version":"ember-text-source-receipt-v1","result":"VERIFIED","source_sha256":sha(content),"generator":"local-normalizer-v1","verifier":"local-license-provenance-v1","model_mediated":False,"borrowed_labels":False}, "split":"train" if n == 0 else "heldout"}

class TextLabCorpusTests(unittest.TestCase):
    def test_checked_in_authority_returns_terminal_unresolved_refusal_after_full_validation(self):
        from text_lab_corpus import validate_authority_index
        result = validate_authority_index(ROOT)
        self.assertEqual(result["result"], "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING")
        self.assertEqual(result["domain_count"], 11)
        self.assertEqual(result["train_source_count"], 22)
        self.assertEqual(result["heldout_source_count"], 22)
        self.assertRegex(result["train_root_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(result["heldout_root_sha256"], r"^[0-9a-f]{64}$")

    def test_empty_protected_registry_rejects_before_unresolved_candidate_refusal(self):
        from text_lab_corpus import validate_authority_index
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            shutil.copytree(ROOT / "data", root / "data")
            tools = root / "tools/ember-restart-3b"
            tools.mkdir(parents=True)
            for name in ("text_lab_corpus.py", "train.py", "run_vertical_slice.py"):
                shutil.copy2(ROOT / "tools/ember-restart-3b" / name, tools / name)
            registry_path = root / "data/ember-restart-3b/protected-eval-registry-v2.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["protected"] = []
            registry_bytes = json.dumps(registry, sort_keys=True, separators=(",", ":")).encode("utf-8")
            registry_path.write_bytes(registry_bytes)
            corpus_path = root / "data/ember-restart-3b/owned-text-lab-corpus-v2.json"
            corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
            corpus["registry_sha256"] = sha(registry_bytes)
            corpus_bytes = json.dumps(corpus, sort_keys=True, separators=(",", ":")).encode("utf-8")
            corpus_path.write_bytes(corpus_bytes)
            identity_path = root / "data/ember-restart-3b/owned-text-lab-input-identity-v2.json"
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
            identity["corpus_sha256"] = sha(corpus_bytes)
            identity_bytes = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
            identity_path.write_bytes(identity_bytes)
            index_path = root / "data/ember-restart-3b/text-lab-authority-index-v1.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["registry"]["sha256"] = sha(registry_bytes)
            index["corpus"]["sha256"] = sha(corpus_bytes)
            index["input_identity"]["sha256"] = sha(identity_bytes)
            index_path.write_text(json.dumps(index), encoding="utf-8")
            import text_lab_corpus
            with patch.object(text_lab_corpus.subprocess, "run", return_value=type("Result", (), {"returncode": 0})()):
                with self.assertRaisesRegex(ValueError, "non-empty"):
                    validate_authority_index(root)

    def test_checked_in_candidates_are_evidence_free_unresolved_descriptors(self):
        corpus = json.loads((ROOT / "data/ember-restart-3b/owned-text-lab-corpus-v2.json").read_text(encoding="utf-8"))
        bundle = json.loads((ROOT / "data/ember-restart-3b/text-lab-source-receipt-bundle-v2.json").read_text(encoding="utf-8"))
        expected = {"source_id", "domain", "split", "admission", "required_evidence", "allowed_license_spdx"}
        self.assertEqual(bundle["result"], "UNRESOLVED_CANDIDATE")
        self.assertEqual(len(corpus["sources"]), 44)
        self.assertEqual(len(bundle["candidates"]), 44)
        for row in corpus["sources"]:
            self.assertEqual(set(row), expected)
            self.assertEqual(row["admission"], "UNRESOLVED_CANDIDATE")
            self.assertTrue(row["source_id"].startswith("candidate-"))
            self.assertEqual(row["required_evidence"], ["source_descriptor", "source_content", "license_evidence", "policy", "verifier_result"])
            self.assertNotIn("content_sha256", row)
            self.assertNotIn("license_spdx", row)
        for candidate in bundle["candidates"]:
            self.assertEqual(set(candidate), expected)
            self.assertEqual(candidate["admission"], "UNRESOLVED_CANDIDATE")
            self.assertNotIn("borrowed_labels", candidate)
            self.assertNotIn("model_mediated", candidate)

    def test_changed_split_root_rejects_before_unresolved_candidate_refusal(self):
        from text_lab_corpus import validate_authority_index
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            shutil.copytree(ROOT / "data", root / "data")
            shutil.copytree(ROOT / "manifests", root / "manifests")
            tools = root / "tools/ember-restart-3b"
            tools.mkdir(parents=True)
            for name in ("text_lab_corpus.py", "train.py", "run_vertical_slice.py"):
                shutil.copy2(ROOT / "tools/ember-restart-3b" / name, tools / name)
            corpus_path = root / "data/ember-restart-3b/owned-text-lab-corpus-v2.json"
            corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
            corpus["train_root_sha256"] = "0" * 64
            corpus_bytes = json.dumps(corpus, sort_keys=True, separators=(",", ":")).encode("utf-8")
            corpus_path.write_bytes(corpus_bytes)
            identity_path = root / "data/ember-restart-3b/owned-text-lab-input-identity-v2.json"
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
            identity["corpus_sha256"] = sha(corpus_bytes)
            identity_bytes = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
            identity_path.write_bytes(identity_bytes)
            index_path = root / "data/ember-restart-3b/text-lab-authority-index-v1.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["corpus"]["sha256"] = sha(corpus_bytes)
            index["input_identity"]["sha256"] = sha(identity_bytes)
            index_path.write_text(json.dumps(index), encoding="utf-8")
            import text_lab_corpus
            with patch.object(text_lab_corpus.subprocess, "run", return_value=type("Result", (), {"returncode": 0})()):
                with self.assertRaisesRegex(ValueError, "split root"):
                    validate_authority_index(root)
    def test_changed_candidate_descriptor_rejects_at_split_root_before_terminal_refusal(self):
        from text_lab_corpus import validate_authority_index
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            shutil.copytree(ROOT / "data", root / "data")
            shutil.copytree(ROOT / "manifests", root / "manifests")
            tools = root / "tools/ember-restart-3b"
            tools.mkdir(parents=True)
            for name in ("text_lab_corpus.py", "train.py", "run_vertical_slice.py"):
                shutil.copy2(ROOT / "tools/ember-restart-3b" / name, tools / name)
            corpus_path = root / "data/ember-restart-3b/owned-text-lab-corpus-v2.json"
            bundle_path = root / "data/ember-restart-3b/text-lab-source-receipt-bundle-v2.json"
            corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            corpus["sources"][0]["source_id"] = "candidate-mathematics-train-9"
            bundle["candidates"][0]["source_id"] = "candidate-mathematics-train-9"
            bundle_bytes = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")
            bundle_path.write_bytes(bundle_bytes)
            corpus["receipt_bundle_sha256"] = sha(bundle_bytes)
            corpus_bytes = json.dumps(corpus, sort_keys=True, separators=(",", ":")).encode("utf-8")
            corpus_path.write_bytes(corpus_bytes)
            identity_path = root / "data/ember-restart-3b/owned-text-lab-input-identity-v2.json"
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
            identity["corpus_sha256"] = sha(corpus_bytes)
            identity_bytes = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
            identity_path.write_bytes(identity_bytes)
            index_path = root / "data/ember-restart-3b/text-lab-authority-index-v1.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["receipt_bundle"]["sha256"] = sha(bundle_bytes)
            index["corpus"]["sha256"] = sha(corpus_bytes)
            index["input_identity"]["sha256"] = sha(identity_bytes)
            index_path.write_text(json.dumps(index), encoding="utf-8")
            import text_lab_corpus
            with patch.object(text_lab_corpus.subprocess, "run", return_value=type("Result", (), {"returncode": 0})()):
                with self.assertRaisesRegex(ValueError, "split root"):
                    validate_authority_index(root)

    def test_checked_in_authority_rejects_changed_corpus_binding(self):
        from text_lab_corpus import validate_authority_index
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            shutil.copytree(ROOT / "data", root / "data")
            index_path = root / "data/ember-restart-3b/text-lab-authority-index-v1.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["corpus"]["sha256"] = "0" * 64
            index_path.write_text(json.dumps(index), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "bound hash"):
                validate_authority_index(root)
            index = json.loads((ROOT / "data/ember-restart-3b/text-lab-authority-index-v1.json").read_text(encoding="utf-8"))
            index["input_identity"]["sha256"] = "1" * 64
            index_path.write_text(json.dumps(index), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "bound hash"):
                validate_authority_index(root)

    def test_unresolved_descriptor_rejects_injected_evidence_derived_hash(self):
        from text_lab_corpus import validate_authority_index
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            shutil.copytree(ROOT / "data", root / "data")
            corpus_path = root / "data/ember-restart-3b/owned-text-lab-corpus-v2.json"
            corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
            corpus["sources"][0]["content_sha256"] = "0" * 64
            corpus_bytes = json.dumps(corpus, sort_keys=True, separators=(",", ":")).encode("utf-8")
            corpus_path.write_bytes(corpus_bytes)
            identity_path = root / "data/ember-restart-3b/owned-text-lab-input-identity-v2.json"
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
            identity["corpus_sha256"] = sha(corpus_bytes)
            identity_bytes = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
            identity_path.write_bytes(identity_bytes)
            index_path = root / "data/ember-restart-3b/text-lab-authority-index-v1.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["corpus"]["sha256"] = sha(corpus_bytes)
            index["input_identity"]["sha256"] = sha(identity_bytes)
            index_path.write_text(json.dumps(index), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Additional properties"):
                validate_authority_index(root)

    def test_checked_in_authority_rejects_changed_bound_code_bytes(self):
        from text_lab_corpus import validate_authority_index
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            shutil.copytree(ROOT / "data", root / "data")
            tools = root / "tools/ember-restart-3b"
            tools.mkdir(parents=True)
            for name in ("text_lab_corpus.py", "train.py", "run_vertical_slice.py"):
                shutil.copy2(ROOT / "tools/ember-restart-3b" / name, tools / name)
            with (tools / "train.py").open("ab") as handle:
                handle.write(b"# changed\n")
            import text_lab_corpus
            with patch.object(text_lab_corpus.subprocess, "run", return_value=type("Result", (), {"returncode": 0})()):
                with self.assertRaisesRegex(ValueError, "code bytes changed"):
                    validate_authority_index(root)

    def test_canonical_runner_rejects_authority_before_cuda_probe(self):
        import run_vertical_slice
        with patch.object(run_vertical_slice, "run_text_lab_preflight", side_effect=ValueError("authority drift")), patch.object(run_vertical_slice.torch.cuda, "is_available", side_effect=AssertionError("CUDA reached")):
            with self.assertRaisesRegex(ValueError, "authority drift"):
                run_vertical_slice.run_semantic(seed=1, artifact_root=ROOT / "unused", receipt_path=ROOT / "unused", shards_root=ROOT / "unused", tokenizer_path=ROOT / "unused", expected_receipt_sha256="r" * 64, expected_tokenizer_sha256="t" * 64, expected_architecture_sha256="a" * 64, steps=1, sequence_length=1, checkpoint_interval=1, write_budget_bytes=1)

    def test_canonical_runner_refuses_terminal_unresolved_receipt_before_cuda_probe(self):
        import run_vertical_slice
        unresolved = {"result": "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING"}
        with patch.object(run_vertical_slice, "run_text_lab_preflight", return_value=unresolved), patch.object(run_vertical_slice.torch.cuda, "is_available", side_effect=AssertionError("CUDA reached")):
            with self.assertRaisesRegex(ValueError, "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING"):
                run_vertical_slice.run_semantic(seed=1, artifact_root=ROOT / "unused", receipt_path=ROOT / "unused", shards_root=ROOT / "unused", tokenizer_path=ROOT / "unused", expected_receipt_sha256="r" * 64, expected_tokenizer_sha256="t" * 64, expected_architecture_sha256="a" * 64, steps=1, sequence_length=1, checkpoint_interval=1, write_budget_bytes=1)

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