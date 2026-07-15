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


def test_precheckpoint_manifest_keeps_files_family_in_required_matrix():
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert "files" in value["required_new_families"]

def test_precheckpoint_manifest_pins_required_comparators_without_authorizing_execution():
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert value["comparators"] == [
        {
            "model_id": "Qwen/Qwen2.5-3B",
            "revision": "3aab1f1954e9cc14eb9509a215f9e5ca08227a9b",
            "size_class": "open_3b",
            "role": "comparison_only",
            "license_status": "UNRESOLVED_CARD_METADATA",
            "execution_status": "PREFLIGHT_ONLY_NO_LICENSE_EVIDENCE_OR_FROZEN_PROTOCOL",
        },
        {
            "model_id": "google/gemma-3-27b-it",
            "revision": "005ad3404e59d6023443cb575daa05336842228a",
            "size_class": "open_27b_or_31b",
            "role": "comparison_only",
            "license_status": "UNRESOLVED_CARD_METADATA",
            "execution_status": "PREFLIGHT_ONLY_NO_LICENSE_EVIDENCE_OR_FROZEN_PROTOCOL",
        },
    ]
