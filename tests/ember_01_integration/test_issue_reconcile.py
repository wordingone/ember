# goal_id: EMBER-01
# workstream_id: EMBER-01A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ember_01_integration" / "issue_reconcile.py"
PUBLIC_MASTER_SHA = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
).strip()


def _run_plan(
    tmp_path: Path,
    census: dict,
    live: list[dict],
    repository_root: Path = REPO_ROOT,
    public_ref: str = "HEAD",
) -> subprocess.CompletedProcess[str]:
    census_path = tmp_path / "census.json"
    live_path = tmp_path / "live.json"
    output_path = tmp_path / "plan.json"
    census_path.write_text(json.dumps(census), encoding="utf-8")
    live_path.write_text(json.dumps(live), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "plan",
            "--census",
            str(census_path),
            "--live",
            str(live_path),
            "--output",
            str(output_path),
            "--repo-root",
            str(repository_root),
            "--public-ref",
            public_ref,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_plan_rejects_an_unclassified_issue(tmp_path: Path) -> None:
    census = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": PUBLIC_MASTER_SHA,
        "issues": [
            {
                "number": 812,
                "title": "canonical current obligation",
                "body_sha256": "b" * 64,
                "disposition": "",
                "closure_proposed": False,
                "completion_proof": [],
                "canonical_issue": None,
                "canonical_obligation_sha256": None,
                "obligation_sha256": "c" * 64,
                "unresolved_remainder": "current obligation remains open",
            }
        ],
    }
    live = [
        {
            "number": 812,
            "state": "OPEN",
            "body_sha256": "b" * 64,
        }
    ]

    result = _run_plan(tmp_path, census, live)

    assert result.returncode == 1
    assert "issue_disposition_invalid:812" in result.stdout


def test_plan_rejects_live_issue_body_drift(tmp_path: Path) -> None:
    census = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": PUBLIC_MASTER_SHA,
        "issues": [
            {
                "number": 812,
                "title": "canonical current obligation",
                "body_sha256": "b" * 64,
                "disposition": "current executable obligation",
                "closure_proposed": False,
                "completion_proof": [],
                "canonical_issue": None,
                "canonical_obligation_sha256": None,
                "obligation_sha256": "c" * 64,
                "unresolved_remainder": "current obligation remains open",
            }
        ],
    }
    live = [
        {
            "number": 812,
            "state": "OPEN",
            "body_sha256": "d" * 64,
        }
    ]

    result = _run_plan(tmp_path, census, live)

    assert result.returncode == 1
    assert "issue_body_changed:812" in result.stdout

def test_plan_rejects_closure_without_immutable_proof(tmp_path: Path) -> None:
    census = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": PUBLIC_MASTER_SHA,
        "issues": [
            {
                "number": 450,
                "title": "fixed defect",
                "body_sha256": "b" * 64,
                "disposition": "implemented and independently verified",
                "closure_proposed": True,
                "completion_proof": [],
                "canonical_issue": None,
                "canonical_obligation_sha256": None,
                "obligation_sha256": "c" * 64,
                "unresolved_remainder": "",
            }
        ],
    }
    live = [
        {
            "number": 450,
            "state": "OPEN",
            "body_sha256": "b" * 64,
        }
    ]

    result = _run_plan(tmp_path, census, live)

    assert result.returncode == 1
    assert "closure_completion_proof_missing:450" in result.stdout

def test_plan_emits_idempotent_label_and_comment_operations(tmp_path: Path) -> None:
    census = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": PUBLIC_MASTER_SHA,
        "issues": [
            {
                "number": 812,
                "title": "canonical current obligation",
                "body_sha256": "b" * 64,
                "disposition": "current executable obligation",
                "closure_proposed": False,
                "completion_proof": [],
                "canonical_issue": None,
                "canonical_obligation_sha256": None,
                "obligation_sha256": "c" * 64,
                "unresolved_remainder": "current obligation remains open",
            }
        ],
    }
    live = [
        {
            "number": 812,
            "state": "OPEN",
            "body_sha256": "b" * 64,
        }
    ]

    result = _run_plan(tmp_path, census, live)

    assert result.returncode == 0
    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    assert plan["schema"] == "ember-01-issue-reconciliation-plan-v1"
    assert plan["mutation_performed"] is False
    assert plan["live_snapshot_authoritative"] is False
    assert plan["requires_live_reverification"] is True
    assert plan["public_master_sha"] == PUBLIC_MASTER_SHA
    issue = plan["issues"][0]
    assert issue["number"] == 812
    assert issue["expected_state"] == "OPEN"
    assert [operation["type"] for operation in issue["operations"]] == [
        "propose_ensure_label",
        "propose_ensure_comment",
    ]
    assert issue["operations"][0]["label"] == "ember:current"
    assert "ember-01-reconcile:v1" in issue["operations"][1]["marker"]
    assert "current obligation remains open" in issue["operations"][1]["body"]

def test_plan_rejects_every_unsupported_closure_shape(tmp_path: Path) -> None:
    valid_proof = [
        {
            "commit": "d" * 40,
            "artifact_sha256": "e" * 64,
            "criterion": "all acceptance items pass",
        }
    ]
    cases = [
        (
            "current executable obligation",
            valid_proof,
            "",
            "closure_disposition_lacks_allowed_basis:500",
        ),
        (
            "expired operational incident",
            [],
            "",
            "closure_completion_proof_missing:500",
        ),
        (
            "implemented and independently verified",
            [{"commit": "short", "artifact_sha256": "e" * 64, "criterion": "x"}],
            "",
            "closure_completion_proof_invalid:500",
        ),
        (
            "implemented and independently verified",
            valid_proof,
            "one acceptance item remains",
            "closure_has_unresolved_remainder:500",
        ),
    ]
    for disposition, proof, remainder, expected_error in cases:
        census = {
            "schema": "ember-01-public-issue-census-v1",
            "public_master_sha": PUBLIC_MASTER_SHA,
            "issues": [
                {
                    "number": 500,
                    "title": "closure candidate",
                    "body_sha256": "b" * 64,
                    "disposition": disposition,
                    "closure_proposed": True,
                    "completion_proof": proof,
                    "canonical_issue": None,
                    "canonical_obligation_sha256": None,
                    "obligation_sha256": "c" * 64,
                    "unresolved_remainder": remainder,
                }
            ],
        }
        live = [{"number": 500, "state": "OPEN", "body_sha256": "b" * 64}]

        result = _run_plan(tmp_path, census, live)

        assert result.returncode == 1
        assert expected_error in result.stdout

def test_exact_successor_closure_requires_live_body_hash_and_emits_close(
    tmp_path: Path,
) -> None:
    successor_body_sha256 = "f" * 64
    source = {
        "number": 682,
        "title": "historical shard path defect",
        "body_sha256": "b" * 64,
        "disposition": "superseded by an exact named successor",
        "closure_proposed": True,
        "completion_proof": [],
        "canonical_issue": 812,
        "canonical_obligation_sha256": "0" * 64,
        "obligation_sha256": "c" * 64,
        "unresolved_remainder": "",
    }
    successor = {
        "number": 812,
        "title": "current EMBER-02 trainer input identity",
        "body_sha256": successor_body_sha256,
        "disposition": "current executable obligation",
        "closure_proposed": False,
        "completion_proof": [],
        "canonical_issue": None,
        "canonical_obligation_sha256": None,
        "obligation_sha256": "c" * 64,
        "unresolved_remainder": "authorized implementation remains open",
    }
    census = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": PUBLIC_MASTER_SHA,
        "issues": [source, successor],
    }
    live = [
        {"number": 682, "state": "OPEN", "body_sha256": "b" * 64},
        {
            "number": 812,
            "state": "OPEN",
            "body_sha256": successor_body_sha256,
            "body": "preserves_issue: #682\nsource_body_sha256: " + "b" * 64,
        },
    ]

    invalid = _run_plan(tmp_path, census, live)

    assert invalid.returncode == 1
    assert "closure_canonical_obligation_mismatch:682" in invalid.stdout

    source["canonical_obligation_sha256"] = successor_body_sha256
    live[1]["body"] = "unrelated successor body"
    not_preserved = _run_plan(tmp_path, census, live)
    assert not_preserved.returncode == 1
    assert "closure_canonical_source_not_preserved:682" in not_preserved.stdout
    live[1]["body"] = "preserves_issue: #682\nsource_body_sha256: " + "b" * 64

    successor["closure_proposed"] = True
    closing_target = _run_plan(tmp_path, census, live)
    assert closing_target.returncode == 1
    assert "closure_canonical_target_not_surviving:682" in closing_target.stdout
    successor["closure_proposed"] = False

    valid = _run_plan(tmp_path, census, live)

    assert valid.returncode == 0
    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    source_plan = next(row for row in plan["issues"] if row["number"] == 682)
    assert [operation["type"] for operation in source_plan["operations"]] == [
        "propose_ensure_label",
        "propose_ensure_comment",
        "propose_close",
    ]
    assert source_plan["operations"][-1]["reason"] == "not_planned"
    assert source_plan["operations"][-1]["canonical_issue"] == 812
    comment = next(
        operation["body"]
        for operation in source_plan["operations"]
        if operation["type"] == "propose_ensure_comment"
    )
    assert "Canonical issue: #812." in comment
    assert f"Canonical obligation SHA-256: {successor_body_sha256}." in comment

def test_plan_rejects_a_live_issue_missing_from_the_census(tmp_path: Path) -> None:
    census = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": PUBLIC_MASTER_SHA,
        "issues": [
            {
                "number": 812,
                "title": "known obligation",
                "body_sha256": "b" * 64,
                "disposition": "current executable obligation",
                "closure_proposed": False,
                "completion_proof": [],
                "canonical_issue": None,
                "canonical_obligation_sha256": None,
                "obligation_sha256": "c" * 64,
                "unresolved_remainder": "open",
            }
        ],
    }
    live = [
        {"number": 812, "state": "OPEN", "body_sha256": "b" * 64},
        {"number": 900, "state": "OPEN", "body_sha256": "d" * 64},
        {"number": 901, "state": "CLOSED", "body_sha256": "e" * 64},
    ]

    result = _run_plan(tmp_path, census, live)

    assert result.returncode == 1
    assert "live_issue_unclassified:900" in result.stdout
    assert "live_issue_unclassified:901" in result.stdout

def test_plan_skips_an_existing_matching_label_and_comment(tmp_path: Path) -> None:
    obligation_sha256 = "c" * 64
    marker = (
        "<!-- ember-01-reconcile:v1 "
        f"issue=812 obligation_sha256={obligation_sha256} -->"
    )
    census = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": PUBLIC_MASTER_SHA,
        "issues": [
            {
                "number": 812,
                "title": "known obligation",
                "body_sha256": "b" * 64,
                "disposition": "current executable obligation",
                "closure_proposed": False,
                "completion_proof": [],
                "canonical_issue": None,
                "canonical_obligation_sha256": None,
                "obligation_sha256": obligation_sha256,
                "unresolved_remainder": "open",
            }
        ],
    }
    live = [
        {
            "number": 812,
            "state": "OPEN",
            "body_sha256": "b" * 64,
            "labels": ["ember:current"],
            "comments": [],
        }
    ]

    initial = _run_plan(tmp_path, census, live)
    assert initial.returncode == 0
    initial_plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    marker = next(
        operation["marker"]
        for operation in initial_plan["issues"][0]["operations"]
        if operation["type"] == "propose_ensure_comment"
    )
    live[0]["comments"] = [{"body": f"classification receipt\n{marker}"}]

    result = _run_plan(tmp_path, census, live)

    assert result.returncode == 0
    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    assert plan["issues"][0]["operations"] == []

def test_plan_removes_conflicting_disposition_labels(tmp_path: Path) -> None:
    obligation_sha256 = "c" * 64
    marker = (
        "<!-- ember-01-reconcile:v1 "
        f"issue=812 obligation_sha256={obligation_sha256} -->"
    )
    census = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": PUBLIC_MASTER_SHA,
        "issues": [
            {
                "number": 812,
                "title": "known obligation",
                "body_sha256": "b" * 64,
                "disposition": "current executable obligation",
                "closure_proposed": False,
                "completion_proof": [],
                "canonical_issue": None,
                "canonical_obligation_sha256": None,
                "obligation_sha256": obligation_sha256,
                "unresolved_remainder": "open",
            }
        ],
    }
    live = [
        {
            "number": 812,
            "state": "OPEN",
            "body_sha256": "b" * 64,
            "labels": ["ember:current", "ember:research"],
            "comments": [],
        }
    ]

    initial = _run_plan(tmp_path, census, live)
    assert initial.returncode == 0
    initial_plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    marker = next(
        operation["marker"]
        for operation in initial_plan["issues"][0]["operations"]
        if operation["type"] == "propose_ensure_comment"
    )
    live[0]["comments"] = [{"body": marker}]

    result = _run_plan(tmp_path, census, live)

    assert result.returncode == 0
    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    assert plan["issues"][0]["operations"] == [
        {"type": "propose_remove_label", "label": "ember:research"}
    ]

def test_completed_closure_comment_carries_immutable_proof(tmp_path: Path) -> None:
    criterion = "all acceptance items pass"
    proof_repository = tmp_path / "proof-repository"
    proof_repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=proof_repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "proof@example.invalid"],
        cwd=proof_repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Proof Fixture"],
        cwd=proof_repository,
        check=True,
    )
    subject = proof_repository / "subject.txt"
    subject.write_text("verified implementation bytes\n", encoding="utf-8")
    subprocess.run(["git", "add", "subject.txt"], cwd=proof_repository, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "Add verified subject"],
        cwd=proof_repository,
        check=True,
    )
    subject_public_master_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=proof_repository, text=True
    ).strip()
    artifact_path = "receipts/issue-450-proof.json"
    artifact = proof_repository / artifact_path
    artifact.parent.mkdir()
    receipt = {
        "schema": "ember-01-issue-closure-proof-v1",
        "issue": 450,
        "disposition": "implemented and independently verified",
        "criterion": criterion,
        "result": "PASSED",
        "independent_verification": True,
        "evidence": ["merged cure and independent focused replay"],
        "source_body_sha256": "b" * 64,
        "obligation_sha256": "c" * 64,
        "subject_public_master_sha": subject_public_master_sha,
    }
    artifact.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    subprocess.run(["git", "add", artifact_path], cwd=proof_repository, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "Add issue closure proof"],
        cwd=proof_repository,
        check=True,
    )
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=proof_repository, text=True
    ).strip()
    proof = {
        "commit": commit,
        "artifact_path": artifact_path,
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "criterion": criterion,
    }
    census = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": commit,
        "issues": [
            {
                "number": 450,
                "title": "verified defect cure",
                "body_sha256": "b" * 64,
                "disposition": "implemented and independently verified",
                "closure_proposed": True,
                "completion_proof": [proof],
                "canonical_issue": None,
                "canonical_obligation_sha256": None,
                "obligation_sha256": "c" * 64,
                "unresolved_remainder": "",
            }
        ],
    }
    live = [{"number": 450, "state": "OPEN", "body_sha256": "b" * 64}]

    census["issues"][0]["closure_proposed"] = False
    initial = _run_plan(tmp_path, census, live, proof_repository)
    initial_plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    initial_comment = next(
        operation
        for operation in initial_plan["issues"][0]["operations"]
        if operation["type"] == "propose_ensure_comment"
    )
    live[0]["labels"] = ["ember:verified"]
    live[0]["comments"] = [{"body": initial_comment["body"]}]
    census["issues"][0]["closure_proposed"] = True

    result = _run_plan(tmp_path, census, live, proof_repository)

    assert result.returncode == 0
    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    operations = plan["issues"][0]["operations"]
    comment = next(row["body"] for row in operations if row["type"] == "propose_ensure_comment")
    assert f"Proof commit: {proof['commit']}." in comment
    assert f"Proof artifact SHA-256: {proof['artifact_sha256']}." in comment
    assert f"Proof criterion: {proof['criterion']}." in comment
    assert operations[-1] == {"type": "propose_close", "reason": "completed"}
    census["issues"][0]["body_sha256"] = "f" * 64
    live[0]["body_sha256"] = "f" * 64
    changed_obligation = _run_plan(tmp_path, census, live, proof_repository)
    assert changed_obligation.returncode == 1
    assert (
        "closure_completion_proof_unverified:450" in changed_obligation.stdout
    )

def test_plan_rejects_duplicate_census_and_live_issue_numbers(tmp_path: Path) -> None:
    row = {
        "number": 812,
        "title": "known obligation",
        "body_sha256": "b" * 64,
        "disposition": "current executable obligation",
        "closure_proposed": False,
        "completion_proof": [],
        "canonical_issue": None,
        "canonical_obligation_sha256": None,
        "obligation_sha256": "c" * 64,
        "unresolved_remainder": "open",
    }
    census = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": PUBLIC_MASTER_SHA,
        "issues": [row, dict(row)],
    }
    live = [{"number": 812, "state": "OPEN", "body_sha256": "b" * 64}]

    duplicate_census = _run_plan(tmp_path, census, live)

    assert duplicate_census.returncode == 1
    assert "census_issue_duplicate:812" in duplicate_census.stdout

    census["issues"] = [row]
    live.append(dict(live[0]))
    duplicate_live = _run_plan(tmp_path, census, live)

    assert duplicate_live.returncode == 1
    assert "live_issue_duplicate:812" in duplicate_live.stdout

def test_plan_rejects_closing_an_already_closed_issue(tmp_path: Path) -> None:
    census = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": PUBLIC_MASTER_SHA,
        "issues": [
            {
                "number": 450,
                "title": "already closed",
                "body_sha256": "b" * 64,
                "disposition": "implemented and independently verified",
                "closure_proposed": True,
                "completion_proof": [
                    {
                        "commit": "d" * 40,
                        "artifact_sha256": "e" * 64,
                        "criterion": "verified",
                    }
                ],
                "canonical_issue": None,
                "canonical_obligation_sha256": None,
                "obligation_sha256": "c" * 64,
                "unresolved_remainder": "",
            }
        ],
    }
    live = [{"number": 450, "state": "CLOSED", "body_sha256": "b" * 64}]

    result = _run_plan(tmp_path, census, live)

    assert result.returncode == 1
    assert "closure_source_not_open:450" in result.stdout

def test_disposition_change_forces_a_new_bound_comment(tmp_path: Path) -> None:
    row = {
        "number": 812,
        "title": "known obligation",
        "body_sha256": "b" * 64,
        "disposition": "current executable obligation",
        "closure_proposed": False,
        "completion_proof": [],
        "canonical_issue": None,
        "canonical_obligation_sha256": None,
        "obligation_sha256": "c" * 64,
        "unresolved_remainder": "implementation remains open",
    }
    census = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": PUBLIC_MASTER_SHA,
        "issues": [row],
    }
    live = [{"number": 812, "state": "OPEN", "body_sha256": "b" * 64}]

    initial = _run_plan(tmp_path, census, live)

    assert initial.returncode == 0
    initial_plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    initial_comment = next(
        operation
        for operation in initial_plan["issues"][0]["operations"]
        if operation["type"] == "propose_ensure_comment"
    )
    live[0]["labels"] = ["ember:current"]
    live[0]["comments"] = [{"body": initial_comment["body"]}]
    row["disposition"] = "preserved research direction"
    row["unresolved_remainder"] = "research direction remains preserved"

    changed = _run_plan(tmp_path, census, live)

    assert changed.returncode == 0
    changed_plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    assert [op["type"] for op in changed_plan["issues"][0]["operations"]] == [
        "propose_remove_label",
        "propose_ensure_label",
        "propose_ensure_comment",
    ]
    changed_comment = changed_plan["issues"][0]["operations"][-1]
    assert changed_comment["marker"] != initial_comment["marker"]

def test_plan_rejects_a_stale_public_master_binding(tmp_path: Path) -> None:
    census = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": "0" * 40,
        "issues": [
            {
                "number": 812,
                "title": "known obligation",
                "body_sha256": "b" * 64,
                "disposition": "current executable obligation",
                "closure_proposed": False,
                "completion_proof": [],
                "canonical_issue": None,
                "canonical_obligation_sha256": None,
                "obligation_sha256": "c" * 64,
                "unresolved_remainder": "open",
            }
        ],
    }
    live = [{"number": 812, "state": "OPEN", "body_sha256": "b" * 64}]
    census_path = tmp_path / "census.json"
    live_path = tmp_path / "live.json"
    census_path.write_text(json.dumps(census), encoding="utf-8")
    live_path.write_text(json.dumps(live), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "plan",
            "--census",
            str(census_path),
            "--live",
            str(live_path),
            "--output",
            str(tmp_path / "plan.json"),
            "--repo-root",
            str(REPO_ROOT),
            "--public-ref",
            "HEAD",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "public_master_mismatch" in result.stdout


def test_plan_requires_an_explicit_public_ref(tmp_path: Path) -> None:
    census_path = tmp_path / "census.json"
    live_path = tmp_path / "live.json"
    census_path.write_text("{}", encoding="utf-8")
    live_path.write_text("[]", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "plan",
            "--census",
            str(census_path),
            "--live",
            str(live_path),
            "--output",
            str(tmp_path / "plan.json"),
            "--repo-root",
            str(REPO_ROOT),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--public-ref" in result.stderr


def test_plan_rejects_valid_shaped_but_unbacked_closure_proof(
    tmp_path: Path,
) -> None:
    census = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": PUBLIC_MASTER_SHA,
        "issues": [
            {
                "number": 450,
                "title": "unbacked cure claim",
                "body_sha256": "b" * 64,
                "disposition": "implemented and independently verified",
                "closure_proposed": True,
                "completion_proof": [
                    {
                        "commit": "d" * 40,
                        "artifact_path": "receipts/fabricated.json",
                        "artifact_sha256": "e" * 64,
                        "criterion": "all acceptance items pass",
                    }
                ],
                "canonical_issue": None,
                "canonical_obligation_sha256": None,
                "obligation_sha256": "c" * 64,
                "unresolved_remainder": "",
            }
        ],
    }
    live = [{"number": 450, "state": "OPEN", "body_sha256": "b" * 64}]

    result = _run_plan(tmp_path, census, live)

    assert result.returncode == 1
    assert "closure_completion_proof_unverified:450" in result.stdout

def test_plan_rejects_multiple_unlinked_canonical_issues_for_one_obligation(
    tmp_path: Path,
) -> None:
    obligation_sha256 = "c" * 64
    rows = []
    live = []
    for number, body_sha256 in ((812, "b" * 64), (813, "d" * 64)):
        rows.append(
            {
                "number": number,
                "title": f"canonical candidate {number}",
                "body_sha256": body_sha256,
                "disposition": "current executable obligation",
                "closure_proposed": False,
                "completion_proof": [],
                "canonical_issue": None,
                "canonical_obligation_sha256": None,
                "obligation_sha256": obligation_sha256,
                "unresolved_remainder": "open",
            }
        )
        live.append(
            {
                "number": number,
                "state": "OPEN",
                "body_sha256": body_sha256,
            }
        )
    census = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": PUBLIC_MASTER_SHA,
        "issues": rows,
    }

    result = _run_plan(tmp_path, census, live)

    assert result.returncode == 1
    assert (
        f"obligation_multiple_unlinked:{obligation_sha256}:812,813"
        in result.stdout
    )


def test_plan_rejects_malformed_content_hash_bindings(tmp_path: Path) -> None:
    census = {
        "schema": "ember-01-public-issue-census-v1",
        "public_master_sha": PUBLIC_MASTER_SHA,
        "issues": [
            {
                "number": 812,
                "title": "malformed identity bindings",
                "body_sha256": "not-a-body-hash",
                "disposition": "current executable obligation",
                "closure_proposed": False,
                "completion_proof": [],
                "canonical_issue": None,
                "canonical_obligation_sha256": None,
                "obligation_sha256": "not-an-obligation-hash",
                "unresolved_remainder": "open",
            }
        ],
    }
    live = [
        {
            "number": 812,
            "state": "OPEN",
            "body_sha256": "not-a-body-hash",
        }
    ]

    result = _run_plan(tmp_path, census, live)

    assert result.returncode == 1
    assert "issue_body_sha256_invalid:812" in result.stdout
    assert "live_issue_body_sha256_invalid:812" in result.stdout
    assert "issue_obligation_sha256_invalid:812" in result.stdout
