#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Derive the A-CLEAN frozen-eval exclusion set from committed protected authority."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence


REGISTRY = "data/ember-restart-3b/protected-eval-registry-v2.json"
OUTPUT = "data/ember-restart-3b/text-lab-frozen-eval-hashes-v1.json"


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def derive(repo_root: Path) -> dict[str, object]:
    root = Path(repo_root).resolve(strict=True)
    registry = json.loads((root / REGISTRY).read_bytes())
    protected = registry.get("protected") if isinstance(registry, dict) else None
    if registry.get("schema_version") != "ember-protected-eval-registry-v2" or not isinstance(protected, list):
        raise ValueError("PROTECTED_EVAL_REGISTRY_REFUSED")
    hashes = sorted({
        item["value"]
        for row in protected
        for item in row.get("protected_identifiers", [])
        if isinstance(item, dict) and item.get("kind") == "content_sha256"
    })
    if not hashes or any(
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in hashes
    ):
        raise ValueError("PROTECTED_EVAL_CONTENT_HASHES_REFUSED")
    return {
        "schema_version": "ember-text-lab-frozen-eval-hashes-v1",
        "hashes": hashes,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--verify", action="store_true")
    group.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    expected = canonical_json(derive(args.repo_root)) + b"\n"
    if args.verify:
        if (args.repo_root.resolve(strict=True) / OUTPUT).read_bytes() != expected:
            raise ValueError("FROZEN_EVAL_DERIVATION_REFUSED")
        print("FROZEN_EVAL_DERIVATION_PASS")
        return 0
    assert args.output is not None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as handle:
        handle.write(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
