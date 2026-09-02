# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed-shape checks for the manual read-only task-015 workflow."""

from __future__ import annotations

from pathlib import Path

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
WORKFLOW = ROOT / ".github" / "workflows" / "oldest-issue-disposition-capture.yml"


def test_workflow_is_manual_master_only_and_read_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8", errors="strict")
    assert "workflow_dispatch:" in text
    assert "push:" not in text
    assert "pull_request:" not in text
    assert 'test "${GITHUB_REF}" = "refs/heads/master"' in text
    assert 'test "${api_master}" = "${GITHUB_SHA}"' in text
    assert 'test "${final_master}" = "${GITHUB_SHA}"' in text
    assert "contents: read" in text
    assert "issues: read" in text
    assert "issues: write" not in text
    assert "gh issue close" not in text
    assert "gh issue edit" not in text
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in text


def test_workflow_captures_complete_pre_and_post_populations() -> None:
    text = WORKFLOW.read_text(encoding="utf-8", errors="strict")
    assert text.count("gh api --paginate --slurp") == 4
    assert "issues_pre.json" in text
    assert "issues_post.json" in text
    assert "comments-${number}-pre.json" in text
    assert "comments-${number}-post.json" in text
    assert 'test "${#issue_numbers[@]}" -ge 1' in text
    assert 'test "${#issue_numbers[@]}" -le 20' in text
    assert 'select(has("pull_request") | not)' in text
    assert "sort_by(.created_at, .number)" in text


def test_workflow_runs_the_real_capture_decision_and_packet_consumers() -> None:
    text = WORKFLOW.read_text(encoding="utf-8", errors="strict")
    assert "scripts/build_oldest_issue_raw_bundle.py" in text
    assert '--raw-bundle "${raw}/ember-oldest-issue-disposition-015-raw-sources-v1.json"' in text
    assert "scripts/oldest_issue_disposition.py capture" in text
    assert "scripts/build_oldest_issue_decisions.py" in text
    assert "scripts/oldest_issue_disposition.py build" in text
    assert "scripts/oldest_issue_disposition.py verify" in text
    assert "scripts/verify_oldest_issue_disposition_packet.py" in text
    assert '--expected-master-sha "${GITHUB_SHA}"' in text
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in text
    assert "SHA256SUMS" in text


def test_raw_capture_is_uploaded_even_if_semantic_classification_fails() -> None:
    text = WORKFLOW.read_text(encoding="utf-8", errors="strict")
    raw_upload = text.index("name: Upload immutable raw capture")
    decisions = text.index("scripts/build_oldest_issue_decisions.py")
    assert raw_upload < decisions
    assert "if: ${{ always() }}" in text[raw_upload:decisions]
    assert "oldest-issue-raw-${{ github.run_id }}-${{ github.sha }}" in text

def test_workflow_consumes_explicit_content_bound_cursor() -> None:
    text = WORKFLOW.read_text(encoding="utf-8", errors="strict")
    assert "after_created_at:" in text
    assert "after_issue_number:" in text
    assert "AFTER_CREATED_AT: ${{ inputs.after_created_at }}" in text
    assert "AFTER_ISSUE_NUMBER: ${{ inputs.after_issue_number }}" in text
    assert "cursor fields must be initial" in text
    assert "--after-created-at" in text
    assert "--after-issue-number" in text
    assert 'test "${#issue_numbers[@]}" -ge 1' in text
    assert 'test "${#issue_numbers[@]}" -le 20' in text
