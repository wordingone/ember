# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_spider.py"


def load_module():
    spec = importlib.util.spec_from_file_location("spider_prediction_contract_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unbound_central_json_list_predictions_are_refused() -> None:
    module = load_module()
    rows = module.build_frozen_rows(
        [{"db_id": "db", "question": "one", "query": "select 1"}],
        [("select 1", "db")],
    )
    with pytest.raises((TypeError, ValueError)):
        module.validate_prediction_envelope(
            [{"index": 0, "sql": "select 1"}], rows, "1" * 64
        )


def test_prediction_envelope_is_bound_to_inference_receipt() -> None:
    module = load_module()
    rows = module.build_frozen_rows(
        [{"db_id": "db", "question": "one", "query": "select 1"}],
        [("select 1", "db")],
    )
    envelope = {
        "schema_version": "ember-spider-prediction-envelope-v1",
        "inference_receipt_raw_sha256": "2" * 64,
        "rows": [{"row_id": rows[0]["row_id"], "sql": "select 1"}],
    }
    with pytest.raises(ValueError, match="inference"):
        module.validate_prediction_envelope(envelope, rows, "1" * 64)
