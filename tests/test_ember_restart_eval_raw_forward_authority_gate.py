# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression coverage for the committed, real execution-authority gate."""
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


def _step2_identities():
    return {
        "model_source_sha256": "5609032c21aa6020ddc7a492ab5817a86d425571ae81a46efe951c784e70c5bf",
        "model_config_sha256": "559959894dc603f9fbccbb091b3a084fef23b58d29add05efd14799a9a298ae0",
        "tokenizer_sha256": "2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97",
        "checkpoint_manifest_sha256": "bf20f05018991eb611b0623edd50a00ec30639da2f8ccae646f6962f152a2a2b",
        "parameter_receipt_sha256": "f3cd8773c9db9e83a1f3566ecb7c02d33be185dde619ea7b4e4c7050bd44e042",
        "parameter_counter_sha256": "6bb505470775a5b36c764a96a7b1e3475b4eaecce339b594efbaf9e16e8ce873",
        "trusted_verifier_registry_sha256": "845ae1cdc34b4df29c4428cda2f2cee8d045a1db9df831e99e4a6f4c1960309e",
    }


def test_current_registry_authorizes_only_the_exact_measured_step2_tuple():
    module = _load_raw_forward()
    identities = _step2_identities()
    expected = {
        **identities,
        "inference_implementation_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
    }
    assert module.require_execution_authority(object(), identities) == expected

    wrong_receipt = dict(identities)
    wrong_receipt["parameter_receipt_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="does not authorize"):
        module.require_execution_authority(object(), wrong_receipt)


def test_authority_rejects_correct_tuple_when_registry_disposition_is_not_authorized(tmp_path):
    module = _load_raw_forward()
    registry = json.loads(module.EXECUTION_AUTHORITY.read_text(encoding="utf-8"))
    registry["disposition"] = "NO_EXECUTION_AUTHORITY_PINNED"
    temporary = tmp_path / "authority.json"
    temporary.write_text(json.dumps(registry), encoding="utf-8")
    module.EXECUTION_AUTHORITY = temporary

    with pytest.raises(ValueError, match="execution authority disposition"):
        module.require_execution_authority(object(), _step2_identities())


def test_authority_registry_binds_the_canonical_git_blob_and_step2_tuple():
    blob = subprocess.run(["git", "show", "HEAD:scripts/ember_restart_eval_raw_forward.py"], cwd=ROOT, check=True, capture_output=True).stdout
    registry = json.loads((ROOT / "manifests" / "ember-restart-execution-authorities-v1.json").read_text(encoding="utf-8"))

    assert len(blob) == 37_075
    assert hashlib.sha256(blob).hexdigest() == "3f8c25e09349197ac02af26a13893e14036a758aa626f45b0457d81602810a45"
    assert registry["disposition"] == "EXACT_OWNED_SHARED_ROUTE_EXECUTION_AUTHORIZED"
    assert registry["authorities"] == [{
        **_step2_identities(),
        "inference_implementation_sha256": hashlib.sha256(blob).hexdigest(),
    }]
    assert hashlib.sha256(SCRIPT.read_bytes()).hexdigest() == registry["authorities"][0]["inference_implementation_sha256"]