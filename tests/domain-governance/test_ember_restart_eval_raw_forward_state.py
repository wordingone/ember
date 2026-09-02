# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import sys
import importlib.util
from pathlib import Path

import pytest
import torch

SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_raw_forward.py"
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
SPEC = importlib.util.spec_from_file_location("raw_forward", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_rejects_unexpected_shared_key_before_load():
    expected = {"weight": torch.zeros(2, 2)}
    with pytest.raises(ValueError, match="unexpected"):
        MODULE.validate_state_map({"weight": torch.zeros(2, 2), "forged": torch.zeros(1)}, expected, "shared")


def test_rejects_shape_drift_before_load():
    expected = {"weight": torch.zeros(2, 2)}
    with pytest.raises(ValueError, match="shape"):
        MODULE.validate_state_map({"weight": torch.zeros(1, 2)}, expected, "shared")
