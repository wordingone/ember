# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Security and authority checks for the trusted close-sweep workflow."""

from pathlib import Path

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
WORKFLOW = ROOT / ".github" / "workflows" / "issue-close-sweep.yml"


def test_close_sweep_is_manual_trusted_master_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8", errors="strict")
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "pull_request_target:" not in text
    assert 'test "${GITHUB_REF}" = "refs/heads/master"' in text
    assert 'test "${api_master}" = "${GITHUB_SHA}"' in text
    assert "ref: ${{ github.sha }}" in text
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in text


def test_write_authority_is_confined_to_apply_job() -> None:
    text = WORKFLOW.read_text(encoding="utf-8", errors="strict")
    assert text.count("issues: write") == 1
    assert "permissions:\n  contents: read" in text
    assert (
        "apply:\n    needs: validate\n    permissions:\n      contents: read\n      issues: write"
        in text
    )
    assert (
        "validate:\n    permissions:\n      contents: read\n      issues: read" in text
    )


def test_apply_consumes_only_checked_in_content_addressed_authorization() -> None:
    text = WORKFLOW.read_text(encoding="utf-8", errors="strict")
    assert (
        text.count(
            '[[ "${AUTHORIZATION_PATH}" =~ ^state/issue-close-sweep/authorizations/[A-Za-z0-9._-]+\\.json$ ]]'
        )
        == 2
    )
    assert (
        text.count(
            '[[ "${packet}" =~ ^receipts/oldest-issue-disposition/approved/[A-Za-z0-9._-]+\\.json$ ]]'
        )
        == 2
    )
    assert "python -B -m scripts.issue_close_sweep validate" in text
    assert "python -B -m scripts.issue_close_sweep apply" in text
    assert "python -B scripts/issue_close_sweep.py" not in text
    assert '--expected-master-sha "${GITHUB_SHA}"' in text
    assert text.count("fetch-depth: 0") == 2
    assert (
        text.count('git merge-base --is-ancestor "${packet_master}" "${GITHUB_SHA}"')
        == 2
    )
    assert text.count("--packet-master-is-ancestor") == 2
    assert "gh issue comment" not in text
    assert "gh issue close" not in text
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in text
