# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_spider.py"


def load_module():
    spec = importlib.util.spec_from_file_location("spider_legacy_cli_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "legacy_arguments",
    [
        ["--spider-root", "legacy"],
        ["--predictions", "legacy.json"],
        ["--database-dir", "legacy-database"],
    ],
)
def test_legacy_aggregate_cli_is_refused(legacy_arguments: list[str]) -> None:
    module = load_module()
    with pytest.raises(SystemExit):
        module.main(legacy_arguments)


def test_terminal_receipt_has_no_criterion_result() -> None:
    module = load_module()
    row = {
        "row_id": "1" * 64,
        "db_id": "db",
        "prediction_sha256": "2" * 64,
        "gold_sha256": "3" * 64,
        "exact_correct": False,
        "execution_correct": False,
        "execution_class": "SYNTAX_ERROR",
        "duration_ms": 1,
        "_owned_cleanup_verified": True,
        "_scorer_stdout": "",
        "_scorer_stderr": "",
    }
    manifest = {key: "0" * 64 for key in module.MANIFEST_KEYS}
    manifest["per_row_timeout_seconds"] = 30
    receipt = module.build_terminal_receipt(manifest, "4" * 64, [row], "5" * 64)
    assert receipt["result"] == "COVERED"
    assert "criterion_result" not in receipt
