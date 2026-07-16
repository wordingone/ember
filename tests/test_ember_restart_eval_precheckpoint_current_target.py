# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
from pathlib import Path


MANIFEST = Path(__file__).resolve().parents[1] / "manifests" / "ember-restart-eval-precheckpoint-v1.json"


def test_precheckpoint_manifest_names_current_v3_structural_input_without_capability_claim():
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert value["execution_status"] == "STRUCTURAL_INPUT_AVAILABLE_VERIFIED_NON_CLAIM_RAW_FORWARD"
    assert value["verified_raw_forward"] == {"result": "VERIFIED_NON_CLAIM_RAW_FORWARD", "receipt_path": "manifests/ember-restart-eval-first-shared-raw-forward-v1.json", "receipt_sha256": "be57f521903967fbca4315684c7b37223380b22d3cd8d254e7e5ee83e4c1722d"}
    target = value["target"]
    assert target["kind"] == "v3_shared_route_structural_checkpoint"
    assert target["checkpoint_sha256"] == "bf20f05018991eb611b0623edd50a00ec30639da2f8ccae646f6962f152a2a2b"
    assert target["model_config_sha256"] == "559959894dc603f9fbccbb091b3a084fef23b58d29add05efd14799a9a298ae0"
    assert target["capability_admission"] == "FORBIDDEN_UNTRAINED_SHARED_ROUTE"


def test_precheckpoint_manifest_keeps_files_family_in_required_matrix():
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert "files" in value["required_new_families"]

def test_precheckpoint_manifest_binds_every_new_family_to_a_custody_or_protocol_artifact():
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bindings = value["frozen_family_artifacts"]
    assert set(bindings) == {"text", "reasoning", "code", "mathematics", "terminal", "sql", "files", "browser_ui", "image", "audio", "structured_tools"}
    for family, artifact in bindings.items():
        assert isinstance(family, str) and family
        assert set(artifact) == {"path", "sha256"}
        assert isinstance(artifact["path"], str) and artifact["path"].startswith("manifests/")
        assert isinstance(artifact["sha256"], str) and len(artifact["sha256"]) == 64
        assert hashlib.sha256((MANIFEST.parents[1] / artifact["path"]).read_bytes()).hexdigest() == artifact["sha256"]

def test_precheckpoint_manifest_binds_materialized_text_reasoning_code_and_mathematics_custody():
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bindings = value["frozen_family_artifacts"]
    assert {key: bindings[key]["path"] for key in ("text", "reasoning", "code", "mathematics")} == {
        "text": "manifests/ember-restart-gsm8k-custody-v1.json",
        "reasoning": "manifests/ember-restart-mmlu-pro-custody-v1.json",
        "code": "manifests/ember-restart-eval-code-math-custody-v1.json",
        "mathematics": "manifests/ember-restart-eval-code-math-custody-v1.json",
    }


def test_precheckpoint_manifest_pins_required_comparators_without_authorizing_execution():
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert value["comparators"] == [
        {
            "model_id": "Qwen/Qwen2.5-3B",
            "revision": "3aab1f1954e9cc14eb9509a215f9e5ca08227a9b",
            "size_class": "open_3b",
            "role": "comparison_only",
            "license_status": "DECLARED_QWEN_RESEARCH_RESTRICTED",
            "license_evidence": {"card_license": "other", "license_name": "qwen-research"},
            "execution_status": "PREFLIGHT_ONLY_RESTRICTED_LICENSE_AND_NO_FROZEN_PROTOCOL",
        },
        {
            "model_id": "google/gemma-3-27b-it",
            "revision": "005ad3404e59d6023443cb575daa05336842228a",
            "size_class": "open_27b_or_31b",
            "role": "comparison_only",
            "license_status": "DECLARED_GEMMA_GATED_LICENSE",
            "license_evidence": {"card_license": "gemma", "access": "gated_license_acceptance_required"},
            "execution_status": "PREFLIGHT_ONLY_GATED_LICENSE_AND_NO_FROZEN_PROTOCOL",
        },
    ]
