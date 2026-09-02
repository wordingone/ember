#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed claim-boundary checks for the #1433 WARM-100 result registry rows."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTINUITY = REPO_ROOT / "docs/domains/governance/authority/CONTINUITY.md"

EXPECTED = {
    "arc-warm100-step100-result": {
        "receipt": "37e2b4c90db2a22777ca0838751bc1eaac6cbd0f51cf2bfbfc0ea8c818d62986",
        "metrics": ("1172 samples", "acc 0.229522", "acc_norm 0.269625"),
        "boundary": "chance=0.25 (chance-level)",
    },
    "hellaswag-warm100-step100-result": {
        "receipt": "efeb0a9848327e08528676f6f49c41eda4f6c380bdd989c1986ee0fed6493a56",
        "metrics": ("10042 samples", "acc 0.258813", "acc_norm 0.260904"),
        "boundary": "chance=0.25 (chance-level)",
    },
    "heldout-nll-warm100-step100-result": {
        "receipt": "88312955fd0e0ff3f7e74a3f42ad1700ddf2e7407e4a5818e192097e83479cca",
        "metrics": (
            "16384 tokens",
            "mean_nll 10.603397",
            "bits_per_packed_byte 7.648734",
        ),
        "boundary": "scoped-clean only versus this run's bound trained consumption",
    },
}

WHOLE_CORPUS_REFUSAL = "5ffd38dca7d8cd10b1133a44c703c2468deb0d4f08f31053678eb9dc873d6aa2"


def _resolver_rows() -> dict[str, list[str]]:
    lines = CONTINUITY.read_text(encoding="utf-8").splitlines()
    header = next(
        index
        for index, raw in enumerate(lines)
        if raw.lstrip().startswith("|")
        and [cell.strip() for cell in raw.strip().strip("|").split("|")][0] == "id"
    )
    rows: dict[str, list[str]] = {}
    for raw in lines[header + 1 :]:
        if not raw.strip() or not raw.lstrip().startswith("|"):
            break
        cells = [cell.strip() for cell in raw.strip().strip("|").split("|")]
        if cells and not all(set(cell) <= {"-", ":"} for cell in cells):
            rows[cells[0]] = cells
    return rows


def test_warm100_registry_has_exact_three_measurement_only_receipts() -> None:
    rows = _resolver_rows()
    actual_ids = {row_id for row_id in rows if "warm100-step100-result" in row_id}
    assert actual_ids == set(EXPECTED)

    for row_id, expected in EXPECTED.items():
        row = rows[row_id]
        assert len(row) == 9
        assert row[1] == "benchmark_result"
        assert row[2] == f"receipt-sha256:{expected['receipt']}"
        assert row[3] == "execution_measurement_only"
        assert row[5] == "51200"
        assert row[7] == "none"
        evidence = row[8]
        assert all(metric in evidence for metric in expected["metrics"])
        assert expected["boundary"] in evidence
        assert "execution+measurement only" in evidence
        assert "no sufficiency/capability/comparison claim" in evidence


def test_warm100_registry_discloses_scoped_nll_and_whole_corpus_refusal() -> None:
    evidence = _resolver_rows()["heldout-nll-warm100-step100-result"][8]
    assert WHOLE_CORPUS_REFUSAL in evidence
    assert "20,777 confirmed non-self matches" in evidence
    assert "whole-corpus refusal" in evidence


def test_warm100_registry_excludes_pre_authority_attempts_and_credit() -> None:
    rows = _resolver_rows()
    evidence = " ".join(rows[row_id][8] for row_id in EXPECTED).lower()
    assert "pre-authority" not in evidence
    assert "cuda_lease_not_authorized" not in evidence
    assert "manifest_sha_mismatch" not in evidence
    assert "permissionerror" not in evidence
    assert "sufficient" not in evidence
    assert "capability credit" not in evidence
    assert "comparison win" not in evidence
