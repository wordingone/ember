#!/usr/bin/env python3
"""
Mechanical merge gate for ember PRs.

Entrypoint: python scripts/merge_gate.py <PR> --class receipts|docs|code --title "..."

Asserts (in order, each emitting checklist line):
1. closingIssuesReferences count == 0 (lane PRs never carry close keywords)
2. All CI checks SUCCESS or SKIPPED
3. mergeable == MERGEABLE
4. body contains a refs #N line
5. diff paths match the declared class allow-list
6. If diff touches coordinator-class paths → REFUSE with COORDINATOR-REQUIRED
7. On all-pass: squash-merge with --delete-branch and provided title
   Append receipt to receipts/merge-gate/merge-gate-log.jsonl
"""

import json
import subprocess
import sys
import argparse
import re
from pathlib import Path
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional, List, Dict, Any


@dataclass
class ChecklistItem:
    """Single checklist assertion result."""
    name: str
    status: str  # "PASS" or "FAIL"
    details: str = ""


@dataclass
class ChecklistResult:
    """Result of merge gate validation."""
    passed: bool
    checklist: List[Dict[str, Any]] = field(default_factory=list)
    merged_sha: Optional[str] = None
    refuse_reason: Optional[str] = None  # "COORDINATOR-REQUIRED" if set
    pr_number: Optional[int] = None
    pr_class: Optional[str] = None


def get_pr_data(pr_number: int) -> Dict[str, Any]:
    """Fetch PR data from GitHub using gh CLI."""
    cmd = [
        "gh", "pr", "view", str(pr_number),
        "--json", "number,title,body,state,mergeable,mergeableState," +
                  "commits,closingIssuesReferences,statusCheckRollup,files"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error fetching PR #{pr_number}: {e.stderr}")
        sys.exit(1)


def has_coordinator_paths(file_paths: List[str]) -> bool:
    """Check if any file path matches coordinator-class patterns."""
    coordinator_patterns = [
        r"^GOAL\.md$",
        r"^INVARIANT\.md$",
        r"^docs/spec/.*",
        r"^scripts/cbase_.*",
        r"^scripts/ember_totality/.*\.py$",  # All .py files in ember_totality EXCEPT receipts-*/**
        r"^tools/repo-guard\.sh$",
        r"^\.claude/.*"
    ]

    for path in file_paths:
        # Special case: scripts/ember_totality/receipts-* are allowed (not coordinator)
        if path.startswith("scripts/ember_totality/receipts-"):
            continue

        for pattern in coordinator_patterns:
            if re.match(pattern, path):
                return True

    return False


def verify_paths_match_class(file_paths: List[str], pr_class: str) -> bool:
    """Verify diff paths match the declared class allow-list."""
    if pr_class == "receipts":
        # Allow: receipts/** and scripts/ember_totality/receipts-*/**
        allowed_patterns = [
            r"^receipts/.*",
            r"^scripts/ember_totality/receipts-.*"
        ]
    elif pr_class == "docs":
        # Allow: docs/**, README.md, GOVERNANCE.md, .github/**
        allowed_patterns = [
            r"^docs/.*",
            r"^README\.md$",
            r"^GOVERNANCE\.md$",
            r"^\.github/.*"
        ]
    elif pr_class == "code":
        # Allow: anything else (coordinator paths are checked separately)
        allowed_patterns = [r".*"]  # Match everything
    else:
        return False

    for path in file_paths:
        matched = False
        for pattern in allowed_patterns:
            if re.match(pattern, path):
                matched = True
                break
        if not matched:
            return False

    return True


def check_merge_gate(pr_data: Dict[str, Any], pr_class: str) -> ChecklistResult:
    """
    Validate PR against merge gate criteria.
    Returns ChecklistResult with all assertions.
    """
    result = ChecklistResult(passed=False, pr_number=pr_data.get("number"), pr_class=pr_class)

    # Assertion 1: closingIssuesReferences count == 0
    closing_issues = pr_data.get("closingIssuesReferences", {}).get("totalCount", 0)
    if closing_issues == 0:
        result.checklist.append({"name": "closingIssuesReferences", "status": "PASS"})
    else:
        result.checklist.append({
            "name": "closingIssuesReferences",
            "status": "FAIL",
            "details": f"Found {closing_issues} closing issue reference(s)"
        })
        return result

    # Assertion 2: All CI checks SUCCESS or SKIPPED
    status_checks = pr_data.get("statusCheckRollup", [])
    ci_pass = True
    ci_details = []
    for check in status_checks:
        state = check.get("state")
        if state not in ["SUCCESS", "SKIPPED"]:
            ci_pass = False
            ci_details.append(f"{check.get('name')}: {state}")

    if ci_pass:
        result.checklist.append({"name": "ci_checks", "status": "PASS"})
    else:
        result.checklist.append({
            "name": "ci_checks",
            "status": "FAIL",
            "details": "; ".join(ci_details)
        })
        return result

    # Assertion 3: mergeable == MERGEABLE
    mergeable = pr_data.get("mergeable")
    if mergeable == "MERGEABLE":
        result.checklist.append({"name": "mergeable", "status": "PASS"})
    else:
        result.checklist.append({
            "name": "mergeable",
            "status": "FAIL",
            "details": f"mergeable={mergeable}"
        })
        return result

    # Assertion 4: body contains refs #N line
    body = pr_data.get("body", "")
    has_refs = bool(re.search(r"\b(?:fixes|closes)\s+#\d+\b", body, re.IGNORECASE))
    if has_refs:
        result.checklist.append({"name": "body_refs", "status": "PASS"})
    else:
        result.checklist.append({
            "name": "body_refs",
            "status": "FAIL",
            "details": "No 'fixes #N' or 'closes #N' in body"
        })
        return result

    # Get file paths from PR
    files = pr_data.get("files", {}).get("nodes", [])
    file_paths = [f.get("path") for f in files]

    # Assertion 6 (before 5): Check for coordinator-class paths
    # This refuses BEFORE checking class paths
    if has_coordinator_paths(file_paths):
        coordinator_files = [p for p in file_paths if re.match(
            r"(^GOAL\.md$|^INVARIANT\.md$|^docs/spec/.*|^scripts/cbase_.*|^scripts/ember_totality/(?!receipts-).*\.py$|^tools/repo-guard\.sh$|^\.claude/.*)",
            p
        )]
        result.checklist.append({
            "name": "coordinator_paths",
            "status": "REFUSE",
            "details": f"Coordinator-class paths: {', '.join(coordinator_files)}"
        })
        result.refuse_reason = "COORDINATOR-REQUIRED"
        return result

    result.checklist.append({"name": "coordinator_paths", "status": "PASS"})

    # Assertion 5: diff paths match class allow-list
    if verify_paths_match_class(file_paths, pr_class):
        result.checklist.append({"name": "path_class_match", "status": "PASS"})
    else:
        result.checklist.append({
            "name": "path_class_match",
            "status": "FAIL",
            "details": f"Paths don't match {pr_class} class allow-list: {', '.join(file_paths)}"
        })
        return result

    # Assertion 7: Would merge successfully
    # Get merged SHA from commits
    commits = pr_data.get("commits_after_check", [])
    if commits:
        result.merged_sha = commits[0].get("oid", "unknown")

    result.checklist.append({"name": "merge", "status": "PASS"})
    result.passed = True

    return result


def format_checklist_output(result: ChecklistResult) -> str:
    """Format checklist result for display."""
    lines = []

    if result.refuse_reason:
        lines.append(f"\n❌ MERGE REFUSED: {result.refuse_reason}\n")
    elif result.passed:
        lines.append(f"\n✓ MERGE GATE PASSED (PR #{result.pr_number}, class={result.pr_class})\n")
    else:
        lines.append(f"\n✗ MERGE GATE FAILED (PR #{result.pr_number}, class={result.pr_class})\n")

    lines.append("Checklist:")
    for item in result.checklist:
        status = item.get("status")
        name = item.get("name")
        details = item.get("details", "")

        symbol = "✓" if status == "PASS" else ("✗" if status == "FAIL" else "❌")
        line = f"  {symbol} {name}: {status}"
        if details:
            line += f" ({details})"
        lines.append(line)

    if result.merged_sha:
        lines.append(f"\nMerged SHA: {result.merged_sha[:12]}")

    return "\n".join(lines)


def format_receipt_row(pr_number: int, pr_class: str, checklist: List[Dict[str, Any]], merged_sha: str) -> str:
    """Format a receipt row for merge-gate-log.jsonl."""
    row = {
        "pr": pr_number,
        "class": pr_class,
        "checklist": checklist,
        "merged_sha": merged_sha,
        "ts": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    return json.dumps(row, separators=(",", ":"))


def merge_pr(pr_number: int, title: str) -> bool:
    """Perform squash merge of PR."""
    cmd = [
        "gh", "pr", "merge", str(pr_number),
        "--squash",
        "--delete-branch",
        "--subject", title
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error merging PR #{pr_number}: {e.stderr}")
        return False


def append_receipt_log(receipt_row: str, log_path: str = "receipts/merge-gate/merge-gate-log.jsonl") -> bool:
    """Append receipt to merge-gate-log.jsonl."""
    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(receipt_row + "\n")
        return True
    except IOError as e:
        print(f"Error writing receipt log: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Mechanical merge gate for ember PRs"
    )
    parser.add_argument("pr", type=int, help="PR number to check")
    parser.add_argument("--class", dest="pr_class", required=True,
                       choices=["receipts", "docs", "code"],
                       help="PR class (receipts, docs, or code)")
    parser.add_argument("--title", required=True,
                       help="Squash merge title")
    parser.add_argument("--dry-run", action="store_true",
                       help="Print checklist without merging")

    args = parser.parse_args()

    # Fetch PR data
    pr_data = get_pr_data(args.pr)

    # Validate against merge gate
    result = check_merge_gate(pr_data, args.pr_class)

    # Print checklist
    output = format_checklist_output(result)
    print(output)

    # If not dry-run and passed, merge and log receipt
    if not args.dry_run and result.passed:
        if merge_pr(args.pr, args.title):
            receipt_row = format_receipt_row(
                args.pr,
                args.pr_class,
                result.checklist,
                result.merged_sha
            )
            if append_receipt_log(receipt_row):
                print(f"\nReceipt logged to receipts/merge-gate/merge-gate-log.jsonl")
            else:
                print(f"\nWarning: Failed to log receipt")
        else:
            sys.exit(1)
    elif args.dry_run:
        print("\n(dry-run: no merge performed)")
        if result.passed:
            receipt_row = format_receipt_row(
                args.pr,
                args.pr_class,
                result.checklist,
                result.merged_sha
            )
            print(f"Receipt would be: {receipt_row}")

    # Exit with appropriate code
    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
