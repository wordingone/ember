# goal_id: EMBER-01
# workstream_id: EMBER-01B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = REPO_ROOT / "scripts" / "ember_01_custody"
sys.path.insert(0, str(SCRIPT_ROOT))

from issue_census import (  # noqa: E402
    ALLOWED_DISPOSITIONS,
    build_issue_census,
    validate_issue_census,
)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def issue(number: int, title: str) -> dict:
    return {
        "number": number,
        "title": title,
        "body": f"body for {number}",
        "url": f"https://github.com/wordingone/ember/issues/{number}",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "labels": [{"name": "research"}],
        "author": {"login": "operator"},
    }


def test_issue_census_binds_master_blobs_and_history_without_closure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "fixture")
    (root / "STATE.md").write_text("Tracks #7.\n", encoding="utf-8")
    git(root, "add", "STATE.md")
    git(root, "commit", "-m", "Bind issue #9 in history")
    head = git(root, "rev-parse", "HEAD")

    payload = build_issue_census(
        root,
        head,
        [issue(9, "History obligation"), issue(7, "Tracked obligation"), issue(11, "Unbound")],
    )
    rows = {row["number"]: row for row in payload["issues"]}

    assert [row["number"] for row in payload["issues"]] == [7, 9, 11]
    assert payload["public_master_sha"] == head
    assert rows[7]["master_evidence"][0]["path"] == "STATE.md"
    assert rows[7]["master_evidence"][0]["blob_sha1"]
    assert rows[9]["history_evidence"] == [{"commit": head}]
    assert rows[11]["disposition"] == "unresolved"
    assert rows[7]["disposition"] == "current executable obligation"
    assert all(row["closure_proposed"] is False for row in rows.values())
    assert validate_issue_census(payload) == []
    assert str(root) not in json.dumps(payload)


def test_validator_rejects_missing_duplicate_or_unproven_closure() -> None:
    payload = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": "a" * 40,
        "open_issue_count": 2,
        "allowed_dispositions": [
            "current executable obligation",
            "preserved research direction",
            "implemented and independently verified",
            "superseded by an exact named successor",
            "exact duplicate of one canonical issue",
            "historical sub-3B or borrowed-lineage non-executable evidence",
            "expired operational incident",
            "unresolved",
        ],
        "issues": [
            {
                "number": 3,
                "disposition": "implemented and independently verified",
                "closure_proposed": True,
                "completion_proof": [],
                "canonical_issue": None,
            },
            {
                "number": 3,
                "disposition": "unresolved",
                "closure_proposed": False,
                "completion_proof": [],
                "canonical_issue": None,
            },
        ],
    }
    errors = validate_issue_census(payload)
    assert "issue_number_duplicate:3" in errors
    assert "closure_completion_proof_missing:3" in errors


def test_expired_incident_cannot_close_from_age_or_label_alone() -> None:
    payload = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": "a" * 40,
        "open_issue_count": 1,
        "allowed_dispositions": list(ALLOWED_DISPOSITIONS),
        "issues": [
            {
                "number": 77,
                "disposition": "expired operational incident",
                "closure_proposed": True,
                "completion_proof": [],
                "canonical_issue": None,
                "obligation_sha256": "b" * 64,
                "canonical_obligation_sha256": None,
            }
        ],
    }
    assert (
        "closure_proof_or_canonical_missing:77"
        in validate_issue_census(payload)
    )

def test_checked_in_public_issue_census_covers_every_snapshot_row() -> None:
    path = REPO_ROOT / "manifests" / "ember-01-custody" / "public-issue-census.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert validate_issue_census(payload) == []
    assert payload["open_issue_count"] == len(payload["issues"])
    assert payload["open_issue_count"] >= 270
    assert all(row["closure_proposed"] is False for row in payload["issues"])
    assert all(row["confidence"] in {"low", "medium", "high"} for row in payload["issues"])
    assert all(
        isinstance(row["unresolved_remainder"], str)
        and row["unresolved_remainder"]
        for row in payload["issues"]
    )
    assert all(row["public_master_sha"] == payload["public_master_sha"] for row in payload["issues"])
