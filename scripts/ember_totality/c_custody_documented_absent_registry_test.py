#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed-contract test for the machine-readable C-CUSTODY disposition registry."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = (
    ROOT
    / "receipts"
    / "ember-01-custody"
    / "documented-absent-custody-dispositions-v1.json"
)
EXPECTED_TOP_LEVEL = {
    "schema_version",
    "ticket",
    "ts",
    "goal_id",
    "workstream_id",
    "next_executed_outcome",
    "invariant_sha256",
    "source_commit",
    "source_document",
    "source_document_sha256",
    "sha_convention",
    "documented_absent",
    "supporting_disposition_receipts",
    "claim_boundary",
}
EXPECTED_ROW_KEYS = {
    "doc",
    "ref",
    "marker",
    "line",
    "disposition_class",
    "evidence",
}
ALLOWED_CLASSES = {
    "BARRED_AT_HEAD_BY_CONTENT_RAIL",
    "CROSS_TREE_LINEAGE_NON_CANONICAL",
    "MIS_ROOTED_NON_CUSTODY_RUNTIME_SENTINEL",
    "MIS_ROOTED_ZERO_TRACE",
    "VOID_SUPERSEDED",
}
EXPECTED_REFS = {
    "receipts/ceff-closure-gate9-shatter-bf16ns5-20260623T132000Z.json",
    "receipts/ceff-shatter-REPUDIATED-20260623T170000Z.json",
    "receipts/governor-repair-080-20260702T180248Z.json",
    "receipts/cgrow-superseded/cgrow-receipt-20260628T061735Z.json",
    "receipts/stale-figure-adjudication-20260702T151929Z.json",
    "receipts/nck-event-mail-mail_arrived-15038-20260612T210139Z.json",
    "receipts/wheel/wheel-real-20260618T143007Z.json",
    "receipts/ember-preloop-resident-gate/real-reference-uiux-ax-observation-20260622T151722Z-adapter-trace.log",
    "receipts/ember-preloop-resident-gate/real-reference-uiux-ax-observation-20260622T151722Z-meta.json",
    "receipts/ember-preloop-resident-gate/real-reference-uiux-ax-observation-20260622T151722Z-process-after.json",
    "receipts/ember-preloop-resident-gate/real-reference-uiux-ax-observation-20260622T151722Z-stub-server-log.jsonl",
    "receipts/ember-preloop-resident-gate/real-reference-uiux-ax-observation-20260622T151722Z-terminal-transcript-clean.txt",
    "receipts/ember-preloop-resident-gate/real-reference-uiux-ax-observation-20260622T151722Z.json",
    "receipts/ceff-RESOLVED-20260703T124623Z.json",
    "receipts/cgrow-prereq/ff-widen-preservation-20260628T053513Z.json",
    "receipts/corpus-manifest-20260702T162110Z.json",
    "receipts/corpus-materiality-adjudication-20260702T162033Z.json",
    "receipts/ember-c-scale/c-scale-s3-deletion-arm-20260704T084922Z.json",
    "receipts/ember-c-scale/w1-collapse-control-20260704T071732Z.json",
    "receipts/ember-c8-execution-binding/ablation-20260703T080952Z.json",
    "receipts/stab524-gpu-window-done-20260709.json",
    "receipts/ember-preloop-resident-gate/reference-cli-full-parity-harness-gate-20260622T141500Z.json",
}

EXPECTED_SUPPORT_KEYS = {
    "path",
    "sha256",
    "voids_ref",
    "source_path",
    "source_sha256",
}
EXPECTED_VOID_KEYS = {
    "ticket",
    "ts",
    "goal_id",
    "workstream_id",
    "next_executed_outcome",
    "invariant_sha256",
    "sha_convention",
    "verdict",
    "voids_missing_identity",
    "supersedes",
    "reason",
    "cites",
    "claim_boundary",
}


def test_registry_is_closed_and_bound_to_current_document_bytes() -> None:
    raw = REGISTRY.read_bytes()
    registry = json.loads(raw.decode("utf-8"))
    assert set(registry) == EXPECTED_TOP_LEVEL
    assert registry["schema_version"] == "ember-c-custody-documented-absent-v1"
    assert registry["ticket"] == "C-CUSTODY-DOCUMENTED-ABSENT-WAVE029"
    assert registry["ts"] == "2026-07-31T15:28:00Z"
    assert registry["goal_id"] == "EMBER-02"
    assert registry["workstream_id"] == "EMBER-02A"
    assert registry["next_executed_outcome"] == (
        "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
    )
    assert registry["sha_convention"] == (
        "sha256 over exact on-disk file bytes, no normalization"
    )
    assert registry["invariant_sha256"] == (
        "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
    )
    assert re.fullmatch(r"[0-9a-f]{40}", registry["source_commit"])

    source_document = registry["source_document"]
    assert source_document == "docs/custody-disposition-20260708.md"
    source_path = ROOT / source_document
    assert subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            registry["source_commit"],
            "HEAD",
        ],
        cwd=ROOT,
        check=False,
    ).returncode == 0
    source_bytes = source_path.read_bytes()
    committed_source_bytes = subprocess.check_output(
        [
            "git",
            "show",
            f"{registry['source_commit']}:{source_document}",
        ],
        cwd=ROOT,
    )
    assert (
        hashlib.sha256(source_bytes).hexdigest()
        == registry["source_document_sha256"]
    )
    assert (
        hashlib.sha256(committed_source_bytes).hexdigest()
        == registry["source_document_sha256"]
    )
    lines = source_bytes.decode("utf-8").splitlines()

    rows = registry["documented_absent"]
    assert isinstance(rows, list)
    assert len(rows) == 22
    assert {row["ref"] for row in rows} == EXPECTED_REFS
    assert len({row["ref"] for row in rows}) == len(rows)

    for row in rows:
        assert set(row) == EXPECTED_ROW_KEYS
        assert row["doc"] == source_document
        assert row["disposition_class"] in ALLOWED_CLASSES
        assert isinstance(row["evidence"], str) and row["evidence"].strip()
        assert isinstance(row["line"], int) and 1 <= row["line"] <= len(lines)
        source_line = lines[row["line"] - 1]
        assert row["ref"] in source_line
        assert row["marker"] in source_line
        assert not (ROOT / row["ref"]).exists()

    supports = registry["supporting_disposition_receipts"]
    assert isinstance(supports, list) and len(supports) == 1
    support = supports[0]
    assert set(support) == EXPECTED_SUPPORT_KEYS
    assert support["voids_ref"] == (
        "receipts/ember-preloop-resident-gate/"
        "reference-cli-full-parity-harness-gate-20260622T141500Z.json"
    )
    support_path = ROOT / support["path"]
    source_path = ROOT / support["source_path"]
    assert support_path.is_file()
    assert source_path.is_file()
    support_bytes = support_path.read_bytes()
    source_bytes = source_path.read_bytes()
    assert hashlib.sha256(support_bytes).hexdigest() == support["sha256"]
    assert hashlib.sha256(source_bytes).hexdigest() == support["source_sha256"]

    void_receipt = json.loads(support_bytes.decode("utf-8"))
    assert set(void_receipt) == EXPECTED_VOID_KEYS
    assert void_receipt["ticket"] == "EMBER-reference-CLI-FULL-PARITY-HARNESS-GATE-VOID"
    assert void_receipt["goal_id"] == "EMBER-02"
    assert void_receipt["workstream_id"] == "EMBER-02A"
    assert void_receipt["next_executed_outcome"] == (
        "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
    )
    assert void_receipt["invariant_sha256"] == (
        "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
    )
    assert void_receipt["sha_convention"] == (
        "sha256 over exact on-disk file bytes, no normalization"
    )
    assert void_receipt["verdict"] == "VOID"
    assert void_receipt["voids_missing_identity"] == support["voids_ref"]
    assert void_receipt["supersedes"] == [
        {
            "filename": support["source_path"],
            "sha256": support["source_sha256"],
        }
    ]
    assert isinstance(void_receipt["reason"], str) and void_receipt["reason"].strip()
    assert void_receipt["cites"] == [
        "https://github.com/wordingone/ember/pull/348",
        "https://github.com/wordingone/ember/issues/349",
        "https://github.com/wordingone/ember/issues/400",
    ]
    assert void_receipt["claim_boundary"] == {
        "restoration_performed": False,
        "deletion_performed": False,
        "capability_claim": False,
    }

    void_row = next(row for row in rows if row["ref"] == support["voids_ref"])
    assert void_row["disposition_class"] == "VOID_SUPERSEDED"

    assert registry["claim_boundary"] == {
        "restoration_performed": False,
        "deletion_performed": False,
        "capability_claim": False,
    }


def main() -> int:
    test_registry_is_closed_and_bound_to_current_document_bytes()
    print("PASS: C-CUSTODY documented-absent registry is closed and source-bound")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
