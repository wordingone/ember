# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


REPO = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
MODULE_PATH = REPO / "scripts" / "roadmap" / "capture_public_state.py"


def load_module():
    spec = importlib.util.spec_from_file_location("capture_public_state", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_capture_is_complete_sorted_and_body_content_addressed() -> None:
    module = load_module()
    responses = {
        "repos/wordingone/ember/commits/master": {"sha": "a" * 40},
        "repos/wordingone/ember/issues?state=open&per_page=100&sort=created&direction=asc": [
            [
                {
                    "number": 9,
                    "title": "Later",
                    "body": "body nine",
                    "html_url": "https://github.com/wordingone/ember/issues/9",
                    "created_at": "2026-01-02T00:00:00Z",
                    "updated_at": "2026-01-03T00:00:00Z",
                    "state": "open",
                    "comments": 2,
                    "labels": [{"name": "bug"}],
                    "milestone": None,
                },
                {
                    "number": 4,
                    "title": "A pull",
                    "body": "",
                    "html_url": "https://github.com/wordingone/ember/pull/4",
                    "pull_request": {"url": "pull"},
                },
                {
                    "number": 3,
                    "title": "Earlier",
                    "body": "body three",
                    "html_url": "https://github.com/wordingone/ember/issues/3",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-04T00:00:00Z",
                    "state": "open",
                    "comments": 1,
                    "labels": [],
                    "milestone": {
                        "number": 15,
                        "title": "EMBER-02",
                        "state": "open",
                    },
                },
            ]
        ],
        "repos/wordingone/ember/milestones?state=all&per_page=100": [
            {"number": 15, "title": "EMBER-02", "state": "open"}
        ],
        "repos/wordingone/ember/labels?per_page=100": [
            [{"name": "bug", "color": "d73a4a", "description": "Bug"}]
        ],
        "search/issues?q=repo%3Awordingone%2Fember+is%3Aissue+is%3Aopen&per_page=1": {
            "total_count": 2
        },
        "search/issues?q=repo%3Awordingone%2Fember+is%3Apr+is%3Aopen&per_page=1": {
            "total_count": 1
        },
    }

    def run(endpoint: str, *, paginate: bool = False):
        assert endpoint in responses
        return responses[endpoint]

    result = module.capture(
        run=run,
        repository="wordingone/ember",
        captured_at="2026-07-27T00:00:00Z",
    )

    assert result["public_master_sha"] == "a" * 40
    assert result["counts"] == {
        "open_issues": 2,
        "open_pull_requests": 1,
        "milestones_all": 1,
        "labels": 1,
    }
    assert [row["number"] for row in result["issues"]] == [3, 9]
    assert result["issues"][0]["body_sha256"] == hashlib.sha256(
        b"body three"
    ).hexdigest()
    assert "body" not in result["issues"][0]
    assert result["issues"][0]["milestone"]["number"] == 15


def test_capture_refuses_incomplete_search_count() -> None:
    module = load_module()

    def run(endpoint: str, *, paginate: bool = False):
        if endpoint.endswith("/commits/master"):
            return {"sha": "b" * 40}
        if "is%3Aissue" in endpoint:
            return {"total_count": 1}
        if "is%3Apr" in endpoint:
            return {"total_count": 0}
        if "/issues?" in endpoint:
            return [[]]
        if "/milestones?" in endpoint or "/labels?" in endpoint:
            return []
        raise AssertionError(endpoint)

    with pytest.raises(module.CaptureError, match="open issue count mismatch"):
        module.capture(
            run=run,
            repository="wordingone/ember",
            captured_at="2026-07-27T00:00:00Z",
        )


def test_capture_refuses_duplicate_issue_number() -> None:
    module = load_module()
    duplicate = {
        "number": 3,
        "title": "Duplicate",
        "body": "",
        "html_url": "https://github.com/wordingone/ember/issues/3",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "state": "open",
        "comments": 0,
        "labels": [],
        "milestone": None,
    }

    def run(endpoint: str, *, paginate: bool = False):
        if endpoint.endswith("/commits/master"):
            return {"sha": "c" * 40}
        if "is%3Aissue" in endpoint:
            return {"total_count": 2}
        if "is%3Apr" in endpoint:
            return {"total_count": 0}
        if "/issues?" in endpoint:
            return [[duplicate, duplicate]]
        if "/milestones?" in endpoint or "/labels?" in endpoint:
            return []
        raise AssertionError(endpoint)

    with pytest.raises(module.CaptureError, match="duplicate issue number"):
        module.capture(
            run=run,
            repository="wordingone/ember",
            captured_at="2026-07-27T00:00:00Z",
        )
