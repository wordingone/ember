# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for the bounded oldest-open-issue disposition packet."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
sys.path.insert(0, str(ROOT))

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
PacketError = getattr(_ember_366a9bf8189d4fa2_module, 'PacketError')
build_capture = getattr(_ember_366a9bf8189d4fa2_module, 'build_capture')
build_packet = getattr(_ember_366a9bf8189d4fa2_module, 'build_packet')
canonical_sha256 = getattr(_ember_366a9bf8189d4fa2_module, 'canonical_sha256')
validate_capture = getattr(_ember_366a9bf8189d4fa2_module, 'validate_capture')
validate_packet = getattr(_ember_366a9bf8189d4fa2_module, 'validate_packet')
# issue2015 exact-local-import-end:src/ember/governance/scripts/oldest_issue_disposition.py

MASTER = "a" * 40


def _issue(number: int, *, created: str | None = None, comments: int = 1) -> dict:
    created_at = created or f"2026-01-{number:02d}T00:00:00Z"
    return {
        "number": number,
        "title": f"Issue {number}",
        "body": f"Acceptance obligation {number}",
        "html_url": f"https://github.com/wordingone/ember/issues/{number}",
        "created_at": created_at,
        "updated_at": created_at,
        "comments": comments,
        "labels": [{"name": "ember"}],
        "user": {"login": "operator"},
        "state": "open",
    }


def _comment(issue_number: int, comment_id: int = 1) -> dict:
    return {
        "id": issue_number * 100 + comment_id,
        "issue_url": f"https://api.github.com/repos/wordingone/ember/issues/{issue_number}",
        "html_url": (
            f"https://github.com/wordingone/ember/issues/{issue_number}"
            f"#issuecomment-{issue_number * 100 + comment_id}"
        ),
        "body": f"Amendment {issue_number}.{comment_id}",
        "created_at": "2026-02-01T00:00:00Z",
        "updated_at": "2026-02-01T00:00:00Z",
        "user": {"login": "operator"},
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _raw_capture(
    root: Path,
    *,
    issue_count: int = 21,
    include_all_comments: bool = False,
) -> None:
    issues = [_issue(number) for number in range(1, issue_count + 1)]
    pull = _issue(999, created="2025-01-01T00:00:00Z", comments=0)
    pull["pull_request"] = {"url": "https://api.github.com/pulls/999"}
    pages = [issues[:10] + [pull], issues[10:]]
    _write_json(root / "issues_pre.json", pages)
    _write_json(root / "issues_post.json", copy.deepcopy(pages))
    comment_issues = issues if include_all_comments else issues[:20]
    for issue in comment_issues:
        comment_pages = [[_comment(issue["number"])]]
        _write_json(root / f"comments-{issue['number']}-pre.json", comment_pages)
        _write_json(
            root / f"comments-{issue['number']}-post.json",
            copy.deepcopy(comment_pages),
        )


def _decisions(capture: dict) -> dict:
    rows = []
    for issue in capture["issues"]:
        sources = [
            {
                "source_kind": "issue_body",
                "citation": issue["url"],
                "source_sha256": issue["body_sha256"],
                "status": "UNBOUND",
            },
            *[
                {
                    "source_kind": "issue_comment",
                    "citation": comment["url"],
                    "source_sha256": comment["body_sha256"],
                    "status": "UNBOUND",
                }
                for comment in issue["comments"]
            ],
        ]
        rows.append(
            {
                "issue_number": issue["number"],
                "disposition": "PARTIAL",
                "source_clause_inventory": sources,
                "unbound_clause": {
                    "citation": issue["url"],
                    "source_sha256": issue["body_sha256"],
                    "description": (
                        f"acceptance obligation {issue['number']} remains unproved"
                    ),
                },
                "smallest_binding_action": (
                    f"produce a current-master receipt for issue {issue['number']}"
                ),
                "replacement_citation": None,
                "retained_lesson": None,
                "close_evidence": [],
                "authority_review": None,
            }
        )
    return {
        "authority": dict(_AUTHORITY),
        "schema_version": "ember-oldest-issue-decisions-v1",
        "master_sha": capture["master_sha"],
        "selection_sha256": capture["selection_sha256"],
        "rows": rows,
    }


class OldestIssueDispositionTests(unittest.TestCase):
    def test_capture_selects_exactly_twenty_oldest_open_issues(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _raw_capture(root)
            capture = build_capture(
                root,
                master_sha=MASTER,
                captured_at="2026-07-25T00:00:00Z",
            )

        self.assertEqual(
            [row["number"] for row in capture["issues"]],
            list(range(1, 21)),
        )
        self.assertEqual(capture["open_issue_population"], 21)
        self.assertEqual(capture["excluded_pull_request_population"], 1)
        self.assertEqual(capture["pagination"]["issues_pre"]["page_count"], 2)
        self.assertEqual(
            capture["selection_sha256"],
            canonical_sha256(
                [[row["number"], row["created_at"]] for row in capture["issues"]]
            ),
        )
        validate_capture(capture, expected_master=MASTER)

    def test_capture_advances_after_content_bound_cursor_and_allows_final_batch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _raw_capture(root, include_all_comments=True)
            capture = build_capture(
                root,
                master_sha=MASTER,
                captured_at="2026-07-25T00:00:00Z",
                after_created_at="2026-01-10T00:00:00Z",
                after_issue_number=10,
            )

        self.assertEqual(
            [row["number"] for row in capture["issues"]],
            list(range(11, 22)),
        )
        self.assertEqual(
            capture["cursor"],
            {
                "after_created_at": "2026-01-10T00:00:00Z",
                "after_issue_number": 10,
            },
        )
        validate_capture(capture, expected_master=MASTER)

    def test_capture_rejects_partial_or_exhausted_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _raw_capture(root)
            with self.assertRaisesRegex(PacketError, "cursor"):
                build_capture(
                    root,
                    master_sha=MASTER,
                    captured_at="2026-07-25T00:00:00Z",
                    after_created_at="2026-01-10T00:00:00Z",
                )
            with self.assertRaisesRegex(PacketError, "after cursor"):
                build_capture(
                    root,
                    master_sha=MASTER,
                    captured_at="2026-07-25T00:00:00Z",
                    after_created_at="2027-01-01T00:00:00Z",
                    after_issue_number=999,
                )

    def test_capture_rejects_full_final_page_as_incomplete_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            issues = [_issue(number) for number in range(1, 101)]
            _write_json(root / "issues_pre.json", [issues])
            _write_json(root / "issues_post.json", copy.deepcopy([issues]))
            with self.assertRaisesRegex(PacketError, "pagination completeness"):
                build_capture(
                    root,
                    master_sha=MASTER,
                    captured_at="2026-07-25T00:00:00Z",
                )

    def test_capture_rejects_issue_or_comment_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _raw_capture(root)
            post = json.loads((root / "issues_post.json").read_text(encoding="utf-8"))
            post[0][0]["updated_at"] = "2026-07-25T00:00:01Z"
            _write_json(root / "issues_post.json", post)
            with self.assertRaisesRegex(PacketError, "issue population drift"):
                build_capture(
                    root,
                    master_sha=MASTER,
                    captured_at="2026-07-25T00:00:00Z",
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _raw_capture(root)
            comments = json.loads(
                (root / "comments-1-post.json").read_text(encoding="utf-8")
            )
            comments[0][0]["updated_at"] = "2026-07-25T00:00:01Z"
            _write_json(root / "comments-1-post.json", comments)
            with self.assertRaisesRegex(PacketError, "comment population drift"):
                build_capture(
                    root,
                    master_sha=MASTER,
                    captured_at="2026-07-25T00:00:00Z",
                )

    def test_capture_preserves_stable_comment_count_contradiction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _raw_capture(root)
            for name in ("issues_pre.json", "issues_post.json"):
                pages = json.loads((root / name).read_text(encoding="utf-8"))
                pages[0][0]["comments"] = 2
                _write_json(root / name, pages)

            capture = build_capture(
                root,
                master_sha=MASTER,
                captured_at="2026-07-25T00:00:00Z",
            )

        issue = capture["issues"][0]
        self.assertEqual(issue["comment_count"], 2)
        self.assertEqual(len(issue["comments"]), 1)
        self.assertEqual(
            issue["comment_count_contradiction"],
            {
                "code": "REST_METADATA_COMMENT_COUNT_MISMATCH",
                "metadata_count": 2,
                "endpoint_count": 1,
            },
        )
        validate_capture(capture, expected_master=MASTER)

        missing = copy.deepcopy(capture)
        del missing["issues"][0]["comment_count_contradiction"]
        missing["capture_sha256"] = canonical_sha256(
            {key: value for key, value in missing.items() if key != "capture_sha256"}
        )
        with self.assertRaisesRegex(PacketError, "comment_count"):
            validate_capture(missing, expected_master=MASTER)

    def test_packet_requires_complete_source_clause_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _raw_capture(root)
            capture = build_capture(
                root,
                master_sha=MASTER,
                captured_at="2026-07-25T00:00:00Z",
            )
        decisions = _decisions(capture)
        packet = build_packet(capture, decisions)
        validate_packet(packet, expected_master=MASTER)
        self.assertEqual(len(packet["receipts"]), 20)
        self.assertEqual(
            packet["deletion_or_issue_mutation_authority"],
            "NOT_GRANTED",
        )
        self.assertFalse(packet["public_issue_mutation_performed"])

        omitted = copy.deepcopy(decisions)
        omitted["rows"][0]["source_clause_inventory"].pop()
        with self.assertRaisesRegex(PacketError, "source clause coverage"):
            build_packet(capture, omitted)

        duplicate = copy.deepcopy(decisions)
        duplicate["rows"][0]["source_clause_inventory"].append(
            copy.deepcopy(duplicate["rows"][0]["source_clause_inventory"][0])
        )
        with self.assertRaisesRegex(PacketError, "source clause coverage"):
            build_packet(capture, duplicate)

    def test_close_requires_authority_review_and_clean_production_evidence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _raw_capture(root)
            capture = build_capture(
                root,
                master_sha=MASTER,
                captured_at="2026-07-25T00:00:00Z",
            )
        decisions = _decisions(capture)
        row = decisions["rows"][0]
        row["disposition"] = "CLOSE"
        row["unbound_clause"] = None
        for source in row["source_clause_inventory"]:
            source["status"] = "BOUND"
        row["close_evidence"] = [
            {
                "citation": "https://github.com/wordingone/ember/pull/1",
                "commit_sha": "b" * 40,
                "path": "tests/test_production.py",
                "blob_sha1": "c" * 40,
                "test_command": ("python -B -m pytest -q tests/test_production.py"),
                "production_shaped": True,
                "clean_checkout": True,
                "passed": True,
            }
        ]
        with self.assertRaisesRegex(PacketError, "authority review"):
            build_packet(capture, decisions)
        row["authority_review"] = {
            "reviewer": "delegated-authority",
            "review_provenance": "INDEPENDENT_DELEGATED",
            "verdict": "PASS",
            "citation": "mailbox:999",
            "reviewed_commit_sha": "b" * 40,
        }
        packet = build_packet(capture, decisions)
        validate_packet(packet, expected_master=MASTER)

        solo_decisions = copy.deepcopy(decisions)
        solo_decisions["rows"][0]["authority_review"] = {
            "reviewer": "self-review-authority",
            "review_provenance": "SELF_ONLY",
            "verdict": "PASS",
            "citation": "https://github.com/wordingone/ember/pull/1200",
            "reviewed_commit_sha": "b" * 40,
        }
        solo_packet = build_packet(capture, solo_decisions)
        validate_packet(solo_packet, expected_master=MASTER)

        tampered = copy.deepcopy(packet)
        tampered["receipts"][0]["close_evidence"][0]["clean_checkout"] = False
        with self.assertRaises(PacketError):
            validate_packet(tampered, expected_master=MASTER)

    def test_packet_rejects_stale_master_hash_and_authority_escalation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _raw_capture(root)
            capture = build_capture(
                root,
                master_sha=MASTER,
                captured_at="2026-07-25T00:00:00Z",
            )
        packet = build_packet(capture, _decisions(capture))

        stale = copy.deepcopy(packet)
        stale["master_sha"] = "d" * 40
        with self.assertRaises(PacketError):
            validate_packet(stale, expected_master=MASTER)

        bad_hash = copy.deepcopy(packet)
        bad_hash["receipts"][0]["receipt_sha256"] = "0" * 64
        with self.assertRaisesRegex(PacketError, "receipt hash"):
            validate_packet(bad_hash, expected_master=MASTER)

        escalated = copy.deepcopy(packet)
        escalated["deletion_or_issue_mutation_authority"] = "GRANTED"
        with self.assertRaisesRegex(PacketError, "authority"):
            validate_packet(escalated, expected_master=MASTER)

    def test_capture_rejects_invalid_utf8_and_malformed_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _raw_capture(root)
            (root / "issues_pre.json").write_bytes(b"\xff")
            with self.assertRaisesRegex(
                PacketError,
                "cannot read issues_pre.json",
            ):
                build_capture(
                    root,
                    master_sha=MASTER,
                    captured_at="2026-07-25T00:00:00Z",
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _raw_capture(root)
            pages = json.loads((root / "issues_pre.json").read_text(encoding="utf-8"))
            pages[0][0].pop("created_at")
            _write_json(root / "issues_pre.json", pages)
            with self.assertRaises(PacketError):
                build_capture(
                    root,
                    master_sha=MASTER,
                    captured_at="2026-07-25T00:00:00Z",
                )
