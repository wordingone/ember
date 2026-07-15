# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build owned arithmetic reasoning and typed-tool records with executed receipts."""

from __future__ import annotations

from typing import Any

from verify_capability_record import expected_receipt


def _episode(index: int) -> tuple[int, int, int]:
    left = 1 + (index * 17) % 997
    right = 1 + (index * 31) % 991
    return left, right, left + right


def build_records(tokenizer: Any, *, count: int, capability: str) -> list[dict[str, object]]:
    """Build receipt-bound owned arithmetic episodes for exactly one specialist family."""
    if capability not in {"reasoning", "tool"}:
        raise ValueError("capability must be reasoning or tool")
    if not isinstance(count, int) or count < 512:
        raise ValueError("owned reasoning/tool semantic records require at least 512 episodes")
    records: list[dict[str, object]] = []
    for index in range(count):
        left, right, result = _episode(index)
        target_text = (f"reasoning sum {left} plus {right} equals {result}" if capability == "reasoning" else f"tool calculator {left} plus {right} equals {result}")
        encoded = list(tokenizer.encode(target_text).ids)
        if len(encoded) < 2:
            raise ValueError("frozen tokenizer cannot encode owned reasoning/tool transcript")
        record: dict[str, object] = {
            "schema_version": "ember-owned-semantic-record-v1",
            "sample_id": f"owned-{capability}-trajectory-{index:08d}",
            "active_expert": capability,
            "token_ids": encoded[:-1],
            "target_ids": encoded[1:],
            "target_text": target_text,
            "image_coordinates": [],
            "multimodal_spans": [],
        }
        if capability == "reasoning":
            record["capability_evidence"] = {"reasoning": {"operands": [left, right], "target": result, "trace": [left, right, result]}}
        else:
            record["capability_evidence"] = {"tool": {"name": "owned_calculator", "arguments": {"expression": f"{left}+{right}"}, "observation": {"value": result}}}
        record["capability_receipt"] = expected_receipt(record)
        records.append(record)
    return records