#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Architecture identity lint for the selected documentation subject.

v2 is a minimal selected architecture identity. The frozen v1 record keeps its
historical cursor, parameter and evidence semantics. This lint verifies selection
and architecture; it grants no checkpoint acceptance, capability or run credit.
Generator integration and the real manifest baseline are separate required legs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

AUTHORITY = {
    "goal_id": "EMBER-02",
    "workstream_id": "EMBER-02A",
    "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
}
SCHEMA = "ember-current-subject-v2"
MAX_METADATA_BYTES = 16 * 1024 * 1024
SHA = re.compile(r"^[0-9a-f]{64}$")

class BindingError(ValueError):
    pass

def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BindingError("AMBIGUOUS_JSON_FIELD:" + key)
        result[key] = value
    return result

def decode(raw, role):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_METADATA_BYTES:
        raise BindingError("METADATA_SIZE:" + role)
    try:
        doc = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
    except BindingError:
        raise
    except (UnicodeError, ValueError) as exc:
        raise BindingError("METADATA_JSON:" + role) from exc
    if not isinstance(doc, dict):
        raise BindingError("METADATA_OBJECT:" + role)
    return doc

def digest(value, role):
    if not isinstance(value, str) or SHA.fullmatch(value) is None:
        raise BindingError("MISSING_OR_INVALID_SHA256:" + role)
    return value

def architecture(value, role):
    if not isinstance(value, str) or not value or value != value.strip():
        raise BindingError("MISSING_OR_INVALID_ARCHITECTURE:" + role)
    return value

def load_subject(raw):
    doc = decode(raw, "canonical_subject")
    if set(doc) != {"schema_version", "authority", "subject"}:
        raise BindingError("CANONICAL_SUBJECT_ROOT_FIELDS")
    if doc["schema_version"] != SCHEMA:
        raise BindingError("CANONICAL_SUBJECT_SCHEMA")
    if doc["authority"] != AUTHORITY:
        raise BindingError("CANONICAL_SUBJECT_AUTHORITY")
    subject = doc["subject"]
    if not isinstance(subject, dict) or set(subject) != {
        "architecture_revision", "checkpoint_manifest_sha256"
    }:
        raise BindingError("CANONICAL_SUBJECT_FIELDS")
    architecture(subject["architecture_revision"], "canonical_subject")
    digest(subject["checkpoint_manifest_sha256"], "canonical_subject")
    return doc

def lint_selected_architecture(subject_raw, pointer_raw, manifest_raw, expected_pointer_sha256):
    subject = load_subject(subject_raw)["subject"]
    expected = digest(expected_pointer_sha256, "approved_selected_pointer")
    actual_pointer = hashlib.sha256(pointer_raw).hexdigest()
    if actual_pointer != expected:
        raise BindingError("SELECTED_POINTER_SHA256_MISMATCH")
    pointer = decode(pointer_raw, "selected_pointer")
    if pointer.get("schema") != "ember-selected-continuation-head-v1":
        raise BindingError("SELECTED_POINTER_SCHEMA")
    selected = digest(pointer.get("lineage_checkpoint_manifest_sha256"), "selected_pointer")
    actual_manifest = hashlib.sha256(manifest_raw).hexdigest()
    if actual_manifest != selected:
        raise BindingError("SELECTED_MANIFEST_SHA256_MISMATCH")
    if subject["checkpoint_manifest_sha256"] != selected:
        raise BindingError("CANONICAL_SUBJECT_SELECTED_HEAD_MISMATCH")
    manifest = decode(manifest_raw, "selected_manifest")
    revision = architecture(manifest.get("architecture_revision"), "selected_manifest")
    if subject["architecture_revision"] != revision:
        raise BindingError("CANONICAL_SUBJECT_ARCHITECTURE_MISMATCH")
    return {
        "schema": "ember-continuity-selected-architecture-lint-v1",
        "status": "PASS_ARCHITECTURE_IDENTITY_ONLY",
        "selected_pointer_sha256": actual_pointer,
        "checkpoint_manifest_sha256": actual_manifest,
        "architecture_revision": revision,
        "checkpoint_acceptance": "UNDETERMINED",
        "capability_credit": "none",
    }

def one(values, role):
    if values is None or len(values) != 1:
        raise BindingError("MISSING_OR_AMBIGUOUS_BINDING:" + role)
    return values[0]

def bounded_read(path, role):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_METADATA_BYTES + 1)
    except OSError as exc:
        raise BindingError("MISSING_BINDING_FILE:" + role) from exc
    if not raw or len(raw) > MAX_METADATA_BYTES:
        raise BindingError("METADATA_SIZE:" + role)
    return raw

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("canonical-subject", "selected-pointer", "selected-manifest", "selected-pointer-sha256"):
        parser.add_argument("--" + flag, action="append")
    args = parser.parse_args(argv)
    try:
        result = lint_selected_architecture(
            bounded_read(one(args.canonical_subject, "canonical_subject"), "canonical_subject"),
            bounded_read(one(args.selected_pointer, "selected_pointer"), "selected_pointer"),
            bounded_read(one(args.selected_manifest, "selected_manifest"), "selected_manifest"),
            one(args.selected_pointer_sha256, "approved_selected_pointer"),
        )
    except BindingError as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
