#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Resolve the only Ember CLI seat allowed to claim an owned checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from contract import validate_manifest


def _registry_approval(approval_path: Path) -> tuple[str, str]:
    approval_bytes = approval_path.read_bytes()
    approval = json.loads(approval_bytes)
    if not isinstance(approval, dict) or set(approval) != {
        "schema_version", "trusted_verifier_registry_sha256",
    }:
        raise ValueError("trusted verifier registry approval must use the closed v1 schema")
    expected = approval.get("trusted_verifier_registry_sha256")
    if (
        approval.get("schema_version") != "ember-trusted-verifier-registry-approval-v1"
        or not isinstance(expected, str)
        or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected)
    ):
        raise ValueError("trusted verifier registry approval is invalid")
    return expected, hashlib.sha256(approval_bytes).hexdigest()


def resolve_owned_seat(
    manifest_path: Path,
    verifier_registry: Path,
    verifier_registry_approval: Path,
) -> dict[str, Any]:
    expected_registry_sha256, approval_sha256 = _registry_approval(verifier_registry_approval)
    validation = validate_manifest(
        manifest_path,
        verifier_registry,
        expected_trusted_verifier_registry_sha256=expected_registry_sha256,
    )
    if not validation["valid"] or validation["stage"] != "OWNED_ADMITTED":
        return {
            "valid": False,
            "seat": None,
            "errors": validation["errors"]
            or ["manifest stage is not OWNED_ADMITTED"],
        }

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cli = manifest["cli"]
    run_manifest_path = manifest_path.resolve()
    root = run_manifest_path.parent
    serving_path = (root / cli["serving_manifest_path"]).resolve()
    serving = json.loads(serving_path.read_text(encoding="utf-8"))
    checkpoint_sha256 = manifest["checkpoint"]["sha256"]
    checkpoint_manifest_path = (root / manifest["checkpoint"]["manifest_path"]).resolve()
    tokenizer_path = (root / manifest["tokenizer"]["path"]).resolve()
    model_config_path = (root / manifest["architecture"]["model_config"]["path"]).resolve()
    server_path = (root / serving["server_implementation"]["path"]).resolve()
    return {
        "valid": True,
        "seat": "OWNED_ADMITTED",
        "run_id": manifest["run_id"],
        "checkpoint_sha256": checkpoint_sha256,
        "endpoint_url": serving["endpoint_url"].rstrip("/"),
        "model_config_sha256": manifest["architecture"]["model_config"]["sha256"],
        "identity_url": serving["endpoint_url"].rstrip("/") + serving["identity_path"],
        "model_name": f"ember-owned:{checkpoint_sha256[:12]}",
        "model_format": serving["model_format"],
        "launch": {
            "checkpoint_dir": str(checkpoint_manifest_path.parent),
            "mode": "INTERACTIVE",
            "model_config_path": str(model_config_path),
            "run_manifest_path": str(run_manifest_path),
            "server_path": str(server_path),
            "tokenizer_path": str(tokenizer_path),
            "trusted_verifier_registry_path": str(verifier_registry.resolve()),
            "trusted_verifier_registry_approval_path": str(verifier_registry_approval.resolve()),
            "trusted_verifier_registry_approval_sha256": approval_sha256,
        },
        "server_source_sha256": serving["server_implementation"]["sha256"],
        "tokenizer_sha256": manifest["tokenizer"]["sha256"],
        "errors": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--trusted-verifier-registry", required=True, type=Path)
    parser.add_argument("--trusted-verifier-registry-approval", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = resolve_owned_seat(
            args.manifest,
            args.trusted_verifier_registry,
            args.trusted_verifier_registry_approval,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        result = {"valid": False, "seat": None, "errors": [f"owned seat: {exc}"]}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
