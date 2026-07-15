#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Resolve the only Ember CLI seat allowed to claim an owned checkpoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from contract import validate_manifest


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
    checkpoint_sha256 = manifest["checkpoint"]["sha256"]
    checkpoint_manifest_path = (root / manifest["checkpoint"]["manifest_path"]).resolve()
    tokenizer_path = (root / manifest["tokenizer"]["path"]).resolve()
    server_path = (root / serving["server_implementation"]["path"]).resolve()
    return {
        "valid": True,
        "seat": "OWNED_ADMITTED",
        "run_id": manifest["run_id"],
        "checkpoint_sha256": checkpoint_sha256,
        "endpoint_url": serving["endpoint_url"].rstrip("/"),
        "identity_url": serving["endpoint_url"].rstrip("/") + serving["identity_path"],
        "model_name": f"ember-owned:{checkpoint_sha256[:12]}",
        "model_format": serving["model_format"],
        "launch": {
            "checkpoint_dir": str(checkpoint_manifest_path.parent),
            "mode": "INTERACTIVE",
            "run_manifest_path": str(run_manifest_path),
            "server_path": str(server_path),
            "tokenizer_path": str(tokenizer_path),
            "trusted_verifier_registry_path": str(verifier_registry.resolve()),
        },
        "server_source_sha256": serving["server_implementation"]["sha256"],
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
