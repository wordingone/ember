#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed validation for Ember issue, PR, review, and comment templates."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml


ISSUE_KINDS = (
    "defect",
    "feature",
    "enhancement",
    "engineering",
    "research",
    "experiment",
    "model-behavior",
    "maintenance",
    "documentation",
    "governance",
)
PR_KINDS = (
    "defect",
    "feature",
    "enhancement",
    "engineering",
    "experiment",
    "research",
    "maintenance",
    "documentation",
    "governance",
    "release",
)
PR_HEADINGS = (
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
BASE_ISSUE_IDS = {
    "outcome",
    "current_state",
    "desired_state",
    "scope",
    "out_of_scope",
    "affected_area",
    "affected_milestone",
    "dependencies",
    "evidence_required",
    "claim_boundary",
    "terminal_disposition",
}


def _strict_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8", errors="strict"))
    if not isinstance(value, dict):
        raise ValueError("top-level value must be a mapping")
    return value


def validate(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    forms = sorted((root / ".github" / "ISSUE_TEMPLATE").glob("[0-9][0-9]-*.yml"))
    if len(forms) != 10:
        errors.append(f"expected 10 issue forms, found {len(forms)}")
    seen_issue_kinds: set[str] = set()
    for path in forms:
        try:
            form = _strict_yaml(path)
        except Exception as exc:
            errors.append(f"{path.name}: unreadable: {exc}")
            continue
        if set(form) != {"name", "description", "title", "labels", "body"}:
            errors.append(f"{path.name}: top-level schema is not closed")
        body = form.get("body")
        if not isinstance(body, list):
            errors.append(f"{path.name}: body must be a list")
            continue
        marker_text = "\n".join(
            str(row.get("attributes", {}).get("value", ""))
            for row in body
            if isinstance(row, dict) and row.get("type") == "markdown"
        )
        match = re.search(r"ember-template: issue/([a-z-]+)@v1", marker_text)
        if not match:
            errors.append(f"{path.name}: missing issue marker")
            continue
        kind = match.group(1)
        seen_issue_kinds.add(kind)
        if f"kind:{kind}" not in form.get("labels", []):
            errors.append(f"{path.name}: kind label/marker mismatch")
        ids = {
            row.get("id")
            for row in body
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
        missing = sorted(BASE_ISSUE_IDS - ids)
        if missing:
            errors.append(f"{path.name}: missing base fields {','.join(missing)}")
        for row in body:
            if not isinstance(row, dict) or row.get("type") == "markdown":
                continue
            if row.get("type") not in {"input", "textarea", "dropdown", "checkboxes"}:
                errors.append(f"{path.name}: unsupported form type")
            if row.get("validations", {}).get("required") is not True:
                errors.append(f"{path.name}:{row.get('id')}: field must be required")
    if seen_issue_kinds != set(ISSUE_KINDS):
        errors.append("issue form kinds are incomplete or duplicated")

    config = _strict_yaml(root / ".github" / "ISSUE_TEMPLATE" / "config.yml")
    if config.get("blank_issues_enabled") is not False:
        errors.append("blank issues must be disabled")

    templates = sorted((root / ".github" / "PULL_REQUEST_TEMPLATE").glob("*.md"))
    if len(templates) != 10:
        errors.append(f"expected 10 PR templates, found {len(templates)}")
    seen_pr_kinds: set[str] = set()
    for path in templates:
        text = path.read_text(encoding="utf-8", errors="strict")
        match = re.search(r"ember-template: pr/([a-z-]+)@v1", text)
        if not match:
            errors.append(f"{path.name}: missing PR marker")
            continue
        seen_pr_kinds.add(match.group(1))
        for heading in PR_HEADINGS:
            if f"## {heading}" not in text:
                errors.append(f"{path.name}: missing heading {heading}")
    if seen_pr_kinds != set(PR_KINDS):
        errors.append("PR template kinds are incomplete or duplicated")

    for folder, expected in (("REVIEW_TEMPLATE", 6), ("COMMENT_TEMPLATE", 8)):
        paths = sorted((root / ".github" / folder).glob("*.md"))
        if len(paths) != expected:
            errors.append(f"{folder}: expected {expected} files, found {len(paths)}")
        if not (root / ".github" / folder / "README.md").is_file():
            errors.append(f"{folder}: README contract missing")
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "issue_form_count": len(forms),
        "pr_template_count": len(templates),
        "claim_boundary": "template structure only",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    result = validate(args.root.resolve())
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
