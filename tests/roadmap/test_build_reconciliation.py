# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "scripts" / "roadmap" / "build_reconciliation.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_reconciliation", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def census(issues: list[dict], milestones: list[dict] | None = None) -> dict:
    return {
        "schema_version": "ember-roadmap-public-state-v1",
        "repository": "wordingone/ember",
        "public_master_sha": "a" * 40,
        "captured_at": "2026-07-27T00:00:00Z",
        "counts": {
            "open_issues": len(issues),
            "open_pull_requests": 0,
            "milestones_all": len(milestones or []),
            "labels": 0,
        },
        "issues": issues,
        "milestones": milestones or [],
        "labels": [],
    }


def issue(number: int, title: str, milestone: dict | None = None) -> dict:
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/wordingone/ember/issues/{number}",
        "body_sha256": f"{number:064x}"[-64:],
        "labels": [],
        "milestone": milestone,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "comment_count": 0,
        "state": "open",
    }


def test_build_accounts_for_every_issue_once_and_never_closes() -> None:
    module = load_module()
    payload = module.build(
        census(
            [
                issue(812, "[EMBER-02] Bind clean-genesis trainer input"),
                issue(894, "Cockpit live view is missing training graphs"),
                issue(873, "[EMBER-04] Implement world-model loop"),
            ]
        )
    )
    rows = payload["reconciliation"]["issues"]
    assert [row["number"] for row in rows] == [812, 873, 894]
    assert len({row["number"] for row in rows}) == 3
    assert all(row["intended_state"] == "open" for row in rows)
    assert payload["projection"]["issue_closures"] == []
    assert rows[0]["disposition"] == "single_milestone"
    assert rows[0]["affected_milestones"] == ["EMBER-02"]
    assert rows[1]["affected_milestones"] == ["EMBER-04"]
    assert rows[2]["affected_milestones"] == ["EMBER-03"]


def test_oldest_historical_contracts_are_preserved_as_mixed() -> None:
    module = load_module()
    payload = module.build(
        census(
            [
                issue(3, "C14 resident-training gate"),
                issue(29, "C-SCALE apex owned >3e9"),
                issue(35, "docs/domains/governance/authority/GOAL.md contract-integrity audit"),
            ]
        )
    )
    rows = {row["number"]: row for row in payload["reconciliation"]["issues"]}
    assert rows[3]["disposition"] == "mixed_historical"
    assert rows[29]["affected_milestones"] == [
        "EMBER-02",
        "EMBER-05",
        "EMBER-07",
        "EMBER-08",
        "EMBER-09",
    ]
    assert rows[35]["affected_milestones"] == ["EMBER-00", "EMBER-01"]
    assert all(row["desired_parent_subissue"] is None for row in rows.values())


def test_projection_reuses_existing_canonical_milestone() -> None:
    module = load_module()
    existing = {
        "number": 15,
        "title": "EMBER-02: Sufficiently pretrained owned 3B",
        "state": "open",
        "open_issues": 4,
        "closed_issues": 0,
        "description_sha256": "b" * 64,
    }
    payload = module.build(census([], [existing]))
    milestones = {
        row["milestone_id"]: row for row in payload["projection"]["milestones"]
    }
    assert len(milestones) == 12
    assert milestones["EMBER-02"]["existing_number"] == 15
    assert milestones["EMBER-00"]["existing_number"] is None
    assert len(payload["projection"]["parent_issues"]) == 12


def test_unclassified_title_is_preserved_fail_closed() -> None:
    module = load_module()
    payload = module.build(census([issue(5000, "Unclear remaining obligation")]))
    row = payload["reconciliation"]["issues"][0]
    assert row["disposition"] == "evidence_pending"
    assert row["affected_milestones"] == []
    assert row["desired_parent_subissue"] is None
    assert "narrower milestone" in row["rationale"]
