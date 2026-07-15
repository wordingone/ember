# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_materialized_multimodal_and_audio_custody_names_current_prediction_boundary():
    for name in (
        "ember-restart-mmmu-validation-custody-v1.json",
        "ember-restart-audiobench-custody-v1.json",
    ):
        custody = json.loads((ROOT / "manifests" / name).read_text(encoding="utf-8"))

        assert custody["admission"] == "NOT_EXECUTABLE_UNTRAINED_SPECIALIST_NO_CHECKPOINT_BOUND_PREDICTIONS"
        assert custody["target_training_access"] == "FORBIDDEN"


def test_spider_retains_its_separate_frozen_gold_and_database_boundary():
    custody = json.loads((ROOT / "manifests" / "ember-restart-spider-custody-v1.json").read_text(encoding="utf-8"))

    assert custody["admission"] == "NOT_EXECUTABLE_NO_FROZEN_GOLD_AND_DATABASE"
