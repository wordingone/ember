# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import copy
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ember_restart_eval_audiobench_bound.py"


def load_module():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("audiobench_protocol_identity", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_protocol_identity_changes_when_frozen_custody_changes():
    module = load_module()
    custody = json.loads((ROOT / "manifests" / "ember-restart-audiobench-custody-v1.json").read_text(encoding="utf-8"))
    original = module._protocol_sha256(custody)
    for field, replacement in (("upstream_tree_git_sha1", "0" * 40), ("license_sha256", "1" * 64), ("scoring_adapter", {**custody["scoring_adapter"], "sha256": "2" * 64})):
        mutated = copy.deepcopy(custody)
        mutated[field] = replacement
        assert module._protocol_sha256(mutated) != original


def test_frozen_custody_rejects_altered_tree_even_when_suite_identity_is_unchanged():
    module = load_module()
    custody = json.loads((ROOT / "manifests" / "ember-restart-audiobench-custody-v1.json").read_text(encoding="utf-8"))
    custody["upstream_tree_git_sha1"] = "0" * 40
    custody["protocol_sha256"] = module._protocol_sha256(custody)
    try:
        module._frozen_custody(json.dumps(custody).encode("utf-8"))
    except ValueError as exc:
        assert "frozen AudioBench custody" in str(exc)
    else:
        raise AssertionError("altered AudioBench tree must fail closed")

def test_frozen_custody_rejects_non_object_json():
    module = load_module()
    try:
        module._frozen_custody(b"[]")
    except ValueError as exc:
        assert "frozen AudioBench custody" in str(exc)
    else:
        raise AssertionError("non-object custody must fail closed")