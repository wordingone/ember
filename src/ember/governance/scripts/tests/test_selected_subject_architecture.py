"""Prepared selected architecture reds/green; not executed during GPU window."""
import hashlib
import json
import unittest
from selected_subject_architecture import (
    AUTHORITY, SCHEMA, BindingError, lint_selected_architecture, one
)

def raw(doc):
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")

class SelectedArchitectureTests(unittest.TestCase):
    def fixture(self, revision="CIA3-R1-N61"):
        manifest = raw({"architecture_revision": "CIA3-R1-N61", "fixture": True})
        manifest_sha = hashlib.sha256(manifest).hexdigest()
        pointer = raw({"schema": "ember-selected-continuation-head-v1",
                       "lineage_checkpoint_manifest_sha256": manifest_sha})
        subject = raw({"schema_version": SCHEMA, "authority": AUTHORITY,
                       "subject": {"checkpoint_manifest_sha256": manifest_sha,
                                   "architecture_revision": revision}})
        return subject, pointer, manifest, hashlib.sha256(pointer).hexdigest()

    def test_green_exact_manifest_architecture(self):
        result = lint_selected_architecture(*self.fixture())
        self.assertEqual(result["status"], "PASS_ARCHITECTURE_IDENTITY_ONLY")
        self.assertEqual(result["architecture_revision"], "CIA3-R1-N61")

    def test_otherwise_valid_subject_wrong_architecture(self):
        with self.assertRaisesRegex(BindingError, "^CANONICAL_SUBJECT_ARCHITECTURE_MISMATCH$"):
            lint_selected_architecture(*self.fixture("ember-sparse-3b-v2"))

    def test_changed_manifest_bytes_fail_whole_digest(self):
        subject, pointer, manifest, pin = self.fixture()
        with self.assertRaisesRegex(BindingError, "^SELECTED_MANIFEST_SHA256_MISMATCH$"):
            lint_selected_architecture(subject, pointer, manifest + b" ", pin)

    def test_modified_pointer_fails_exact_owner_pin(self):
        subject, pointer, manifest, pin = self.fixture()
        with self.assertRaisesRegex(BindingError, "^SELECTED_POINTER_SHA256_MISMATCH$"):
            lint_selected_architecture(subject, pointer + b" ", manifest, pin)

    def test_subject_different_selected_head_fails(self):
        subject, pointer, manifest, pin = self.fixture()
        doc = json.loads(subject)
        doc["subject"]["checkpoint_manifest_sha256"] = "f" * 64
        with self.assertRaisesRegex(BindingError, "^CANONICAL_SUBJECT_SELECTED_HEAD_MISMATCH$"):
            lint_selected_architecture(raw(doc), pointer, manifest, pin)

    def test_missing_manifest_architecture_explicit(self):
        manifest = raw({"fixture": True})
        sha = hashlib.sha256(manifest).hexdigest()
        pointer = raw({"schema": "ember-selected-continuation-head-v1",
                       "lineage_checkpoint_manifest_sha256": sha})
        subject = raw({"schema_version": SCHEMA, "authority": AUTHORITY,
                       "subject": {"checkpoint_manifest_sha256": sha,
                                   "architecture_revision": "CIA3-R1-N61"}})
        with self.assertRaisesRegex(BindingError, "^MISSING_OR_INVALID_ARCHITECTURE:selected_manifest$"):
            lint_selected_architecture(subject, pointer, manifest, hashlib.sha256(pointer).hexdigest())

    def test_ambiguous_json_architecture_rejected(self):
        manifest = b'{"architecture_revision":"CIA3-R1-N61","architecture_revision":"v2"}'
        sha = hashlib.sha256(manifest).hexdigest()
        pointer = raw({"schema": "ember-selected-continuation-head-v1",
                       "lineage_checkpoint_manifest_sha256": sha})
        subject = raw({"schema_version": SCHEMA, "authority": AUTHORITY,
                       "subject": {"checkpoint_manifest_sha256": sha,
                                   "architecture_revision": "CIA3-R1-N61"}})
        with self.assertRaisesRegex(BindingError, "^AMBIGUOUS_JSON_FIELD:architecture_revision$"):
            lint_selected_architecture(subject, pointer, manifest, hashlib.sha256(pointer).hexdigest())

    def test_missing_and_ambiguous_command_binding_explicit(self):
        for values in (None, [], ["first", "second"]):
            with self.subTest(values=values):
                with self.assertRaisesRegex(BindingError, "^MISSING_OR_AMBIGUOUS_BINDING:manifest$"):
                    one(values, "manifest")

    def test_config_only_document_without_selected_pointer_fails(self):
        subject, pointer, manifest, pin = self.fixture()
        config = raw({"architecture_revision": "CIA3-R1-N61"})
        with self.assertRaisesRegex(BindingError, "^SELECTED_POINTER_SHA256_MISMATCH$"):
            lint_selected_architecture(subject, config, manifest, pin)

if __name__ == "__main__":
    unittest.main()
