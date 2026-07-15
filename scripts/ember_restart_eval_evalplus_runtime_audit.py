#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed audit of EvalPlus Docker build reproducibility; never runs Docker."""
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evalplus-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output must not pre-exist")
    try:
        dockerfile = arguments.evalplus_root / "Dockerfile"
        data = dockerfile.read_bytes()
        lines = data.decode("utf-8").splitlines()
        from_lines = [line.strip() for line in lines if line.strip().upper().startswith("FROM ")]
        if len(from_lines) != 1:
            raise ValueError("Dockerfile must have one base image")
        base = from_lines[0][5:].strip()
        mutable_base = "@sha256:" not in base
        lowered = "\n".join(lines).lower()
        live_dependency = "pip install" in lowered and ("--require-hashes" not in lowered or "pip install --upgrade" in lowered)
        live_dataset = "get_human_eval_plus" in lowered or "get_mbpp_plus" in lowered or "get_evalperf_data" in lowered
    except (OSError, UnicodeDecodeError, ValueError) as error:
        parser.error(str(error))
    payload = {
        "schema_version": "ember-restart-evalplus-runtime-audit-v1",
        "result": "PREFLIGHT_ONLY",
        "claim_status": "RUNTIME_HELD_MUTABLE_CONTAINER_BUILD",
        "dockerfile_sha256": sha256(data),
        "base_image": base,
        "mutable_base_image": mutable_base,
        "live_dependency_resolution": live_dependency,
        "live_dataset_fetch": live_dataset,
        "target_execution_permitted": False,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.output.parent, prefix=arguments.output.name + ".", suffix=".tmp", delete=False) as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    os.replace(temporary, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())