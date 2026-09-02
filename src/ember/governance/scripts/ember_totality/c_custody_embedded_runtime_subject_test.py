#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression for self-contained receipts that hash an ephemeral runtime subject."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
MISSING_REF = "receipts/ember-cli/issue-1043-text-wrap/ember.exe"
SUBJECT_RECEIPT = "receipts/ember-cli/issue-1043-text-wrap/capture-receipt.json"
SUBJECT_RECEIPT_SHA256 = "0c856572684b449427d493dd38a1d8c2faa0f959e47890c7be323fc06dd0ba43"
BINARY_SHA256 = "1181f882bdb71e329ff185f0939b9cc352b75e1bd6f106b25ec989915653ad5c"


def _load_probe():
    spec = importlib.util.spec_from_file_location(
        "c_custody_probe", ROOT / "scripts" / "ember_totality" / "test_c_custody.py"
    )
    assert spec and spec.loader
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    return probe


def _record() -> dict[str, object]:
    return {
        "schema_version": "ember-c-custody-embedded-runtime-subject/v1",
        "missing_ref": MISSING_REF,
        "subject_receipt": SUBJECT_RECEIPT,
        "subject_receipt_sha256": SUBJECT_RECEIPT_SHA256,
        "binary_sha256": BINARY_SHA256,
        "classification": "EPHEMERAL_COMPILED_TEST_SUBJECT",
        "reason": "the self-contained capture receipt embeds the compiled subject hash and frames",
    }


def test_hash_bound_self_contained_runtime_subject_resolves() -> None:
    probe = _load_probe()
    assert probe._resolve_embedded_runtime_subject(
        MISSING_REF, [_record()], {SUBJECT_RECEIPT}, ROOT
    ) == {
        "ref": MISSING_REF,
        "subject_receipt": SUBJECT_RECEIPT,
        "subject_receipt_sha256": SUBJECT_RECEIPT_SHA256,
        "binary_sha256": BINARY_SHA256,
        "classification": "EPHEMERAL_COMPILED_TEST_SUBJECT",
    }


def test_wrong_receipt_or_binary_hash_fails_closed() -> None:
    probe = _load_probe()
    wrong_receipt = {**_record(), "subject_receipt_sha256": "0" * 64}
    wrong_binary = {**_record(), "binary_sha256": "0" * 64}
    assert probe._resolve_embedded_runtime_subject(
        MISSING_REF, [wrong_receipt], {SUBJECT_RECEIPT}, ROOT
    ) is None
    assert probe._resolve_embedded_runtime_subject(
        MISSING_REF, [wrong_binary], {SUBJECT_RECEIPT}, ROOT
    ) is None


def test_duplicate_or_traversing_authority_fails_closed() -> None:
    probe = _load_probe()
    duplicate = [_record(), _record()]
    traversing = {**_record(), "missing_ref": "receipts/../ember.exe"}
    mixed_slash = {**_record(), "subject_receipt": r"receipts/ember-cli\..\capture.json"}
    assert probe._resolve_embedded_runtime_subject(
        MISSING_REF, duplicate, {SUBJECT_RECEIPT}, ROOT
    ) is None
    assert probe._resolve_embedded_runtime_subject(
        "receipts/../ember.exe", [traversing], {SUBJECT_RECEIPT}, ROOT
    ) is None
    assert probe._resolve_embedded_runtime_subject(
        MISSING_REF, [mixed_slash], {mixed_slash["subject_receipt"]}, ROOT
    ) is None
