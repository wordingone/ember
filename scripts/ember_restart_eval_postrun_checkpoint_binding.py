#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bind a future emitted checkpoint to the exact manifest/config bytes used."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

SHA256 = re.compile(r"[0-9a-f]{64}")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-manifest", required=True, type=Path)
    parser.add_argument("--model-config", required=True, type=Path)
    parser.add_argument("--pre-run-manifest-sha256", required=True)
    parser.add_argument("--pre-run-config-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must not pre-exist")
    if not SHA256.fullmatch(args.pre_run_manifest_sha256) or not SHA256.fullmatch(args.pre_run_config_sha256):
        parser.error("pre-run identities must be lowercase SHA-256")
    try:
        manifest_bytes = args.checkpoint_manifest.read_bytes()
        config_bytes = args.model_config.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != "ember-sparse-checkpoint-v3":
            raise ValueError("post-run checkpoint manifest must use corrected v3 schema")
        config_sha256 = digest(config_bytes)
        manifest_sha256 = digest(manifest_bytes)
        if manifest.get("model_config_sha256") != config_sha256:
            raise ValueError("post-run manifest model_config_sha256 does not match exact config bytes")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        parser.error(f"invalid post-run checkpoint binding: {error}")
    payload = {
        "schema_version": "ember-restart-postrun-checkpoint-binding-v1",
        "result": "PREFLIGHT_ONLY",
        "binding_scope": "POST_RUN_EMITTED_CHECKPOINT",
        "checkpoint_manifest_sha256": manifest_sha256,
        "model_config_sha256": config_sha256,
        "pre_run_anchor": {
            "checkpoint_manifest_sha256": args.pre_run_manifest_sha256,
            "model_config_sha256": args.pre_run_config_sha256,
            "disposition": "REFERENCE_ONLY_PRE_RUN_ANCHOR",
        },
        "claim_boundary": "NO_CAPABILITY_ADMISSION_OR_SUFFICIENT_PRETRAINING_CREDIT",
    }
    payload["content_sha256"] = digest(canonical(payload))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.output.parent, delete=False) as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())