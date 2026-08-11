# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import base64
import copy
import hashlib
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
        "state": "OPEN",
        "stateReason": None,
        "closedAt": None,
    }


def test_issue_census_binds_master_blobs_and_history_without_closure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "fixture")
    (root / "docs/authority/STATE.md").write_text("Tracks #7.\n", encoding="utf-8")
    git(root, "add", "docs/authority/STATE.md")
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
    assert rows[7]["master_evidence"][0]["path"] == "docs/authority/STATE.md"
    assert rows[7]["master_evidence"][0]["blob_sha1"]
    assert rows[9]["history_evidence"] == [{"commit": head}]
    assert rows[11]["disposition"] == "unresolved"
    assert rows[7]["disposition"] == "current executable obligation"
    assert all(row["closure_proposed"] is False for row in rows.values())
    assert validate_issue_census(payload, repository_root=REPO_ROOT) == []
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
    assert validate_issue_census(payload, repository_root=REPO_ROOT) == []
    assert payload["open_issue_count"] == len(payload["issues"])
    assert all(row["closure_proposed"] is False for row in payload["issues"])
    assert all(row["confidence"] in {"low", "medium", "high"} for row in payload["issues"])
    assert all(
        row["unresolved_remainder"] is None
        if row["disposition"] == "implemented and independently verified"
        else isinstance(row["unresolved_remainder"], str)
        and bool(row["unresolved_remainder"])
        for row in payload["issues"]
    )
    assert all(row["public_master_sha"] == payload["public_master_sha"] for row in payload["issues"])
    rows = {row["number"]: row for row in payload["issues"]}
    first_source = payload["issue_source_snapshot"][0]
    decoded_body = base64.b64decode(first_source["body_base64"], validate=True).decode("utf-8")
    assert isinstance(decoded_body, str)
    assert rows[first_source["number"]]["compound_obligations"] == [
        first_source["title"],
        f"body_sha256:{rows[first_source['number']]['body_sha256']}",
    ]
    serialized = json.dumps(payload)
    assert all(fragment not in serialized for fragment in ("B" + ":/M/", "B" + ":\\M\\"))
    assert payload["open_issue_count"] == 216
    assert {
        row["number"]
        for row in payload["issues"]
        if row["disposition"] == "implemented and independently verified"
    } == set()
    assert payload["closed_outcome_count"] == 38
    assert {row["number"] for row in payload["closed_outcomes"]} == {
        56,
        133,
        327,
        336,
        343,
        349,
        351,
        357,
        358,
        365,
        368,
        375,
        377,
        394,
        401,
        410,
        412,
        417,
        420,
        424,
        433,
        437,
        445,
        450,
        468,
        482,
        504,
        533,
        575,
        581,
        602,
        615,
        628,
        629,
        631,
        639,
        665,
        749,
    }
    assert all(row["state_reason"] == "COMPLETED" for row in payload["closed_outcomes"])
    assert {row["number"] for row in payload["closed_outcomes"] if row["disposition"] == "unresolved"} == {327, 343, 468, 482, 615, 631, 749}


def test_issue_snapshot_and_row_hashes_are_recomputed_from_raw_source(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "fixture")
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    git(root, "add", "README.md")
    git(root, "commit", "-m", "fixture")
    head = git(root, "rev-parse", "HEAD")
    payload = build_issue_census(root, head, [issue(7, "First"), issue(9, "Second")])
    assert validate_issue_census(payload, repository_root=REPO_ROOT) == []
    payload["issue_source_snapshot"][0]["title"] = "tampered"
    errors = validate_issue_census(payload)
    assert "issue_record_hash_mismatch:7" in errors
    assert "issue_obligation_hash_mismatch:7" in errors
    assert "issue_snapshot_hash_mismatch" in errors


def test_closed_outcome_snapshot_is_content_bound() -> None:
    path = REPO_ROOT / "manifests" / "ember-01-custody" / "public-issue-census.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["closed_issue_source_snapshot"][0]["title"] = "tampered"
    assert "closed_issue_snapshot_hash_mismatch" in validate_issue_census(payload)


def _evidence_comment(number: int, head: str) -> dict:
    return {
        "url": f"https://github.com/wordingone/ember/issues/{number}#issuecomment-1",
        "body": f"Implementation {head[:8]}. Independent verification: python verify.py\nPASS\nexit code 0",
        "author": {"login": "independent-auditor"},
        "createdAt": "2026-07-12T00:00:00Z",
        "updatedAt": "2026-07-12T00:00:00Z",
    }


def _real_proof(root: Path, head: str, number: int) -> dict:
    criterion = f"verified issue {number}"
    comment = _evidence_comment(number, head)
    changed_paths = sorted(
        set(git(root, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-m", head).splitlines())
    )
    return {
        "number": number,
        "commit": head,
        "implementation_commit": head,
        "implementation_paths": ["receipt.json", "verify.py"],
        "implementation_diff_sha256": hashlib.sha256(
            ("\n".join(changed_paths) + "\n").encode()
        ).hexdigest(),
        "artifact_path": "receipt.json",
        "artifact_sha256": hashlib.sha256((root / "receipt.json").read_bytes()).hexdigest(),
        "verifier_path": "verify.py",
        "verifier_sha256": hashlib.sha256((root / "verify.py").read_bytes()).hexdigest(),
        "criterion": criterion,
        "criterion_sha256": hashlib.sha256(criterion.encode()).hexdigest(),
        "evidence_comment_url": comment["url"],
        "evidence_comment_body_sha256": hashlib.sha256(comment["body"].encode()).hexdigest(),
        "verification_evidence_excerpt": "python verify.py",
        "verification_exit_code": 0,
        "verification_outcome": "independently_verified",
        "verification_executed_at": comment["createdAt"],
    }


def _proof_repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"; root.mkdir(); git(root, "init"); git(root, "config", "user.email", "fixture@example.invalid"); git(root, "config", "user.name", "fixture")
    (root / "receipt.json").write_text("proof\n", encoding="utf-8"); (root / "verify.py").write_text("verify\n", encoding="utf-8"); git(root, "add", "."); git(root, "commit", "-m", "proof")
    return root, git(root, "rev-parse", "HEAD")


def test_implemented_open_row_requires_resolved_git_proof(tmp_path: Path) -> None:
    root, head = _proof_repo(tmp_path); proof = _real_proof(root, head, 7)
    open_issue = {**issue(7, "Done"), "comments": [_evidence_comment(7, head)]}
    payload = build_issue_census(root, head, [open_issue], completion_evidence=[proof])
    assert payload["issues"][0]["closure_proposed"] is False
    assert validate_issue_census(payload, repository_root=root) == []
    payload["issues"][0]["completion_proof"][0]["artifact_sha256"] = "f" * 64
    assert "completion_artifact_hash_mismatch:7" in validate_issue_census(payload, repository_root=root)


def test_generator_emits_content_bound_closed_outcome(tmp_path: Path) -> None:
    root, head = _proof_repo(tmp_path); proof = _real_proof(root, head, 56); closed = {**issue(56, "Closed"), "state": "CLOSED", "stateReason": "COMPLETED", "closedAt": "2026-07-12T00:00:00Z", "comments": [_evidence_comment(56, head)]}
    payload = build_issue_census(root, head, [issue(7, "Open")], closed_issues=[closed], completion_evidence=[proof])
    outcome = payload["closed_outcomes"][0]
    assert payload["closed_issue_source_snapshot"][0]["state"] == "CLOSED"
    assert payload["closed_issue_source_snapshot"][0]["state_reason"] == "COMPLETED"
    assert outcome["author"] == "operator" and outcome["created_at"] == closed["createdAt"]
    assert "verification_evidence_excerpt" not in outcome["completion_proof"][0]
    assert validate_issue_census(payload, repository_root=root) == []
    limited_proof = {**proof, "closed_disposition": "unresolved", "unresolved_remainder": "reported execution lacks a retained decisive replay receipt"}
    limited = build_issue_census(root, head, [issue(7, "Open")], closed_issues=[closed], completion_evidence=[limited_proof])
    assert limited["closed_outcomes"][0]["disposition"] == "unresolved"
    assert validate_issue_census(limited, repository_root=root) == []
    outcome["completion_proof"][0]["absent_paths"] = ["receipt.json"]
    assert "completion_absent_path_present:56" in validate_issue_census(payload, repository_root=root)
    outcome["completion_proof"][0]["absent_paths"] = []
    outcome["completion_proof"][0]["number"] = 7
    assert "completion_proof_issue_mismatch:56" in validate_issue_census(payload, repository_root=root)
    outcome["completion_proof"][0]["number"] = 56
    duplicate = copy.deepcopy(payload)
    duplicate["closed_issue_source_snapshot"].append(copy.deepcopy(duplicate["closed_issue_source_snapshot"][0]))
    duplicate["closed_outcomes"].append(copy.deepcopy(duplicate["closed_outcomes"][0]))
    duplicate["closed_outcome_count"] = 2
    assert "closed_issue_number_duplicate:56" in validate_issue_census(duplicate, repository_root=root)
    outcome["author"] = "invented"
    assert "closed_outcome_source_mismatch:56:author" in validate_issue_census(payload, repository_root=root)
    outcome["author"] = "operator"
    outcome["completion_proof"][0]["implementation_commit"] = "0" * 40
    assert "implementation_commit_not_ancestor:56" in validate_issue_census(payload, repository_root=root)
    outcome["completion_proof"][0]["implementation_commit"] = head
    outcome["completion_proof"][0]["implementation_paths"] = ["not-changed.txt"]
    assert "implementation_paths_not_changed:56" in validate_issue_census(payload, repository_root=root)
    outcome["completion_proof"][0]["implementation_paths"] = proof["implementation_paths"]
    outcome["completion_proof"][0]["evidence_comment_body_sha256"] = "0" * 64
    assert "completion_evidence_comment_hash_mismatch:56" in validate_issue_census(payload, repository_root=root)
    outcome["completion_proof"][0]["evidence_comment_body_sha256"] = proof["evidence_comment_body_sha256"]
    payload["issue_source_snapshot"][0]["state"] = "CLOSED"
    assert "open_issue_state_invalid:7" in validate_issue_census(payload, repository_root=root)
    payload["issue_source_snapshot"][0]["state"] = "OPEN"
    overlap = copy.deepcopy(payload)
    overlap["closed_issue_source_snapshot"][0]["number"] = 7
    assert "open_closed_issue_overlap:7" in validate_issue_census(overlap, repository_root=root)


def test_issue_cli_accepts_closed_and_evidence_inputs(tmp_path: Path) -> None:
    root, head = _proof_repo(tmp_path); proof = _real_proof(root, head, 56)
    open_path, closed_path, evidence_path, output = tmp_path / "open.json", tmp_path / "closed.json", tmp_path / "evidence.json", tmp_path / "out.json"
    open_path.write_text(json.dumps([issue(7, "Open")]), encoding="utf-8"); closed_path.write_text(json.dumps([{**issue(56, "Closed"), "state": "CLOSED", "stateReason": "COMPLETED", "closedAt": "2026-07-12T00:00:00Z", "comments": [_evidence_comment(56, head)]}]), encoding="utf-8"); evidence_path.write_text(json.dumps([proof]), encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT_ROOT / "issue_census.py"), "--repo-root", str(root), "--public-ref", head, "--issues-json", str(open_path), "--closed-issues-json", str(closed_path), "--completion-evidence-json", str(evidence_path), "--output", str(output)], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["closed_outcome_count"] == 1


def test_audit_override_preserves_nonclosure_historical_successor_mapping(tmp_path: Path) -> None:
    root, head = _proof_repo(tmp_path)
    override = {"number": 682, "disposition": "historical sub-3B or borrowed-lineage non-executable evidence", "canonical_issue": 812, "canonical_issue_url": "https://github.com/wordingone/ember/issues/812", "canonical_obligation_sha256": hashlib.sha256(b"body for 812").hexdigest(), "preserved_issue_body_sha256": hashlib.sha256(b"body for 682").hexdigest()}
    payload = build_issue_census(root, head, [issue(682, "Historical"), issue(812, "Canonical")], completion_evidence=[override])
    row = next(item for item in payload["issues"] if item["number"] == 682)
    assert row["disposition"] == override["disposition"] and row["canonical_issue"] == 812
    assert row["preserved_issue_body_sha256"] == override["preserved_issue_body_sha256"]
    assert row["closure_proposed"] is False and row["completion_proof"] == []
    assert validate_issue_census(payload, repository_root=root) == []
    row["canonical_obligation_sha256"] = "0" * 64
    assert "historical_canonical_mapping_invalid:682" in validate_issue_census(payload, repository_root=root)
