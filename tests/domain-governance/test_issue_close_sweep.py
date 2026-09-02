# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed tests for the trusted issue close-sweep apply boundary."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
sys.path.insert(0, str(ROOT))

from scripts import issue_close_sweep
# issue2015 exact-local-import:src/ember/governance/scripts/issue_close_sweep.py
import importlib.util as _ember_5c01894f4e13f2b2_importlib
import sys as _ember_5c01894f4e13f2b2_sys
from pathlib import Path as _ember_5c01894f4e13f2b2_Path
_ember_5c01894f4e13f2b2_path = _ember_5c01894f4e13f2b2_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'issue_close_sweep.py')
if not _ember_5c01894f4e13f2b2_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/issue_close_sweep.py')
_ember_5c01894f4e13f2b2_aliases = ('_ember_issue2015_5c01894f4e13f2b2', 'issue_close_sweep', 'scripts.issue_close_sweep', 'src.ember.governance.scripts.issue_close_sweep')
_ember_5c01894f4e13f2b2_existing = []
for _ember_5c01894f4e13f2b2_alias in _ember_5c01894f4e13f2b2_aliases:
    _ember_5c01894f4e13f2b2_candidate = _ember_5c01894f4e13f2b2_sys.modules.get(_ember_5c01894f4e13f2b2_alias)
    if _ember_5c01894f4e13f2b2_candidate is not None and all(_ember_5c01894f4e13f2b2_candidate is not item for item in _ember_5c01894f4e13f2b2_existing):
        _ember_5c01894f4e13f2b2_existing.append(_ember_5c01894f4e13f2b2_candidate)
if len(_ember_5c01894f4e13f2b2_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/issue_close_sweep.py')
if _ember_5c01894f4e13f2b2_existing:
    _ember_5c01894f4e13f2b2_module = _ember_5c01894f4e13f2b2_existing[0]
    _ember_5c01894f4e13f2b2_observed = getattr(_ember_5c01894f4e13f2b2_module, '__file__', None)
    if _ember_5c01894f4e13f2b2_observed is None or _ember_5c01894f4e13f2b2_Path(_ember_5c01894f4e13f2b2_observed).resolve() != _ember_5c01894f4e13f2b2_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/issue_close_sweep.py')
else:
    _ember_5c01894f4e13f2b2_spec = _ember_5c01894f4e13f2b2_importlib.spec_from_file_location('_ember_issue2015_5c01894f4e13f2b2', _ember_5c01894f4e13f2b2_path)
    if _ember_5c01894f4e13f2b2_spec is None or _ember_5c01894f4e13f2b2_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/issue_close_sweep.py')
    _ember_5c01894f4e13f2b2_module = _ember_5c01894f4e13f2b2_importlib.module_from_spec(_ember_5c01894f4e13f2b2_spec)
    for _ember_5c01894f4e13f2b2_alias in _ember_5c01894f4e13f2b2_aliases:
        _ember_5c01894f4e13f2b2_prior = _ember_5c01894f4e13f2b2_sys.modules.get(_ember_5c01894f4e13f2b2_alias)
        if _ember_5c01894f4e13f2b2_prior is not None and _ember_5c01894f4e13f2b2_prior is not _ember_5c01894f4e13f2b2_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/issue_close_sweep.py')
        _ember_5c01894f4e13f2b2_sys.modules[_ember_5c01894f4e13f2b2_alias] = _ember_5c01894f4e13f2b2_module
    try:
        _ember_5c01894f4e13f2b2_spec.loader.exec_module(_ember_5c01894f4e13f2b2_module)
    except BaseException:
        for _ember_5c01894f4e13f2b2_alias in _ember_5c01894f4e13f2b2_aliases:
            if _ember_5c01894f4e13f2b2_sys.modules.get(_ember_5c01894f4e13f2b2_alias) is _ember_5c01894f4e13f2b2_module:
                _ember_5c01894f4e13f2b2_sys.modules.pop(_ember_5c01894f4e13f2b2_alias, None)
        raise
for _ember_5c01894f4e13f2b2_alias in _ember_5c01894f4e13f2b2_aliases:
    _ember_5c01894f4e13f2b2_prior = _ember_5c01894f4e13f2b2_sys.modules.get(_ember_5c01894f4e13f2b2_alias)
    if _ember_5c01894f4e13f2b2_prior is not None and _ember_5c01894f4e13f2b2_prior is not _ember_5c01894f4e13f2b2_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/issue_close_sweep.py')
    _ember_5c01894f4e13f2b2_sys.modules[_ember_5c01894f4e13f2b2_alias] = _ember_5c01894f4e13f2b2_module
CloseSweepError = getattr(_ember_5c01894f4e13f2b2_module, 'CloseSweepError')
apply_close_plan = getattr(_ember_5c01894f4e13f2b2_module, 'apply_close_plan')
build_close_plan = getattr(_ember_5c01894f4e13f2b2_module, 'build_close_plan')
canonical_sha256 = getattr(_ember_5c01894f4e13f2b2_module, 'canonical_sha256')
# issue2015 exact-local-import-end:src/ember/governance/scripts/issue_close_sweep.py
# issue2015 exact-local-import:src/ember/governance/scripts/oldest_issue_disposition.py
import importlib.util as _ember_366a9bf8189d4fa2_importlib
import sys as _ember_366a9bf8189d4fa2_sys
from pathlib import Path as _ember_366a9bf8189d4fa2_Path
_ember_366a9bf8189d4fa2_path = _ember_366a9bf8189d4fa2_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'oldest_issue_disposition.py')
if not _ember_366a9bf8189d4fa2_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/oldest_issue_disposition.py')
_ember_366a9bf8189d4fa2_aliases = ('_ember_issue2015_366a9bf8189d4fa2', 'oldest_issue_disposition', 'scripts.oldest_issue_disposition', 'src.ember.governance.scripts.oldest_issue_disposition')
_ember_366a9bf8189d4fa2_existing = []
for _ember_366a9bf8189d4fa2_alias in _ember_366a9bf8189d4fa2_aliases:
    _ember_366a9bf8189d4fa2_candidate = _ember_366a9bf8189d4fa2_sys.modules.get(_ember_366a9bf8189d4fa2_alias)
    if _ember_366a9bf8189d4fa2_candidate is not None and all(_ember_366a9bf8189d4fa2_candidate is not item for item in _ember_366a9bf8189d4fa2_existing):
        _ember_366a9bf8189d4fa2_existing.append(_ember_366a9bf8189d4fa2_candidate)
if len(_ember_366a9bf8189d4fa2_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/oldest_issue_disposition.py')
if _ember_366a9bf8189d4fa2_existing:
    _ember_366a9bf8189d4fa2_module = _ember_366a9bf8189d4fa2_existing[0]
    _ember_366a9bf8189d4fa2_observed = getattr(_ember_366a9bf8189d4fa2_module, '__file__', None)
    if _ember_366a9bf8189d4fa2_observed is None or _ember_366a9bf8189d4fa2_Path(_ember_366a9bf8189d4fa2_observed).resolve() != _ember_366a9bf8189d4fa2_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/oldest_issue_disposition.py')
else:
    _ember_366a9bf8189d4fa2_spec = _ember_366a9bf8189d4fa2_importlib.spec_from_file_location('_ember_issue2015_366a9bf8189d4fa2', _ember_366a9bf8189d4fa2_path)
    if _ember_366a9bf8189d4fa2_spec is None or _ember_366a9bf8189d4fa2_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/oldest_issue_disposition.py')
    _ember_366a9bf8189d4fa2_module = _ember_366a9bf8189d4fa2_importlib.module_from_spec(_ember_366a9bf8189d4fa2_spec)
    for _ember_366a9bf8189d4fa2_alias in _ember_366a9bf8189d4fa2_aliases:
        _ember_366a9bf8189d4fa2_prior = _ember_366a9bf8189d4fa2_sys.modules.get(_ember_366a9bf8189d4fa2_alias)
        if _ember_366a9bf8189d4fa2_prior is not None and _ember_366a9bf8189d4fa2_prior is not _ember_366a9bf8189d4fa2_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/oldest_issue_disposition.py')
        _ember_366a9bf8189d4fa2_sys.modules[_ember_366a9bf8189d4fa2_alias] = _ember_366a9bf8189d4fa2_module
    try:
        _ember_366a9bf8189d4fa2_spec.loader.exec_module(_ember_366a9bf8189d4fa2_module)
    except BaseException:
        for _ember_366a9bf8189d4fa2_alias in _ember_366a9bf8189d4fa2_aliases:
            if _ember_366a9bf8189d4fa2_sys.modules.get(_ember_366a9bf8189d4fa2_alias) is _ember_366a9bf8189d4fa2_module:
                _ember_366a9bf8189d4fa2_sys.modules.pop(_ember_366a9bf8189d4fa2_alias, None)
        raise
for _ember_366a9bf8189d4fa2_alias in _ember_366a9bf8189d4fa2_aliases:
    _ember_366a9bf8189d4fa2_prior = _ember_366a9bf8189d4fa2_sys.modules.get(_ember_366a9bf8189d4fa2_alias)
    if _ember_366a9bf8189d4fa2_prior is not None and _ember_366a9bf8189d4fa2_prior is not _ember_366a9bf8189d4fa2_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/oldest_issue_disposition.py')
    _ember_366a9bf8189d4fa2_sys.modules[_ember_366a9bf8189d4fa2_alias] = _ember_366a9bf8189d4fa2_module
_AUTHORITY = getattr(_ember_366a9bf8189d4fa2_module, '_AUTHORITY')
build_capture = getattr(_ember_366a9bf8189d4fa2_module, 'build_capture')
build_packet = getattr(_ember_366a9bf8189d4fa2_module, 'build_packet')
# issue2015 exact-local-import-end:src/ember/governance/scripts/oldest_issue_disposition.py


def _packet() -> dict:
    issue = {
        "number": 805,
        "title": "Issue-close sweep loop",
        "body_sha256": hashlib.sha256(b"body").hexdigest(),
        "url": "https://github.com/wordingone/ember/issues/805",
        "created_at": "2026-07-11T17:36:53Z",
        "updated_at": "2026-07-30T02:51:51Z",
        "labels": ["kind:maintenance", "state:ready"],
        "author": "wordingone",
        "state": "open",
        "comment_count": 0,
        "comments": [],
        "source_stability": {
            "pre_sha256": "1" * 64,
            "post_sha256": "1" * 64,
            "stable": True,
        },
    }
    receipt = {
        "issue_number": 805,
        "disposition": "CLOSE",
        "source_clause_inventory": [
            {
                "source_kind": "issue_body",
                "citation": issue["url"],
                "source_sha256": issue["body_sha256"],
                "status": "BOUND",
            }
        ],
        "unbound_clause": None,
        "smallest_binding_action": None,
        "replacement_citation": None,
        "retained_lesson": None,
        "close_evidence": [
            {
                "citation": "https://github.com/wordingone/ember/pull/1200",
                "commit_sha": "a" * 40,
                "path": "src/ember/governance/scripts/issue_close_sweep.py",
                "blob_sha1": "b" * 40,
                "test_command": "python -B -m pytest -q tests/domain-governance/test_issue_close_sweep.py",
                "production_shaped": True,
                "clean_checkout": True,
                "passed": True,
            }
        ],
        "authority_review": {
            "reviewer": "self-review-authority",
            "review_provenance": "SELF_ONLY",
            "verdict": "PASS",
            "citation": "https://github.com/wordingone/ember/pull/1200",
            "reviewed_commit_sha": "a" * 40,
        },
        "issue_url": issue["url"],
        "capture_issue_sha256": canonical_sha256(issue),
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    packet = {
        "authority": {
            "goal_id": "EMBER-02",
            "workstream_id": "EMBER-02A",
            "next_executed_outcome": (
                "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
            ),
        },
        "schema_version": "ember-oldest-issue-disposition-packet-v1",
        "repository": "wordingone/ember",
        "master_sha": "c" * 40,
        "capture": {"issues": [issue]},
        "capture_sha256": "d" * 64,
        "selection_sha256": "e" * 64,
        "receipts": [receipt],
        "disposition_counts": {"CLOSE": 1},
        "deletion_or_issue_mutation_authority": "NOT_GRANTED",
        "public_issue_mutation_performed": False,
    }
    packet["packet_sha256"] = canonical_sha256(
        {key: value for key, value in packet.items() if key != "packet_sha256"}
    )
    return packet


def _canonical_packet(root: Path) -> dict:
    issues = []
    numbers = [805, *range(1001, 1021)]
    for index, number in enumerate(numbers):
        issue = {
            "number": number,
            "title": "Issue-close sweep loop" if number == 805 else f"Issue {number}",
            "body": "body" if number == 805 else f"Acceptance obligation {number}",
            "html_url": f"https://github.com/wordingone/ember/issues/{number}",
            "created_at": f"2026-01-{index + 1:02d}T00:00:00Z",
            "updated_at": f"2026-01-{index + 1:02d}T00:00:00Z",
            "comments": 0,
            "labels": [
                {"name": "kind:maintenance"},
                {"name": "state:ready"},
            ],
            "user": {"login": "wordingone"},
            "state": "open",
        }
        if number == 805:
            issue["created_at"] = "2026-01-01T00:00:00Z"
            issue["updated_at"] = "2026-01-01T00:00:00Z"
        issues.append(issue)
    pages = [issues]
    for name in ("issues_pre.json", "issues_post.json"):
        (root / name).write_text(
            json.dumps(copy.deepcopy(pages)),
            encoding="utf-8",
        )
    for issue in issues[:20]:
        for phase in ("pre", "post"):
            (root / f"comments-{issue['number']}-{phase}.json").write_text(
                "[[]]",
                encoding="utf-8",
            )
    capture = build_capture(
        root,
        master_sha="c" * 40,
        captured_at="2026-07-30T00:00:00Z",
    )
    rows = []
    for issue in capture["issues"]:
        row = {
            "issue_number": issue["number"],
            "disposition": "PARTIAL",
            "source_clause_inventory": [
                {
                    "source_kind": "issue_body",
                    "citation": issue["url"],
                    "source_sha256": issue["body_sha256"],
                    "status": "UNBOUND",
                }
            ],
            "unbound_clause": {
                "citation": issue["url"],
                "source_sha256": issue["body_sha256"],
                "description": "acceptance remains unproved",
            },
            "smallest_binding_action": "produce current-master evidence",
            "replacement_citation": None,
            "retained_lesson": None,
            "close_evidence": [],
            "authority_review": None,
        }
        if issue["number"] == 805:
            row.update(
                {
                    "disposition": "CLOSE",
                    "source_clause_inventory": [
                        {
                            "source_kind": "issue_body",
                            "citation": issue["url"],
                            "source_sha256": issue["body_sha256"],
                            "status": "BOUND",
                        }
                    ],
                    "unbound_clause": None,
                    "smallest_binding_action": None,
                    "close_evidence": [
                        {
                            "citation": "https://github.com/wordingone/ember/pull/1200",
                            "commit_sha": "a" * 40,
                            "path": "src/ember/governance/scripts/issue_close_sweep.py",
                            "blob_sha1": "b" * 40,
                            "test_command": "python -B -m pytest -q tests/domain-governance/test_issue_close_sweep.py",
                            "production_shaped": True,
                            "clean_checkout": True,
                            "passed": True,
                        }
                    ],
                    "authority_review": {
                        "reviewer": "self-review-authority",
                        "review_provenance": "SELF_ONLY",
                        "verdict": "PASS",
                        "citation": "https://github.com/wordingone/ember/pull/1200",
                        "reviewed_commit_sha": "a" * 40,
                    },
                }
            )
        rows.append(row)
    decisions = {
        "authority": dict(_AUTHORITY),
        "schema_version": "ember-oldest-issue-decisions-v1",
        "master_sha": capture["master_sha"],
        "selection_sha256": capture["selection_sha256"],
        "rows": rows,
    }
    return build_packet(capture, decisions)


def _authorization(packet: dict) -> dict:
    value = {
        "schema_version": "ember-issue-close-sweep-authorization-v1",
        "repository": "wordingone/ember",
        "packet_sha256": packet["packet_sha256"],
        "packet_path": ("receipts/oldest-issue-disposition/approved/batch-001.json"),
        "close_issue_numbers": [805],
        "reviewer": "self-review-authority",
        "review_provenance": "SELF_ONLY",
        "citation": "https://github.com/wordingone/ember/pull/1200",
    }
    value["authorization_sha256"] = canonical_sha256(value)
    return value


def _live_issue() -> dict:
    return {
        "number": 805,
        "title": "Issue-close sweep loop",
        "body": "body",
        "html_url": "https://github.com/wordingone/ember/issues/805",
        "created_at": "2026-07-11T17:36:53Z",
        "updated_at": "2026-07-30T02:51:51Z",
        "labels": [{"name": "kind:maintenance"}, {"name": "state:ready"}],
        "user": {"login": "wordingone"},
        "state": "open",
        "comments": 0,
    }


def test_build_plan_requires_separate_content_addressed_authorization() -> None:
    packet = _packet()
    authorization = _authorization(packet)
    authorization["packet_sha256"] = "0" * 64
    authorization["authorization_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in authorization.items()
            if key != "authorization_sha256"
        }
    )
    with pytest.raises(CloseSweepError, match="packet"):
        build_close_plan(
            packet,
            authorization,
            expected_master_sha="c" * 40,
            live_issues={805: (_live_issue(), [])},
        )


def test_build_plan_rejects_stale_or_ambiguous_live_issue() -> None:
    packet = _packet()
    authorization = _authorization(packet)
    live = _live_issue()
    live["body"] = "changed"
    with pytest.raises(CloseSweepError, match="live source"):
        build_close_plan(
            packet,
            authorization,
            expected_master_sha="c" * 40,
            live_issues={805: (live, [])},
        )


def test_build_plan_accepts_ancestor_packet_only_when_trusted_check_passed() -> None:
    packet = _packet()
    authorization = _authorization(packet)
    with pytest.raises(CloseSweepError, match="stale"):
        build_close_plan(
            packet,
            authorization,
            expected_master_sha="f" * 40,
            packet_master_is_ancestor=False,
            live_issues={805: (_live_issue(), [])},
        )
    plan = build_close_plan(
        packet,
        authorization,
        expected_master_sha="f" * 40,
        packet_master_is_ancestor=True,
        live_issues={805: (_live_issue(), [])},
    )
    assert plan["packet_master_sha"] == "c" * 40
    assert plan["expected_master_sha"] == "f" * 40


def test_authorization_rejects_packet_path_outside_trusted_namespace() -> None:
    packet = _packet()
    authorization = _authorization(packet)
    authorization["packet_path"] = "../untrusted.json"
    authorization["authorization_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in authorization.items()
            if key != "authorization_sha256"
        }
    )
    with pytest.raises(CloseSweepError, match="packet path"):
        build_close_plan(
            packet,
            authorization,
            expected_master_sha="c" * 40,
            live_issues={805: (_live_issue(), [])},
        )


def test_authorization_citation_must_match_reviewed_evidence() -> None:
    packet = _packet()
    authorization = _authorization(packet)
    authorization["citation"] = "https://github.com/wordingone/ember/pull/9999"
    authorization["authorization_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in authorization.items()
            if key != "authorization_sha256"
        }
    )
    with pytest.raises(CloseSweepError, match="citation"):
        build_close_plan(
            packet,
            authorization,
            expected_master_sha="c" * 40,
            live_issues={805: (_live_issue(), [])},
        )


def test_build_plan_rejects_goal_or_initiative_rows() -> None:
    packet = _packet()
    packet["capture"]["issues"][0]["labels"].append("kind:initiative")
    packet["receipts"][0]["capture_issue_sha256"] = canonical_sha256(
        packet["capture"]["issues"][0]
    )
    packet["receipts"][0]["receipt_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in packet["receipts"][0].items()
            if key != "receipt_sha256"
        }
    )
    packet["packet_sha256"] = canonical_sha256(
        {key: value for key, value in packet.items() if key != "packet_sha256"}
    )
    authorization = _authorization(packet)
    live = _live_issue()
    live["labels"].append({"name": "kind:initiative"})
    with pytest.raises(CloseSweepError, match="protected"):
        build_close_plan(
            packet,
            authorization,
            expected_master_sha="c" * 40,
            live_issues={805: (live, [])},
        )


def test_apply_posts_receipt_comment_before_close() -> None:
    packet = _packet()
    authorization = _authorization(packet)
    plan = build_close_plan(
        packet,
        authorization,
        expected_master_sha="c" * 40,
        live_issues={805: (_live_issue(), [])},
    )
    calls: list[tuple[str, int, str | None]] = []

    def mutate(action: str, number: int, body: str | None = None) -> None:
        calls.append((action, number, body))

    receipt = apply_close_plan(plan, mutate=mutate)
    assert [row[0] for row in calls] == ["comment", "close"]
    assert "PR #1200" in calls[0][2]
    assert "a" * 40 in calls[0][2]
    assert receipt["closed_issue_numbers"] == [805]
    assert (
        receipt["closed"][0]["receipt_sha256"]
        == plan["operations"][0]["receipt_sha256"]
    )
    assert receipt["skipped"] == []
    assert receipt["cursor"]["first_issue_number"] == 805
    assert receipt["cursor"]["last_issue_number"] == 805
    assert (
        receipt["cursor"]["last_issue_created_at"]
        == "2026-07-11T17:36:53Z"
    )
    assert receipt["mutation_count"] == 2


def test_validate_cli_reads_live_issue_and_writes_content_addressed_plan(
    tmp_path: Path,
) -> None:
    capture_root = tmp_path / "capture"
    capture_root.mkdir()
    packet = _canonical_packet(capture_root)
    authorization = _authorization(packet)
    packet_path = tmp_path / "packet.json"
    authorization_path = tmp_path / "authorization.json"
    output_path = tmp_path / "plan.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
    calls: list[list[str]] = []

    def run_gh(argv: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if argv[-1] == ".sha":
            return subprocess.CompletedProcess(argv, 0, "c" * 40 + "\n", "")
        if argv[-1].endswith("/comments?per_page=100"):
            return subprocess.CompletedProcess(argv, 0, "[]\n", "")
        if argv[-1].endswith("/issues/805"):
            live = _live_issue()
            live["created_at"] = "2026-01-01T00:00:00Z"
            live["updated_at"] = "2026-01-01T00:00:00Z"
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(live) + "\n",
                "",
            )
        raise AssertionError(argv)

    assert (
        issue_close_sweep.main(
            [
                "validate",
                "--repository",
                "wordingone/ember",
                "--packet",
                str(packet_path),
                "--authorization",
                str(authorization_path),
                "--expected-master-sha",
                "c" * 40,
                "--output",
                str(output_path),
            ],
            run_gh=run_gh,
        )
        == 0
    )
    plan = json.loads(output_path.read_text(encoding="utf-8"))
    assert plan["operations"][0]["issue_number"] == 805
    assert plan["plan_sha256"] == canonical_sha256(
        {key: value for key, value in plan.items() if key != "plan_sha256"}
    )
    assert any(argv[-1].endswith("/issues/805") for argv in calls)
    assert len(plan["chunk_issue_numbers"]) == 20
    assert plan["chunk_issue_numbers"][0] == 805
    assert len(plan["skipped"]) == 19
    assert all(row["reason"] for row in plan["skipped"])


def test_build_plan_resumes_after_receipt_comment_without_duplicate() -> None:
    packet = _packet()
    authorization = _authorization(packet)
    first_plan = build_close_plan(
        packet,
        authorization,
        expected_master_sha="c" * 40,
        live_issues={805: (_live_issue(), [])},
    )
    calls: list[tuple[str, int, str | None]] = []
    apply_close_plan(
        first_plan,
        mutate=lambda action, number, body=None: calls.append((action, number, body)),
    )
    prior_comment = {
        "id": 9001,
        "html_url": "https://github.com/wordingone/ember/issues/805#issuecomment-9001",
        "body": calls[0][2],
        "user": {"login": "github-actions[bot]"},
        "created_at": "2026-07-30T03:00:00Z",
        "updated_at": "2026-07-30T03:00:00Z",
    }
    live = _live_issue()
    live["comments"] = 1
    live["updated_at"] = "2026-07-30T03:00:00Z"
    retry_plan = build_close_plan(
        packet,
        authorization,
        expected_master_sha="c" * 40,
        live_issues={805: (live, [prior_comment])},
    )
    assert retry_plan["operations"][0]["comment_needed"] is False
    assert retry_plan["operations"][0]["close_needed"] is True
    retry_calls: list[tuple[str, int, str | None]] = []
    receipt = apply_close_plan(
        retry_plan,
        mutate=lambda action, number, body=None: retry_calls.append(
            (action, number, body)
        ),
    )
    assert [row[0] for row in retry_calls] == ["close"]
    assert receipt["mutation_count"] == 1


def test_build_plan_recognizes_already_closed_authorized_issue() -> None:
    packet = _packet()
    authorization = _authorization(packet)
    first_plan = build_close_plan(
        packet,
        authorization,
        expected_master_sha="c" * 40,
        live_issues={805: (_live_issue(), [])},
    )
    calls: list[tuple[str, int, str | None]] = []
    apply_close_plan(
        first_plan,
        mutate=lambda action, number, body=None: calls.append((action, number, body)),
    )
    prior_comment = {
        "id": 9001,
        "html_url": "https://github.com/wordingone/ember/issues/805#issuecomment-9001",
        "body": calls[0][2],
        "user": {"login": "github-actions[bot]"},
        "created_at": "2026-07-30T03:00:00Z",
        "updated_at": "2026-07-30T03:00:00Z",
    }
    live = _live_issue()
    live["state"] = "closed"
    live["comments"] = 1
    live["updated_at"] = "2026-07-30T03:00:00Z"
    retry_plan = build_close_plan(
        packet,
        authorization,
        expected_master_sha="c" * 40,
        live_issues={805: (live, [prior_comment])},
    )
    assert retry_plan["operations"][0]["comment_needed"] is False
    assert retry_plan["operations"][0]["close_needed"] is False
    retry_calls: list[tuple[str, int, str | None]] = []
    receipt = apply_close_plan(
        retry_plan,
        mutate=lambda action, number, body=None: retry_calls.append(
            (action, number, body)
        ),
    )
    assert retry_calls == []
    assert receipt["mutation_count"] == 0
    assert receipt["already_closed_issue_numbers"] == [805]


def test_authorization_schema_rejects_unknown_fields() -> None:
    packet = _packet()
    authorization = _authorization(packet)
    authorization["unexpected"] = "unsafe"
    authorization["authorization_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in authorization.items()
            if key != "authorization_sha256"
        }
    )
    with pytest.raises(CloseSweepError, match="authorization schema"):
        build_close_plan(
            packet,
            authorization,
            expected_master_sha="c" * 40,
            live_issues={805: (_live_issue(), [])},
        )


def test_cli_rejects_packet_that_fails_canonical_packet_validation(
    tmp_path: Path,
) -> None:
    capture_root = tmp_path / "capture"
    capture_root.mkdir()
    packet = _canonical_packet(capture_root)
    packet["unexpected"] = "unsafe"
    packet["packet_sha256"] = canonical_sha256(
        {key: value for key, value in packet.items() if key != "packet_sha256"}
    )
    authorization = _authorization(packet)
    packet_path = tmp_path / "packet.json"
    authorization_path = tmp_path / "authorization.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")

    def run_gh(argv: list[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError("invalid packet must be rejected before GitHub access")

    with pytest.raises(CloseSweepError, match="canonical packet"):
        issue_close_sweep.main(
            [
                "validate",
                "--repository",
                "wordingone/ember",
                "--packet",
                str(packet_path),
                "--authorization",
                str(authorization_path),
                "--expected-master-sha",
                "c" * 40,
                "--output",
                str(tmp_path / "plan.json"),
            ],
            run_gh=run_gh,
        )


def test_build_plan_rejects_review_not_bound_to_landing_evidence() -> None:
    packet = _packet()
    receipt = packet["receipts"][0]
    receipt["authority_review"]["reviewed_commit_sha"] = "f" * 40
    receipt["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    packet["packet_sha256"] = canonical_sha256(
        {key: value for key, value in packet.items() if key != "packet_sha256"}
    )
    authorization = _authorization(packet)
    with pytest.raises(CloseSweepError, match="reviewed commit"):
        build_close_plan(
            packet,
            authorization,
            expected_master_sha="c" * 40,
            live_issues={805: (_live_issue(), [])},
        )


def test_build_plan_rejects_spoofed_retry_marker_comment() -> None:
    packet = _packet()
    authorization = _authorization(packet)
    first_plan = build_close_plan(
        packet,
        authorization,
        expected_master_sha="c" * 40,
        live_issues={805: (_live_issue(), [])},
    )
    calls: list[tuple[str, int, str | None]] = []
    apply_close_plan(
        first_plan,
        mutate=lambda action, number, body=None: calls.append((action, number, body)),
    )
    spoofed_comment = {
        "id": 9001,
        "html_url": "https://github.com/wordingone/ember/issues/805#issuecomment-9001",
        "body": calls[0][2],
        "user": {"login": "untrusted-user"},
        "created_at": "2026-07-30T03:00:00Z",
        "updated_at": "2026-07-30T03:00:00Z",
    }
    live = _live_issue()
    live["comments"] = 1
    live["updated_at"] = "2026-07-30T03:00:00Z"
    with pytest.raises(CloseSweepError, match="live source"):
        build_close_plan(
            packet,
            authorization,
            expected_master_sha="c" * 40,
            live_issues={805: (live, [spoofed_comment])},
        )


def test_build_plan_rejects_live_issue_that_is_a_parent_tracker() -> None:
    packet = _packet()
    authorization = _authorization(packet)
    live = _live_issue()
    live["sub_issues_summary"] = {
        "total": 2,
        "completed": 1,
        "percent_completed": 50,
    }
    with pytest.raises(CloseSweepError, match="protected"):
        build_close_plan(
            packet,
            authorization,
            expected_master_sha="c" * 40,
            live_issues={805: (live, [])},
        )


def test_cli_independently_rejects_unproven_packet_ancestry(tmp_path: Path) -> None:
    capture_root = tmp_path / "capture"
    capture_root.mkdir()
    packet = _canonical_packet(capture_root)
    authorization = _authorization(packet)
    packet_path = tmp_path / "packet.json"
    authorization_path = tmp_path / "authorization.json"
    output_path = tmp_path / "plan.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")

    def run_gh(argv: list[str]) -> subprocess.CompletedProcess[str]:
        assert argv[-1] == ".sha"
        return subprocess.CompletedProcess(argv, 0, "f" * 40 + "\n", "")

    def run_git(argv: list[str]) -> subprocess.CompletedProcess[str]:
        assert argv == ["merge-base", "--is-ancestor", "c" * 40, "f" * 40]
        return subprocess.CompletedProcess(argv, 1, "", "")

    with pytest.raises(CloseSweepError, match="ancestor"):
        issue_close_sweep.main(
            [
                "validate",
                "--repository",
                "wordingone/ember",
                "--packet",
                str(packet_path),
                "--authorization",
                str(authorization_path),
                "--expected-master-sha",
                "f" * 40,
                "--packet-master-is-ancestor",
                "--output",
                str(output_path),
            ],
            run_gh=run_gh,
            run_git=run_git,
        )
