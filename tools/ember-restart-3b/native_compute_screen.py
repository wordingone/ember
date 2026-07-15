# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""`ngoal_id: EMBER-02`nnext_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember`n`nCurrent-native, non-admissible full-step throughput screen.`n"""

from __future__ import annotations

from typing import Any

_SEQUENCE_LENGTH = 1024
_REQUIRED_BATCHES = (1, 2)
_MEMORY_GATE_BATCHES = (4, 8)


def screen_plan(*, total_vram_bytes: int) -> dict[str, object]:
    if not isinstance(total_vram_bytes, int) or total_vram_bytes <= 0:
        raise ValueError("total VRAM bytes must be positive")
    return {
        "sequence_length": _SEQUENCE_LENGTH,
        "required_batches": list(_REQUIRED_BATCHES),
        "memory_gate_only_batches": list(_MEMORY_GATE_BATCHES),
        "max_peak_allocated_bytes": int(total_vram_bytes * 0.8),
        "minimum_free_margin_bytes": int(1.5 * 1024**3),
    }


def screen_receipt(
    *,
    model_config_sha256: str,
    optimizer_contract_sha256: str,
    tokenizer_sha256: str,
    checkpoint_manifest_sha256: str,
    source_sha256: str,
    total_vram_bytes: int,
    batch_measurements: list[dict[str, Any]],
) -> dict[str, object]:
    plan = screen_plan(total_vram_bytes=total_vram_bytes)
    required = list(plan["required_batches"])
    max_peak = int(plan["max_peak_allocated_bytes"])
    for item in batch_measurements:
        if not isinstance(item.get("elapsed_seconds"), (int, float)) or item["elapsed_seconds"] <= 0:
            raise ValueError("screen step timing must be positive")
        if not isinstance(item.get("peak_allocated_bytes"), int) or item["peak_allocated_bytes"] > max_peak:
            raise MemoryError("0.8 VRAM governor rejects the measured allocation")
        if not isinstance(item.get("peak_reserved_bytes"), int) or item["peak_reserved_bytes"] < item["peak_allocated_bytes"]:
            raise ValueError("screen reserved peak must cover allocated peak")
    return {
        "schema_version": "ember-native-compute-screen-v1",
        "result": "MEASURED",
        "admission": "NON_ADMISSIBLE_COMPUTE_PRIMITIVE",
        "operation": "CLEAN_GENESIS_FULL_FORWARD_BACKWARD_OPTIMIZER_STEP",
        "sequence_length": _SEQUENCE_LENGTH,
        "required_batches": required,
        "memory_gate_only_batches": list(plan["memory_gate_only_batches"]),
        "vram_governor": {"maximum_fraction": 0.8, "minimum_free_margin_bytes": plan["minimum_free_margin_bytes"]},
        "model_config_sha256": model_config_sha256,
        "optimizer_contract_sha256": optimizer_contract_sha256,
        "tokenizer_sha256": tokenizer_sha256,
        "checkpoint_manifest_sha256": checkpoint_manifest_sha256,
        "source_sha256": source_sha256,
        "steps": batch_measurements,
    }