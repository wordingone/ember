#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed byte/line bindings for the Wave 31 custody dispositions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "custody-disposition-20260731-wave031.md"
REGISTRY = (
    ROOT
    / "receipts"
    / "ember-01-custody"
    / "documented-absent-custody-dispositions-wave031-v1.json"
)
PROOF = ROOT / "receipts" / "proof-growth-identity-20260702T064211Z.json"


def test_disposition_registry_binds_exact_document_lines() -> None:
    doc_bytes = DOC.read_bytes()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert hashlib.sha256(doc_bytes).hexdigest() == registry["source_document_sha256"]
    lines = doc_bytes.decode("utf-8").splitlines()
    rows = registry["documented_absent"]
    assert len(rows) == 9
    assert {row["disposition_class"] for row in rows} == {
        "CROSS_LINEAGE_CONTENT_RAIL_BARRED",
        "DECLARED_HASH_ZERO_GIT_TRACE",
    }
    for row in rows:
        line = lines[row["line"] - 1]
        assert row["ref"] in line
        assert row["marker"] in line


def test_restored_growth_identity_receipt_is_exact_historical_object() -> None:
    assert hashlib.sha256(PROOF.read_bytes()).hexdigest() == (
        "34c0a350a885efc339325e04f714ecda1366958e4d4f88dff41b10ad75010f22"
    )
    proof = json.loads(PROOF.read_text(encoding="utf-8"))
    assert proof["identity_pass"] is True
    assert proof["trains_pass"] is True
    assert proof["pass"] is True
    assert proof["goal_id"] == "EMBER-02"
    assert proof["workstream_id"] == "EMBER-02A"
