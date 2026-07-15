# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_result_surfaces_disclose_materialized_math500_and_nonadmissible_runtime_holds():
    model = (ROOT / "docs" / "ember-restart-model-card-results.md").read_text(encoding="utf-8")
    paper = (ROOT / "docs" / "ember-restart-paper-results.md").read_text(encoding="utf-8")
    assert "2cd6fe926f1203a15d19f73c9a329cbe62b806fd" in model
    assert "FROZEN_MATH500_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS" in model
    assert "SELFTEST_ONLY_FIXTURE_BROWSER_OUTCOMES" in paper
    assert "RUNTIME_HELD_UNPINNED_DEPENDENCY_AND_LIVE_TOOL_NETWORK" in paper