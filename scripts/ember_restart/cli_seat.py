#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Resolve the only Ember CLI seat allowed to claim an owned checkpoint.

cond3 seat-chain identity bridge (state/specs/cond3-seat-bridge-spec.md, goal
line 95): this resolver is NOT an independent identity authority. Every
identity-bearing field (checkpoint/model-config/tokenizer sha256) is DERIVED
from the ``ember-model-experiment-identity-v1`` cert manifest the run manifest
references (``cert_manifest_path`` / ``cert_manifest_digest``), via
``seat_identity_bridge.derive_seat_identity`` -- fail-closed, no fallback. The
run manifest's own values are read only as cross-check INPUT (Step 4 of the
bridge), never as final truth.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from contract import validate_manifest
from seat_identity_bridge import derive_seat_identity, require_admitted_seat

REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_owned_seat(manifest_path: Path, verifier_registry: Path) -> dict[str, Any]:
    validation = validate_manifest(manifest_path, verifier_registry)
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
    checkpoint_manifest_path = (root / manifest["checkpoint"]["manifest_path"]).resolve()
    tokenizer_path = (root / manifest["tokenizer"]["path"]).resolve()
    model_config_path = (root / manifest["architecture"]["model_config"]["path"]).resolve()
    server_path = (root / serving["server_implementation"]["path"]).resolve()

    # cond3 seat-chain bridge: derive identity from the referenced cert
    # manifest. The run manifest's own model-config/tokenizer sha256 values
    # are supplied ONLY as cross-check input (bridge Step 4) -- they are
    # never returned to callers except after the bridge confirms they equal
    # the cert-derived value byte-for-byte.
    #
    # checkpointSha256 is deliberately NOT supplied here.
    # manifest["checkpoint"]["sha256"] is the sha256 of the checkpoint INDEX
    # JSON at checkpoint_manifest_path (contract.py's own self-consistency
    # check on that file) -- it identifies the index, not the checkpoint
    # bytes the index lists. Passing it as checkpointSha256 cross-check
    # material is exactly the field-reinterpretation this bridge closes
    # (state/failure-classes/semantic-validation-without-bytes-2026-07-25.md):
    # the bridge derives and verifies the real checkpoint-byte identity
    # itself, from checkpointPath, via resolve_checkpoint_byte_identity
    # (Step 5) -- every load-bearing shard hashed against its own declared
    # digest, never the index's digest substituted for it.
    cert_manifest_path = manifest.get("cert_manifest_path")
    bridge_seat_config = {
        "certManifestPath": (
            str((root / cert_manifest_path).resolve())
            if isinstance(cert_manifest_path, str)
            else cert_manifest_path
        ),
        "certManifestDigest": manifest.get("cert_manifest_digest"),
        "checkpointPath": str(checkpoint_manifest_path),
        # Shard "path" entries inside the checkpoint index are relative to
        # the run-manifest ROOT (contract.py's own convention), not to the
        # index file's own directory -- root must travel with checkpointPath.
        "checkpointRoot": str(root),
        "modelConfigSha256": manifest["architecture"]["model_config"]["sha256"],
        "tokenizerSha256": manifest["tokenizer"]["sha256"],
    }
    bridge = derive_seat_identity(bridge_seat_config, repo_root=REPO_ROOT)
    if not bridge["valid"]:
        return {"valid": False, "seat": None, "errors": bridge["errors"]}
    try:
        derived = require_admitted_seat(bridge["seat"])
    except PermissionError as exc:
        return {"valid": False, "seat": None, "errors": [str(exc)]}

    checkpoint_sha256 = derived["checkpointSha256"]
    return {
        "valid": True,
        "seat": "OWNED_ADMITTED",
        "run_id": manifest["run_id"],
        "checkpoint_sha256": checkpoint_sha256,
        "endpoint_url": serving["endpoint_url"].rstrip("/"),
        "model_config_sha256": derived["modelConfigSha256"],
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
        },
        "server_source_sha256": serving["server_implementation"]["sha256"],
        "tokenizer_sha256": derived["tokenizerSha256"],
        "errors": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--trusted-verifier-registry", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = resolve_owned_seat(args.manifest, args.trusted_verifier_registry)
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        result = {"valid": False, "seat": None, "errors": [f"owned seat: {exc}"]}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
