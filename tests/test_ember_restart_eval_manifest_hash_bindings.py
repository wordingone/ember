# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_all_public_script_and_manifest_path_hash_bindings_match_bytes():
    checked = 0
    for manifest_path in sorted((ROOT / "manifests").glob("*.json")):
        value = json.loads(manifest_path.read_text(encoding="utf-8"))

        def walk(node):
            nonlocal checked
            if isinstance(node, dict):
                rel = node.get("path")
                expected = node.get("sha256")
                if isinstance(rel, str) and isinstance(expected, str) and len(expected) == 64 and rel.startswith(("scripts/", "manifests/")):
                    path = ROOT / rel
                    assert path.is_file(), f"missing bound path: {manifest_path.name}:{rel}"
                    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, f"stale bound hash: {manifest_path.name}:{rel}"
                    checked += 1
                for child in node.values():
                    walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)

        walk(value)
    assert checked >= 28
