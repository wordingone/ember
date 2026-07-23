"""Pagination and receipt contracts for EMBER-LIFECYCLE-CENSUS-001."""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import hashlib
import json

from pathlib import Path
import pytest


from scripts.lifecycle_census import CensusError, build_receipt, build_stale_report, collect_population
from scripts.lifecycle_census import GitHubApi, collect_live_populations


def _items(start: int, count: int, *, pull_request: bool = False) -> list[dict[str, object]]:
    return [
        {
            "number": number,
            "title": f"item-{number}",
            "updated_at": f"2026-07-22T00:{number % 60:02d}:00Z",
            **({"pull_request": {"url": f"https://example.test/pr/{number}"}} if pull_request else {}),
        }
        for number in range(start, start + count)
    ]


def test_collect_population_paginates_past_default_limit_and_deduplicates_boundary() -> None:
    pages = {
        (1, 100): _items(1, 100),
        (2, 100): _items(100, 3),
        (3, 100): [],
    }
    calls: list[tuple[int, int]] = []

    def fetch(page: int, per_page: int) -> list[dict[str, object]]:
        calls.append((page, per_page))
        return pages[(page, per_page)]

    result = collect_population(fetch, kind="issue", page_size=100)

    assert len(result) == 102
    assert [item["number"] for item in result] == list(range(1, 103))
    assert calls == [(1, 100), (2, 100), (3, 100)]


def test_collect_population_fails_closed_on_partial_page_error() -> None:
    def fetch(page: int, per_page: int) -> list[dict[str, object]]:
        if page == 1:
            return _items(1, 100)
        raise OSError("rate limited")

    with pytest.raises(CensusError, match="page 2"):
        collect_population(fetch, kind="issue", page_size=100)


def test_issue_population_excludes_pull_request_rows_but_pr_population_keeps_identity() -> None:
    issue_rows = _items(1, 2) + _items(3, 1, pull_request=True)
    assert [item["number"] for item in collect_population(lambda _page, _size: issue_rows if _page == 1 else [], kind="issue", page_size=100)] == [1, 2]
    prs = collect_population(lambda _page, _size: _items(3, 1, pull_request=True) if _page == 1 else [], kind="pull_request", page_size=100)
    assert [item["number"] for item in prs] == [3]


def test_collect_population_rejects_conflicting_duplicate_identity() -> None:
    first = _items(7, 1)[0]
    second = {**first, "title": "changed"}

    def fetch(page: int, _size: int) -> list[dict[str, object]]:
        return [first] if page == 1 else [second] if page == 2 else []

    with pytest.raises(CensusError, match="conflicting duplicate issue identity 7"):
        collect_population(fetch, kind="issue", page_size=1)


def test_collect_population_fails_closed_when_server_never_terminates_pages() -> None:
    with pytest.raises(CensusError, match="max_pages=2"):
        collect_population(lambda _page, _size: _items(1, 1), kind="issue", page_size=1, max_pages=2)


def test_receipt_binds_master_and_item_hashes_without_claiming_closure() -> None:
    issues = [{"number": 1, "title": "one"}]
    prs = [{"number": 2, "title": "two"}]

    receipt = build_receipt(
        repository="wordingone/ember",
        master_sha="c75738946168e6272743eda08efcaad270d0195b",
        collected_at="2026-07-22T00:00:00Z",
        issues=issues,
        pull_requests=prs,
    )

    assert receipt["master_sha"] == "c75738946168e6272743eda08efcaad270d0195b"
    assert receipt["counts"] == {"issues": 1, "pull_requests": 1}
    assert receipt["claim_limits"] == ["No issue closure or capability claim follows."]
    assert receipt["receipt_sha256"] == hashlib.sha256(
        json.dumps({key: value for key, value in receipt.items() if key != "receipt_sha256"}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
def test_stale_report_includes_stale_item_beyond_first_default_page() -> None:


    stale_item = {"number": 101, "title": "old item", "updated_at": "2026-07-01T00:00:00Z"}
    pages = {(1, 100): _items(1, 100), (2, 100): [stale_item], (3, 100): []}
    issues = collect_population(lambda page, size: pages[(page, size)], kind="issue", page_size=100)
    receipt = build_receipt(repository="wordingone/ember", master_sha="c75738946168e6272743eda08efcaad270d0195b", collected_at="2026-07-22T00:00:00Z", issues=issues, pull_requests=[])
    report = build_stale_report(receipt=receipt, issues=issues, pull_requests=[], stale_before="2026-07-10T00:00:00Z")
    assert report["receipt_sha256"] == receipt["receipt_sha256"]
    assert report["counts"] == {"issues": 1, "pull_requests": 0}
    assert report["issues"] == [{"item_sha256": next(item["item_sha256"] for item in issues if item["number"] == 101), **stale_item}]
def test_workflow_derives_stale_tracker_from_complete_census_report() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "freshness-monitor.yml").read_text(encoding="utf-8")
    assert "--stale-before" in workflow
    assert "stale_report" in workflow
    assert "gh pr list" not in workflow
    assert "gh issue list" not in workflow
def test_workflow_tracker_shell_and_count_validation_fail_closed() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "freshness-monitor.yml").read_text(encoding="utf-8")
    assert "set -euo pipefail" in workflow
    assert "\n          set -u\n" not in workflow
    assert "jq -er" in workflow
    assert "stale_pr" in workflow and "stale_is" in workflow


def test_workflow_makes_census_and_report_failures_terminal() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "freshness-monitor.yml").read_text(encoding="utf-8")
    assert "if ! python scripts/lifecycle_census.py" in workflow
    assert "if ! jq -e" in workflow
    assert "invalid stale report schema" in workflow


def test_workflow_count_contract_rejects_missing_or_nonnumeric_shell_values() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "freshness-monitor.yml").read_text(encoding="utf-8")
    assert "require_count()" in workflow
    assert 'case "$value" in' in workflow
    assert "*[!0-9]*" in workflow
    assert "stale_pr=" + "$" + "{stale_pr:-0}" not in workflow
    assert "stale_is=" + "$" + "{stale_is:-0}" not in workflow


def test_main_computes_stale_report_before_writing_receipt() -> None:
    source = (Path(__file__).parents[1] / "scripts" / "lifecycle_census.py").read_text(encoding="utf-8")
    assert source.index("stale_report = build_stale_report") < source.index("write_receipt(receipt, path)")


def test_collect_population_preserves_unlabeled_unassigned_items() -> None:
    item = {
        "number": 11,
        "title": "unclassified",
        "updated_at": "2026-07-22T00:00:00Z",
        "labels": [],
        "assignee": None,
    }
    result = collect_population(lambda page, _size: [item] if page == 1 else [], kind="issue")
    assert result[0]["labels"] == []
    assert result[0]["assignee"] is None


def test_collect_live_populations_refuses_public_master_move(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = "a" * 40
    moved = "b" * 40
    master_values = iter([expected, moved])

    monkeypatch.setattr(GitHubApi, "master_sha", lambda _self: next(master_values))
    monkeypatch.setattr(GitHubApi, "page", lambda _self, _endpoint, page, _per_page: [])

    with pytest.raises(CensusError, match="public master changed during collection"):
        collect_live_populations(repository="wordingone/ember", token="fixture", expected_master_sha=expected)


def test_collect_live_populations_rejects_master_reader_without_expected_sha() -> None:
    with pytest.raises(CensusError, match="expected_master_sha"):
        collect_live_populations(repository="wordingone/ember", token="fixture", master_sha_reader=lambda: "a" * 40)
