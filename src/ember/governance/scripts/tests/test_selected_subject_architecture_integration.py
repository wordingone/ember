# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Generator/writer integration for canonical CIA architecture identity."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "src/ember/governance/scripts"))
import gen_readme_status as gen
import update_current_subject as writer
from selected_subject_architecture import AUTHORITY, SCHEMA, BindingError, bounded_read

class ArchitectureIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / "checkpoint-manifest.json"
        self.manifest.write_text(json.dumps({"architecture_revision": "CIA3-R1-N61", "synthetic": True}))
        self.manifest_sha = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        self.pointer = self.root / "pointer.json"
        self.pointer.write_text(json.dumps({"schema": "ember-selected-continuation-head-v1",
            "lineage_checkpoint_manifest_sha256": self.manifest_sha}))
        self.pointer_sha = hashlib.sha256(self.pointer.read_bytes()).hexdigest()
        self.payload = {"schema_version": SCHEMA, "authority": AUTHORITY,
            "subject": {"architecture_revision": "CIA3-R1-N61",
                        "checkpoint_manifest_sha256": self.manifest_sha}}
        self.subject = self.root / "subject.json"
        self.subject.write_text(json.dumps(self.payload))
        self.bindings = {"pointer": [self.pointer], "manifest": [self.manifest],
                         "pointer_sha256": [self.pointer_sha]}

    def test_generator_green_uses_full_metadata(self):
        payload = gen.load_current_subject(self.subject)
        result = gen.validate_current_subject_evidence(payload, ROOT, self.bindings)
        rendered = gen.render_current_subject_block(payload, result)
        self.assertIn("CIA3-R1-N61", rendered)
        self.assertIn(self.manifest_sha, rendered)

    def test_generator_valid_wrong_architecture_fails_before_render(self):
        self.payload["subject"]["architecture_revision"] = "ember-sparse-3b-v2"
        self.subject.write_text(json.dumps(self.payload))
        payload = gen.load_current_subject(self.subject)
        with self.assertRaisesRegex(BindingError, "^CANONICAL_SUBJECT_ARCHITECTURE_MISMATCH$"):
            gen.validate_current_subject_evidence(payload, ROOT, self.bindings)

    def test_generator_missing_and_ambiguous_bindings_refuse(self):
        for bindings in (None, {**self.bindings, "pointer": [self.pointer, self.pointer]}):
            with self.subTest(bindings=bindings):
                with self.assertRaisesRegex(BindingError, "^MISSING_OR_AMBIGUOUS_BINDING:selected_pointer$"):
                    gen.validate_current_subject_evidence(self.payload, ROOT, bindings)

    def test_missing_manifest_explicit(self):
        with self.assertRaisesRegex(BindingError, "^MISSING_BINDING_FILE:selected_manifest$"):
            bounded_read(self.root / "absent.json", "selected_manifest")

    def test_v1_historical_parse_render_regression(self):
        payload = gen.load_current_subject(ROOT / "manifests/ember-current-subject-v1.json")
        self.assertEqual(payload["schema_version"], "ember-current-subject-v1")
        gen.validate_current_subject_evidence(payload, ROOT)
        self.assertIn("Historical v2 checkpoint snapshot", gen.render_current_subject_block(payload))
        self.assertEqual(payload["subject"]["predecessor"]["relationship"], "historical_step1_predecessor")

    def write(self, payload=None, expected="GENESIS", target=None):
        return writer.update_current_subject(
            repo_root=ROOT, published_checkpoint_root=self.root,
            candidate_payload=payload or self.payload,
            expected_parent_checkpoint_manifest_sha256=expected,
            current_subject_path=target or self.root / "canonical.json",
            selected_pointer=self.pointer, selected_pointer_sha256=self.pointer_sha)

    def test_writer_verifies_declared_digest_without_predecessor(self):
        result = self.write()
        self.assertEqual(result["subject"]["checkpoint_manifest_sha256"], self.manifest_sha)
        self.assertNotIn("predecessor", result["subject"])
        self.assertEqual(gen.load_current_subject(self.root / "canonical.json"), result)

    def test_writer_wrong_architecture_refuses_unchanged_target(self):
        self.write()
        before = (self.root / "canonical.json").read_bytes()
        self.payload["subject"]["architecture_revision"] = "ember-sparse-3b-v2"
        with self.assertRaisesRegex(ValueError, "^CANONICAL_SUBJECT_ARCHITECTURE_MISMATCH$"):
            self.write(expected=self.manifest_sha)
        self.assertEqual((self.root / "canonical.json").read_bytes(), before)

    def test_writer_stale_parent_refuses_unchanged_target(self):
        self.write()
        before = (self.root / "canonical.json").read_bytes()
        with self.assertRaises(writer.StaleParentError):
            self.write(expected="f" * 64)
        self.assertEqual((self.root / "canonical.json").read_bytes(), before)

    def cli(self, candidate_path, schema="ember-current-subject-v2"):
        argv = ["--root", str(ROOT), "--published-checkpoint-root", str(self.root),
                "--candidate-payload", str(candidate_path),
                "--expected-parent-checkpoint-manifest-sha256", self.manifest_sha,
                "--current-subject-path", str(self.root / "canonical.json"),
                "--selected-pointer", str(self.pointer),
                "--selected-pointer-sha256", self.pointer_sha]
        if schema is not None:
            argv += ["--candidate-schema", schema]
        return writer.main(argv)

    def test_writer_cli_valid_raw_v2_green(self):
        self.write()
        self.assertEqual(self.cli(self.subject), 0)

    def test_writer_cli_v2_without_raw_schema_refuses_unchanged(self):
        self.write()
        before = (self.root / "canonical.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "^V2_CANDIDATE_REQUIRES_EXPLICIT_RAW_SCHEMA$"):
            self.cli(self.subject, None)
        self.assertEqual((self.root / "canonical.json").read_bytes(), before)

    def assert_duplicate_refuses(self, field, first):
        self.write()
        target = self.root / "canonical.json"
        before = target.read_bytes()
        raw = json.dumps(self.payload)
        value = self.payload["schema_version"] if field == "schema_version" else self.payload["subject"][field]
        needle = json.dumps(field) + ": " + json.dumps(value)
        replacement = json.dumps(field) + ": " + json.dumps(first) + ", " + needle
        self.assertIn(needle, raw)
        raw = raw.replace(needle, replacement, 1)
        candidate = self.root / "duplicate-candidate.json"
        candidate.write_text(raw)
        with self.assertRaisesRegex(BindingError, "^AMBIGUOUS_JSON_FIELD:" + field + "$"):
            self.cli(candidate)
        self.assertEqual(target.read_bytes(), before)

    def test_writer_cli_duplicate_digest_target_unchanged(self):
        self.assert_duplicate_refuses("checkpoint_manifest_sha256", "0" * 64)

    def test_writer_cli_duplicate_architecture_target_unchanged(self):
        self.assert_duplicate_refuses("architecture_revision", "ember-sparse-3b-v2")

    def test_writer_cli_duplicate_root_target_unchanged(self):
        self.assert_duplicate_refuses("schema_version", "ember-current-subject-v1")

    def test_writer_one_hex_off_head_refuses_unchanged_target(self):
        self.write()
        before = (self.root / "canonical.json").read_bytes()
        first = "0" if self.manifest_sha[0] != "0" else "1"
        self.payload["subject"]["checkpoint_manifest_sha256"] = first + self.manifest_sha[1:]
        with self.assertRaisesRegex(ValueError, "^CANONICAL_SUBJECT_SELECTED_HEAD_MISMATCH$"):
            self.write(expected=self.manifest_sha)
        self.assertEqual((self.root / "canonical.json").read_bytes(), before)

    def test_v1_main_nondefault_root_passes_resolved_target(self):
        from unittest.mock import patch
        candidate = {"schema_version": "ember-current-subject-v1", "subject": {}}
        candidate_path = self.root / "v1-candidate.json"
        candidate_path.write_text(json.dumps(candidate))
        returned = {"schema_version": "ember-current-subject-v1",
                    "subject": {"checkpoint_manifest_sha256": "a" * 64}}
        with patch.object(writer, "update_current_subject", return_value=returned) as consumer:
            self.assertEqual(writer.main(["--root", str(self.root),
                "--published-checkpoint-root", str(self.root),
                "--candidate-payload", str(candidate_path),
                "--expected-parent-checkpoint-manifest-sha256", "GENESIS"]), 0)
        self.assertEqual(consumer.call_args.kwargs["repo_root"], self.root.resolve())
        self.assertEqual(consumer.call_args.kwargs["current_subject_path"],
                         self.root.resolve() / "manifests/ember-current-subject-v1.json")

    def test_writer_verify_only_v2_has_no_v1_field_assumption(self):
        self.write()
        self.assertEqual(writer.main(["--root", str(ROOT), "--current-subject-path",
                                     str(self.root / "canonical.json"), "--verify-only"]), 0)

    def test_writer_cannot_overwrite_historical_v1(self):
        with self.assertRaisesRegex(ValueError, "^V2_CANNOT_OVERWRITE_HISTORICAL_V1$"):
            self.write(target=self.root / "ember-current-subject-v1.json")
        self.assertFalse((self.root / "ember-current-subject-v1.json").exists())

if __name__ == "__main__":
    unittest.main()
