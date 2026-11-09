# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The custody directory for archived-ancestor attestation must reach the governed worker (lead ruling 82046 (c)).

H44 v2 trained 33 minutes and died at cia_hour.verify_checkpoint_restore, whose bare chain reopen needs the variable in the
WORKER's environment; the preparer's class-kill refusal would otherwise reject the exported name outright."""
import importlib.util
import os
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "src/ember/infrastructure/tools/ember-restart-3b/prepare_hour.py"
NAME = "EMBER_CIA_ANCESTOR_CUSTODY_DIR"


def load():
    spec = importlib.util.spec_from_file_location("prepare_hour_custody_env_under_test", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clean_ember_environment():
    return {key: value for key, value in os.environ.items() if not key.startswith("EMBER_")}


def test_the_custody_variable_is_passed_through_to_the_manifest_env(tmp_path):
    module = load()
    env = {}
    with mock.patch.dict(os.environ, {**clean_ember_environment(), NAME: str(tmp_path)}, clear=True):
        module.apply_arm_env_allowlist(env)
    assert env == {NAME: str(tmp_path)}


def test_the_manifest_env_carries_nothing_when_the_variable_is_unset():
    module = load()
    env = {}
    with mock.patch.dict(os.environ, clean_ember_environment(), clear=True):
        module.apply_arm_env_allowlist(env)
    assert NAME not in env


def test_an_unlisted_sibling_name_is_still_refused(tmp_path):
    module = load()
    with mock.patch.dict(os.environ, {**clean_ember_environment(), NAME + "_TYPO": str(tmp_path)}, clear=True):
        with pytest.raises(ValueError, match="unlisted EMBER_"):
            module.apply_arm_env_allowlist({})
