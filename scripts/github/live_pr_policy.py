#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Validate live pull-request metadata acquired by a trusted base-pinned kernel."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.check_pr_authority_binding import load_goal_binding, validate_pr_body
from src.ember.governance.scripts.ember_cli_spec_policy import (
    validate_added_component_coverage_between_roots,
)


SNAPSHOT_FIELDS = {
    "actor_login",
    "title",
    "body",
    "base_sha",
    "head_sha",
    "event_base_sha",
    "event_head_sha",
    "draft",
    "labels",
    "milestone",
    "changed_files",
    "closing_issue_numbers",
}
TITLE_RE = re.compile(
    r"^(?:feat|fix|docs|test|refactor|perf|build|ci|chore|release|security)"
    r"\([a-z0-9][a-z0-9-]{0,31}\): [^\r\n]{8,120}$"
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# GitHub's own auto-close keyword set (close/closes/closed/fix/fixes/fixed/
# resolve/resolves/resolved), matched only as a clean, standalone line -- not
# embedded in prose -- so a negated mention ("does not close #898") never
# counts as a declaration. GitHub's own closing-keyword parser has no such
# distinction (issue #898, 2026-08-22: a PR body reading "Does not close
# #898" still closed #898 on merge); this regex is deliberately stricter than
# GitHub's so an author must state the closure as its own line to justify it.
CLOSING_KEYWORD_LINE_RE = re.compile(
    r"(?im)^\s*(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*#(\d+)\s*$"
)
DEPENDABOT_TITLE_RE = re.compile(
    r"^(?:(?:build|chore)\(deps(?:-dev)?\): bump|Bump) [^\r\n]{3,120}$"
)
REQUIRED_SECTIONS = (
    "Linked issue or governing contract",
    "Exact base SHA",
    "Exact reviewed head SHA",
    "Intended outcome",
    "Why this is one coherent PR",
    "Affected areas",
    "Affected milestones",
    "Implementation summary",
    "Acceptance-clause mapping",
    "Local reproduction commands",
    "Automated tests",
    "Executed evidence",
    "Generated receipts and artifacts",
    "Known failures",
    "Unverified areas",
    "Claim boundary",
    "Review provenance",
    "Rollback or revert procedure",
    "Follow-up obligations that remain",
)
DEPENDABOT_LABELS = {
    "kind:maintenance",
    "area:ci",
    "state:ready",
    "priority:p3",
}
DEPENDABOT_PATHS = (
    re.compile(r"^\.github/(?:dependabot\.yml|workflows/[^/]+\.ya?ml)$"),
    re.compile(r"^(?:Cargo\.(?:toml|lock)|pyproject\.toml|package\.json|bun\.lockb?)$"),
    re.compile(r"^(?:requirements[^/]*\.txt|[^/]+/package\.json|[^/]+/bun\.lockb?)$"),
    re.compile(r"^(?:runtime/[^/]+/Cargo\.(?:toml|lock))$"),
)


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> tuple[int, str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        input=stdin,
        capture_output=True,
        check=False,
    )
    return result.returncode, result.stdout.decode("utf-8", errors="replace")


def _own_diff_identity(repo: Path, base_tip: str, head: str) -> str | None:
    """Byte-sensitive identity of merge-base(base_tip, head)..head.

    The explicit diff options make the byte stream independent of user Git
    configuration.  Unlike ``git patch-id``, the digest preserves whitespace
    and every other diff byte while remaining unaffected by unrelated base
    commits outside the PR's own diff.
    """
    code, merge_base = _git(repo, "merge-base", base_tip, head)
    if code != 0:
        return None
    result = subprocess.run(
        [
            "git",
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-color",
            "--no-renames",
            "--binary",
            "--full-index",
            merge_base.strip(),
            head,
            "--",
        ],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return hashlib.sha256(result.stdout).hexdigest()


def pinned_head_covers_live_head(
    repo: Path, pinned_head: str, live_head: str
) -> bool:
    """Accept a stale head pin only when the branch update left the PR's own
    diff byte-identical: the pinned reviewed head must be an ancestor of the
    live head, and the own-diff (merge-base against the live base tip) must
    carry the same byte-sensitive own-diff identity at both heads. Any PR-side
    edit after the pin, including whitespace, changes that identity and fails."""
    if not SHA_RE.fullmatch(pinned_head or ""):
        return False
    code, _ = _git(repo, "merge-base", "--is-ancestor", pinned_head, live_head)
    if code != 0:
        return False
    code, base_tip = _git(repo, "rev-parse", "--verify", "--quiet", "HEAD^2")
    if code == 0:
        # Subject is the refs/pull/N/merge test-merge: first parent is the
        # live base tip, second is the live PR head.
        code, base_tip = _git(repo, "rev-parse", "HEAD^1")
        if code != 0:
            return False
        base_tip = base_tip.strip()
    else:
        return False
    pinned_id = _own_diff_identity(repo, base_tip, pinned_head)
    live_id = _own_diff_identity(repo, base_tip, live_head)
    return pinned_id is not None and pinned_id == live_id


def pinned_base_covers_live_base(
    repo: Path,
    pinned_base: str,
    pinned_head: str,
    live_base: str,
    live_head: str,
) -> bool:
    """Accept a stale reviewed base only when the reviewed PR patch is intact.

    Base advancement alone is harmless when both reviewed tips remain ancestors
    of their live counterparts and the PR's own byte-sensitive diff identity
    is identical between the reviewed and live base/head pairs. Overlap
    resolution or any PR-side mutation changes that identity and therefore
    refuses until re-pin.
    """
    if not all(
        SHA_RE.fullmatch(value or "")
        for value in (pinned_base, pinned_head, live_base, live_head)
    ):
        return False
    for ancestor, descendant in (
        (pinned_base, live_base),
        (pinned_head, live_head),
    ):
        code, _ = _git(repo, "merge-base", "--is-ancestor", ancestor, descendant)
        if code != 0:
            return False
    pinned_id = _own_diff_identity(repo, pinned_base, pinned_head)
    live_id = _own_diff_identity(repo, live_base, live_head)
    return pinned_id is not None and pinned_id == live_id


def _sections(body: str) -> dict[str, str]:
    matches = list(re.finditer(r"(?m)^## ([^\r\n]+)\s*$", body))
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        result[match.group(1).strip()] = body[match.end() : end].strip()
    return result


def _label_cardinality(labels: Sequence[str]) -> list[str]:
    errors: list[str] = []
    for family, minimum, maximum in (
        ("kind:", 1, 1),
        ("area:", 1, 3),
        ("state:", 1, 1),
        ("priority:", 1, 1),
        ("review:", 1, 1),
    ):
        count = sum(label.startswith(family) for label in labels)
        if not minimum <= count <= maximum:
            errors.append(f"labels:{family[:-1]}-cardinality")
    return errors


def declared_closing_issue_numbers(body: str) -> set[int]:
    """Issue numbers this body explicitly declares closure of, one clean
    line at a time (see ``CLOSING_KEYWORD_LINE_RE``)."""
    return {int(match.group(1)) for match in CLOSING_KEYWORD_LINE_RE.finditer(body or "")}


def _validate_closing_linkage(snapshot: Mapping[str, Any]) -> list[str]:
    """FAIL when GitHub's live closingIssuesReferences names an issue this
    body never explicitly declared with its own ``Closes #<n>`` line.

    Operator ruling (2026-08-22, receipted on #898): an unjustified
    issue-close via merge linkage is banned, and the ban must be structural.
    GitHub computes ``closingIssuesReferences`` with a negation-blind
    keyword parser -- a body reading "does not close #898" still produces a
    live closing reference for #898, and merging closes it anyway. This
    check does not try to out-parse GitHub's parser; it requires the body to
    make its OWN, unambiguous declaration for every issue GitHub's live
    metadata says the merge will close.
    """
    closing_numbers = snapshot.get("closing_issue_numbers")
    if not isinstance(closing_numbers, list) or not all(
        type(number) is int and number > 0 for number in closing_numbers
    ):
        return ["snapshot:closing-issue-numbers-invalid"]
    if not closing_numbers:
        return []
    declared = declared_closing_issue_numbers(str(snapshot.get("body", "")))
    undeclared = sorted(set(closing_numbers) - declared)
    if undeclared:
        return [
            "closing-linkage:body-live-mismatch:"
            + ",".join(f"#{number}" for number in undeclared)
        ]
    return []


def _validate_common(snapshot: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    unknown = sorted(set(snapshot) - SNAPSHOT_FIELDS)
    missing = sorted(SNAPSHOT_FIELDS - set(snapshot))
    if unknown:
        errors.append(f"snapshot:unknown-fields:{','.join(unknown)}")
    if missing:
        errors.append(f"snapshot:missing-fields:{','.join(missing)}")
    for name in ("actor_login", "title", "body", "base_sha", "head_sha"):
        if not isinstance(snapshot.get(name), str):
            errors.append(f"snapshot:{name}-invalid")
    if not isinstance(snapshot.get("draft"), bool):
        errors.append("snapshot:draft-invalid")
    labels = snapshot.get("labels")
    if not isinstance(labels, list) or not all(
        isinstance(label, str) and label for label in labels
    ):
        errors.append("snapshot:labels-invalid")
    files = snapshot.get("changed_files")
    if not isinstance(files, list) or not files or not all(
        isinstance(path, str) and path and "\\" not in path for path in files
    ):
        errors.append("snapshot:changed-files-invalid")
    for actual, event, name in (
        (snapshot.get("base_sha"), snapshot.get("event_base_sha"), "event-base"),
        (snapshot.get("head_sha"), snapshot.get("event_head_sha"), "event-head"),
    ):
        if not isinstance(actual, str) or not SHA_RE.fullmatch(actual):
            errors.append(f"snapshot:{name}-sha-invalid")
        if actual != event:
            errors.append(f"snapshot:{name}-mismatch")
    milestone = snapshot.get("milestone")
    if milestone is not None and (
        not isinstance(milestone, str) or not milestone.strip()
    ):
        errors.append("snapshot:milestone-invalid")
    errors.extend(_validate_closing_linkage(snapshot))
    return errors


def _validate_dependabot(snapshot: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    title = str(snapshot.get("title", ""))
    if not DEPENDABOT_TITLE_RE.fullmatch(title):
        errors.append("dependabot:title-invalid")
    if set(snapshot.get("labels", [])) != DEPENDABOT_LABELS:
        errors.append("dependabot:labels-invalid")
    if snapshot.get("milestone") is not None:
        errors.append("dependabot:milestone-must-be-null")
    for path in snapshot.get("changed_files", []):
        if not isinstance(path, str) or not any(rule.fullmatch(path) for rule in DEPENDABOT_PATHS):
            errors.append(f"dependabot:path-not-allowed:{path}")
    return errors


def validate_live_pull_request(
    snapshot: Mapping[str, Any],
    *,
    authority: tuple[str, str, Sequence[str]] = (
        "EMBER-02",
        "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        ("EMBER-02A", "EMBER-02B", "EMBER-02C"),
    ),
    base_root: Path | None = None,
    subject_root: Path | None = None,
) -> list[str]:
    errors = _validate_common(snapshot)
    if errors:
        return errors
    if snapshot["actor_login"] == "dependabot[bot]":
        return _validate_dependabot(snapshot)

    if base_root is not None and subject_root is None:
        return ["spec-floor:subject-root-required"]
    if subject_root is not None and base_root is None:
        return ["spec-floor:base-root-required"]
    if base_root is not None and subject_root is not None:
        spec_errors = validate_added_component_coverage_between_roots(
            base_root,
            subject_root,
            snapshot["changed_files"],
        )
        if spec_errors:
            return spec_errors

    title = str(snapshot["title"])
    if not TITLE_RE.fullmatch(title):
        errors.append("title:grammar-invalid")
    labels = list(snapshot["labels"])
    errors.extend(_label_cardinality(labels))
    body = str(snapshot["body"])
    if not re.search(r"<!--\s*ember-template:\s*pr/[a-z-]+@v1\s*-->", body):
        errors.append("body:template-marker-missing")
    goal, outcome, workstreams = authority
    errors.extend(f"authority:{error}" for error in validate_pr_body(
        body, goal, outcome, workstreams
    ))
    sections = _sections(body)
    for heading in REQUIRED_SECTIONS:
        value = sections.get(heading, "").strip()
        if not value:
            errors.append(f"body:section-empty:{heading}")
    base_section = sections.get("Exact base SHA", "").strip("` \r\n")
    head_section = sections.get("Exact reviewed head SHA", "").strip("` \r\n")
    if base_section != snapshot["base_sha"] and not (
        subject_root is not None
        and pinned_base_covers_live_base(
            subject_root,
            base_section,
            head_section,
            snapshot["base_sha"],
            snapshot["head_sha"],
        )
    ):
        errors.append("body:base-sha-mismatch")
    if head_section != snapshot["head_sha"] and not (
        subject_root is not None
        and pinned_head_covers_live_head(
            subject_root, head_section, snapshot["head_sha"]
        )
    ):
        errors.append("body:head-sha-mismatch")
    milestone = snapshot["milestone"]
    milestone_section = sections.get("Affected milestones", "")
    if milestone is None:
        if not re.search(r"(?im)^exception:\s*\S", milestone_section):
            errors.append("milestone:required-or-exception")
    elif milestone not in milestone_section:
        errors.append("milestone:body-live-mismatch")
    return errors


def build_snapshot(
    pr: Mapping[str, Any],
    file_pages: Any,
    *,
    event_base_sha: str,
    event_head_sha: str,
    closing_issue_numbers: Sequence[int],
) -> dict[str, Any]:
    pages = file_pages
    if isinstance(pages, list) and pages and all(isinstance(page, dict) for page in pages):
        pages = [pages]
    if not isinstance(pages, list) or not all(isinstance(page, list) for page in pages):
        raise ValueError("files JSON must be a list or paginated list")
    files: list[str] = []
    for page in pages:
        for row in page:
            if not isinstance(row, dict) or not isinstance(row.get("filename"), str):
                raise ValueError("file row is malformed")
            files.append(row["filename"])
    return {
        "actor_login": pr.get("user", {}).get("login"),
        "title": pr.get("title"),
        "body": pr.get("body") or "",
        "base_sha": pr.get("base", {}).get("sha"),
        "head_sha": pr.get("head", {}).get("sha"),
        "event_base_sha": event_base_sha,
        "event_head_sha": event_head_sha,
        "draft": pr.get("draft"),
        "labels": [row.get("name") for row in pr.get("labels", [])],
        "milestone": (pr.get("milestone") or {}).get("title"),
        "changed_files": files,
        "closing_issue_numbers": list(closing_issue_numbers),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pr-json", type=Path, required=True)
    parser.add_argument("--files-json", type=Path, required=True)
    parser.add_argument("--event-base-sha", required=True)
    parser.add_argument("--event-head-sha", required=True)
    parser.add_argument("--snapshot-output", type=Path)
    parser.add_argument("--subject-root", type=Path)
    parser.add_argument(
        "--closing-issues-json",
        type=Path,
        required=True,
        help=(
            "Path to a JSON array of issue numbers from the live PR's "
            "GraphQL closingIssuesReferences (e.g. produced by "
            "'gh api graphql')."
        ),
    )
    args = parser.parse_args(argv)
    try:
        pr = json.loads(args.pr_json.read_text(encoding="utf-8", errors="strict"))
        files = json.loads(args.files_json.read_text(encoding="utf-8", errors="strict"))
        closing_issue_numbers = json.loads(
            args.closing_issues_json.read_text(encoding="utf-8", errors="strict")
        )
        if not isinstance(closing_issue_numbers, list) or not all(
            type(number) is int for number in closing_issue_numbers
        ):
            raise ValueError("closing-issues-json must be a JSON array of integers")
        snapshot = build_snapshot(
            pr,
            files,
            event_base_sha=args.event_base_sha,
            event_head_sha=args.event_head_sha,
            closing_issue_numbers=closing_issue_numbers,
        )
        authority = load_goal_binding(args.root.resolve())
        policy_roots = (
            {
                "base_root": args.root.resolve(),
                "subject_root": args.subject_root.resolve(),
            }
            if args.subject_root is not None else {}
        )
        errors = validate_live_pull_request(
            snapshot,
            authority=authority,
            **policy_roots,
        )
        if args.snapshot_output:
            args.snapshot_output.write_text(
                json.dumps(snapshot, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "errors": [str(exc)]}, sort_keys=True))
        return 1
    print(json.dumps(
        {
            "status": "PASS" if not errors else "FAIL",
            "errors": errors,
            "claim_boundary": "live pull-request policy only",
        },
        sort_keys=True,
    ))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
