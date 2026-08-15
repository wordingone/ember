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
    # v2 receipt shape (hardening 2026-07-20): license_spdx + evidence_sha256 bound into the
    # receipt. The manifest layer (build_manifest/validate_manifest, this module's caller) has
    # no license_evidence field of its own and does not re-derive - `_validate`'s receipt check
    # is shape-only here (format-checks evidence_sha256, doesn't recompute it), so a synthetic
    # digest is sufficient for this layer's own tests.
    content = f"human authored {domain} source {n}".encode()
    content_sha = sha(content)
    evidence_sha256 = sha(json.dumps({"kind": "spdx_repo_license", "declared_spdx": "CC-BY-4.0"}, sort_keys=True, separators=(",", ":")).encode())
    return {"source_id": f"{domain}-{n}", "domain": domain, "license_spdx": "CC-BY-4.0", "content_sha256": content_sha, "l4_receipt": {"schema_version":"ember-text-source-receipt-v2","result":"VERIFIED","source_sha256":content_sha,"generator":"local-normalizer-v1","verifier":"local-license-provenance-v1","model_mediated":False,"borrowed_labels":False,"license_spdx":"CC-BY-4.0","evidence_sha256":evidence_sha256}, "split":"train" if n == 0 else "heldout"}

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
_ALLOWED_LICENSES_SORTED = ["Apache-2.0", "BSD-3-Clause", "CC-BY-4.0", "CC0-1.0", "MIT", "ODC-By-1.0", "PDDL-1.0"]
_REQUIRED_EVIDENCE_V2 = ["source_descriptor", "source_content", "license_evidence", "policy", "verifier_result"]


def _admitted_rows():
    # Receipts are constructed by CALLING the real verifier (local_license_provenance_v1), not
    # hand-written literals - hardening 2026-07-20 (state/ember02-resolver-review-findings.md
    # Finding 1) requires the VERIFIED path to re-derive each row's receipt from its
    # license_evidence, so the fixture must be genuinely self-consistent under that
    # re-derivation, not merely shape-valid.
    from text_lab_corpus import local_license_provenance_v1
    rows = []
    for domain in DOMAINS:
        for split, n in (("train", 0), ("train", 1), ("heldout", 0), ("heldout", 1)):
            content = sha(f"admitted-content::{domain}::{split}::{n}".encode())
            evidence = {
                "kind": "spdx_repo_license",
                "license_sha256": sha(f"license-file::{domain}::{split}::{n}".encode()),
                "declared_spdx": "CC-BY-4.0",
            }
            receipt = local_license_provenance_v1(content_sha256=content, license_spdx="CC-BY-4.0", evidence=evidence)
            rows.append({
                "source_id": f"candidate-{domain}-{split}-{n}",
                "domain": domain,
                "split": split,
                "admission": "ADMITTED",
                "required_evidence": _REQUIRED_EVIDENCE_V2,
                "allowed_license_spdx": _ALLOWED_LICENSES_SORTED,
                "content_sha256": content,
                "license_spdx": "CC-BY-4.0",
                "license_evidence": evidence,
                "l4_receipt": receipt,
            })
    return rows


def _default_frozen_eval_hashes():
    # A hash disjoint from every _admitted_rows() content_sha256 - used so the VERIFIED-reaching
    # fixtures populate the frozen-eval registry (hardening 2026-07-20 Finding 3: VERIFIED
    # requires the registry present + non-empty) without self-contaminating.
    return {sha(b"held-out canary content, never claimed by an admitted row")}


def _write_v2_fixture(root, rows, *, bundle_result="RESOLVED", frozen_eval_hashes=None, corrupt_code_after=False):
    from text_lab_corpus import _authority_split_root
    shutil.copytree(ROOT / "data", root / "data")
    shutil.copytree(ROOT / "manifests", root / "manifests")
    tools = root / "tools/ember-restart-3b"
    tools.mkdir(parents=True)
    for name in ("text_lab_corpus.py", "train.py", "run_vertical_slice.py"):
        shutil.copy2(ROOT / "tools/ember-restart-3b" / name, tools / name)
    data_dir = root / "data/ember-restart-3b"
    registry_bytes = (data_dir / "protected-eval-registry-v2.json").read_bytes()
    corpus_schema_bytes = (data_dir / "text-lab-corpus-v3.schema.json").read_bytes()
    bundle_schema_bytes = (data_dir / "text-lab-bundle-v3.schema.json").read_bytes()
    identity_schema_bytes = (data_dir / "text-lab-identity-v2.schema.json").read_bytes()
    registry_schema_bytes = (data_dir / "text-lab-registry-v2.schema.json").read_bytes()

    bundle = {"schema_version": "ember-text-source-receipt-bundle-v3", "result": bundle_result, "candidates": rows}
    bundle_bytes = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")
    (data_dir / "text-lab-source-receipt-bundle-v3.json").write_bytes(bundle_bytes)

    corpus = {
        "schema_version": "ember-text-lab-corpus-v3",
        "registry_sha256": sha(registry_bytes),
        "receipt_bundle_sha256": sha(bundle_bytes),
        "sources": rows,
        "train_root_sha256": _authority_split_root(rows, "train"),
        "heldout_root_sha256": _authority_split_root(rows, "heldout"),
    }
    corpus_bytes = json.dumps(corpus, sort_keys=True, separators=(",", ":")).encode("utf-8")
    (data_dir / "owned-text-lab-corpus-v3.json").write_bytes(corpus_bytes)

    identity = {
        "schema_version": "ember-text-lab-input-identity-v2",
        "corpus_sha256": sha(corpus_bytes),
        "code_files": {
            "text_lab_corpus": sha((tools / "text_lab_corpus.py").read_bytes()),
            "train": sha((tools / "train.py").read_bytes()),
            "run_vertical_slice": sha((tools / "run_vertical_slice.py").read_bytes()),
        },
        "source_base_commit": "0" * 40,
    }
    identity_bytes = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    (data_dir / "owned-text-lab-input-identity-v3.json").write_bytes(identity_bytes)

    if corrupt_code_after:
        with (tools / "train.py").open("ab") as handle:
            handle.write(b"# corrupted after identity signing\n")

    index = {
        "schema_version": "ember-text-lab-authority-index-v2",
        "result": "PREFLIGHT_ONLY",
        "boundary": "NO_ACQUISITION_NO_TRAINING_NO_SUFFICIENT_PRETRAINING_CLAIM",
        "registry": {"path": "data/ember-restart-3b/protected-eval-registry-v2.json", "sha256": sha(registry_bytes), "schema": {"path": "data/ember-restart-3b/text-lab-registry-v2.schema.json", "sha256": sha(registry_schema_bytes)}},
        "receipt_bundle": {"path": "data/ember-restart-3b/text-lab-source-receipt-bundle-v3.json", "sha256": sha(bundle_bytes), "schema": {"path": "data/ember-restart-3b/text-lab-bundle-v3.schema.json", "sha256": sha(bundle_schema_bytes)}},
        "corpus": {"path": "data/ember-restart-3b/owned-text-lab-corpus-v3.json", "sha256": sha(corpus_bytes), "schema": {"path": "data/ember-restart-3b/text-lab-corpus-v3.schema.json", "sha256": sha(corpus_schema_bytes)}},
        "input_identity": {"path": "data/ember-restart-3b/owned-text-lab-input-identity-v3.json", "sha256": sha(identity_bytes), "schema": {"path": "data/ember-restart-3b/text-lab-identity-v2.schema.json", "sha256": sha(identity_schema_bytes)}},
    }
    index_path = data_dir / "text-lab-authority-index-v2.json"
    index_path.write_text(json.dumps(index, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    if frozen_eval_hashes is not None:
        # None (default) = registry file absent entirely. An explicit value - including
        # set() - WRITES the file, so callers can distinguish "absent" from "present but
        # empty" (hardening 2026-07-20 Finding 3 requires refusing VERIFIED on either).
        (data_dir / "text-lab-frozen-eval-hashes-v1.json").write_text(
            json.dumps({"schema_version": "ember-text-lab-frozen-eval-hashes-v1", "hashes": sorted(frozen_eval_hashes)}),
            encoding="utf-8",
        )
    return index_path


class TextLabResolverV2Tests(unittest.TestCase):
    """D1-D5 VERIFIED path. Fixture-only (never live data/*.json). v1 must stay untouched."""

    def _fixture_root(self, rows, **kwargs):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name) / "repo"
        self._write(root, rows, **kwargs)
        return root

    @staticmethod
    def _write(root, rows, **kwargs):
        return _write_v2_fixture(root, rows, **kwargs)

    def _validate_v2(self, root):
        import text_lab_corpus
        with patch.object(text_lab_corpus.subprocess, "run", return_value=type("Result", (), {"returncode": 0})()):
            return text_lab_corpus.validate_authority_index(root, index_relative="data/ember-restart-3b/text-lab-authority-index-v2.json")

    def test_v1_authority_index_still_refuses_unchanged(self):
        from text_lab_corpus import validate_authority_index
        result = validate_authority_index(ROOT)
        self.assertEqual(result["result"], "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING")

    def test_fully_admitted_v2_authority_reaches_verified(self):
        root = self._fixture_root(_admitted_rows(), frozen_eval_hashes=_default_frozen_eval_hashes())
        result = self._validate_v2(root)
        self.assertEqual(result["result"], "VERIFIED")

    def test_one_unadmitted_slot_among_admitted_refuses(self):
        # Caught by: the `all_admitted` gate at the tail of validate_authority_index (43 rows
        # ADMITTED + 1 still UNRESOLVED_CANDIDATE -> all_admitted=False -> falls through to
        # the SAME NOT_ADMITTED_SOURCE_EVIDENCE_MISSING v1 always returns). Asserted by return
        # value, not exception-catch, since falling through is not an exception path -
        # stronger than message-matching: proves no false VERIFIED, not just "some error fired".
        rows = _admitted_rows()
        rows[0] = {
            "source_id": rows[0]["source_id"], "domain": rows[0]["domain"], "split": rows[0]["split"],
            "admission": "UNRESOLVED_CANDIDATE", "required_evidence": _REQUIRED_EVIDENCE_V2,
            "allowed_license_spdx": _ALLOWED_LICENSES_SORTED,
        }
        root = self._fixture_root(rows, bundle_result="UNRESOLVED_CANDIDATE")
        result = self._validate_v2(root)
        self.assertEqual(result["result"], "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING")

    def test_duplicate_content_hash_across_admitted_slots_refuses(self):
        # Caught by: reused `_validate` (text_lab_corpus.py, "duplicate source content is
        # forbidden") - reaches the VERIFIED path's admitted-rows projection first (schema,
        # candidate-bundle-binding, 44/2+2 structural, split-root checks all pass unchanged
        # since content_sha256 isn't part of any of those), so this exercises the manifest-
        # layer dup gate specifically, not an earlier structural rejection.
        rows = _admitted_rows()
        rows[1]["content_sha256"] = rows[0]["content_sha256"]
        rows[1]["l4_receipt"]["source_sha256"] = rows[0]["content_sha256"]
        root = self._fixture_root(rows, frozen_eval_hashes=_default_frozen_eval_hashes())
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self._validate_v2(root)

    def test_frozen_eval_contaminated_heldout_source_refuses(self):
        # Caught by: reused `_validate` ("source contaminates frozen eval"), fed the D5
        # on-disk registry loaded by `_frozen_eval_hashes(root)` - proves the registry is
        # actually WIRED into the VERIFIED path (closes spec hole #3), not just a loader
        # that exists but is never consulted.
        rows = _admitted_rows()
        heldout_row = next(r for r in rows if r["split"] == "heldout")
        root = self._fixture_root(rows, frozen_eval_hashes={heldout_row["content_sha256"]})
        with self.assertRaisesRegex(ValueError, "frozen"):
            self._validate_v2(root)

    def test_non_allow_set_license_refuses(self):
        # Caught by the v3 corpus/bundle JSON-schema's per-row oneOf (Proprietary matches
        # neither the UNRESOLVED_CANDIDATE nor the ADMITTED alternative, since the ADMITTED
        # alternative's license_spdx is enum-pinned to the same 6-value allow-set as the
        # Python-level `_validate` L31 check) - defense-in-depth ahead of `_validate`, which
        # would independently reject this value on the identical allow-set if ever reached
        # un-schema-gated. Assert the SPECIFIC schema-rejection message, not a bare ValueError.
        rows = _admitted_rows()
        rows[0]["license_spdx"] = "Proprietary"
        root = self._fixture_root(rows, frozen_eval_hashes=_default_frozen_eval_hashes())
        with self.assertRaisesRegex(ValueError, "authority schema rejects bytes"):
            self._validate_v2(root)

    def test_tampered_l4_receipt_field_refuses(self):
        # Caught by: reused `_validate`'s exact-dict-equality receipt check ("source L4
        # provenance receipt is invalid"). The v3 schema's l4_receipt field is deliberately
        # unconstrained ({"type":"object"}) so this is NOT schema-caught - it genuinely
        # reaches the Python-level literal-match gate.
        rows = _admitted_rows()
        rows[0]["l4_receipt"]["generator"] = "some-other-generator"
        root = self._fixture_root(rows, frozen_eval_hashes=_default_frozen_eval_hashes())
        with self.assertRaisesRegex(ValueError, "L4 provenance receipt"):
            self._validate_v2(root)

    def test_model_mediated_source_refuses(self):
        # Caught by: the SAME reused `_validate` receipt-literal check as above (model_mediated
        # is one field of the exact-match dict) - proves borrowed/model-mediated content can't
        # slip through by itself flipping one receipt field.
        rows = _admitted_rows()
        rows[0]["l4_receipt"]["model_mediated"] = True
        root = self._fixture_root(rows, frozen_eval_hashes=_default_frozen_eval_hashes())
        with self.assertRaisesRegex(ValueError, "L4 provenance receipt"):
            self._validate_v2(root)

    def test_stale_code_files_binding_refuses(self):
        # Caught by: the pre-existing, UNCHANGED code_files-sha256 check ("input identity code
        # bytes changed") - runs before the is_v2 branch even matters, identical for v1 and v2.
        root = self._fixture_root(_admitted_rows(), frozen_eval_hashes=_default_frozen_eval_hashes(), corrupt_code_after=True)
        with self.assertRaisesRegex(ValueError, "code bytes changed"):
            self._validate_v2(root)

    def test_admitted_license_spdx_swapped_from_its_proven_evidence_refuses(self):
        # Hardening 2026-07-20 (Finding 1b, state/ember02-resolver-review-findings.md).
        # Caught by: the evidence re-derivation loop at the tail of validate_authority_index,
        # AFTER `_validate` and the frozen-eval gate both pass. Both row["license_spdx"] and
        # the receipt's own "license_spdx" field are swapped together to "MIT", so `_validate`'s
        # shape check (receipt.license_spdx == row.license_spdx) is satisfied and does NOT
        # catch this alone - only re-running local_license_provenance_v1(content, "MIT",
        # <evidence that only ever proved CC-BY-4.0>) surfaces the mismatch, at the verifier's
        # own "does not prove the declared SPDX id" guard.
        rows = _admitted_rows()
        rows[0]["license_spdx"] = "MIT"
        rows[0]["l4_receipt"]["license_spdx"] = "MIT"
        root = self._fixture_root(rows, frozen_eval_hashes=_default_frozen_eval_hashes())
        with self.assertRaisesRegex(ValueError, "does not prove the declared SPDX id"):
            self._validate_v2(root)

    def test_admitted_receipt_forged_without_valid_evidence_refuses(self):
        # Hardening 2026-07-20 (Finding 1, state/ember02-resolver-review-findings.md).
        # Caught by: the evidence re-derivation loop - the l4_receipt itself is untouched and
        # shape-valid (passes `_validate`'s format-only check), but license_evidence is
        # replaced with an unrecognized route, so local_license_provenance_v1 raises the
        # instant it is re-run - proving a well-formed receipt alone is not sufficient without
        # re-deriving it from evidence.
        rows = _admitted_rows()
        rows[0]["license_evidence"] = {"kind": "not_a_real_route"}
        root = self._fixture_root(rows, frozen_eval_hashes=_default_frozen_eval_hashes())
        with self.assertRaisesRegex(ValueError, "kind is not recognized"):
            self._validate_v2(root)

    def test_verified_requires_frozen_eval_registry_present(self):
        # Hardening 2026-07-20 (Finding 3). Caught by: the frozen-eval PRESENCE gate at the
        # tail of validate_authority_index - D5's _frozen_eval_hashes(root) treats an absent
        # registry file as an empty set for the manifest layer's own (unwired) callers, which
        # would otherwise let VERIFIED be reached with zero heldout-contamination protection
        # wired in. This fixture is fully admitted and otherwise valid; only the registry file
        # is missing (no frozen_eval_hashes passed -> _write_v2_fixture never writes it).
        root = self._fixture_root(_admitted_rows())
        with self.assertRaisesRegex(ValueError, "frozen eval hash registry is required for VERIFIED and is absent"):
            self._validate_v2(root)

    def test_verified_requires_frozen_eval_registry_non_empty(self):
        # Companion to the above - a PRESENT but EMPTY registry file must also refuse ("is
        # required ... and is empty"), not just an absent one. frozen_eval_hashes=set() (not
        # None) forces _write_v2_fixture to write the file with zero hashes.
        root = self._fixture_root(_admitted_rows(), frozen_eval_hashes=set())
        with self.assertRaisesRegex(ValueError, "frozen eval hash registry is required for VERIFIED and is empty"):
            self._validate_v2(root)


class LocalNormalizerAndLicenseProvenanceTests(unittest.TestCase):
    def test_normalizer_is_deterministic_across_newline_and_bom_variants(self):
        from text_lab_corpus import local_normalizer_v1
        a, hash_a = local_normalizer_v1(b"line one\r\nline two   \r\nline three\n")
        b, hash_b = local_normalizer_v1("﻿line one\nline two\nline three".encode("utf-8"))
        self.assertEqual(hash_a, hash_b)
        self.assertEqual(a, b)
        self.assertRegex(hash_a, r"^[0-9a-f]{64}$")

    def test_license_provenance_us_gov_pd_admits_only_under_cc0(self):
        from text_lab_corpus import local_normalizer_v1, local_license_provenance_v1
        _, content = local_normalizer_v1(b"a federal statistics handbook chapter\n")
        evidence = {"kind": "us_gov_federal_authorship", "agency": "NIST", "federal_employee_work_of_authorship": True}
        receipt = local_license_provenance_v1(content_sha256=content, license_spdx="CC0-1.0", evidence=evidence)
        expected_evidence_sha256 = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        self.assertEqual(receipt, {
            "schema_version": "ember-text-source-receipt-v2", "result": "VERIFIED", "source_sha256": content,
            "generator": "local-normalizer-v1", "verifier": "local-license-provenance-v1",
            "model_mediated": False, "borrowed_labels": False,
            "license_spdx": "CC0-1.0", "evidence_sha256": expected_evidence_sha256,
        })
        with self.assertRaisesRegex(ValueError, "only admits under CC0-1.0"):
            local_license_provenance_v1(
                content_sha256=content, license_spdx="MIT",
                evidence={"kind": "us_gov_federal_authorship", "agency": "NIST", "federal_employee_work_of_authorship": True},
            )

    def test_license_provenance_rejects_incomplete_or_nonallowset_evidence(self):
        # Each assertion is pinned to the SPECIFIC guard clause it is meant to exercise
        # (tightening pass, "vacuous-negative guard") - three genuinely distinct code paths in
        # local_license_provenance_v1: the unconditional allow-set gate (runs before any
        # evidence-kind routing at all), an incomplete-but-recognized route, and an
        # unrecognized route.
        from text_lab_corpus import local_normalizer_v1, local_license_provenance_v1
        _, content = local_normalizer_v1(b"some source text\n")
        with self.assertRaisesRegex(ValueError, "not in the allow-set"):
            local_license_provenance_v1(content_sha256=content, license_spdx="Proprietary", evidence={"kind": "publisher_terms", "terms_url": "https://example.com", "declared_spdx": "Proprietary"})
        with self.assertRaisesRegex(ValueError, "attestation is incomplete"):
            local_license_provenance_v1(content_sha256=content, license_spdx="CC0-1.0", evidence={"kind": "us_gov_federal_authorship", "agency": "NIST"})
        with self.assertRaisesRegex(ValueError, "kind is not recognized"):
            local_license_provenance_v1(content_sha256=content, license_spdx="MIT", evidence={"kind": "not_a_real_route"})

    def test_license_provenance_admits_odc_by_1_0(self):
        # Named, narrow allow-set extension: ODC-By-1.0 (Open Data Commons Attribution
        # License v1.0) -- academic/pretraining-scale corpora (S2ORC, peS2o, S2ORC-ML,
        # Zyda-2, Dolma) concentrate under this license and no CC0/CC-BY/MIT/Apache/
        # BSD/PDDL alternative exists at comparable scale for the 5 slots this unblocks.
        from text_lab_corpus import local_normalizer_v1, local_license_provenance_v1
        _, content = local_normalizer_v1(b"odc-by licensed source text\n")
        evidence = {"kind": "publisher_terms", "terms_url": "https://opendatacommons.org/licenses/by/1-0/", "declared_spdx": "ODC-By-1.0"}
        receipt = local_license_provenance_v1(content_sha256=content, license_spdx="ODC-By-1.0", evidence=evidence)
        self.assertEqual(receipt["license_spdx"], "ODC-By-1.0")
        self.assertEqual(receipt["result"], "VERIFIED")


class ConnectorReceiptAdapterTests(unittest.TestCase):
    """adapt_connector_receipt: reshape tools/corpus_connectors.Receipt into an admitted row."""

    def _fetch_dir(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def _write_fetched_file(self, dest_root, relative, content: bytes):
        path = dest_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return sha(content)

    def _receipt(self, dest_root, *, path="source.txt", content_sha256, license="CC-BY-4.0"):
        return {
            "schema": "corpus-connector-receipt-v1",
            "source": "http_fetch", "source_id": "candidate-mathematics-train-0",
            "canonical_url": "https://example.org/source.txt",
            "license": license, "license_evidence": "publisher terms page",
            "revision": None,
            "files": [{"path": path, "bytes": 20, "sha256": content_sha256}],
            "total_bytes": 20, "sha256_manifest": sha(content_sha256.encode()),
            "fetched_at": "2026-08-14T00:00:00Z",
            "connector": {"name": "http_fetch", "version": "v1"},
            "l3_statement": "fetch-only; no external model authored/filtered/ranked/scored/selected any token",
            "dest_root": str(dest_root), "notes": "",
        }

    def test_adapts_valid_receipt_into_admitted_row_fields(self):
        from text_lab_corpus import adapt_connector_receipt, local_normalizer_v1
        dest_root = self._fetch_dir()
        content = b"a human-authored mathematics passage\r\n"
        content_sha256 = self._write_fetched_file(dest_root, "source.txt", content)
        receipt = self._receipt(dest_root, content_sha256=content_sha256)
        evidence = {"kind": "publisher_terms", "terms_url": "https://example.org/license", "declared_spdx": "CC-BY-4.0"}
        row = adapt_connector_receipt(receipt, evidence=evidence)
        self.assertEqual(set(row), {"content_sha256", "license_spdx", "license_evidence", "l4_receipt"})
        self.assertEqual(row["license_spdx"], "CC-BY-4.0")
        self.assertEqual(row["license_evidence"], evidence)
        _, expected_content_sha256 = local_normalizer_v1(content)
        self.assertEqual(row["content_sha256"], expected_content_sha256)
        self.assertEqual(row["l4_receipt"]["source_sha256"], expected_content_sha256)
        self.assertEqual(row["l4_receipt"]["result"], "VERIFIED")

    def test_rejects_wrong_receipt_schema(self):
        from text_lab_corpus import adapt_connector_receipt
        dest_root = self._fetch_dir()
        content_sha256 = self._write_fetched_file(dest_root, "source.txt", b"x")
        receipt = self._receipt(dest_root, content_sha256=content_sha256)
        receipt["schema"] = "some-other-schema"
        with self.assertRaisesRegex(ValueError, "corpus-connector-receipt-v1"):
            adapt_connector_receipt(receipt, evidence={"kind": "publisher_terms", "terms_url": "u", "declared_spdx": "CC-BY-4.0"})

    def test_rejects_tampered_file_bytes(self):
        from text_lab_corpus import adapt_connector_receipt
        dest_root = self._fetch_dir()
        content_sha256 = self._write_fetched_file(dest_root, "source.txt", b"original bytes")
        receipt = self._receipt(dest_root, content_sha256=content_sha256)
        (dest_root / "source.txt").write_bytes(b"tampered bytes")
        with self.assertRaisesRegex(ValueError, "do not match its own recorded hash"):
            adapt_connector_receipt(receipt, evidence={"kind": "publisher_terms", "terms_url": "u", "declared_spdx": "CC-BY-4.0"})

    def test_rejects_license_outside_allow_set(self):
        from text_lab_corpus import adapt_connector_receipt
        dest_root = self._fetch_dir()
        content_sha256 = self._write_fetched_file(dest_root, "source.txt", b"x")
        receipt = self._receipt(dest_root, content_sha256=content_sha256, license="Proprietary")
        with self.assertRaisesRegex(ValueError, "not on the text-lab allow-list"):
            adapt_connector_receipt(receipt, evidence={"kind": "publisher_terms", "terms_url": "u", "declared_spdx": "Proprietary"})

    def test_rejects_multi_file_receipt(self):
        from text_lab_corpus import adapt_connector_receipt
        dest_root = self._fetch_dir()
        content_sha256 = self._write_fetched_file(dest_root, "source.txt", b"x")
        receipt = self._receipt(dest_root, content_sha256=content_sha256)
        receipt["files"].append({"path": "extra.txt", "bytes": 1, "sha256": sha(b"y")})
        with self.assertRaisesRegex(ValueError, "exactly one fetched file"):
            adapt_connector_receipt(receipt, evidence={"kind": "publisher_terms", "terms_url": "u", "declared_spdx": "CC-BY-4.0"})


if __name__ == "__main__": unittest.main()