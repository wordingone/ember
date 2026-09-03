# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Planted producer test: every declared fixed-prior INVENTORY path exists in the tree.

Before the canonical-layout repoint the ember-cli tree entry named
``tools/ember-cli/src``, a directory the cutover had already moved, so the
builder refused with an empty tree digest. This test binds the inventory to the
tree it will hash, so a future move fails here instead of at mint time.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPTS = ROOT / "src" / "ember" / "governance" / "scripts"


def _load_builder():
    path = SCRIPTS / "build_fixed_prior_manifest.py"
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("build_fixed_prior_manifest_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_declared_file_and_tree_prior_exists_on_disk() -> None:
    builder = _load_builder()
    missing = []
    for entry in builder.INVENTORY:
        if entry["kind"] == "file" and not (ROOT / entry["path"]).is_file():
            missing.append(entry["path"])
        elif entry["kind"] == "tree" and not (ROOT / entry["path"]).is_dir():
            missing.append(entry["path"])
    assert missing == [], f"declared priors absent from the tree: {missing}"


def test_ember_cli_tree_prior_names_the_canonical_source_root() -> None:
    builder = _load_builder()
    trees = [e["path"] for e in builder.INVENTORY if e["kind"] == "tree" and e["category"] == "ember_cli"]
    assert trees == ["src/ember/infrastructure/tools/ember-cli/src"]
