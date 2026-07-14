# goal_id: EMBER-01
# workstream_id: EMBER-01A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Malformed-manifest regression tests for the restart evaluation contract."""

from test_ember_restart_eval_contract import manifest, run


def test_rejects_comparator_object_instead_of_list() -> None:
    value = manifest()
    value["comparators"] = {"policy": "comparison_only"}
    result = run(value)
    assert result.returncode == 2
    assert "COMPARATORS_NOT_LIST" in result.stderr
