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
import re
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


POST_HOUR_GATE = 'post_hour_promotion_gate.py'
PROMOTION_CALLS = ('promote_with_pending_v1', 'advance_selected_continuation_head', 'scored_pair_cli')
HEAD_MOVING_CALLS = ('promote_with_pending_v1', 'advance_selected_continuation_head')     # these move the selected head, so the cadence check (--advance-child) must run
_SWALLOWS_REFUSAL = re.compile(r'(\|\|\s*(true|:)(\s|$|;|\))|;\s*true(\s|$))')
_REFUSAL_EXITS = re.compile(r'\b(exit|return)\b')


def dispatch_script_gate_problems(script_text: str) -> list[str]:
    """Issue #2119 clause 1: an hour dispatch script must call the post-hour promotion gate on a non-comment line, and must not reach any
    promotion entry (promote_with_pending_v1, advance_selected_continuation_head, scored_pair_cli) on a non-comment line BEFORE that call.
    Returns the problems found (empty list = the script routes promotion through the gate). A commented-out call does not count."""
    live = [(number, line.strip()) for number, line in enumerate(script_text.splitlines(), 1) if line.strip() and not line.strip().startswith('#')]
    gate_index = next((i for i, (_, text) in enumerate(live) if POST_HOUR_GATE in text), None)
    gate_line = live[gate_index][0] if gate_index is not None else None
    early = [number for number, text in live[:gate_index if gate_index is not None else len(live)]
             if POST_HOUR_GATE not in text and any(name in text for name in PROMOTION_CALLS)]
    problems = []
    if gate_line is None:
        problems.append(f'no non-comment call to {POST_HOUR_GATE}')
    for number in early:
        problems.append(f'line {number} reaches a promotion entry before the gate')
    if gate_index is not None:
        gate_text = live[gate_index][1]
        handler = ' '.join(text for _, text in live[gate_index:gate_index + 2])           # the gate line and the line that reads its exit code
        if _SWALLOWS_REFUSAL.search(gate_text):
            problems.append(f'line {gate_line} swallows the gate refusal (|| true / || : / ; true)')
        elif not _REFUSAL_EXITS.search(handler):
            problems.append(f'line {gate_line} has no refusal handler: the gate line or the next line must exit on a refusal')
        if any(name in text for _, text in live for name in HEAD_MOVING_CALLS) and '--advance-child' not in gate_text:
            problems.append(f'line {gate_line} does not pass --advance-child although the script moves the selected head: the row 20 cadence check would not run')
    return problems


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
