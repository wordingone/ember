#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Validate file-custody inputs for a local evaluator execution; never admits claims."""
import hashlib
import json
import re
import sys
from pathlib import Path


SHA256 = re.compile(r"^[0-9a-f]{64}$")
CAPABILITIES = {"text", "image", "audio", "reasoning", "tool"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    if not argv:
        print("usage: ember_restart_eval_execution_manifest.py MANIFEST", file=sys.stderr)
        return 2
    manifest_path = Path(argv[0]).resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"invalid manifest: {exc}", file=sys.stderr)
        return 2
    if not isinstance(manifest, dict) or manifest.get("capability") not in CAPABILITIES:
        print("manifest capability is required", file=sys.stderr)
        return 2
    if not isinstance(manifest.get("benchmark_id"), str) or not manifest["benchmark_id"].strip() or not isinstance(manifest.get("benchmark_version"), str) or not manifest["benchmark_version"].strip():
        print("benchmark id and version are required", file=sys.stderr)
        return 2
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        print("artifacts object is required", file=sys.stderr)
        return 2
    result = {}
    for name in ("split", "harness", "protocol"):
        record = artifacts.get(name)
        if not isinstance(record, dict) or not isinstance(record.get("path"), str) or not isinstance(record.get("sha256"), str) or not SHA256.fullmatch(record["sha256"]):
            print(f"{name} artifact requires relative path and SHA-256", file=sys.stderr)
            return 2
        path = (manifest_path.parent / record["path"]).resolve()
        if path.is_relative_to(manifest_path.parent) is False or not path.is_file() or digest(path) != record["sha256"]:
            print(f"{name} artifact is missing or hash-mismatched", file=sys.stderr)
            return 2
        result[f"{name}_sha256"] = record["sha256"]
    print(json.dumps({"valid": True, "capability": manifest["capability"], "benchmark_id": manifest["benchmark_id"], "benchmark_version": manifest["benchmark_version"], "artifact_sha256": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
