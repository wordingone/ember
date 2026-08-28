#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD tests for merge_gate.py — mechanical merge gating."""

import json
import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestMergeGatePassCases:
    """Passing merge cases for each class."""

    def test_pass_receipts_class(self):
        """Pass: receipts class PR with valid paths."""
        fixture_path = Path(__file__).parent / "fixtures/merge_gate/pr_pass_receipts.json"
        with open(fixture_path) as f:
            fixture = json.load(f)

        from merge_gate import check_merge_gate, ChecklistResult

        result = check_merge_gate(fixture, pr_class="receipts")

        assert result.passed, f"Should pass: {result.checklist}"
        assert len(result.checklist) == 7  # All 7 assertions
        assert all(item["status"] == "PASS" for item in result.checklist)
        assert result.merged_sha == "abc123def456"

    def test_pass_docs_class(self):
        """Pass: docs class PR with valid paths."""
        fixture_path = Path(__file__).parent / "fixtures/merge_gate/pr_pass_docs.json"
        with open(fixture_path) as f:
            fixture = json.load(f)

        from merge_gate import check_merge_gate

        result = check_merge_gate(fixture, pr_class="docs")

        assert result.passed, f"Should pass: {result.checklist}"
        assert all(item["status"] == "PASS" for item in result.checklist)

    def test_pass_code_class(self):
        """Pass: code class PR with valid paths."""
        fixture_path = Path(__file__).parent / "fixtures/merge_gate/pr_pass_code.json"
        with open(fixture_path) as f:
            fixture = json.load(f)

        from merge_gate import check_merge_gate

        result = check_merge_gate(fixture, pr_class="code")

        assert result.passed, f"Should pass: {result.checklist}"
        assert all(item["status"] == "PASS" for item in result.checklist)


class TestMergeGateAssertion1:
    """Test assertion 1: closingIssuesReferences count == 0."""

    def test_fail_closing_issues_references(self):
        """Fail: closingIssuesReferences count != 0."""
        fixture_path = Path(__file__).parent / "fixtures/merge_gate/pr_fail_closes_issues.json"
        with open(fixture_path) as f:
            fixture = json.load(f)

        from merge_gate import check_merge_gate

        result = check_merge_gate(fixture, pr_class="receipts")

        assert not result.passed
        assert result.checklist[0]["name"] == "closingIssuesReferences"
        assert result.checklist[0]["status"] == "FAIL"


class TestMergeGateAssertion2:
    """Test assertion 2: all CI checks SUCCESS or SKIPPED."""

    def test_fail_ci_check_failed(self):
        """Fail: CI check is FAILURE."""
        fixture_path = Path(__file__).parent / "fixtures/merge_gate/pr_fail_ci_failed.json"
        with open(fixture_path) as f:
            fixture = json.load(f)

        from merge_gate import check_merge_gate

        result = check_merge_gate(fixture, pr_class="receipts")

        assert not result.passed
        # Should fail at assertion 2 (CI checks)
        assert any(item["status"] == "FAIL" for item in result.checklist)


class TestMergeGateAssertion3:
    """Test assertion 3: mergeable == MERGEABLE."""

    def test_fail_not_mergeable(self):
        """Fail: mergeable is CONFLICTING."""
        fixture_path = Path(__file__).parent / "fixtures/merge_gate/pr_fail_not_mergeable.json"
        with open(fixture_path) as f:
            fixture = json.load(f)

        from merge_gate import check_merge_gate

        result = check_merge_gate(fixture, pr_class="receipts")

        assert not result.passed
        assert any(item["name"] == "mergeable" and item["status"] == "FAIL" for item in result.checklist)


class TestMergeGateAssertion4:
    """Test assertion 4: body contains refs #N line."""

    def test_fail_no_refs(self):
        """Fail: body has no refs #N."""
        fixture_path = Path(__file__).parent / "fixtures/merge_gate/pr_fail_no_refs.json"
        with open(fixture_path) as f:
            fixture = json.load(f)

        from merge_gate import check_merge_gate

        result = check_merge_gate(fixture, pr_class="docs")

        assert not result.passed
        assert any(item["name"] == "body_refs" and item["status"] == "FAIL" for item in result.checklist)


class TestMergeGateAssertion5:
    """Test assertion 5: diff paths match declared class allow-list."""

    def test_fail_receipts_class_wrong_paths(self):
        """Fail: receipts class but touches code files."""
        fixture_path = Path(__file__).parent / "fixtures/merge_gate/pr_fail_receipts_class_wrong_paths.json"
        with open(fixture_path) as f:
            fixture = json.load(f)

        from merge_gate import check_merge_gate

        result = check_merge_gate(fixture, pr_class="receipts")

        assert not result.passed
        assert any(item["name"] == "path_class_match" and item["status"] == "FAIL" for item in result.checklist)


class TestMergeGateAssertion6:
    """Test assertion 6: coordinator-class paths cause REFUSE."""

    def test_refuse_goal_md(self):
        """Refuse: docs/domains/governance/authority/GOAL.md touched."""
        fixture_path = Path(__file__).parent / "fixtures/merge_gate/pr_refuse_goal_md.json"
        with open(fixture_path) as f:
            fixture = json.load(f)

        from merge_gate import check_merge_gate

        result = check_merge_gate(fixture, pr_class="docs")

        assert not result.passed
        assert result.refuse_reason == "COORDINATOR-REQUIRED"
        assert any("docs/domains/governance/authority/GOAL.md" in str(item.get("details", "")) for item in result.checklist)

    def test_refuse_docs_spec(self):
        """Refuse: docs/spec/* touched."""
        fixture_path = Path(__file__).parent / "fixtures/merge_gate/pr_refuse_docs_spec.json"
        with open(fixture_path) as f:
            fixture = json.load(f)

        from merge_gate import check_merge_gate

        result = check_merge_gate(fixture, pr_class="docs")

        assert not result.passed
        assert result.refuse_reason == "COORDINATOR-REQUIRED"

    def test_refuse_cbase(self):
        """Refuse: scripts/cbase_* touched."""
        fixture_path = Path(__file__).parent / "fixtures/merge_gate/pr_refuse_cbase.json"
        with open(fixture_path) as f:
            fixture = json.load(f)

        from merge_gate import check_merge_gate

        result = check_merge_gate(fixture, pr_class="code")

        assert not result.passed
        assert result.refuse_reason == "COORDINATOR-REQUIRED"


class TestMergeGateDryRun:
    """Test --dry-run mode."""

    def test_dry_run_no_merge(self):
        """--dry-run prints checklist, no merge."""
        fixture_path = Path(__file__).parent / "fixtures/merge_gate/pr_pass_receipts.json"
        with open(fixture_path) as f:
            fixture = json.load(f)

        from merge_gate import check_merge_gate, format_checklist_output

        result = check_merge_gate(fixture, pr_class="receipts")
        output = format_checklist_output(result)

        # Should produce readable checklist
        assert "PASS" in output
        # Verify checklist format is correct
        assert "Checklist:" in output
        assert "Merged SHA:" in output


class TestMergeGateReceiptLog:
    """Test receipt logging."""

    def test_receipt_log_format(self):
        """Receipt row format: {pr, class, checklist, merged_sha, ts}."""
        from merge_gate import format_receipt_row
        from datetime import datetime

        receipt = format_receipt_row(
            pr_number=1,
            pr_class="receipts",
            checklist=[
                {"name": "closingIssuesReferences", "status": "PASS"},
                {"name": "ci_checks", "status": "PASS"},
                {"name": "mergeable", "status": "PASS"},
                {"name": "body_refs", "status": "PASS"},
                {"name": "path_class_match", "status": "PASS"},
                {"name": "coordinator_paths", "status": "PASS"},
                {"name": "merge", "status": "PASS"}
            ],
            merged_sha="abc123def456"
        )

        # Parse as JSON
        row = json.loads(receipt)
        assert row["pr"] == 1
        assert row["class"] == "receipts"
        assert row["merged_sha"] == "abc123def456"
        assert "ts" in row
        assert "checklist" in row


class TestMergeGatePathClassification:
    """Test path classification for each class."""

    def test_receipts_class_allows_receipts_paths(self):
        """receipts class allows receipts/** and scripts/ember_totality/receipts-*/**."""
        from merge_gate import verify_paths_match_class

        paths = [
            "receipts/merge-gate/test.jsonl",
            "scripts/ember_totality/receipts-log/entry.json"
        ]

        assert verify_paths_match_class(paths, "receipts")

    def test_receipts_class_rejects_code_paths(self):
        """receipts class rejects code paths."""
        from merge_gate import verify_paths_match_class

        paths = [
            "receipts/merge-gate/test.jsonl",
            "scripts/runner.py"
        ]

        assert not verify_paths_match_class(paths, "receipts")

    def test_docs_class_allows_doc_paths(self):
        """docs class allows docs/**, README.md, docs/authority/GOVERNANCE.md, .github/**."""
        from merge_gate import verify_paths_match_class

        paths = [
            "docs/api/reference.md",
            "README.md",
            "docs/authority/GOVERNANCE.md",
            ".github/workflows/test.yml"
        ]

        assert verify_paths_match_class(paths, "docs")

    def test_docs_class_rejects_code_paths(self):
        """docs class rejects code paths."""
        from merge_gate import verify_paths_match_class

        paths = [
            "docs/api/reference.md",
            "scripts/runner.py"
        ]

        assert not verify_paths_match_class(paths, "docs")

    def test_code_class_allows_any_non_coordinator(self):
        """code class allows anything not coordinator-class."""
        from merge_gate import verify_paths_match_class

        paths = [
            "scripts/runner.py",
            "tests/test_runner.py",
            "src/main.py"
        ]

        assert verify_paths_match_class(paths, "code")

    def test_coordinator_paths_always_refuse(self):
        """Coordinator-class paths always refuse regardless of class."""
        from merge_gate import has_coordinator_paths

        coordinator_paths = [
            "docs/domains/governance/authority/GOAL.md",
            "docs/authority/INVARIANT.md",
            "docs/spec/inference.md",
            "scripts/cbase_bootstrap.py",
            "scripts/ember_totality/some_runner.py",
            "tools/repo-guard.sh",
            ".claude/CLAUDE.md"
        ]

        for path in coordinator_paths:
            assert has_coordinator_paths([path]), f"{path} should be coordinator-class"

    def test_coordinator_paths_excluded(self):
        """Non-coordinator paths are allowed."""
        from merge_gate import has_coordinator_paths

        allowed_paths = [
            "scripts/ember_totality/receipts-log/entry.json",
            "receipts/merge-gate/test.jsonl",
            "src/main.py",
            "README.md"
        ]

        for path in allowed_paths:
            assert not has_coordinator_paths([path]), f"{path} should NOT be coordinator-class"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
