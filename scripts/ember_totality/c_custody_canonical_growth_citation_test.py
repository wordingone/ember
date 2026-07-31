#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed binding for the canonical live growth receipt cited by the S1 draft."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "spec" / "c-scale-s1-growth-chain-DRAFT.md"
RECEIPT_REF = "receipts/cbase-grow-live/cbase-grow-live-live-20260703T053225Z.json"
RECEIPT_SHA256 = "43217cc5f31cce0320bf0627a603b11a7e4782ed1e03c48510c55346ac27c2d5"
OLD_REF = "receipts/cbase-grow-live-live-20260703T053225Z-import-edition.json"


def test_growth_draft_binds_canonical_live_receipt() -> None:
    lines = DOC.read_text(encoding="utf-8").splitlines()
    table_line = lines[131]
    assert RECEIPT_REF in table_line

    receipt_bytes = (ROOT / RECEIPT_REF).read_bytes()
    assert hashlib.sha256(receipt_bytes).hexdigest() == RECEIPT_SHA256
    receipt = json.loads(receipt_bytes.decode("utf-8"))
    assert receipt["ticket"] == "CBASE-GROW-LIVE"
    assert receipt["mode"] == "live"
    assert receipt["function_preservation_check"] == {
        "mechanism": receipt["function_preservation_check"]["mechanism"],
        "input_batch": receipt["function_preservation_check"]["input_batch"],
        "logit_max_abs_diff": 2.384185791015625e-06,
        "pass_tolerance": 0.0001,
        "function_preserving": True,
    }
    assert receipt["verdict"] == "GROW_LIVE_PASS"
    assert receipt["pass"] is True


def test_custody_accepts_only_hash_bound_canonical_citation_correction() -> None:
    spec = importlib.util.spec_from_file_location(
        "c_custody_probe", ROOT / "scripts" / "ember_totality" / "test_c_custody.py"
    )
    assert spec and spec.loader
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)

    correction = {
        "schema_version": "ember-citation-correction/v1",
        "old_ref": OLD_REF,
        "canonical_ref": RECEIPT_REF,
        "canonical_sha256": RECEIPT_SHA256,
        "reason": "historical citation used a non-existent import-edition name",
    }
    tracked = {RECEIPT_REF}
    assert probe._resolve_citation_correction(OLD_REF, [correction], tracked, ROOT) == {
        "old": OLD_REF,
        "new": RECEIPT_REF,
        "sha256": RECEIPT_SHA256,
    }

    wrong_hash = {**correction, "canonical_sha256": "0" * 64}
    assert probe._resolve_citation_correction(OLD_REF, [wrong_hash], tracked, ROOT) is None
