# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from pathlib import Path


MANIFEST = Path(__file__).resolve().parents[1] / "manifests" / "ember-restart-eval-precheckpoint-v1.json"


def test_precheckpoint_manifest_names_current_v3_structural_input_without_capability_claim():
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert value["execution_status"] == "STRUCTURAL_INPUT_AVAILABLE_EXECUTION_AUTHORITY_REFUSES"
    target = value["target"]
    assert target["kind"] == "v3_shared_route_structural_checkpoint"
    assert target["checkpoint_sha256"] == "bf20f05018991eb611b0623edd50a00ec30639da2f8ccae646f6962f152a2a2b"
    assert target["model_config_sha256"] == "559959894dc603f9fbccbb091b3a084fef23b58d29add05efd14799a9a298ae0"
    assert target["capability_admission"] == "FORBIDDEN_UNTRAINED_SHARED_ROUTE"
