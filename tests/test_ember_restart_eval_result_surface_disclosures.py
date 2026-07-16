# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_result_surfaces_disclose_materialized_math500_and_nonadmissible_runtime_holds():
    model = (ROOT / "docs" / "ember-restart-model-card-results.md").read_text(encoding="utf-8")
    paper = (ROOT / "docs" / "ember-restart-paper-results.md").read_text(encoding="utf-8")
    demo = (ROOT / "docs" / "ember-restart-demo-results.md").read_text(encoding="utf-8")
    assert "2cd6fe926f1203a15d19f73c9a329cbe62b806fd" in model
    assert "FROZEN_MATH500_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS" in model
    assert "561724c0c751b31828bf8c2f5c7ffc20dc92deb804657c86d9f07a99e8100fd9" in model
    assert "BrowserGym source commit/tree/license is custody-bound" in model
    assert "SELFTEST_ONLY_FIXTURE_BROWSER_OUTCOMES" in paper
    assert "RUNTIME_HELD_UNPINNED_DEPENDENCY_AND_LIVE_TOOL_NETWORK" in paper
    assert "BrowserGym source is custody-bound" in demo
    assert "no local runtime or frozen MiniWoB task set" in demo

def test_result_surfaces_disclose_verified_step2_raw_forward_without_score_credit():
    model = (ROOT / "docs" / "ember-restart-model-card-results.md").read_text(encoding="utf-8")
    paper = (ROOT / "docs" / "ember-restart-paper-results.md").read_text(encoding="utf-8")
    demo = (ROOT / "docs" / "ember-restart-demo-results.md").read_text(encoding="utf-8")
    results = (ROOT / "docs" / "ember-restart-evaluation-results.md").read_text(encoding="utf-8")
    for surface in (model, paper, demo, results):
        assert "VERIFIED_NON_CLAIM_RAW_FORWARD" in surface
        assert "ember-step2-raw-forward/1" in surface
        assert "lev" in surface
        assert r"\n" not in surface
    assert "no benchmark score" in results
