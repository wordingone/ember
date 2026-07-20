# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPO_ROOT / "docs" / "ember-restart" / "integration-contract-v1.md"


def test_contract_names_current_step2_truth_and_fail_closed_boundary() -> None:
    text = CONTRACT.read_text(encoding="utf-8")

    assert "BF20F05018991EB611B0623EDD50A00EC30639DA2F8CCAE646F6962F152A2A2B" in text
    assert "2,048 observed text tokens" in text
    assert "1,020,589,568 active parameters" in text
    assert "shared route only" in text
    assert "PREPARED_NOT_EXECUTABLE_AWAITING_PROMPT_AND_SAME_BYTE_RUNTIME_BINDING" in text
    assert "not sufficiently pretrained" in text
    assert "not capability-admitted" in text


def test_contract_next_execution_requires_runtime_and_receipt_closure_before_gpu() -> None:
    text = CONTRACT.read_text(encoding="utf-8")

    assert "exact step-2 checkpoint is both parent and immutable root" in text
    assert "same-byte hardened-counter realization receipt" in text
    assert "same-open-handle required-shard loading" in text
    assert "No GPU dispatch is authorized by this contract state" in text
