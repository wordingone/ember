#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Terminal-completeness regressions for issue #1497 carrier A."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import frontier_receipt as frontier  # noqa: E402
import r1_exit_battery as battery  # noqa: E402
import run_attempt_registry as registry  # noqa: E402


START = "2026-08-08T00:00:00Z"
END = "2026-08-08T00:01:00Z"


def _write_evidence(run_root: Path, relative: str) -> str:
    path = run_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"fixture":true}\n', encoding="utf-8")
    return relative


def _row(
    run_root: Path,
    *,
    outcome: str,
    run_id: str = "run-alpha",
    attempt_id: str = "attempt-one",
    backfill: bool = False,
    evidence_ref: str | None = None,
    start_utc: str = START,
    end_utc: str | None = None,
) -> dict:
    if evidence_ref is None:
        evidence_ref = (
            f"attempts/{attempt_id}/terminal.json"
            if outcome != "running"
            else "run-spec.json"
        )
    _write_evidence(run_root, evidence_ref)
    if outcome != "running" and end_utc is None:
        end_utc = END
    return registry.build_row(
        run_root=run_root,
        outcome=outcome,
        run_id=run_id,
        attempt_id=attempt_id,
        start_utc=start_utc,
        end_utc=end_utc,
        checkpoint_manifest_sha256=None,
        launch_receipt_ref=evidence_ref,
        source_receipt=evidence_ref,
        outcome_basis=f"fixture {outcome}",
        backfill=backfill,
    )


def _validate(rows: list[dict], run_root: Path, *, bound: int | None = None) -> list[str]:
    return battery.validate_run_attempt_completion(
        rows,
        selected_run_id="run-alpha",
        run_root=run_root,
        bound_row_count=len(rows) if bound is None else bound,
    )


def test_live_pair_and_historical_backfill_are_accepted(tmp_path: Path):
    run_root = tmp_path / "custody" / "run-alpha"
    run_root.mkdir(parents=True)
    running = _row(run_root, outcome="running")
    terminal = _row(run_root, outcome="failed")
    assert _validate([running, terminal], run_root) == []

    historical = _row(
        run_root,
        outcome="completed",
        attempt_id="evidence-floor",
        backfill=True,
        evidence_ref="disk-budget-runner-receipt.json",
    )
    assert _validate([historical], run_root) == []


@pytest.mark.parametrize(
    ("rows_factory", "expected"),
    [
        (lambda root: [_row(root, outcome="running")], "missing terminal"),
        (lambda root: [_row(root, outcome="failed")], "orphan terminal"),
        (
            lambda root: [
                _row(root, outcome="running"),
                _row(root, outcome="failed"),
                _row(root, outcome="killed"),
            ],
            "duplicate terminal",
        ),
        (
            lambda root: [
                _row(root, outcome="failed"),
                _row(root, outcome="running"),
            ],
            "terminal precedes running",
        ),
    ],
)
def test_incomplete_or_ambiguous_live_attempts_refuse(
    tmp_path: Path, rows_factory, expected: str
):
    run_root = tmp_path / "custody" / "run-alpha"
    run_root.mkdir(parents=True)
    defects = _validate(rows_factory(run_root), run_root)
    assert any(expected in defect for defect in defects), defects


def test_foreign_run_root_and_attempt_rows_refuse(tmp_path: Path):
    run_root = tmp_path / "custody" / "run-alpha"
    run_root.mkdir(parents=True)
    other_root = tmp_path / "custody" / "run-foreign"
    other_root.mkdir(parents=True)

    foreign_run = _row(run_root, outcome="completed", run_id="run-foreign", backfill=True)
    assert any("foreign run" in defect for defect in _validate([foreign_run], run_root))

    foreign_root = _row(other_root, outcome="completed", backfill=True)
    assert any("foreign root" in defect for defect in _validate([foreign_root], run_root))

    running = _row(run_root, outcome="running")
    foreign_attempt = _row(run_root, outcome="failed", attempt_id="attempt-other")
    defects = _validate([running, foreign_attempt], run_root)
    assert any("orphan terminal" in defect for defect in defects), defects
    assert any("missing terminal" in defect for defect in defects), defects


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda running, terminal: terminal.__setitem__("start_utc", "2026-08-08T00:00:01Z"), "start_utc"),
        (lambda running, terminal: terminal.__setitem__("end_utc", "2026-08-07T23:59:59Z"), "precedes start_utc"),
        (lambda running, terminal: running.__setitem__("source_receipt", "other-run-spec.json"), "running receipt references"),
        (lambda running, terminal: terminal.__setitem__("source_receipt", "other-terminal.json"), "terminal receipt references"),
        (lambda running, terminal: terminal.__setitem__("launch_receipt_ref", running["launch_receipt_ref"]), "must not reuse running evidence"),
    ],
)
def test_inconsistent_timestamps_and_receipt_references_refuse(
    tmp_path: Path, mutate, expected: str
):
    run_root = tmp_path / "custody" / "run-alpha"
    run_root.mkdir(parents=True)
    running = _row(run_root, outcome="running")
    terminal = _row(run_root, outcome="failed")
    mutate(running, terminal)
    defects = _validate([running, terminal], run_root)
    assert any(expected in defect for defect in defects), defects


def test_prefix_pairing_is_append_stable_but_current_tail_schema_is_closed(
    tmp_path: Path,
):
    run_root = tmp_path / "custody" / "run-alpha"
    run_root.mkdir(parents=True)
    pair = [_row(run_root, outcome="running"), _row(run_root, outcome="completed")]
    later = _row(
        run_root,
        outcome="running",
        attempt_id="attempt-appended-after-mint",
        evidence_ref="later-run-spec.json",
    )
    assert _validate(pair + [later], run_root, bound=2) == []

    malformed_later = dict(later, foreign_claim="accepted")
    defects = _validate(pair + [malformed_later], run_root, bound=2)
    assert any("unknown fields" in defect for defect in defects), defects


def test_frontier_producer_refuses_missing_terminal_before_asserting_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo_root = tmp_path / "repo"
    run_root = tmp_path / "custody" / "run-alpha"
    run_root.mkdir(parents=True)
    registry_path = repo_root / frontier.RUN_ATTEMPTS_REGISTRY
    registry_path.parent.mkdir(parents=True)

    running = _row(run_root, outcome="running")
    terminal = _row(run_root, outcome="completed")
    registry_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in (running, terminal)),
        encoding="utf-8",
    )
    monkeypatch.setattr(frontier, "REPO_ROOT", repo_root)
    coverage = frontier.ledger_all_compute_coverage(run_root, "run-alpha", "f" * 64)
    assert coverage["failed_work_included"] is True
    assert coverage["registry_rows"] == 2

    registry_path.write_text(json.dumps(running, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(frontier.FrontierRefusal, match="missing terminal"):
        frontier.ledger_all_compute_coverage(run_root, "run-alpha", "f" * 64)


def test_issue1464_historical_backfills_are_runner_receipt_sourced():
    registry_path = ROOT / "receipts" / "run-attempts.jsonl"
    rows = [json.loads(line) for line in registry_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected = {
        ("issue1464-r1-e5-composition-20260820T090432Z", "issue1296-warm100-run-20260819T203314Z"): ("completed", "f28a9d8c175f6816a50277afd861d081b966293a2460afb69e642886992da366"),
        ("issue1464-r1-e7-seed84-20260820T2355Z", "issue1464-r1-e7-seed84-20260820T2355Z"): ("aborted", "c9b462c46bfe23b162d1eb1f3d11538727f78cc634d774af62e2dc011b5392a9"),
        ("issue1464-r1-e7-seed84-20260821T0040Z", "issue1464-r1-e7-seed84-20260821T0040Z"): ("failed", "9342c290cd576c386dd400697c431aa5c9a44d457d21c27b6f1bbae94c916d71"),
        ("issue1464-r1-e7-seed84-20260821T0047Z", "issue1464-r1-e7-seed84-20260821T0047Z"): ("failed", "12e1f801fb1e9089b18647f85cb9b9b79e09a7640b551b5a84684ed041b04807"),
        ("issue1464-r1-e7-seed84-20260821T0121Z", "issue1464-r1-e7-seed84-20260821T0121Z"): ("completed", "404f70b26d8fc3fcd62152d622950c4e0c7ba2edc6f2d85c57eec3a37e603c99"),
    }
    actual = {
        (row["run_root_name"], row["run_id"]): row
        for row in rows
        if row.get("outcome_basis", "").startswith("gate-order-24762 runner receipt sha256 ")
    }
    assert set(actual) == set(expected)
    for identity, (outcome, receipt_sha256) in expected.items():
        row = actual[identity]
        assert row["backfill"] is True
        assert row["outcome"] == outcome
        assert row["source_receipt"] == row["launch_receipt_ref"]
        assert receipt_sha256 in row["outcome_basis"]


def test_historical_backfill_refuses_an_unsourced_runner_receipt(tmp_path: Path):
    run_root = tmp_path / "custody" / "run-alpha"
    run_root.mkdir(parents=True)
    unsourced = registry.build_row(
        run_root=run_root,
        outcome="completed",
        run_id="run-alpha",
        attempt_id="terminal-runner-receipt",
        start_utc=START,
        end_utc=END,
        checkpoint_manifest_sha256=None,
        launch_receipt_ref="runner-receipt.json",
        source_receipt="runner-receipt.json",
        outcome_basis="runner receipt sha256 " + "a" * 64,
        backfill=True,
    )
    defects = _validate([unsourced], run_root)
    assert any("source_receipt does not resolve to existing custody evidence" in defect for defect in defects)
