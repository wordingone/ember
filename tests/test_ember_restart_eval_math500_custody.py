# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "manifests" / "ember-restart-eval-code-math-custody-v1.json"


def test_math500_exact_mit_revision_and_frozen_test_split_are_custody_bound():
    custody = json.loads(MANIFEST.read_text(encoding="utf-8"))
    math = custody["mathematics"]
    assert math["asset_disposition"] == "FROZEN_MATH500_TASKS_AND_DETERMINISTIC_SCORER_NO_CHECKPOINT_BOUND_PREDICTIONS"
    assert math["frozen_math500"] == {
        "revision": "2cd6fe926f1203a15d19f73c9a329cbe62b806fd",
        "license": "MIT",
        "license_sha256": "561724c0c751b31828bf8c2f5c7ffc20dc92deb804657c86d9f07a99e8100fd9",
        "rows": 500,
        "split_sha256": "35dc41080a3680858b27fa7e0533d2d547825316fc5daf e5d316f4ccc5a06132".replace(" ", ""),
        "artifact_sha256": "32a13d5fc494bb5ff7a83522cce14941c00b98a7e861f665f7ac2cf4a8cee380",
        "runner_receipt_sha256": "2453fac63dbeaba4d68e259e7f12e6bca802ab34899447bfb35d846dbdad28c6",
        "claim_status": "FROZEN_MATH500_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS",
    }
    assert math["target_execution_permitted"] is False
