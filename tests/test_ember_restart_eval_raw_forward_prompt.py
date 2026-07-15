# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_raw_forward.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("raw_forward_prompt", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_loads_closed_owned_prompt_without_targets(tmp_path):
    prompt = tmp_path / "prompt.json"
    prompt.write_text(json.dumps({"schema_version": "ember-owned-inference-prompt-v1", "id": "row-1", "active_expert": "shared", "token_ids": [8, 9]}), encoding="utf-8")

    loaded = MODULE.load_owned_prompt(prompt)

    assert loaded == {"id": "row-1", "active_expert": "shared", "token_ids": [8, 9]}


def test_rejects_target_ids_in_owned_prompt_before_generation(tmp_path):
    prompt = tmp_path / "prompt.json"
    prompt.write_text(json.dumps({"schema_version": "ember-owned-inference-prompt-v1", "id": "row-1", "active_expert": "shared", "token_ids": [8, 9], "target_ids": [9, 10]}), encoding="utf-8")

    with pytest.raises(ValueError, match="target_ids"):
        MODULE.load_owned_prompt(prompt)
