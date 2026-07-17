# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import hashlib
import json
from pathlib import Path
from typing import Any
from checkpoint_artifacts import write_checkpoint_artifacts as _production_write
from parameter_counter import validate_realization_receipt


def fixture_counter_receipt(candidate: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    architecture = manifest["architecture"]
    payload = {
        "schema_version": "ember-sparse-realization-receipt-v1",
        "verification_boundary": "VERIFIED_MEASURED",
        "result": "MEASURED",
        "model_config_sha256": manifest["model_config_sha256"],
        "subject_checkpoint_sha256": manifest["checkpoint_manifest_sha256"],
        "architecture_revision": manifest["architecture_revision"],
        "counter_sha256": hashlib.sha256((Path(__file__).resolve().parents[2] / "tools" / "ember-restart-3b" / "parameter_counter.py").read_bytes()).hexdigest(),
        "active_expert_ids": manifest["active_expert_ids"],
        "expert_genesis_sha256": manifest["expert_genesis_sha256"],
        "expert_parameter_sha256": manifest["expert_parameter_sha256"],
    }
    for field in ("allocated_parameters", "unique_parameters", "trainable_parameters", "served_parameters", "active_parameters", "episode_trainable_parameters"):
        payload[field] = architecture[field]
    validate_realization_receipt(payload)
    (candidate / "parameter-counter-receipt.json").write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def write_checkpoint_artifacts(*args: Any, **kwargs: Any) -> dict[str, Any]:
    kwargs.pop("test_only_allow_unverified", None)
    kwargs.setdefault("pre_publish_verifier", fixture_counter_receipt)
    return _production_write(*args, **kwargs)
