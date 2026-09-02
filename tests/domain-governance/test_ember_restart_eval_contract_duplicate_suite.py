# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from test_ember_restart_eval_contract import manifest, run

def test_rejects_duplicate_frozen_suite_family():
    value = manifest()
    value["suites"].append(dict(value["suites"][0]))
    result = run(value)
    assert result.returncode == 2
    assert "DUPLICATE_FAMILIES: text" in result.stderr
