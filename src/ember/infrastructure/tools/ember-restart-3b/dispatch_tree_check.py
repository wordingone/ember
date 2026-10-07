# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Pre-dispatch tree checks for a governed hour (Issue #2119, H26 pointer switch, 2026-10-05).

The H26 hour was dispatched from a tree whose cia_hour.py still advanced selected-continuation-head.json after an ordinary hour
(the candidate-only change c13998ac was not in that tree), so the hour moved the selected head to an unscored child. Two checks close the class:

* require_commit_in_head(tree, commit): the dispatch tree's HEAD must contain the required commit (git merge-base --is-ancestor). An unknown
  commit, an unreadable tree or a non-ancestor all REFUSE (DispatchTreeRefusal); an abbreviated id that cannot be resolved is never read as present.
* hour_source_advances_selected_head(source_text): True when the hour source CALLS advance_selected_continuation_head or
  seed_selected_continuation_head (the pre-c13998ac shape). A dispatcher refuses such a tree before the window opens.

Both are pure reads: no write, no network, no pointer access.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

POINTER_MOVERS = ('advance_selected_continuation_head', 'seed_selected_continuation_head')


class DispatchTreeRefusal(RuntimeError):
    """The dispatch tree cannot be proven to contain the required change."""


def _git(tree: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(['git', '-C', str(tree), *args], capture_output=True, text=True, timeout=60, shell=False)


def require_commit_in_head(tree: str | Path, commit: str) -> str:
    """Return the full id of `commit` when it is an ancestor of the tree's HEAD, else raise DispatchTreeRefusal."""
    tree = Path(tree)
    head = _git(tree, 'rev-parse', '--verify', 'HEAD')
    if head.returncode != 0:
        raise DispatchTreeRefusal(f'cannot read HEAD of {tree}: {head.stderr.strip()[:160]}')
    full = _git(tree, 'rev-parse', '--verify', f'{commit}^{{commit}}')
    if full.returncode != 0:
        raise DispatchTreeRefusal(f'required commit {commit} is unknown in {tree} (head {head.stdout.strip()})')
    if _git(tree, 'merge-base', '--is-ancestor', full.stdout.strip(), head.stdout.strip()).returncode != 0:
        # A cherry-pick carries the same patch under a new id: accept it only when git cherry (patch-id) marks the commit '-' (already in HEAD).
        cherry = _git(tree, 'cherry', head.stdout.strip(), full.stdout.strip(), full.stdout.strip() + '^')
        marks = [line[:1] for line in cherry.stdout.splitlines() if line.endswith(' ' + full.stdout.strip())]
        if cherry.returncode != 0 or marks != ['-']:
            raise DispatchTreeRefusal(f'head {head.stdout.strip()} does not contain required commit {full.stdout.strip()} (not an ancestor, not a cherry-pick)')
    return full.stdout.strip()


def hour_source_advances_selected_head(source_text: str) -> list[int]:
    """Line numbers of every call to a pointer mover in the hour source (empty list = candidate-only publication)."""
    hits = []
    for node in ast.walk(ast.parse(source_text)):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, 'id', '')
            if name in POINTER_MOVERS:
                hits.append(node.lineno)
    return sorted(hits)
