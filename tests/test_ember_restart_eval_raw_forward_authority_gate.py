# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression coverage for the committed, real execution-authority gate."""
import argparse
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ember_restart_eval_raw_forward.py"


def _load_raw_forward():
    sys.path.insert(0, str(SCRIPT.parent))
    specification = importlib.util.spec_from_file_location("raw_forward_authority_gate", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_committed_authority_accepts_the_current_public_forward_dependency_bytes():
    """No monkeypatch: this is the exact gate used before model loading."""
    module = _load_raw_forward()
    arguments = argparse.Namespace(
        model_source=ROOT / "tools" / "ember-restart-3b" / "model.py",
        model_config=ROOT / "configs" / "ember-restart-3b.json",
        tokenizer=ROOT / "tokenizer" / "tokenizer.json",
    )

    # RED until a reviewed successor records the public PR #839 model/config
    # bytes and this file's current implementation hash in the registry.
    module.require_execution_authority(arguments)