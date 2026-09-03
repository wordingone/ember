"""Pagination and receipt contracts for EMBER-LIFECYCLE-CENSUS-001."""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import hashlib
import json

from pathlib import Path
import pytest


from src.ember.governance.scripts import lifecycle_census
# issue2015 exact-local-import:src/ember/governance/scripts/lifecycle_census.py
import importlib.util as _ember_e08f3c7c35cc91f0_importlib
import sys as _ember_e08f3c7c35cc91f0_sys
from pathlib import Path as _ember_e08f3c7c35cc91f0_Path
_ember_e08f3c7c35cc91f0_path = _ember_e08f3c7c35cc91f0_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'lifecycle_census.py')
if not _ember_e08f3c7c35cc91f0_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/lifecycle_census.py')
_ember_e08f3c7c35cc91f0_aliases = ('_ember_issue2015_e08f3c7c35cc91f0', 'lifecycle_census', 'scripts.lifecycle_census', 'src.ember.governance.scripts.lifecycle_census')
_ember_e08f3c7c35cc91f0_existing = []
for _ember_e08f3c7c35cc91f0_alias in _ember_e08f3c7c35cc91f0_aliases:
    _ember_e08f3c7c35cc91f0_candidate = _ember_e08f3c7c35cc91f0_sys.modules.get(_ember_e08f3c7c35cc91f0_alias)
    if _ember_e08f3c7c35cc91f0_candidate is not None and all(_ember_e08f3c7c35cc91f0_candidate is not item for item in _ember_e08f3c7c35cc91f0_existing):
        _ember_e08f3c7c35cc91f0_existing.append(_ember_e08f3c7c35cc91f0_candidate)
if len(_ember_e08f3c7c35cc91f0_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/lifecycle_census.py')
if _ember_e08f3c7c35cc91f0_existing:
    _ember_e08f3c7c35cc91f0_module = _ember_e08f3c7c35cc91f0_existing[0]
    _ember_e08f3c7c35cc91f0_observed = getattr(_ember_e08f3c7c35cc91f0_module, '__file__', None)
    if _ember_e08f3c7c35cc91f0_observed is None or _ember_e08f3c7c35cc91f0_Path(_ember_e08f3c7c35cc91f0_observed).resolve() != _ember_e08f3c7c35cc91f0_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/lifecycle_census.py')
else:
    _ember_e08f3c7c35cc91f0_spec = _ember_e08f3c7c35cc91f0_importlib.spec_from_file_location('_ember_issue2015_e08f3c7c35cc91f0', _ember_e08f3c7c35cc91f0_path)
    if _ember_e08f3c7c35cc91f0_spec is None or _ember_e08f3c7c35cc91f0_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/lifecycle_census.py')
    _ember_e08f3c7c35cc91f0_module = _ember_e08f3c7c35cc91f0_importlib.module_from_spec(_ember_e08f3c7c35cc91f0_spec)
    for _ember_e08f3c7c35cc91f0_alias in _ember_e08f3c7c35cc91f0_aliases:
        _ember_e08f3c7c35cc91f0_prior = _ember_e08f3c7c35cc91f0_sys.modules.get(_ember_e08f3c7c35cc91f0_alias)
        if _ember_e08f3c7c35cc91f0_prior is not None and _ember_e08f3c7c35cc91f0_prior is not _ember_e08f3c7c35cc91f0_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/lifecycle_census.py')
        _ember_e08f3c7c35cc91f0_sys.modules[_ember_e08f3c7c35cc91f0_alias] = _ember_e08f3c7c35cc91f0_module
    try:
        _ember_e08f3c7c35cc91f0_spec.loader.exec_module(_ember_e08f3c7c35cc91f0_module)
    except BaseException:
        for _ember_e08f3c7c35cc91f0_alias in _ember_e08f3c7c35cc91f0_aliases:
            if _ember_e08f3c7c35cc91f0_sys.modules.get(_ember_e08f3c7c35cc91f0_alias) is _ember_e08f3c7c35cc91f0_module:
                _ember_e08f3c7c35cc91f0_sys.modules.pop(_ember_e08f3c7c35cc91f0_alias, None)
        raise
for _ember_e08f3c7c35cc91f0_alias in _ember_e08f3c7c35cc91f0_aliases:
    _ember_e08f3c7c35cc91f0_prior = _ember_e08f3c7c35cc91f0_sys.modules.get(_ember_e08f3c7c35cc91f0_alias)
    if _ember_e08f3c7c35cc91f0_prior is not None and _ember_e08f3c7c35cc91f0_prior is not _ember_e08f3c7c35cc91f0_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/lifecycle_census.py')
    _ember_e08f3c7c35cc91f0_sys.modules[_ember_e08f3c7c35cc91f0_alias] = _ember_e08f3c7c35cc91f0_module
CensusError = getattr(_ember_e08f3c7c35cc91f0_module, 'CensusError')
build_receipt = getattr(_ember_e08f3c7c35cc91f0_module, 'build_receipt')
build_stale_report = getattr(_ember_e08f3c7c35cc91f0_module, 'build_stale_report')
collect_population = getattr(_ember_e08f3c7c35cc91f0_module, 'collect_population')
# issue2015 exact-local-import-end:src/ember/governance/scripts/lifecycle_census.py
# issue2015 exact-local-import:src/ember/governance/scripts/lifecycle_census.py
import importlib.util as _ember_e08f3c7c35cc91f0_importlib
import sys as _ember_e08f3c7c35cc91f0_sys
from pathlib import Path as _ember_e08f3c7c35cc91f0_Path
_ember_e08f3c7c35cc91f0_path = _ember_e08f3c7c35cc91f0_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'lifecycle_census.py')
if not _ember_e08f3c7c35cc91f0_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/lifecycle_census.py')
_ember_e08f3c7c35cc91f0_aliases = ('_ember_issue2015_e08f3c7c35cc91f0', 'lifecycle_census', 'scripts.lifecycle_census', 'src.ember.governance.scripts.lifecycle_census')
_ember_e08f3c7c35cc91f0_existing = []
for _ember_e08f3c7c35cc91f0_alias in _ember_e08f3c7c35cc91f0_aliases:
    _ember_e08f3c7c35cc91f0_candidate = _ember_e08f3c7c35cc91f0_sys.modules.get(_ember_e08f3c7c35cc91f0_alias)
    if _ember_e08f3c7c35cc91f0_candidate is not None and all(_ember_e08f3c7c35cc91f0_candidate is not item for item in _ember_e08f3c7c35cc91f0_existing):
        _ember_e08f3c7c35cc91f0_existing.append(_ember_e08f3c7c35cc91f0_candidate)
if len(_ember_e08f3c7c35cc91f0_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/lifecycle_census.py')
if _ember_e08f3c7c35cc91f0_existing:
    _ember_e08f3c7c35cc91f0_module = _ember_e08f3c7c35cc91f0_existing[0]
    _ember_e08f3c7c35cc91f0_observed = getattr(_ember_e08f3c7c35cc91f0_module, '__file__', None)
    if _ember_e08f3c7c35cc91f0_observed is None or _ember_e08f3c7c35cc91f0_Path(_ember_e08f3c7c35cc91f0_observed).resolve() != _ember_e08f3c7c35cc91f0_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/lifecycle_census.py')
else:
    _ember_e08f3c7c35cc91f0_spec = _ember_e08f3c7c35cc91f0_importlib.spec_from_file_location('_ember_issue2015_e08f3c7c35cc91f0', _ember_e08f3c7c35cc91f0_path)
    if _ember_e08f3c7c35cc91f0_spec is None or _ember_e08f3c7c35cc91f0_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/lifecycle_census.py')
    _ember_e08f3c7c35cc91f0_module = _ember_e08f3c7c35cc91f0_importlib.module_from_spec(_ember_e08f3c7c35cc91f0_spec)
    for _ember_e08f3c7c35cc91f0_alias in _ember_e08f3c7c35cc91f0_aliases:
        _ember_e08f3c7c35cc91f0_prior = _ember_e08f3c7c35cc91f0_sys.modules.get(_ember_e08f3c7c35cc91f0_alias)
        if _ember_e08f3c7c35cc91f0_prior is not None and _ember_e08f3c7c35cc91f0_prior is not _ember_e08f3c7c35cc91f0_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/lifecycle_census.py')
        _ember_e08f3c7c35cc91f0_sys.modules[_ember_e08f3c7c35cc91f0_alias] = _ember_e08f3c7c35cc91f0_module
    try:
        _ember_e08f3c7c35cc91f0_spec.loader.exec_module(_ember_e08f3c7c35cc91f0_module)
    except BaseException:
        for _ember_e08f3c7c35cc91f0_alias in _ember_e08f3c7c35cc91f0_aliases:
            if _ember_e08f3c7c35cc91f0_sys.modules.get(_ember_e08f3c7c35cc91f0_alias) is _ember_e08f3c7c35cc91f0_module:
                _ember_e08f3c7c35cc91f0_sys.modules.pop(_ember_e08f3c7c35cc91f0_alias, None)
        raise
for _ember_e08f3c7c35cc91f0_alias in _ember_e08f3c7c35cc91f0_aliases:
    _ember_e08f3c7c35cc91f0_prior = _ember_e08f3c7c35cc91f0_sys.modules.get(_ember_e08f3c7c35cc91f0_alias)
    if _ember_e08f3c7c35cc91f0_prior is not None and _ember_e08f3c7c35cc91f0_prior is not _ember_e08f3c7c35cc91f0_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/lifecycle_census.py')
    _ember_e08f3c7c35cc91f0_sys.modules[_ember_e08f3c7c35cc91f0_alias] = _ember_e08f3c7c35cc91f0_module
GitHubApi = getattr(_ember_e08f3c7c35cc91f0_module, 'GitHubApi')
collect_live_populations = getattr(_ember_e08f3c7c35cc91f0_module, 'collect_live_populations')
# issue2015 exact-local-import-end:src/ember/governance/scripts/lifecycle_census.py


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
    assert "run: |\n          set -euo pipefail" in workflow
    assert "\n          set -u\n" not in workflow
    assert "jq -er" in workflow
    assert "stale_pr" in workflow and "stale_is" in workflow


def test_workflow_makes_census_and_report_failures_terminal() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "freshness-monitor.yml").read_text(encoding="utf-8")
    assert "if ! python src/ember/governance/scripts/lifecycle_census.py" in workflow
    assert "if ! jq -e" in workflow
    assert "invalid stale report schema" in workflow


def test_workflow_validates_report_file_before_extracting_terminal_counts() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "freshness-monitor.yml").read_text(encoding="utf-8")
    assert "require_stale_report()" in workflow
    assert "if ! jq -e" in workflow
    assert workflow.index('require_stale_report "$stale_report"') < workflow.index("stale_pr=$(extract_stale_count")


def test_workflow_count_contract_rejects_missing_or_nonnumeric_shell_values() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "freshness-monitor.yml").read_text(encoding="utf-8")
    assert "require_count()" in workflow
    assert 'case "$value" in' in workflow
    assert "*[!0-9]*" in workflow
    assert "if ! value=$(jq -er --arg name \"$name\"" in workflow
    assert "unable to extract %s count from stale report" in workflow
    assert "stale_pr=" + "$" + "{stale_pr:-0}" not in workflow
    assert "stale_is=" + "$" + "{stale_is:-0}" not in workflow


def test_workflow_schema_validation_binds_report_and_population_counts() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "freshness-monitor.yml").read_text(encoding="utf-8")
    assert ".report_sha256 | type == \"string\" and test(\"^[0-9a-f]{64}$\")" in workflow
    assert ".counts.pull_requests == (.pull_requests | length)" in workflow
    assert ".counts.issues == (.issues | length)" in workflow


def test_main_computes_stale_report_before_writing_receipt() -> None:
    source = (Path(__file__).parents[1] / "scripts" / "lifecycle_census.py").read_text(encoding="utf-8")
    assert source.index("stale_report = build_stale_report") < source.index("write_outputs(receipt, path")


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


def test_write_outputs_serializes_receipt_and_report_before_publishing_either(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt_path = tmp_path / "receipt.json"
    report_path = tmp_path / "stale.json"
    receipt = {"receipt_sha256": "a" * 64}
    report = {"report_sha256": "b" * 64}
    original = lifecycle_census._canonical_json
    calls = 0

    def fail_during_report_serialization(value: object) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise CensusError("report serialization failed")
        return original(value)

    monkeypatch.setattr(lifecycle_census, "_canonical_json", fail_during_report_serialization)
    with pytest.raises(CensusError, match="report serialization failed"):
        lifecycle_census.write_outputs(receipt, receipt_path, stale_report=report, stale_output=report_path)
    assert not receipt_path.exists()
    assert not report_path.exists()
