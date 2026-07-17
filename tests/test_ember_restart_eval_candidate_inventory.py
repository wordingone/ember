# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Keep the public candidate inventory explicit for every required family."""
from pathlib import Path


DOC = Path(__file__).resolve().parents[1] / "docs" / "ember-restart-eval-candidates-v1.md"


def test_candidate_inventory_has_explicit_terminal_files_and_tools_rows():
    text = DOC.read_text(encoding="utf-8")
    assert "| Terminal/file work |" not in text
    expected = {
        "Terminal": "harbor-framework/terminal-bench-2",
        "Files": "SWE-bench/SWE-bench_Lite",
        "Structured tools": "ShishirPatil/gorilla",
    }
    for family, source in expected.items():
        rows = [line for line in text.splitlines() if line.startswith(f"| {family} |")]
        assert len(rows) == 1
        assert source in rows[0]


def test_candidate_inventory_preserves_honest_unavailable_boundaries():
    text = DOC.read_text(encoding="utf-8")
    assert "digest-pinned task images" in text
    assert "offline repository sandbox" in text
    assert "live dependency/tool network" in text
