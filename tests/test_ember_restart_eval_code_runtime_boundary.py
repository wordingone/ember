# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from pathlib import Path


MANIFEST = Path(__file__).resolve().parents[1] / "manifests" / "ember-restart-eval-code-math-custody-v1.json"


def test_evalplus_assets_are_held_without_a_digest_pinned_execution_sandbox():
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert value["target_execution_permitted"] is False
    assert value["execution_runtime_disposition"] == "NO_LOCAL_DIGEST_PINNED_CODE_SANDBOX"
    assert value["unsafe_runtime_exclusion"] == "MUTABLE_EVALPLUS_DOCKER_LATEST_FORBIDDEN"
    assert value["mathematics"] == {"asset_disposition": "NO_LOCAL_PINNED_FROZEN_MATHEMATICS_TASKS_OR_HARNESS", "target_execution_permitted": False}
