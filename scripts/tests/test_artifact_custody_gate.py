# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""RED-first: ``default_catalog_db``/``canonical_ember_lab_binary`` must resolve
the durable main-tree root, not whichever worktree happens to be executing them.

#1741 Known Limitation B: both functions took ``repo_root`` as a caller-supplied
path and every real call site computed it as ``Path(__file__).resolve().parents[2]``
(``src/ember/governance/scripts/ember_restart/contract.py``) -- the tree the *executing script* lives
in. From a worktree (the normal working pattern here), that resolves to the
worktree's own (nonexistent) ``state/`` directory instead of the durable
``<main-tree>/state/ember-lab-catalog.sqlite3`` every custody gate must share,
and to the worktree's own (unbuilt) ``runtime/ember-lab/target/...`` instead of
the one repository-governed binary. Both fail closed today (no bypass), but
every real checkpoint validation run from a worktree refuses by construction.

Fix precedent: ``src/ember/governance/scripts/worktree_lifecycle.py::common_dir`` and
``src/ember/governance/scripts/ember_restart/source_authority.py::_common_dir`` both resolve the
main tree from any worktree via
``git rev-parse --path-format=absolute --git-common-dir`` -- the main
checkout's ``.git`` is a real directory that IS the common dir; a worktree's
``.git`` is a file pointing elsewhere. This suite proves the same property for
``artifact_custody_gate.py``'s two functions using a real git worktree (no
mocked git), precedent: ``tests/ember_restart/test_contract_source_binding.py``.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "artifact_custody_gate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("_test_artifact_custody_gate", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_module()


def _git(root: Path, *args: str) -> str:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "custody-db-resolution-test",
            "GIT_AUTHOR_EMAIL": "custody-db-resolution@example.invalid",
            "GIT_COMMITTER_NAME": "custody-db-resolution-test",
            "GIT_COMMITTER_EMAIL": "custody-db-resolution@example.invalid",
        }
    )
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout.strip()


@pytest.fixture
def main_tree(tmp_path: Path) -> Path:
    """A real, standalone repository standing in for the durable main tree."""
    root = tmp_path / "main-tree"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "master", str(root)], check=True, capture_output=True)
    (root / "README.md").write_text("main tree marker\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "seed")
    return root


@pytest.fixture
def worktree(tmp_path: Path, main_tree: Path) -> Path:
    """A real ``git worktree add`` checkout of ``main_tree`` (not the main tree)."""
    path = tmp_path / "a-worktree"
    _git(main_tree, "worktree", "add", "-b", "resolution-test-branch", str(path), "HEAD")
    return path


def test_default_catalog_db_from_worktree_resolves_to_main_tree_state(
    main_tree: Path, worktree: Path
):
    """Invoked with a WORKTREE path, the returned catalog path must live under
    the main tree's ``state/``, not the worktree's own -- proven by comparing
    against the resolved main-tree root directly, not by string-matching the
    worktree's path out of the result.
    """
    resolved = gate.default_catalog_db(worktree)
    expected = main_tree.resolve() / "state" / "ember-lab-catalog.sqlite3"
    assert resolved == expected
    assert not str(resolved).startswith(str(worktree.resolve()))


def test_default_catalog_db_from_main_tree_itself_still_resolves_correctly(main_tree: Path):
    """Control: invoked directly on the main tree (no worktree involved), the
    fix must not change the answer for the one caller shape that already
    worked -- same assertion shape as the worktree case, real git both times.
    """
    resolved = gate.default_catalog_db(main_tree)
    expected = main_tree.resolve() / "state" / "ember-lab-catalog.sqlite3"
    assert resolved == expected


def test_canonical_ember_lab_binary_from_worktree_finds_main_tree_build(
    main_tree: Path, worktree: Path
):
    """A binary built only in the main tree's ``runtime/ember-lab/target/release``
    must still be found when this function is invoked with a WORKTREE path --
    proving the worktree's own (unbuilt) target dir is never consulted instead.
    """
    release_dir = main_tree / "runtime" / "ember-lab" / "target" / "release"
    release_dir.mkdir(parents=True)
    binary = release_dir / "ember-lab.exe"
    binary.write_bytes(b"stand-in binary bytes")

    resolved = gate.canonical_ember_lab_binary(worktree)
    assert resolved == binary.resolve()


def test_canonical_ember_lab_binary_from_worktree_with_no_main_tree_build_is_none(
    main_tree: Path, worktree: Path
):
    """No build anywhere in the main tree -> ``None``, not a worktree-local miss
    masquerading as the real answer (real refusal shape, not silently correct
    by accident of both paths being equally empty).
    """
    assert gate.canonical_ember_lab_binary(worktree) is None
