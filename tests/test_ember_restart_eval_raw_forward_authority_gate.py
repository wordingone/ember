# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression coverage for the committed, real execution-authority gate."""
import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ember_restart_eval_raw_forward.py"


def _load_raw_forward():
    sys.path.insert(0, str(SCRIPT.parent))
    specification = importlib.util.spec_from_file_location("raw_forward_authority_gate", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_current_registry_rejects_exact_tuple_while_runtime_same_byte_binding_is_unimplemented():
    """The real gate must fail closed until runtime consumes authorized bytes once."""
    module = _load_raw_forward()
    arguments = argparse.Namespace(
        model_source=ROOT / "tools" / "ember-restart-3b" / "model.py",
        model_config=ROOT / "configs" / "ember-restart-3b.json",
        tokenizer=ROOT / "tokenizer" / "tokenizer.json",
    )

    with pytest.raises(ValueError, match="execution authority disposition"):
        module.require_execution_authority(arguments)

def test_authority_rejects_correct_tuple_when_registry_disposition_is_not_authorized(tmp_path):
    module = _load_raw_forward()
    arguments = argparse.Namespace(
        model_source=ROOT / "tools" / "ember-restart-3b" / "model.py",
        model_config=ROOT / "configs" / "ember-restart-3b.json",
        tokenizer=ROOT / "tokenizer" / "tokenizer.json",
    )
    registry = json.loads(module.EXECUTION_AUTHORITY.read_text(encoding="utf-8"))
    registry["disposition"] = "NO_EXECUTION_AUTHORITY_PINNED"
    temporary = tmp_path / "authority.json"
    temporary.write_text(json.dumps(registry), encoding="utf-8")
    module.EXECUTION_AUTHORITY = temporary

    with pytest.raises(ValueError, match="execution authority disposition"):
        module.require_execution_authority(arguments)

def test_authority_registry_binds_the_canonical_git_blob_bytes():
    blob = subprocess.run(["git", "show", "HEAD:scripts/ember_restart_eval_raw_forward.py"], cwd=ROOT, check=True, capture_output=True).stdout
    registry = json.loads((ROOT / "manifests" / "ember-restart-execution-authorities-v1.json").read_text(encoding="utf-8"))

    assert len(blob) == 13_398
    assert hashlib.sha256(blob).hexdigest() == "1e7f6bbdb19bd2f98285d1cbeb0e53ef5449e537e1b7d67fec29c1df1612a59e"
    assert registry["disposition"] == "PREPARED_NOT_EXECUTABLE_AWAITING_PROMPT_AND_SAME_BYTE_RUNTIME_BINDING"
    assert registry["authorities"] == [{
        "model_source_sha256": "5609032c21aa6020ddc7a492ab5817a86d425571ae81a46efe951c784e70c5bf",
        "model_config_sha256": "559959894dc603f9fbccbb091b3a084fef23b58d29add05efd14799a9a298ae0",
        "tokenizer_sha256": "2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97",
        "inference_implementation_sha256": hashlib.sha256(blob).hexdigest(),
    }]