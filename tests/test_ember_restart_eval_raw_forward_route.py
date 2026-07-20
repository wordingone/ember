# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_raw_forward.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("raw_forward_route", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_accepts_shared_route_when_it_matches_the_verified_manifest():
    assert MODULE.require_active_route({"active_expert_ids": ["shared"]}, "shared") == "shared"


def test_rejects_route_substitution_before_loading_any_shard():
    with pytest.raises(ValueError, match="active route does not match verified checkpoint manifest"):
        MODULE.require_active_route({"active_expert_ids": ["shared"]}, "tool")
