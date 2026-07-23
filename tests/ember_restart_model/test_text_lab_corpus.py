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
    split = "train" if n % 2 == 0 else "heldout"
    return verified_source(domain, split, n, f"{domain}-{split}-origin-{n}")

def verified_source(domain: str, split: str, number: int, origin_id: str) -> dict[str, object]:
    content = f"human authored {domain} {split} source {number}".encode("utf-8")
    receipt = {
        "schema_version": "ember-text-source-receipt-v2",
        "result": "VERIFIED",
        "source_sha256": sha(content),
        "provenance_origin_id": origin_id,
        "source_descriptor_sha256": sha(f"descriptor:{origin_id}".encode("utf-8")),
        "license_evidence_sha256": sha(f"license:{origin_id}".encode("utf-8")),
        "policy_sha256": sha(b"local-license-provenance-policy-v1"),
        "verifier_sha256": sha(b"local-license-provenance-verifier-v1"),
        "model_mediated": False,
        "borrowed_labels": False,
    }
    return {"source_id": f"{domain}-{split}-{number}", "domain": domain, "license_spdx": "CC-BY-4.0", "content_sha256": sha(content), "l4_receipt": receipt, "split": split, "provenance_origin_id": origin_id}


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

    def test_checked_in_authority_binds_actual_token_shard_writer_bytes(self):
        identity = json.loads((ROOT / "data/ember-restart-3b/owned-text-lab-input-identity-v2.json").read_text(encoding="utf-8"))
        self.assertEqual(
            identity["code_files"]["token_shards_v0"],
            sha((ROOT / "scripts/token_shards_v0.py").read_bytes()),
        )

    def test_empty_protected_registry_rejects_before_unresolved_candidate_refusal(self):
        from text_lab_corpus import validate_authority_index
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            shutil.copytree(ROOT / "data", root / "data")
            tools = root / "tools/ember-restart-3b"
            tools.mkdir(parents=True)
            for name in ("text_lab_corpus.py", "train.py", "run_vertical_slice.py"):
                shutil.copy2(ROOT / "tools/ember-restart-3b" / name, tools / name)
            (root / "scripts").mkdir(parents=True)
            shutil.copy2(ROOT / "scripts/token_shards_v0.py", root / "scripts/token_shards_v0.py")
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
            (root / "scripts").mkdir(parents=True)
            shutil.copy2(ROOT / "scripts/token_shards_v0.py", root / "scripts/token_shards_v0.py")
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
            (root / "scripts").mkdir(parents=True)
            shutil.copy2(ROOT / "scripts/token_shards_v0.py", root / "scripts/token_shards_v0.py")
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
            (root / "scripts").mkdir(parents=True)
            shutil.copy2(ROOT / "scripts/token_shards_v0.py", root / "scripts/token_shards_v0.py")
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
                run_vertical_slice.run_semantic(seed=1, artifact_root=ROOT / "unused", receipt_path=ROOT / "unused", shards_root=ROOT / "unused", tokenizer_path=ROOT / "unused", steps=1, sequence_length=1, checkpoint_interval=1, write_budget_bytes=1)

    def test_canonical_runner_refuses_terminal_unresolved_receipt_before_cuda_probe(self):
        import run_vertical_slice
        unresolved = {"result": "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING"}
        with patch.object(run_vertical_slice, "run_text_lab_preflight", return_value=unresolved), patch.object(run_vertical_slice.torch.cuda, "is_available", side_effect=AssertionError("CUDA reached")):
            with self.assertRaisesRegex(ValueError, "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING"):
                run_vertical_slice.run_semantic(seed=1, artifact_root=ROOT / "unused", receipt_path=ROOT / "unused", shards_root=ROOT / "unused", tokenizer_path=ROOT / "unused", steps=1, sequence_length=1, checkpoint_interval=1, write_budget_bytes=1)

    def test_manifest_requires_two_sources_all_domains_and_deterministic_splits(self):
        from text_lab_corpus import build_manifest, validate_manifest
        entries=[source(d,n) for d in DOMAINS for n in range(4)]
        manifest=build_manifest(entries, frozen_eval_hashes={sha(b"frozen eval")})
        self.assertEqual(tuple(manifest["domains"]), DOMAINS)
        self.assertEqual(validate_manifest(manifest, frozen_eval_hashes={sha(b"frozen eval")})["result"], "PREFLIGHT_ONLY")
        self.assertNotEqual(manifest["train_root_sha256"], manifest["heldout_root_sha256"])

    def test_manifest_requires_two_sources_in_each_split_for_every_domain(self):
        from text_lab_corpus import build_manifest
        entries = [source(domain, number) for domain in DOMAINS for number in range(2)]
    def test_manifest_accepts_verifier_bound_independent_origins_per_split(self):
        from text_lab_corpus import build_manifest, validate_manifest
        entries = [
            verified_source(domain, split, number, f"{domain}-{split}-origin-{number}")
            for domain in DOMAINS
            for split in ("train", "heldout")
            for number in range(2)
        ]
        manifest = build_manifest(entries, frozen_eval_hashes={sha(b"frozen eval")})
        self.assertEqual(validate_manifest(manifest, frozen_eval_hashes={sha(b"frozen eval")})["result"], "PREFLIGHT_ONLY")
        self.assertEqual({row["provenance_origin_id"] for row in manifest["sources"]}, {row["provenance_origin_id"] for row in entries})
        self.assertNotEqual(manifest["train_root_sha256"], manifest["heldout_root_sha256"])

        for entry in entries:
            entry["split"] = "train"
        with self.assertRaisesRegex(ValueError, "train.*heldout"):
            build_manifest(entries, frozen_eval_hashes=set())

    def test_admitted_manifest_resolves_canonical_raw_sources_in_stable_order(self):
        from text_lab_corpus import admitted_token_shard_sources, build_manifest
        with tempfile.TemporaryDirectory() as directory:
            raw_root = Path(directory)
            entries = []
            for domain in DOMAINS:
                for split in ("train", "heldout"):
                    for number in range(2):
                        row = verified_source(domain, split, number, f"{domain}-{split}-origin-{number}")
                        raw = (json.dumps({"text": f"{domain} {split} {number}"}, sort_keys=True) + "\n").encode("utf-8")
                        row["content_sha256"] = sha(raw)
                        row["l4_receipt"]["source_sha256"] = sha(raw)
                        (raw_root / f"{row['source_id']}.jsonl").write_bytes(raw)
                        entries.append(row)
            manifest = build_manifest(reversed(entries), frozen_eval_hashes=set())
            sources = admitted_token_shard_sources(manifest, raw_root=raw_root)
            self.assertEqual([name for name, _ in sources], sorted(row["source_id"] for row in entries))
            self.assertTrue(all(len(paths) == 1 and paths[0].parent == raw_root for _, paths in sources))
            self.assertEqual(
                [path.read_bytes() for _, paths in sources for path in paths],
                [(raw_root / f"{row['source_id']}.jsonl").read_bytes() for row in sorted(entries, key=lambda row: row["source_id"])],
            )

    def test_admitted_builder_passes_only_canonical_hash_bound_sources_to_token_shards(self):
        from text_lab_corpus import build_admitted_token_shards, build_manifest
        with tempfile.TemporaryDirectory() as directory:
            raw_root = Path(directory)
            entries = []
            for domain in DOMAINS:
                for split in ("train", "heldout"):
                    for number in range(2):
                        row = verified_source(domain, split, number, f"{domain}-{split}-origin-{number}")
                        raw = (json.dumps({"text": f"{domain} {split} {number}"}, sort_keys=True) + "\n").encode("utf-8")
                        row["content_sha256"] = sha(raw)
                        row["l4_receipt"]["source_sha256"] = sha(raw)
                        (raw_root / f"{row['source_id']}.jsonl").write_bytes(raw)
                        entries.append(row)
            manifest = build_manifest(reversed(entries), frozen_eval_hashes=set())
            observed = {}

            def shard_writer(*, sources, **kwargs):
                observed["sources"] = sources
                observed["kwargs"] = kwargs
                return {"ticket": "TOKEN-SHARDS-V0", "result": "MEASURED", "per_source": {name: {} for name, _ in sources}}

            result = build_admitted_token_shards(
                manifest,
                raw_root=raw_root,
                shard_writer=shard_writer,
                writer_kwargs={"out_dir": raw_root / "shards", "token_cap": 64},
            )
            self.assertEqual(result["result"], "MEASURED")
            self.assertEqual([name for name, _ in observed["sources"]], sorted(row["source_id"] for row in entries))
            self.assertEqual(observed["kwargs"], {
                "out_dir": raw_root / "shards",
                "token_cap": 64,
                "source_manifest_premise": {
                    "schema_version": "ember-text-lab-corpus-manifest-v2",
                    "sha256": sha(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")),
                    "source_ids": sorted(row["source_id"] for row in entries),
                    "train_root_sha256": manifest["train_root_sha256"],
                    "heldout_root_sha256": manifest["heldout_root_sha256"],
                },
            })

            def mismatched_writer(*, sources, **kwargs):
                return {"ticket": "TOKEN-SHARDS-V0", "result": "MEASURED", "per_source": {"wrong-source": {}}}

            with self.assertRaisesRegex(ValueError, "does not bind the canonical source set"):
                build_admitted_token_shards(
                    manifest,
                    raw_root=raw_root,
                    shard_writer=mismatched_writer,
                    writer_kwargs={"out_dir": raw_root / "shards", "token_cap": 64},
                )

    def test_admitted_sources_refuse_content_drift_and_malformed_jsonl_before_sharding(self):
        from text_lab_corpus import admitted_token_shard_sources, build_manifest
        with tempfile.TemporaryDirectory() as directory:
            raw_root = Path(directory)
            entries = []
            for domain in DOMAINS:
                for split in ("train", "heldout"):
                    for number in range(2):
                        row = verified_source(domain, split, number, f"{domain}-{split}-origin-{number}")
                        raw = (json.dumps({"text": f"{domain} {split} {number}"}, sort_keys=True) + "\n").encode("utf-8")
                        row["content_sha256"] = sha(raw)
                        row["l4_receipt"]["source_sha256"] = sha(raw)
                        (raw_root / f"{row['source_id']}.jsonl").write_bytes(raw)
                        entries.append(row)
            manifest = build_manifest(entries, frozen_eval_hashes=set())
            target = raw_root / f"{entries[0]['source_id']}.jsonl"
            target.write_bytes(b'{"text":"changed"}\n')
            with self.assertRaisesRegex(ValueError, "bytes do not match"):
                admitted_token_shard_sources(manifest, raw_root=raw_root)

            malformed = b'{"text":"unterminated"\n'
            target.write_bytes(malformed)
            entries[0]["content_sha256"] = sha(malformed)
            entries[0]["l4_receipt"]["source_sha256"] = sha(malformed)
            malformed_manifest = build_manifest(entries, frozen_eval_hashes=set())
            with self.assertRaisesRegex(ValueError, "valid UTF-8 JSONL"):
                admitted_token_shard_sources(malformed_manifest, raw_root=raw_root)

    def test_manifest_last_publication_cleans_interruption_and_retries_deterministically(self):
        import text_lab_corpus
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory) / "published"
            attempts = []

            def staged_build(manifest, *, raw_root, shard_writer, writer_kwargs):
                shard_dir = Path(writer_kwargs["out_dir"])
                shard_dir.mkdir(parents=True, exist_ok=True)
                (shard_dir / "v0-00000.bin").write_bytes(b"owned-token-bytes")
                attempts.append(shard_dir)
                if len(attempts) == 1:
                    raise RuntimeError("interrupted")
                return {"ticket": "TOKEN-SHARDS-V0", "result": "MEASURED", "per_source": {}, "shards": [{"name": "v0-00000.bin", "sha256": sha(b"owned-token-bytes"), "n_tokens": 8}]}

            with patch.object(text_lab_corpus, "build_admitted_token_shards", side_effect=staged_build):
                with self.assertRaisesRegex(RuntimeError, "interrupted"):
                    text_lab_corpus.publish_admitted_token_shards({}, raw_root=output_root, output_root=output_root, build_id="episode", shard_writer=object(), writer_kwargs={})
                self.assertFalse((output_root / ".episode.staging").exists())
                self.assertFalse((output_root / "episode").exists())
                result = text_lab_corpus.publish_admitted_token_shards({}, raw_root=output_root, output_root=output_root, build_id="episode", shard_writer=object(), writer_kwargs={})

            self.assertEqual(result["schema_version"], "ember-owned-text-shard-build-v1")
            self.assertEqual(result["build_id"], "episode")
            self.assertTrue((output_root / "episode" / "v0-00000.bin").is_file())
            self.assertTrue((output_root / "episode" / "build-receipt.json").is_file())
            self.assertTrue((output_root / "episode" / "token-shards-v0.json").is_file())
            self.assertEqual((output_root / "episode" / "v0-00000.bin").read_bytes(), b"owned-token-bytes")
            self.assertFalse((output_root / ".episode.staging").exists())

    def test_manifest_last_rebuild_is_byte_identical(self):
        import text_lab_corpus
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def staged_build(manifest, *, raw_root, shard_writer, writer_kwargs):
                shard_dir = Path(writer_kwargs["out_dir"])
                (shard_dir / "v0-00000.bin").write_bytes(b"deterministic-owned-bytes")
                return {"ticket": "TOKEN-SHARDS-V0", "result": "MEASURED", "per_source": {}, "shards": [{"name": "v0-00000.bin", "sha256": sha(b"deterministic-owned-bytes"), "n_tokens": 12}]}

            with patch.object(text_lab_corpus, "build_admitted_token_shards", side_effect=staged_build):
                first = text_lab_corpus.publish_admitted_token_shards({"stable": True}, raw_root=root, output_root=root / "one", build_id="episode", shard_writer=object(), writer_kwargs={})
                second = text_lab_corpus.publish_admitted_token_shards({"stable": True}, raw_root=root, output_root=root / "two", build_id="episode", shard_writer=object(), writer_kwargs={})

            self.assertEqual(first, second)
            self.assertEqual((root / "one" / "episode" / "build-receipt.json").read_bytes(), (root / "two" / "episode" / "build-receipt.json").read_bytes())
            self.assertEqual((root / "one" / "episode" / "v0-00000.bin").read_bytes(), (root / "two" / "episode" / "v0-00000.bin").read_bytes())

    def test_promoted_token_receipt_opens_canonical_semantic_stream_and_advances_cursor(self):
        import text_lab_corpus
        from semantic_stream import ManifestBoundTokenStream
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tokenizer = root / "tokenizer.json"
            tokenizer.write_text('{"model":{"vocab":{"a":0,"b":1,"c":2,"d":3,"e":4,"f":5,"g":6,"h":7,"i":8,"j":9,"k":10,"l":11,"m":12,"n":13}}}', encoding="utf-8")
            payload = b"\x08\x00\x09\x00\x0a\x00\x0b\x00\x0c\x00"
            token_hash = sha(tokenizer.read_bytes())

            def staged_build(manifest, *, raw_root, shard_writer, writer_kwargs):
                shard_dir = Path(writer_kwargs["out_dir"])
                (shard_dir / "v0-00000.bin").write_bytes(payload)
                return {"ticket": "TOKEN-SHARDS-V0", "result": "MEASURED", "per_source": {}, "shards": [{"name": "v0-00000.bin", "sha256": sha(payload), "n_tokens": 5}], "total_stream_tokens": 5, "premises": {"tokenizer_json": {"path": "tokenizer.json", "sha256": token_hash}}}

            with patch.object(text_lab_corpus, "build_admitted_token_shards", side_effect=staged_build):
                text_lab_corpus.publish_admitted_token_shards({}, raw_root=root, output_root=root / "out", build_id="episode", shard_writer=object(), writer_kwargs={})
            final = root / "out" / "episode"
            stream = ManifestBoundTokenStream.from_receipt(receipt_path=final / "token-shards-v0.json", shards_root=final, tokenizer_path=tokenizer)
            episode, cursor = stream.next_episode(shard_index=0, token_offset=0, sequence_length=4)
            self.assertEqual(episode["token_ids"], [8, 9, 10, 11])
            self.assertEqual(cursor, {"shard_index": 0, "token_offset": 4, "tokens_seen": 4})

    def test_source_custody_receipt_binds_raw_bytes_and_refuses_unpermitted_license(self):
        from text_lab_corpus import record_source_custody
        raw = b"<article><body>owned public text</body></article>"
        descriptor = {
            "source_id": "plos-pcbi-1007704",
            "domain": "scientific_method",
            "split": "train",
            "source_url": "https://example.invalid/source.xml",
            "license_spdx": "CC-BY-4.0",
            "provenance_origin_id": "doi:10.1371/journal.pcbi.1007704",
            "human_provenance_basis": "publisher supplied DOI metadata and license statement",
            "fetched_ts": "2026-07-23T09:50:39Z",
            "selection_rule": "direct-publication-human-provenance-v1",
            "expected_source_sha256": sha(raw),
            "expected_source_bytes": len(raw),
        }
        receipt = record_source_custody(
            descriptor=descriptor,
            raw_bytes=raw,
            license_evidence_bytes=b"CC-BY-4.0 license evidence",
            policy_bytes=b"local source policy v1",
            verifier_bytes=b"local XML verifier v1",
        )
        self.assertEqual(receipt["result"], "ACQUIRED_NOT_ADMITTED")
        self.assertEqual(receipt["source_sha256"], sha(raw))
        self.assertEqual(receipt["source_descriptor_sha256"], sha(json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode("utf-8")))
        self.assertNotIn("local_path", receipt)
        self.assertEqual(receipt, record_source_custody(
            descriptor=descriptor, raw_bytes=raw,
            license_evidence_bytes=b"CC-BY-4.0 license evidence",
            policy_bytes=b"local source policy v1", verifier_bytes=b"local XML verifier v1",
        ))
        restricted = dict(descriptor, license_spdx="Proprietary")
        with self.assertRaisesRegex(ValueError, "not permitted"):
            record_source_custody(
                descriptor=restricted, raw_bytes=raw,
                license_evidence_bytes=b"license", policy_bytes=b"policy", verifier_bytes=b"verifier",
            )

    def test_source_custody_file_rehashes_expected_bytes_without_path_in_receipt(self):
        from text_lab_corpus import record_source_custody_file
        raw = b"court-authored public record"
        descriptor = {
            "source_id": "courtlistener-scotus-caption", "domain": "application_worlds", "split": "train",
            "source_url": "https://example.invalid/court.csv", "license_spdx": "PDDL-1.0",
            "provenance_origin_id": "courtlistener:scotus-caption",
            "human_provenance_basis": "court-authored opinion metadata", "fetched_ts": "2026-07-06T17:09:00Z",
            "selection_rule": "supreme-court opinions set", "expected_source_sha256": sha(raw),
            "expected_source_bytes": len(raw),
        }
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "court.csv"
            payload.write_bytes(raw)
            receipt = record_source_custody_file(
                descriptor=descriptor, raw_path=payload, license_evidence_bytes=b"receipt entry",
                policy_bytes=b"local source policy v1", verifier_bytes=b"local CSV verifier v1",
            )
        self.assertEqual(receipt["source_sha256"], sha(raw))
        self.assertEqual(receipt["source_bytes"], len(raw))
        self.assertNotIn("raw_path", receipt)

    def test_source_inventory_closes_receipted_wave_entry_and_blocks_unspecified_license(self):
        from text_lab_corpus import source_inventory_descriptor
        raw = b"court-authored public record"
        entry = {
            "source_url": "https://example.invalid/court.csv",
            "sha256": sha(raw),
            "bytes": len(raw),
            "license": "public domain",
            "human_provenance_basis": "court-authored opinion metadata",
            "fetched_ts": "2026-07-06T17:09:00Z",
            "selection_rule": "supreme-court opinions set",
        }
        descriptor = source_inventory_descriptor(
            source_id="courtlistener-scotus-caption", domain="application_worlds", split="train",
            provenance_origin_id="courtlistener:scotus-caption", receipt_entry=entry,
        )
        self.assertEqual(descriptor["license_spdx"], "PDDL-1.0")
        self.assertEqual(descriptor["expected_source_sha256"], sha(raw))
        self.assertEqual(descriptor["expected_source_bytes"], len(raw))
        self.assertEqual(descriptor["selection_rule"], "supreme-court opinions set")
        blocked = dict(entry, license="unspecified")
        with self.assertRaisesRegex(ValueError, "license is not permitted"):
            source_inventory_descriptor(
                source_id="blocked", domain="application_worlds", split="heldout",
                provenance_origin_id="blocked-origin", receipt_entry=blocked,
            )

    def test_source_inventory_normalizes_existing_gutenberg_receipt_encoding(self):
        from text_lab_corpus import source_inventory_descriptor
        entry = {
            "source_url": "https://www.gutenberg.org",
            "sha256": "A" * 64,
            "bytes": 12,
            "license": "Public Domain",
            "human_provenance_basis": "pre-copyright human literature (Project Gutenberg)",
            "fetched_ts": "2026-07-07T00:33:11.0367122Z",
            "selection_rule": "catalog language != en, plain-text",
        }
        descriptor = source_inventory_descriptor(
            source_id="gutenberg-1000", domain="application_worlds", split="heldout",
            provenance_origin_id="gutenberg:1000", receipt_entry=entry,
        )
        self.assertEqual(descriptor["expected_source_sha256"], "a" * 64)
        self.assertEqual(descriptor["license_spdx"], "PDDL-1.0")
        self.assertEqual(descriptor["fetched_ts"], "2026-07-07T00:33:11Z")

    def test_pre_admission_transform_is_deterministic_resumable_and_rejects_cross_split_overlap(self):
        from text_lab_corpus import build_pre_admission_text_tranche, iter_pre_admission_text_records, record_source_custody_file
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            train = root / "gutenberg.txt"; heldout = root / "court.csv"
            train.write_text("alpha\n\nbeta\n\n gamma \n", encoding="utf-8")
            heldout.write_text("case_name,citations\nDelta v. State,1 U.S. 1\nOmega v. City,2 U.S. 2\n", encoding="utf-8")
            def descriptor(source_id, split, payload, transform):
                return {
                    "source_id": source_id, "domain": "application_worlds", "split": split,
                    "source_url": f"https://example.invalid/{source_id}", "license_spdx": "PDDL-1.0",
                    "provenance_origin_id": f"origin:{source_id}", "human_provenance_basis": "human authored public record",
                    "fetched_ts": "2026-07-07T00:00:00Z", "selection_rule": transform,
                    "expected_source_sha256": sha(payload), "expected_source_bytes": len(payload),
                }
            train_descriptor = descriptor("gutenberg-1000", "train", train.read_bytes(), "utf8_nonblank_lines_v1")
            heldout_descriptor = descriptor("courtlistener-caption", "heldout", heldout.read_bytes(), "csv_case_citation_v1")
            receipts = {
                "gutenberg-1000": record_source_custody_file(descriptor=train_descriptor, raw_path=train, license_evidence_bytes=b"pd", policy_bytes=b"policy", verifier_bytes=b"verifier"),
                "courtlistener-caption": record_source_custody_file(descriptor=heldout_descriptor, raw_path=heldout, license_evidence_bytes=b"pd", policy_bytes=b"policy", verifier_bytes=b"verifier"),
            }
            sources = [
                {"source_id": "courtlistener-caption", "split": "heldout", "transform_id": "csv_case_citation_v1"},
                {"source_id": "gutenberg-1000", "split": "train", "transform_id": "utf8_nonblank_lines_v1"},
            ]
            full = list(iter_pre_admission_text_records(sources=sources, raw_paths={"gutenberg-1000": train, "courtlistener-caption": heldout}, source_custody_receipts=receipts))
            first, cursor = next(iter_pre_admission_text_records(sources=sources, raw_paths={"gutenberg-1000": train, "courtlistener-caption": heldout}, source_custody_receipts=receipts, emit_cursor=True))
            resumed = [first] + list(iter_pre_admission_text_records(sources=sources, raw_paths={"gutenberg-1000": train, "courtlistener-caption": heldout}, source_custody_receipts=receipts, cursor=cursor))
            self.assertEqual(full, resumed)
            one = build_pre_admission_text_tranche(sources=sources, raw_paths={"gutenberg-1000": train, "courtlistener-caption": heldout}, source_custody_receipts=receipts, output_root=root / "one", build_id="episode")
            two = build_pre_admission_text_tranche(sources=list(reversed(sources)), raw_paths={"gutenberg-1000": train, "courtlistener-caption": heldout}, source_custody_receipts=receipts, output_root=root / "two", build_id="episode")
            self.assertEqual(one, two)
            self.assertEqual((root / "one" / "episode" / "train.jsonl").read_bytes(), (root / "two" / "episode" / "train.jsonl").read_bytes())
            self.assertEqual((root / "one" / "episode" / "manifest.json").read_bytes(), (root / "two" / "episode" / "manifest.json").read_bytes())
            heldout.write_text("case_name,citations\nalpha,\n", encoding="utf-8")
            bad_receipt = record_source_custody_file(descriptor=descriptor("courtlistener-caption", "heldout", heldout.read_bytes(), "csv_case_citation_v1"), raw_path=heldout, license_evidence_bytes=b"pd", policy_bytes=b"policy", verifier_bytes=b"verifier")
            with self.assertRaisesRegex(ValueError, "cross-split duplicate"):
                build_pre_admission_text_tranche(sources=sources, raw_paths={"gutenberg-1000": train, "courtlistener-caption": heldout}, source_custody_receipts={**receipts, "courtlistener-caption": bad_receipt}, output_root=root / "bad", build_id="episode")
            train.write_text("alpha\nalpha\n", encoding="utf-8")
            heldout.write_text("case_name,citations\nDelta v. State,1 U.S. 1\nOmega v. City,2 U.S. 2\n", encoding="utf-8")
            duplicate_receipt = record_source_custody_file(descriptor=descriptor("gutenberg-1000", "train", train.read_bytes(), "utf8_nonblank_lines_v1"), raw_path=train, license_evidence_bytes=b"pd", policy_bytes=b"policy", verifier_bytes=b"verifier")
            restored_heldout_receipt = record_source_custody_file(descriptor=descriptor("courtlistener-caption", "heldout", heldout.read_bytes(), "csv_case_citation_v1"), raw_path=heldout, license_evidence_bytes=b"pd", policy_bytes=b"policy", verifier_bytes=b"verifier")
            deduplicated = build_pre_admission_text_tranche(sources=sources, raw_paths={"gutenberg-1000": train, "courtlistener-caption": heldout}, source_custody_receipts={**receipts, "gutenberg-1000": duplicate_receipt, "courtlistener-caption": restored_heldout_receipt}, output_root=root / "same-split", build_id="episode")
            self.assertEqual(deduplicated["train_record_count"], 1)
    def test_l4_admission_binds_pre_admission_manifest_and_refuses_custody_drift(self):
        from text_lab_corpus import admit_pre_admission_text_tranche, build_pre_admission_text_tranche, record_source_custody_file
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            train = root / "train.txt"; heldout = root / "heldout.txt"
            train.write_text("human authored train\n", encoding="utf-8")
            heldout.write_text("human authored heldout\n", encoding="utf-8")
            def descriptor(source_id, split, path):
                payload = path.read_bytes()
                return {
                    "source_id": source_id, "domain": "application_worlds", "split": split,
                    "source_url": f"https://example.invalid/{source_id}", "license_spdx": "PDDL-1.0",
                    "provenance_origin_id": f"origin:{source_id}", "human_provenance_basis": "human public record",
                    "fetched_ts": "2026-07-07T00:00:00Z", "selection_rule": "rule based text selection",
                    "expected_source_sha256": sha(payload), "expected_source_bytes": len(payload),
                }
            receipts = {
                "train": record_source_custody_file(descriptor=descriptor("train", "train", train), raw_path=train, license_evidence_bytes=b"pd", policy_bytes=b"policy", verifier_bytes=b"verifier"),
                "heldout": record_source_custody_file(descriptor=descriptor("heldout", "heldout", heldout), raw_path=heldout, license_evidence_bytes=b"pd", policy_bytes=b"policy", verifier_bytes=b"verifier"),
            }
            sources = [
                {"source_id": "train", "split": "train", "transform_id": "utf8_nonblank_lines_v1"},
                {"source_id": "heldout", "split": "heldout", "transform_id": "utf8_nonblank_lines_v1"},
            ]
            build_pre_admission_text_tranche(sources=sources, raw_paths={"train": train, "heldout": heldout}, source_custody_receipts=receipts, output_root=root / "tranche", build_id="bounded", max_records_per_source=1)
            admitted = admit_pre_admission_text_tranche(tranche_root=root / "tranche" / "bounded", source_custody_receipts=receipts, policy_bytes=b"l4-policy", verifier_bytes=b"l4-verifier")
            self.assertEqual(admitted["result"], "VERIFIED")
            self.assertEqual(admitted["train_record_count"], 1)
            self.assertEqual(admitted["heldout_record_count"], 1)
            changed = dict(receipts["train"], source_sha256="0" * 64)
            with self.assertRaisesRegex(ValueError, "custody receipt"):
                admit_pre_admission_text_tranche(tranche_root=root / "tranche" / "bounded", source_custody_receipts={**receipts, "train": changed}, policy_bytes=b"l4-policy", verifier_bytes=b"l4-verifier")

    def test_rejects_single_source_bad_l4_duplicate_or_eval_contamination(self):
        entries=[source(d,n) for d in DOMAINS for n in range(4)]
        from text_lab_corpus import build_manifest
        with self.assertRaisesRegex(ValueError,"two sources in train"): build_manifest(entries[:-1], frozen_eval_hashes=set())
        bad=[dict(x) for x in entries]; bad[0]["license_spdx"]="Proprietary"
        with self.assertRaisesRegex(ValueError,"license"): build_manifest(bad, frozen_eval_hashes=set())
        duplicate=[dict(x) for x in entries]; duplicate[1]["content_sha256"]=duplicate[0]["content_sha256"]
        with self.assertRaisesRegex(ValueError,"duplicate"): build_manifest(duplicate, frozen_eval_hashes=set())
        with self.assertRaisesRegex(ValueError,"frozen eval"): build_manifest(entries, frozen_eval_hashes={entries[0]["content_sha256"]})
if __name__ == "__main__": unittest.main()