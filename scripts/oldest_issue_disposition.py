#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build and verify a non-authorizing oldest-open-issue disposition packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class PacketError(RuntimeError):
    """An evidence, schema, or authority violation."""


_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
_AUTHORITY = {
    "goal_id": "EMBER-02",
    "workstream_id": "EMBER-02A",
    "next_executed_outcome": (
        "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
    ),
}
_DISPOSITIONS = {"CLOSE", "PARTIAL", "SUPERSEDED", "NEGATIVE-KEEP"}
_SOURCE_STATUSES = {"BOUND", "UNBOUND", "SUPERSEDED", "NEGATIVE"}
_CAPTURE_KEYS = {
    "authority",
    "schema_version",
    "repository",
    "master_sha",
    "captured_at",
    "pagination",
    "source_evidence",
    "open_issue_population",
    "excluded_pull_request_population",
    "issues",
    "selection_sha256",
    "capture_sha256",
}
_ISSUE_KEYS = {
    "number",
    "title",
    "body_sha256",
    "url",
    "created_at",
    "updated_at",
    "labels",
    "author",
    "state",
    "comment_count",
    "comments",
    "source_stability",
}
_COMMENT_KEYS = {
    "id",
    "url",
    "body_sha256",
    "author",
    "created_at",
    "updated_at",
}
_DECISION_KEYS = {
    "issue_number",
    "disposition",
    "source_clause_inventory",
    "unbound_clause",
    "smallest_binding_action",
    "replacement_citation",
    "retained_lesson",
    "close_evidence",
    "authority_review",
}
_RECEIPT_KEYS = _DECISION_KEYS | {
    "issue_url",
    "capture_issue_sha256",
    "receipt_sha256",
}
_PACKET_KEYS = {
    "authority",
    "schema_version",
    "repository",
    "master_sha",
    "capture",
    "capture_sha256",
    "selection_sha256",
    "receipts",
    "disposition_counts",
    "deletion_or_issue_mutation_authority",
    "public_issue_mutation_performed",
    "packet_sha256",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_keys(
    value: Mapping[str, Any],
    expected: set[str],
    *,
    field: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise PacketError(
            f"{field} has invalid keys; "
            f"missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PacketError(f"{field} must be an object")
    return value


def _list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise PacketError(f"{field} must be a list")
    return value


def _text(value: Any, *, field: str, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise PacketError(f"{field} must be a nonempty string")
    return value


def _integer(value: Any, *, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PacketError(f"{field} must be an integer >= {minimum}")
    return value


def _sha1(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _SHA1.fullmatch(value) is None:
        raise PacketError(f"{field} must be a lowercase 40-character SHA-1")
    return value


def _sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PacketError(f"{field} must be a lowercase 64-character SHA-256")
    return value


def _timestamp(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _TIMESTAMP.fullmatch(value) is None:
        raise PacketError(f"{field} must be an RFC3339 UTC timestamp")
    return value


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PacketError(f"cannot read {path.name}: {exc}") from exc


def _flatten_pages(
    value: Any,
    *,
    field: str,
    page_size: int = 100,
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    pages = _list(value, field=field)
    if not pages:
        raise PacketError(f"{field} pagination completeness is unproven")
    rows: list[Mapping[str, Any]] = []
    page_lengths: list[int] = []
    for page_index, raw_page in enumerate(pages):
        page = _list(raw_page, field=f"{field}[{page_index}]")
        if len(page) > page_size:
            raise PacketError(f"{field}[{page_index}] exceeds page size")
        page_lengths.append(len(page))
        for row_index, raw_row in enumerate(page):
            rows.append(
                _mapping(
                    raw_row,
                    field=f"{field}[{page_index}][{row_index}]",
                )
            )
    if page_lengths[-1] >= page_size:
        raise PacketError(f"{field} pagination completeness is unproven")
    return rows, {
        "complete": True,
        "page_size": page_size,
        "page_count": len(pages),
        "page_lengths": page_lengths,
        "row_count": len(rows),
        "terminal_page_short": True,
    }


def _required_api_fields(
    row: Mapping[str, Any],
    fields: Sequence[str],
    *,
    field: str,
) -> None:
    missing = [name for name in fields if name not in row]
    if missing:
        raise PacketError(f"{field} is missing required API fields: {missing}")


def _population_issue(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    _required_api_fields(
        row,
        (
            "number",
            "title",
            "body",
            "html_url",
            "created_at",
            "updated_at",
            "comments",
            "labels",
            "user",
            "state",
        ),
        field=field,
    )
    number = _integer(row["number"], field=f"{field}.number", minimum=1)
    title = _text(row["title"], field=f"{field}.title")
    body = row["body"]
    if body is None:
        body = ""
    if not isinstance(body, str):
        raise PacketError(f"{field}.body must be a string or null")
    url = _text(row["html_url"], field=f"{field}.html_url")
    created_at = _timestamp(row["created_at"], field=f"{field}.created_at")
    updated_at = _timestamp(row["updated_at"], field=f"{field}.updated_at")
    comment_count = _integer(
        row["comments"],
        field=f"{field}.comments",
    )
    labels_raw = _list(row["labels"], field=f"{field}.labels")
    labels: list[str] = []
    for index, label_raw in enumerate(labels_raw):
        label = _mapping(label_raw, field=f"{field}.labels[{index}]")
        labels.append(_text(label.get("name"), field=f"{field}.labels[{index}].name"))
    if len(labels) != len(set(labels)):
        raise PacketError(f"{field}.labels contains duplicates")
    user = _mapping(row["user"], field=f"{field}.user")
    author = _text(user.get("login"), field=f"{field}.user.login")
    state = _text(row["state"], field=f"{field}.state")
    if state != "open":
        raise PacketError(f"{field}.state must be open")
    is_pull_request = "pull_request" in row
    return {
        "number": number,
        "title": title,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "url": url,
        "created_at": created_at,
        "updated_at": updated_at,
        "comment_count": comment_count,
        "labels": sorted(labels),
        "author": author,
        "state": state,
        "is_pull_request": is_pull_request,
    }


def _population_projection(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized = [
        _population_issue(row, field=f"issues[{index}]")
        for index, row in enumerate(rows)
    ]
    numbers = [row["number"] for row in normalized]
    if len(numbers) != len(set(numbers)):
        raise PacketError("issue population contains duplicate numbers")
    return sorted(normalized, key=lambda row: row["number"])


def _comment(
    row: Mapping[str, Any],
    *,
    issue_number: int,
    field: str,
) -> dict[str, Any]:
    _required_api_fields(
        row,
        (
            "id",
            "issue_url",
            "html_url",
            "body",
            "created_at",
            "updated_at",
            "user",
        ),
        field=field,
    )
    identifier = _integer(row["id"], field=f"{field}.id", minimum=1)
    issue_url = _text(row["issue_url"], field=f"{field}.issue_url")
    if not issue_url.endswith(f"/issues/{issue_number}"):
        raise PacketError(f"{field}.issue_url does not bind issue")
    body = row["body"]
    if body is None:
        body = ""
    if not isinstance(body, str):
        raise PacketError(f"{field}.body must be a string or null")
    user = _mapping(row["user"], field=f"{field}.user")
    return {
        "id": identifier,
        "url": _text(row["html_url"], field=f"{field}.html_url"),
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "author": _text(user.get("login"), field=f"{field}.user.login"),
        "created_at": _timestamp(
            row["created_at"],
            field=f"{field}.created_at",
        ),
        "updated_at": _timestamp(
            row["updated_at"],
            field=f"{field}.updated_at",
        ),
    }


def _comment_projection(
    rows: Sequence[Mapping[str, Any]],
    *,
    issue_number: int,
) -> list[dict[str, Any]]:
    normalized = [
        _comment(
            row,
            issue_number=issue_number,
            field=f"comments[{issue_number}][{index}]",
        )
        for index, row in enumerate(rows)
    ]
    identifiers = [row["id"] for row in normalized]
    if len(identifiers) != len(set(identifiers)):
        raise PacketError(f"comments[{issue_number}] contains duplicate IDs")
    return sorted(normalized, key=lambda row: (row["created_at"], row["id"]))


def _capture_projection(capture: Mapping[str, Any]) -> dict[str, Any]:
    return {key: capture[key] for key in sorted(_CAPTURE_KEYS - {"capture_sha256"})}


def build_capture(
    raw_root: Path,
    *,
    master_sha: str,
    captured_at: str,
) -> dict[str, Any]:
    master = _sha1(master_sha, field="master_sha")
    captured = _timestamp(captured_at, field="captured_at")
    pre_path = raw_root / "issues_pre.json"
    post_path = raw_root / "issues_post.json"
    pre_rows, pre_page = _flatten_pages(
        _read_json(pre_path),
        field="issues_pre",
    )
    post_rows, post_page = _flatten_pages(
        _read_json(post_path),
        field="issues_post",
    )
    pre = _population_projection(pre_rows)
    post = _population_projection(post_rows)
    if pre != post:
        raise PacketError("issue population drift between pre and post capture")

    open_issues = [row for row in pre if not row["is_pull_request"]]
    pulls = [row for row in pre if row["is_pull_request"]]
    selected = sorted(
        open_issues,
        key=lambda row: (row["created_at"], row["number"]),
    )[:20]
    if len(selected) != 20:
        raise PacketError("capture must select exactly twenty open issues")

    pagination: dict[str, Any] = {
        "issues_pre": pre_page,
        "issues_post": post_page,
        "comments": [],
    }
    source_evidence = {
        "issues_pre.json": _file_sha256(pre_path),
        "issues_post.json": _file_sha256(post_path),
    }
    issues: list[dict[str, Any]] = []
    for population_row in selected:
        number = population_row["number"]
        comments_pre_path = raw_root / f"comments-{number}-pre.json"
        comments_post_path = raw_root / f"comments-{number}-post.json"
        comments_pre_raw, comments_pre_page = _flatten_pages(
            _read_json(comments_pre_path),
            field=f"comments-{number}-pre",
        )
        comments_post_raw, comments_post_page = _flatten_pages(
            _read_json(comments_post_path),
            field=f"comments-{number}-post",
        )
        comments_pre = _comment_projection(
            comments_pre_raw,
            issue_number=number,
        )
        comments_post = _comment_projection(
            comments_post_raw,
            issue_number=number,
        )
        if comments_pre != comments_post:
            raise PacketError(f"comment population drift for issue {number}")
        if len(comments_pre) != population_row["comment_count"]:
            raise PacketError(
                f"comment count mismatch for issue {number}: "
                f"API={population_row['comment_count']} "
                f"captured={len(comments_pre)}"
            )
        source_evidence[comments_pre_path.name] = _file_sha256(comments_pre_path)
        source_evidence[comments_post_path.name] = _file_sha256(comments_post_path)
        pagination["comments"].append(
            {
                "issue_number": number,
                "pre": comments_pre_page,
                "post": comments_post_page,
            }
        )
        issue = {
            key: value
            for key, value in population_row.items()
            if key != "is_pull_request"
        }
        issue["comments"] = comments_pre
        issue["source_stability"] = {
            "pre_sha256": canonical_sha256(population_row),
            "post_sha256": canonical_sha256(population_row),
            "comments_pre_sha256": canonical_sha256(comments_pre),
            "comments_post_sha256": canonical_sha256(comments_post),
        }
        issues.append(issue)

    capture: dict[str, Any] = {
        "authority": dict(_AUTHORITY),
        "schema_version": "ember-oldest-issue-capture-v1",
        "repository": "wordingone/ember",
        "master_sha": master,
        "captured_at": captured,
        "pagination": pagination,
        "source_evidence": dict(sorted(source_evidence.items())),
        "open_issue_population": len(open_issues),
        "excluded_pull_request_population": len(pulls),
        "issues": issues,
        "selection_sha256": canonical_sha256(
            [[row["number"], row["created_at"]] for row in issues]
        ),
    }
    capture["capture_sha256"] = canonical_sha256(_capture_projection(capture))
    validate_capture(capture, expected_master=master)
    return capture


def _validate_pagination(value: Any) -> None:
    pagination = _mapping(value, field="capture.pagination")
    _strict_keys(
        pagination,
        {"issues_pre", "issues_post", "comments"},
        field="capture.pagination",
    )
    for name in ("issues_pre", "issues_post"):
        row = _mapping(
            pagination[name],
            field=f"capture.pagination.{name}",
        )
        _strict_keys(
            row,
            {
                "complete",
                "page_size",
                "page_count",
                "page_lengths",
                "row_count",
                "terminal_page_short",
            },
            field=f"capture.pagination.{name}",
        )
        if row["complete"] is not True or row["terminal_page_short"] is not True:
            raise PacketError(f"capture.pagination.{name} is incomplete")
        lengths = _list(
            row["page_lengths"],
            field=f"capture.pagination.{name}.page_lengths",
        )
        if not lengths or lengths[-1] >= row["page_size"]:
            raise PacketError(f"capture.pagination.{name} is incomplete")
        if sum(lengths) != row["row_count"] or len(lengths) != row["page_count"]:
            raise PacketError(f"capture.pagination.{name} counts mismatch")
    comments = _list(
        pagination["comments"],
        field="capture.pagination.comments",
    )
    if len(comments) != 20:
        raise PacketError("capture.pagination.comments must have twenty rows")


def _validate_comment(value: Any, *, field: str) -> dict[str, Any]:
    row = dict(_mapping(value, field=field))
    _strict_keys(row, _COMMENT_KEYS, field=field)
    _integer(row["id"], field=f"{field}.id", minimum=1)
    _text(row["url"], field=f"{field}.url")
    _sha256(row["body_sha256"], field=f"{field}.body_sha256")
    _text(row["author"], field=f"{field}.author")
    _timestamp(row["created_at"], field=f"{field}.created_at")
    _timestamp(row["updated_at"], field=f"{field}.updated_at")
    return row


def _validate_capture_issue(value: Any, *, index: int) -> dict[str, Any]:
    field = f"capture.issues[{index}]"
    row = dict(_mapping(value, field=field))
    _strict_keys(row, _ISSUE_KEYS, field=field)
    _integer(row["number"], field=f"{field}.number", minimum=1)
    _text(row["title"], field=f"{field}.title")
    _sha256(row["body_sha256"], field=f"{field}.body_sha256")
    _text(row["url"], field=f"{field}.url")
    _timestamp(row["created_at"], field=f"{field}.created_at")
    _timestamp(row["updated_at"], field=f"{field}.updated_at")
    labels = _list(row["labels"], field=f"{field}.labels")
    if any(not isinstance(item, str) or not item for item in labels):
        raise PacketError(f"{field}.labels is invalid")
    if labels != sorted(set(labels)):
        raise PacketError(f"{field}.labels must be sorted and unique")
    _text(row["author"], field=f"{field}.author")
    if row["state"] != "open":
        raise PacketError(f"{field}.state must be open")
    count = _integer(
        row["comment_count"],
        field=f"{field}.comment_count",
    )
    comments = [
        _validate_comment(item, field=f"{field}.comments[{comment_index}]")
        for comment_index, item in enumerate(
            _list(row["comments"], field=f"{field}.comments")
        )
    ]
    if len(comments) != count:
        raise PacketError(f"{field}.comment_count mismatch")
    identifiers = [comment["id"] for comment in comments]
    if len(identifiers) != len(set(identifiers)):
        raise PacketError(f"{field}.comments contains duplicate IDs")
    stability = _mapping(
        row["source_stability"],
        field=f"{field}.source_stability",
    )
    _strict_keys(
        stability,
        {
            "pre_sha256",
            "post_sha256",
            "comments_pre_sha256",
            "comments_post_sha256",
        },
        field=f"{field}.source_stability",
    )
    for name, digest in stability.items():
        _sha256(digest, field=f"{field}.source_stability.{name}")
    if stability["pre_sha256"] != stability["post_sha256"]:
        raise PacketError(f"{field} issue source drift")
    if stability["comments_pre_sha256"] != stability["comments_post_sha256"]:
        raise PacketError(f"{field} comment source drift")
    if stability["comments_pre_sha256"] != canonical_sha256(comments):
        raise PacketError(f"{field} comment digest mismatch")
    return row


def validate_capture(
    value: Mapping[str, Any],
    *,
    expected_master: str | None = None,
) -> dict[str, Any]:
    capture = dict(_mapping(value, field="capture"))
    _strict_keys(capture, _CAPTURE_KEYS, field="capture")
    if capture["authority"] != _AUTHORITY:
        raise PacketError("capture authority binding is invalid")
    if (
        capture["schema_version"] != "ember-oldest-issue-capture-v1"
        or capture["repository"] != "wordingone/ember"
    ):
        raise PacketError("capture identity is invalid")
    master = _sha1(capture["master_sha"], field="capture.master_sha")
    if expected_master is not None and master != _sha1(
        expected_master,
        field="expected_master",
    ):
        raise PacketError("capture is bound to a stale master")
    _timestamp(capture["captured_at"], field="capture.captured_at")
    _validate_pagination(capture["pagination"])
    evidence = _mapping(
        capture["source_evidence"],
        field="capture.source_evidence",
    )
    if not evidence:
        raise PacketError("capture.source_evidence cannot be empty")
    for name, digest in evidence.items():
        _text(name, field="capture.source_evidence key")
        _sha256(digest, field=f"capture.source_evidence.{name}")
    _integer(
        capture["open_issue_population"],
        field="capture.open_issue_population",
        minimum=20,
    )
    _integer(
        capture["excluded_pull_request_population"],
        field="capture.excluded_pull_request_population",
    )
    issues = [
        _validate_capture_issue(item, index=index)
        for index, item in enumerate(_list(capture["issues"], field="capture.issues"))
    ]
    if len(issues) != 20:
        raise PacketError("capture must contain exactly twenty issues")
    order = [(row["created_at"], row["number"]) for row in issues]
    if order != sorted(order) or len({row["number"] for row in issues}) != 20:
        raise PacketError("capture issues are not unique oldest-order rows")
    expected_selection = canonical_sha256(
        [[row["number"], row["created_at"]] for row in issues]
    )
    if capture["selection_sha256"] != expected_selection:
        raise PacketError("capture selection hash mismatch")
    expected_capture = canonical_sha256(_capture_projection(capture))
    if capture["capture_sha256"] != expected_capture:
        raise PacketError("capture hash mismatch")
    return capture


def _source_units(issue: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    return [
        ("issue_body", str(issue["url"]), str(issue["body_sha256"])),
        *[
            (
                "issue_comment",
                str(comment["url"]),
                str(comment["body_sha256"]),
            )
            for comment in issue["comments"]
        ],
    ]


def _validate_source_inventory(
    value: Any,
    *,
    issue: Mapping[str, Any],
    field: str,
) -> list[dict[str, Any]]:
    rows = _list(value, field=field)
    actual: list[tuple[str, str, str]] = []
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        item_field = f"{field}[{index}]"
        row = dict(_mapping(raw, field=item_field))
        _strict_keys(
            row,
            {"source_kind", "citation", "source_sha256", "status"},
            field=item_field,
        )
        if row["source_kind"] not in {"issue_body", "issue_comment"}:
            raise PacketError(f"{item_field}.source_kind is invalid")
        _text(row["citation"], field=f"{item_field}.citation")
        _sha256(row["source_sha256"], field=f"{item_field}.source_sha256")
        if row["status"] not in _SOURCE_STATUSES:
            raise PacketError(f"{item_field}.status is invalid")
        actual.append(
            (
                row["source_kind"],
                row["citation"],
                row["source_sha256"],
            )
        )
        normalized.append(row)
    if Counter(actual) != Counter(_source_units(issue)):
        raise PacketError(f"{field} source clause coverage is incomplete or duplicate")
    return normalized


def _validate_unbound(
    value: Any,
    *,
    source_units: set[tuple[str, str]],
    field: str,
) -> Mapping[str, Any] | None:
    if value is None:
        return None
    row = _mapping(value, field=field)
    _strict_keys(
        row,
        {"citation", "source_sha256", "description"},
        field=field,
    )
    citation = _text(row["citation"], field=f"{field}.citation")
    digest = _sha256(row["source_sha256"], field=f"{field}.source_sha256")
    _text(row["description"], field=f"{field}.description")
    if (citation, digest) not in source_units:
        raise PacketError(f"{field} is not bound to a captured source")
    return row


def _validate_close_evidence(value: Any, *, field: str) -> list[Mapping[str, Any]]:
    rows = _list(value, field=field)
    normalized: list[Mapping[str, Any]] = []
    expected = {
        "citation",
        "commit_sha",
        "path",
        "blob_sha1",
        "test_command",
        "production_shaped",
        "clean_checkout",
        "passed",
    }
    for index, raw in enumerate(rows):
        item_field = f"{field}[{index}]"
        row = _mapping(raw, field=item_field)
        _strict_keys(row, expected, field=item_field)
        _text(row["citation"], field=f"{item_field}.citation")
        _sha1(row["commit_sha"], field=f"{item_field}.commit_sha")
        _text(row["path"], field=f"{item_field}.path")
        _sha1(row["blob_sha1"], field=f"{item_field}.blob_sha1")
        _text(row["test_command"], field=f"{item_field}.test_command")
        for name in ("production_shaped", "clean_checkout", "passed"):
            if row[name] is not True:
                raise PacketError(f"{item_field}.{name} must be true")
        normalized.append(row)
    return normalized


def _validate_authority_review(value: Any, *, field: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    row = _mapping(value, field=field)
    _strict_keys(
        row,
        {
            "reviewer",
            "review_provenance",
            "verdict",
            "citation",
            "reviewed_commit_sha",
        },
        field=field,
    )
    allowed_review = (
        row["reviewer"] == "delegated-authority"
        and row["review_provenance"] == "INDEPENDENT_DELEGATED"
    ) or (
        row["reviewer"] == "self-review-authority"
        and row["review_provenance"] == "SELF_ONLY"
    )
    if not allowed_review or row["verdict"] != "PASS":
        raise PacketError(f"{field} must record an allowed authority review PASS")
    _text(row["citation"], field=f"{field}.citation")
    _sha1(row["reviewed_commit_sha"], field=f"{field}.reviewed_commit_sha")
    return row


def _receipt_projection(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {key: receipt[key] for key in sorted(_RECEIPT_KEYS - {"receipt_sha256"})}


def _validate_receipt(
    value: Any,
    *,
    issue: Mapping[str, Any],
    field: str,
) -> dict[str, Any]:
    receipt = dict(_mapping(value, field=field))
    _strict_keys(receipt, _RECEIPT_KEYS, field=field)
    if receipt["issue_number"] != issue["number"]:
        raise PacketError(f"{field}.issue_number mismatch")
    if receipt["issue_url"] != issue["url"]:
        raise PacketError(f"{field}.issue_url mismatch")
    if receipt["capture_issue_sha256"] != canonical_sha256(issue):
        raise PacketError(f"{field}.capture_issue_sha256 mismatch")
    disposition = receipt["disposition"]
    if disposition not in _DISPOSITIONS:
        raise PacketError(f"{field}.disposition is invalid")
    inventory = _validate_source_inventory(
        receipt["source_clause_inventory"],
        issue=issue,
        field=f"{field}.source_clause_inventory",
    )
    source_units = {(row["citation"], row["source_sha256"]) for row in inventory}
    unbound = _validate_unbound(
        receipt["unbound_clause"],
        source_units=source_units,
        field=f"{field}.unbound_clause",
    )
    action = receipt["smallest_binding_action"]
    replacement = receipt["replacement_citation"]
    retained = receipt["retained_lesson"]
    close_evidence = _validate_close_evidence(
        receipt["close_evidence"],
        field=f"{field}.close_evidence",
    )
    authority_review = _validate_authority_review(
        receipt["authority_review"],
        field=f"{field}.authority_review",
    )
    for name, item in (
        ("smallest_binding_action", action),
        ("replacement_citation", replacement),
        ("retained_lesson", retained),
    ):
        if item is not None:
            _text(item, field=f"{field}.{name}")

    if disposition == "CLOSE":
        if unbound is not None:
            raise PacketError(f"{field} CLOSE cannot have an unbound clause")
        if any(row["status"] != "BOUND" for row in inventory):
            raise PacketError(f"{field} CLOSE requires all sources BOUND")
        if not close_evidence:
            raise PacketError(f"{field} CLOSE requires production evidence")
        if authority_review is None:
            raise PacketError(f"{field} CLOSE requires authority review")
    elif disposition == "PARTIAL":
        if unbound is None or action is None:
            raise PacketError(f"{field} PARTIAL requires an unbound clause and action")
        if close_evidence or authority_review is not None:
            raise PacketError(f"{field} PARTIAL cannot claim close evidence")
    elif disposition == "SUPERSEDED":
        if replacement is None:
            raise PacketError(f"{field} SUPERSEDED requires replacement citation")
        if close_evidence or authority_review is not None:
            raise PacketError(f"{field} SUPERSEDED cannot claim close evidence")
    elif disposition == "NEGATIVE-KEEP":
        if retained is None or action is None:
            raise PacketError(
                f"{field} NEGATIVE-KEEP requires retained lesson and action"
            )
        if close_evidence or authority_review is not None:
            raise PacketError(f"{field} NEGATIVE-KEEP cannot claim close evidence")

    expected_hash = canonical_sha256(_receipt_projection(receipt))
    if receipt["receipt_sha256"] != expected_hash:
        raise PacketError(f"{field} receipt hash mismatch")
    return receipt


def _packet_projection(packet: Mapping[str, Any]) -> dict[str, Any]:
    return {key: packet[key] for key in sorted(_PACKET_KEYS - {"packet_sha256"})}


def build_packet(
    capture_value: Mapping[str, Any],
    decisions_value: Mapping[str, Any],
) -> dict[str, Any]:
    capture = validate_capture(capture_value)
    decisions = _mapping(decisions_value, field="decisions")
    _strict_keys(
        decisions,
        {"authority", "schema_version", "master_sha", "selection_sha256", "rows"},
        field="decisions",
    )
    if decisions["authority"] != _AUTHORITY:
        raise PacketError("decisions authority binding is invalid")
    if decisions["schema_version"] != "ember-oldest-issue-decisions-v1":
        raise PacketError("decisions schema is invalid")
    if decisions["master_sha"] != capture["master_sha"]:
        raise PacketError("decisions are bound to a stale master")
    if decisions["selection_sha256"] != capture["selection_sha256"]:
        raise PacketError("decisions selection mismatch")
    decision_rows = _list(decisions["rows"], field="decisions.rows")
    if len(decision_rows) != 20:
        raise PacketError("decisions must contain exactly twenty rows")
    by_number: dict[int, Mapping[str, Any]] = {}
    for index, raw in enumerate(decision_rows):
        row = _mapping(raw, field=f"decisions.rows[{index}]")
        _strict_keys(row, _DECISION_KEYS, field=f"decisions.rows[{index}]")
        number = _integer(
            row["issue_number"],
            field=f"decisions.rows[{index}].issue_number",
            minimum=1,
        )
        if number in by_number:
            raise PacketError("decisions contain duplicate issue numbers")
        by_number[number] = row
    if set(by_number) != {issue["number"] for issue in capture["issues"]}:
        raise PacketError("decisions omit or add selected issues")

    receipts: list[dict[str, Any]] = []
    for index, issue in enumerate(capture["issues"]):
        decision = dict(by_number[issue["number"]])
        receipt = {
            **decision,
            "issue_url": issue["url"],
            "capture_issue_sha256": canonical_sha256(issue),
        }
        receipt["receipt_sha256"] = canonical_sha256(_receipt_projection(receipt))
        receipts.append(
            _validate_receipt(
                receipt,
                issue=issue,
                field=f"receipts[{index}]",
            )
        )
    counts = Counter(receipt["disposition"] for receipt in receipts)
    packet: dict[str, Any] = {
        "authority": dict(_AUTHORITY),
        "schema_version": "ember-oldest-issue-disposition-packet-v1",
        "repository": "wordingone/ember",
        "master_sha": capture["master_sha"],
        "capture": capture,
        "capture_sha256": capture["capture_sha256"],
        "selection_sha256": capture["selection_sha256"],
        "receipts": receipts,
        "disposition_counts": {
            name: counts.get(name, 0) for name in sorted(_DISPOSITIONS)
        },
        "deletion_or_issue_mutation_authority": "NOT_GRANTED",
        "public_issue_mutation_performed": False,
    }
    packet["packet_sha256"] = canonical_sha256(_packet_projection(packet))
    validate_packet(packet, expected_master=capture["master_sha"])
    return packet


def validate_packet(
    value: Mapping[str, Any],
    *,
    expected_master: str,
) -> dict[str, Any]:
    packet = dict(_mapping(value, field="packet"))
    _strict_keys(packet, _PACKET_KEYS, field="packet")
    if packet["authority"] != _AUTHORITY:
        raise PacketError("packet authority binding is invalid")
    if (
        packet["schema_version"] != "ember-oldest-issue-disposition-packet-v1"
        or packet["repository"] != "wordingone/ember"
    ):
        raise PacketError("packet identity is invalid")
    capture = validate_capture(
        _mapping(packet["capture"], field="packet.capture"),
        expected_master=expected_master,
    )
    if packet["master_sha"] != capture["master_sha"]:
        raise PacketError("packet master mismatch")
    if packet["capture_sha256"] != capture["capture_sha256"]:
        raise PacketError("packet capture hash mismatch")
    if packet["selection_sha256"] != capture["selection_sha256"]:
        raise PacketError("packet selection mismatch")
    receipts_raw = _list(packet["receipts"], field="packet.receipts")
    if len(receipts_raw) != 20:
        raise PacketError("packet must contain exactly twenty receipts")
    receipts = [
        _validate_receipt(
            raw,
            issue=capture["issues"][index],
            field=f"packet.receipts[{index}]",
        )
        for index, raw in enumerate(receipts_raw)
    ]
    numbers = [receipt["issue_number"] for receipt in receipts]
    expected_numbers = [issue["number"] for issue in capture["issues"]]
    if numbers != expected_numbers:
        raise PacketError("packet receipt order or issue binding mismatch")
    expected_counts = Counter(receipt["disposition"] for receipt in receipts)
    if packet["disposition_counts"] != {
        name: expected_counts.get(name, 0) for name in sorted(_DISPOSITIONS)
    }:
        raise PacketError("packet disposition counts mismatch")
    if (
        packet["deletion_or_issue_mutation_authority"] != "NOT_GRANTED"
        or packet["public_issue_mutation_performed"] is not False
    ):
        raise PacketError("packet authority escalation is forbidden")
    expected_hash = canonical_sha256(_packet_projection(packet))
    if packet["packet_sha256"] != expected_hash:
        raise PacketError("packet hash mismatch")
    return packet


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _load_mapping(path: Path, *, field: str) -> Mapping[str, Any]:
    return _mapping(_read_json(path), field=field)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--raw-root", type=Path, required=True)
    capture_parser.add_argument("--master-sha", required=True)
    capture_parser.add_argument("--captured-at", required=True)
    capture_parser.add_argument("--output", type=Path, required=True)

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--capture", type=Path, required=True)
    build_parser.add_argument("--decisions", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--packet", type=Path, required=True)
    verify_parser.add_argument("--expected-master-sha", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            capture = build_capture(
                args.raw_root,
                master_sha=args.master_sha,
                captured_at=args.captured_at,
            )
            _write_json(args.output, capture)
            print(
                json.dumps(
                    {
                        "status": "CAPTURE_VALID",
                        "issue_count": len(capture["issues"]),
                        "capture_sha256": capture["capture_sha256"],
                    },
                    sort_keys=True,
                )
            )
        elif args.command == "build":
            packet = build_packet(
                _load_mapping(args.capture, field="capture"),
                _load_mapping(args.decisions, field="decisions"),
            )
            _write_json(args.output, packet)
            print(
                json.dumps(
                    {
                        "status": "PACKET_VALID_NON_AUTHORIZING",
                        "receipt_count": len(packet["receipts"]),
                        "packet_sha256": packet["packet_sha256"],
                    },
                    sort_keys=True,
                )
            )
        else:
            packet = validate_packet(
                _load_mapping(args.packet, field="packet"),
                expected_master=args.expected_master_sha,
            )
            print(
                json.dumps(
                    {
                        "status": "PACKET_VALID_NON_AUTHORIZING",
                        "receipt_count": len(packet["receipts"]),
                        "packet_sha256": packet["packet_sha256"],
                    },
                    sort_keys=True,
                )
            )
    except PacketError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
