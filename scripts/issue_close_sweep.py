#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Apply an explicitly authorized, receipt-bearing issue close sweep."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.oldest_issue_disposition import PacketError, validate_packet


class CloseSweepError(RuntimeError):
    """The close-sweep evidence or authority boundary is invalid."""


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _without(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != field}


def _verify_content_hash(
    value: Mapping[str, Any],
    field: str,
    *,
    label: str,
) -> None:
    actual = value.get(field)
    if not isinstance(actual, str) or actual != canonical_sha256(
        _without(value, field)
    ):
        raise CloseSweepError(f"{label} content hash is invalid")


def _live_projection(
    issue: Mapping[str, Any],
    comments: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        raise CloseSweepError("live source labels are invalid")
    label_names = []
    for raw in labels:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("name"), str):
            raise CloseSweepError("live source label is invalid")
        label_names.append(raw["name"])
    user = issue.get("user")
    if not isinstance(user, Mapping) or not isinstance(user.get("login"), str):
        raise CloseSweepError("live source author is invalid")
    normalized_comments = []
    for raw in comments:
        comment_user = raw.get("user")
        if (
            not isinstance(comment_user, Mapping)
            or not isinstance(comment_user.get("login"), str)
            or not isinstance(raw.get("body"), str)
        ):
            raise CloseSweepError("live source comment is invalid")
        normalized_comments.append(
            {
                "id": raw["id"],
                "url": raw["html_url"],
                "body_sha256": hashlib.sha256(raw["body"].encode("utf-8")).hexdigest(),
                "author": comment_user["login"],
                "created_at": raw["created_at"],
                "updated_at": raw["updated_at"],
            }
        )
    body = issue.get("body")
    if not isinstance(body, str):
        raise CloseSweepError("live source body is invalid")
    return {
        "number": issue["number"],
        "title": issue["title"],
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "url": issue["html_url"],
        "created_at": issue["created_at"],
        "updated_at": issue["updated_at"],
        "labels": sorted(label_names),
        "author": user["login"],
        "state": issue["state"],
        "comment_count": len(normalized_comments),
        "comments": normalized_comments,
    }


def _captured_projection(issue: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: issue[key]
        for key in (
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
        )
    }


def _is_protected(issue: Mapping[str, Any]) -> bool:
    labels = set(issue["labels"])
    title = issue["title"]
    return bool(
        labels.intersection({"kind:initiative", "kind:constitution", "kind:tracking"})
        or re.match(r"^\[EMBER-\d{2}\]", title)
    )


def _validate_close_receipt(
    receipt: Mapping[str, Any],
    *,
    issue: Mapping[str, Any],
) -> None:
    _verify_content_hash(receipt, "receipt_sha256", label="receipt")
    if receipt.get("issue_number") != issue["number"]:
        raise CloseSweepError("receipt issue binding is invalid")
    if receipt.get("capture_issue_sha256") != canonical_sha256(issue):
        raise CloseSweepError("receipt captured issue binding is invalid")
    if receipt.get("disposition") != "CLOSE":
        raise CloseSweepError("authorized issue does not have CLOSE disposition")
    if receipt.get("unbound_clause") is not None:
        raise CloseSweepError("CLOSE receipt contains an unbound clause")
    inventory = receipt.get("source_clause_inventory")
    if (
        not isinstance(inventory, list)
        or not inventory
        or any(
            not isinstance(row, Mapping) or row.get("status") != "BOUND"
            for row in inventory
        )
    ):
        raise CloseSweepError("CLOSE receipt sources are not fully bound")
    evidence = receipt.get("close_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise CloseSweepError("CLOSE receipt has no production evidence")
    for row in evidence:
        if not isinstance(row, Mapping):
            raise CloseSweepError("CLOSE evidence row is invalid")
        if any(
            row.get(field) is not True
            for field in ("production_shaped", "clean_checkout", "passed")
        ):
            raise CloseSweepError("CLOSE evidence is not replayed cleanly")
        if not re.fullmatch(r"[0-9a-f]{40}", str(row.get("commit_sha", ""))):
            raise CloseSweepError("CLOSE evidence commit is invalid")
        if not re.fullmatch(r"[0-9a-f]{40}", str(row.get("blob_sha1", ""))):
            raise CloseSweepError("CLOSE evidence blob is invalid")
    review = receipt.get("authority_review")
    if not isinstance(review, Mapping):
        raise CloseSweepError("CLOSE receipt lacks authority review")
    allowed_review = (
        review.get("reviewer") == "self-review-authority"
        and review.get("review_provenance") == "SELF_ONLY"
        and review.get("verdict") == "PASS"
    )
    if not allowed_review:
        raise CloseSweepError("CLOSE authority review is invalid")
    evidence_commits = {str(row["commit_sha"]) for row in evidence}
    evidence_citations = {str(row["citation"]) for row in evidence}
    if review.get("reviewed_commit_sha") not in evidence_commits:
        raise CloseSweepError("CLOSE reviewed commit is not bound to evidence")
    if review.get("citation") not in evidence_citations:
        raise CloseSweepError("CLOSE review citation is not bound to evidence")


def build_close_plan(
    packet: Mapping[str, Any],
    authorization: Mapping[str, Any],
    *,
    expected_master_sha: str,
    packet_master_is_ancestor: bool = False,
    live_issues: Mapping[
        int,
        tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]],
    ],
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", expected_master_sha):
        raise CloseSweepError("expected master SHA is invalid")
    _verify_content_hash(packet, "packet_sha256", label="packet")
    _verify_content_hash(
        authorization,
        "authorization_sha256",
        label="authorization",
    )
    packet_master_sha = packet.get("master_sha")
    if not isinstance(packet_master_sha, str) or not re.fullmatch(
        r"[0-9a-f]{40}", packet_master_sha
    ):
        raise CloseSweepError("packet master SHA is invalid")
    if packet_master_sha != expected_master_sha and not packet_master_is_ancestor:
        raise CloseSweepError("packet master is stale")
    if (
        packet.get("deletion_or_issue_mutation_authority") != "NOT_GRANTED"
        or packet.get("public_issue_mutation_performed") is not False
    ):
        raise CloseSweepError("source packet authority boundary is invalid")
    expected_authorization_fields = {
        "schema_version",
        "repository",
        "packet_sha256",
        "packet_path",
        "close_issue_numbers",
        "reviewer",
        "review_provenance",
        "citation",
        "authorization_sha256",
    }
    if (
        authorization.get("schema_version")
        != "ember-issue-close-sweep-authorization-v1"
        or set(authorization) != expected_authorization_fields
    ):
        raise CloseSweepError("authorization schema is invalid")
    if authorization.get("packet_sha256") != packet["packet_sha256"]:
        raise CloseSweepError("authorization packet binding is invalid")
    packet_path = authorization.get("packet_path")
    if not isinstance(packet_path, str) or not re.fullmatch(
        r"receipts/oldest-issue-disposition/approved/[A-Za-z0-9._-]+\.json",
        packet_path,
    ):
        raise CloseSweepError("authorization packet path is invalid")
    if (
        authorization.get("repository") != packet.get("repository")
        or authorization.get("reviewer") != "self-review-authority"
        or authorization.get("review_provenance") != "SELF_ONLY"
    ):
        raise CloseSweepError("authorization provenance is invalid")
    numbers = authorization.get("close_issue_numbers")
    if (
        not isinstance(numbers, list)
        or not 1 <= len(numbers) <= 25
        or any(
            isinstance(number, bool) or not isinstance(number, int) or number < 1
            for number in numbers
        )
        or numbers != sorted(set(numbers))
    ):
        raise CloseSweepError("authorization issue selection is invalid")
    capture = packet.get("capture")
    if not isinstance(capture, Mapping) or not isinstance(capture.get("issues"), list):
        raise CloseSweepError("packet capture is invalid")
    issues = {
        row["number"]: row
        for row in capture["issues"]
        if isinstance(row, Mapping) and isinstance(row.get("number"), int)
    }
    receipts_raw = packet.get("receipts")
    if not isinstance(receipts_raw, list):
        raise CloseSweepError("packet receipts are invalid")
    receipts = {
        row["issue_number"]: row
        for row in receipts_raw
        if isinstance(row, Mapping) and isinstance(row.get("issue_number"), int)
    }
    authorization_citation = authorization.get("citation")
    for number in numbers:
        receipt = receipts.get(number)
        review = (
            receipt.get("authority_review") if isinstance(receipt, Mapping) else None
        )
        if (
            not isinstance(authorization_citation, str)
            or not isinstance(review, Mapping)
            or authorization_citation != review.get("citation")
        ):
            raise CloseSweepError(
                "authorization citation is not bound to reviewed evidence"
            )
    chunk_issue_numbers = [
        row["number"]
        for row in capture["issues"]
        if isinstance(row, Mapping) and isinstance(row.get("number"), int)
    ]
    chunk_last_created_at = capture["issues"][-1].get("created_at")
    if not isinstance(chunk_last_created_at, str):
        raise CloseSweepError("packet chunk cursor timestamp is invalid")
    skipped = []
    for number in chunk_issue_numbers:
        if number in numbers:
            continue
        receipt = receipts.get(number)
        if receipt is None:
            raise CloseSweepError("packet receipt is absent from chunk")
        unbound = receipt.get("unbound_clause")
        if isinstance(unbound, Mapping) and isinstance(unbound.get("description"), str):
            reason = unbound["description"]
        elif isinstance(receipt.get("retained_lesson"), str):
            reason = receipt["retained_lesson"]
        elif isinstance(receipt.get("replacement_citation"), str):
            reason = f"superseded by {receipt['replacement_citation']}"
        else:
            reason = f"{receipt.get('disposition')} is not authorized for closure"
        skipped.append(
            {
                "issue_number": number,
                "disposition": receipt.get("disposition"),
                "reason": reason,
                "receipt_sha256": receipt.get("receipt_sha256"),
            }
        )
    operations = []
    for number in numbers:
        if number not in issues or number not in receipts:
            raise CloseSweepError("authorized issue is absent from packet")
        issue = issues[number]
        receipt = receipts[number]
        _validate_close_receipt(receipt, issue=issue)
        if _is_protected(issue):
            raise CloseSweepError(f"issue {number} is protected GOAL/initiative work")
        if number not in live_issues:
            raise CloseSweepError("authorized issue live source is missing")
        live_issue, live_comments = live_issues[number]
        sub_issues = live_issue.get("sub_issues_summary")
        if (
            isinstance(sub_issues, Mapping)
            and isinstance(sub_issues.get("total"), int)
            and not isinstance(sub_issues.get("total"), bool)
            and sub_issues["total"] > 0
        ):
            raise CloseSweepError(f"issue {number} is protected parent/tracking work")
        if issue.get("state") != "open":
            raise CloseSweepError("captured issue is not open")
        operation = {
            "issue_number": number,
            "issue_url": issue["url"],
            "receipt_sha256": receipt["receipt_sha256"],
            "evidence": receipt["close_evidence"],
        }
        marker = (
            "<!-- ember-issue-close-sweep:"
            f"{authorization['authorization_sha256']}:{number} -->"
        )
        expected_comment = _comment_body(operation, marker)
        matching_comments = [
            row
            for row in live_comments
            if (
                isinstance(row, Mapping)
                and row.get("body") == expected_comment
                and isinstance(row.get("user"), Mapping)
                and row["user"].get("login") == "github-actions[bot]"
            )
        ]
        if len(matching_comments) > 1:
            raise CloseSweepError("authorized close receipt comment is duplicated")
        comment_present = len(matching_comments) == 1
        remaining_comments = [
            row for row in live_comments if row not in matching_comments
        ]
        live_projection = _live_projection(live_issue, remaining_comments)
        captured_projection = _captured_projection(issue)
        if comment_present:
            live_projection["updated_at"] = captured_projection["updated_at"]
            if live_projection["state"] == "closed":
                live_projection["state"] = "open"
        if live_projection != captured_projection:
            raise CloseSweepError(
                f"issue {number} live source differs from captured evidence"
            )
        operation["comment_needed"] = not comment_present
        operation["close_needed"] = live_issue.get("state") != "closed"
        operations.append(operation)
    plan = {
        "schema_version": "ember-issue-close-sweep-plan-v1",
        "repository": packet["repository"],
        "expected_master_sha": expected_master_sha,
        "packet_master_sha": packet_master_sha,
        "packet_sha256": packet["packet_sha256"],
        "authorization_sha256": authorization["authorization_sha256"],
        "selection_sha256": packet.get("selection_sha256"),
        "chunk_issue_numbers": chunk_issue_numbers,
        "chunk_last_created_at": chunk_last_created_at,
        "operations": operations,
        "skipped": skipped,
    }
    plan["plan_sha256"] = canonical_sha256(plan)
    return plan


def _comment_body(operation: Mapping[str, Any], marker: str) -> str:
    evidence_lines = []
    for row in operation["evidence"]:
        match = re.search(r"/pull/(\d+)(?:$|[#/?])", row["citation"])
        pr = f"PR #{match.group(1)}" if match else row["citation"]
        evidence_lines.append(
            f"- {pr}; landing commit `{row['commit_sha']}`; "
            f"`{row['path']}` blob `{row['blob_sha1']}`; "
            f"replay `{row['test_command']}`."
        )
    return "\n".join(
        [
            marker,
            "Ember backlog-drain closure receipt.",
            "",
            *evidence_lines,
            "",
            f"Disposition receipt: `{operation['receipt_sha256']}`.",
            (
                "Review provenance: `self-review-authority` / `SELF_ONLY`; "
                "independent review remains append-only future work."
            ),
            "Rollback: reopen this issue and revert the cited landing commit.",
            (
                "No model, training, benchmark, capability, or research claim "
                "is made by this closure."
            ),
        ]
    )


def apply_close_plan(
    plan: Mapping[str, Any],
    *,
    mutate: Callable[[str, int, str | None], None],
) -> dict[str, Any]:
    _verify_content_hash(plan, "plan_sha256", label="plan")
    operations = plan.get("operations")
    if not isinstance(operations, list) or not operations:
        raise CloseSweepError("close plan has no operations")
    closed = []
    closed_rows = []
    mutation_count = 0
    for operation in operations:
        number = operation["issue_number"]
        marker = (
            f"<!-- ember-issue-close-sweep:{plan['authorization_sha256']}:{number} -->"
        )
        if operation.get("comment_needed") is True:
            mutate("comment", number, _comment_body(operation, marker))
            mutation_count += 1
        if operation.get("close_needed") is True:
            mutate("close", number, None)
            mutation_count += 1
        closed.append(number)
        closed_rows.append(
            {
                "issue_number": number,
                "receipt_sha256": operation["receipt_sha256"],
                "evidence": operation["evidence"],
                "comment_posted": operation.get("comment_needed") is True,
                "close_performed": operation.get("close_needed") is True,
            }
        )
    chunk_issue_numbers = plan.get("chunk_issue_numbers")
    if not isinstance(chunk_issue_numbers, list) or not chunk_issue_numbers:
        raise CloseSweepError("close plan chunk cursor is invalid")
    receipt = {
        "schema_version": "ember-issue-close-sweep-execution-v1",
        "repository": plan["repository"],
        "expected_master_sha": plan["expected_master_sha"],
        "plan_sha256": plan["plan_sha256"],
        "authorization_sha256": plan["authorization_sha256"],
        "closed_issue_numbers": closed,
        "closed": closed_rows,
        "skipped": plan.get("skipped", []),
        "cursor": {
            "selection_sha256": plan.get("selection_sha256"),
            "packet_master_sha": plan.get("packet_master_sha"),
            "first_issue_number": chunk_issue_numbers[0],
            "last_issue_number": chunk_issue_numbers[-1],
            "last_issue_created_at": plan.get("chunk_last_created_at"),
            "chunk_issue_numbers": chunk_issue_numbers,
        },
        "already_closed_issue_numbers": [
            operation["issue_number"]
            for operation in operations
            if operation.get("close_needed") is False
        ],
        "mutation_count": mutation_count,
        "executed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt


def _default_run_gh(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *argv],
        capture_output=True,
        text=True,
        check=False,
    )


def _default_run_git(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *argv],
        capture_output=True,
        text=True,
        check=False,
    )


def _run_gh_text(
    run_gh: Callable[[list[str]], subprocess.CompletedProcess[str]],
    argv: list[str],
) -> str:
    result = run_gh(argv)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CloseSweepError(f"GitHub query failed: {detail}")
    return result.stdout


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CloseSweepError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise CloseSweepError(f"{label} must be a JSON object")
    return value


def _write_object(path: Path, value: Mapping[str, Any]) -> None:
    payload = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8", errors="strict")
    temporary.replace(path)


def _decode_json(text: str, *, label: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CloseSweepError(f"{label} returned invalid JSON") from exc


def _fetch_live_issue(
    repository: str,
    number: int,
    *,
    run_gh: Callable[[list[str]], subprocess.CompletedProcess[str]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issue = _decode_json(
        _run_gh_text(run_gh, ["api", f"repos/{repository}/issues/{number}"]),
        label=f"issue {number}",
    )
    if not isinstance(issue, dict) or "pull_request" in issue:
        raise CloseSweepError(f"issue {number} live source is invalid")
    raw_comments = _decode_json(
        _run_gh_text(
            run_gh,
            [
                "api",
                "--paginate",
                "--slurp",
                f"repos/{repository}/issues/{number}/comments?per_page=100",
            ],
        ),
        label=f"issue {number} comments",
    )
    if not isinstance(raw_comments, list):
        raise CloseSweepError(f"issue {number} comments are invalid")
    comments: list[dict[str, Any]] = []
    for page in raw_comments:
        if isinstance(page, list):
            if any(not isinstance(row, dict) for row in page):
                raise CloseSweepError(f"issue {number} comments are invalid")
            comments.extend(page)
        elif isinstance(page, dict):
            comments.append(page)
        else:
            raise CloseSweepError(f"issue {number} comments are invalid")
    return issue, comments


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "apply"))
    parser.add_argument("--repository", required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--expected-master-sha", required=True)
    parser.add_argument("--packet-master-is-ancestor", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    run_gh: Callable[[list[str]], subprocess.CompletedProcess[str]] = _default_run_gh,
    run_git: Callable[[list[str]], subprocess.CompletedProcess[str]] = _default_run_git,
) -> int:
    args = _parser().parse_args(argv)
    packet = _load_object(args.packet, label="packet")
    authorization = _load_object(args.authorization, label="authorization")
    if packet.get("repository") != args.repository:
        raise CloseSweepError("packet repository binding is invalid")
    try:
        validate_packet(packet, expected_master=packet.get("master_sha"))
    except PacketError as exc:
        raise CloseSweepError(f"canonical packet validation failed: {exc}") from exc
    live_master = _run_gh_text(
        run_gh,
        ["api", f"repos/{args.repository}/commits/master", "--jq", ".sha"],
    ).strip()
    if live_master != args.expected_master_sha:
        raise CloseSweepError("live master differs from expected master")
    packet_master = packet.get("master_sha")
    if packet_master != args.expected_master_sha:
        if not args.packet_master_is_ancestor:
            raise CloseSweepError("packet master is stale")
        ancestry = run_git(
            [
                "merge-base",
                "--is-ancestor",
                str(packet_master),
                args.expected_master_sha,
            ]
        )
        if ancestry.returncode != 0:
            raise CloseSweepError("packet master ancestor check failed")
    numbers = authorization.get("close_issue_numbers")
    if not isinstance(numbers, list):
        raise CloseSweepError("authorization issue selection is invalid")
    live_issues = {
        number: _fetch_live_issue(args.repository, number, run_gh=run_gh)
        for number in numbers
        if isinstance(number, int) and not isinstance(number, bool)
    }
    plan = build_close_plan(
        packet,
        authorization,
        expected_master_sha=args.expected_master_sha,
        packet_master_is_ancestor=args.packet_master_is_ancestor,
        live_issues=live_issues,
    )
    if args.command == "validate":
        result: Mapping[str, Any] = plan
    else:

        def mutate(action: str, number: int, body: str | None = None) -> None:
            if action == "comment":
                command = [
                    "api",
                    "--method",
                    "POST",
                    f"repos/{args.repository}/issues/{number}/comments",
                    "-f",
                    f"body={body}",
                ]
            elif action == "close":
                command = [
                    "api",
                    "--method",
                    "PATCH",
                    f"repos/{args.repository}/issues/{number}",
                    "-f",
                    "state=closed",
                ]
            else:
                raise CloseSweepError(f"unsupported mutation action: {action}")
            _run_gh_text(run_gh, command)

        result = apply_close_plan(plan, mutate=mutate)
    _write_object(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
