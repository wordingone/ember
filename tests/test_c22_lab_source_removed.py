# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""C22: the Ember Lab source is not carried in this repository."""

from __future__ import annotations

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LAB_DIR = "runtime/ember-lab"


def test_no_lab_source_is_tracked_or_present() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", LAB_DIR],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    assert [path for path in tracked if path] == []
    assert not (ROOT / LAB_DIR).exists()


def test_no_workflow_builds_the_removed_lab() -> None:
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        assert "working-directory: runtime/ember-lab" not in text, workflow.name
        assert "cargo " not in text, workflow.name


def test_docs_name_the_private_home_of_the_lab_source() -> None:
    docs = (ROOT / "scripts" / "docs_information_system.py").read_text(encoding="utf-8")
    assert 'MOVED_PRIVATE_PREFIXES = {"runtime/ember-lab": "wordingone/ember-lab"}' in docs
