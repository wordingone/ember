# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Emit the exact non-A1 resource projection bound to the 3B launch authority."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

GIB = 1024**3
_ROOT = Path(__file__).resolve().parents[2]
_LAUNCH_PACKET = _ROOT / "tools" / "ember-restart-3b" / "launch_packet.py"
_SPEC = importlib.util.spec_from_file_location("issue898_launch_packet_authority", _LAUNCH_PACKET)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("issue898 resource projection cannot load launch_packet authority")
_AUTHORITY = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_AUTHORITY)


def _required_object(value: Any, key: str) -> dict[str, Any]:
    child = value.get(key) if isinstance(value, dict) else None
    if not isinstance(child, dict):
        raise ValueError(f"resource projection requires object {key}")
    return child


def _positive_number(value: Any, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"resource projection requires positive {label}")
    return value


def exact_resource_projection(config_path: Path) -> dict[str, Any]:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    counts = _AUTHORITY.compute_param_counts(cfg)
    memory = _required_object(_required_object(cfg, "training"), "memory")
    serialization = _required_object(_required_object(cfg, "checkpoints"), "serialization")

    total = int(_positive_number(counts.get("total_unique_trainable"), "total parameters"))
    active = int(_positive_number(counts.get("active_parameters"), "active parameters"))
    parameter_bytes = int(_positive_number(memory.get("parameter_bytes"), "parameter bytes"))
    gradient_bytes = int(_positive_number(
        memory.get("gradient_bytes_per_active_parameter"), "gradient bytes"
    ))
    optimizer_bytes = int(_positive_number(
        memory.get("optimizer_state_bytes_per_active_parameter"), "optimizer bytes"
    ))
    activation_gib = _positive_number(memory.get("activation_reserve_gib"), "activation reserve")
    runtime_gib = _positive_number(memory.get("runtime_reserve_gib"), "runtime reserve")
    checkpoint_reserve_gib = int(_positive_number(
        serialization.get("host_commit_reserve_gib"), "checkpoint publication reserve"
    ))

    params_b = total * parameter_bytes
    grads_b = active * gradient_bytes
    opt_b = active * optimizer_bytes
    activation_b = int(activation_gib * GIB)
    runtime_b = int(runtime_gib * GIB)
    peak_b = params_b + grads_b + opt_b + activation_b + runtime_b

    authority = _AUTHORITY.preflight_resource(cfg, config_path.resolve().parent.parent)
    breakdown = authority.get("breakdown_gib") if isinstance(authority, dict) else None
    expected_rounded = {
        "params_all": round(params_b / GIB, 4),
        "gradients_active": round(grads_b / GIB, 4),
        "optimizer_active": round(opt_b / GIB, 4),
        "activation_reserve": activation_gib,
        "runtime_reserve": runtime_gib,
    }
    if authority.get("status") != "pass" or breakdown != expected_rounded:
        raise ValueError("exact resource projection drifted from preflight_resource authority")

    return {
        "schema_version": "ember-issue898-resource-projection-v1",
        "authority": "tools/ember-restart-3b/launch_packet.py::preflight_resource",
        "total_parameters": total,
        "active_parameters": active,
        "parameter_bytes_all": params_b,
        "gradient_bytes_active": grads_b,
        "optimizer_state_bytes_active": opt_b,
        "activation_reserve_bytes": activation_b,
        "runtime_reserve_bytes": runtime_b,
        "mechanism_peak_bytes": peak_b,
        "checkpoint_publication_host_commit_reserve_bytes": checkpoint_reserve_gib * GIB,
        "authority_rounded_breakdown_gib": breakdown,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(exact_resource_projection(args.config), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
