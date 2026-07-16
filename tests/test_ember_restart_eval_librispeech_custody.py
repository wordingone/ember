# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from pathlib import Path


MANIFEST = Path(__file__).resolve().parents[1] / "manifests" / "ember-restart-librispeech-clean-test-custody-v1.json"


def test_librispeech_clean_test_custody_binds_pinned_external_references_without_capability_credit():
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert value["target_execution_permitted"] is False
    assert value["target_training_access"] == "FORBIDDEN"
    assert value["materialization"] == {
        "upstream_revision": "71cacbfb7e2354c4226d01e70d77d5fca3d04ba1",
        "artifact_sha256": "249113534ffcaf6fa814d01b297e083a18efb81ac75e9ff139f180514cd26fd9",
        "runner_receipt_sha256": "1b234f190a0adf3b5db89154b9f431e00d8b3fb39997fba633d44df96bd4b366",
        "split_sha256": "7113aa4c3cf963fb54697145719a7725f984c8836d1c494a554cbb9f1a017df0",
        "claim_status": "FROZEN_LIBRISPEECH_CLEAN_TEST_REFERENCES_NO_CHECKPOINT_BOUND_PREDICTIONS",
    }