# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from pathlib import Path


def test_generation_loop_breaks_on_declared_stop_token():
    source = (Path(__file__).parents[1] / "scripts" / "ember_restart_eval_raw_forward.py").read_text(encoding="utf-8")
    assert "if token == arguments.stop_token_id:" in source
    assert "generated.append(token)\n            if token == arguments.stop_token_id:\n                break" in source
