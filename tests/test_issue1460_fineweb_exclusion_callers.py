#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""#1460: direct W1 loader callers bind the ruled exclusion policy.

These callers predate #1436's enforcing loader default and are currently
execution-denied historical harnesses. They still must carry the explicit
``None`` sentinel: it means "resolve the governed exclusion policy" and keeps
future revival from silently opting out of the ruling. ``[]`` is the only
documented opt-out and must not appear in these production callers.
"""
from __future__ import annotations

import ast
from pathlib import Path


SCRIPT_NAMES = (
    "w1_collapse_control_run.py",
    "w1_fullstate_resume_verify.py",
    "w1_baseline_replay_closure.py",
)
EXPECTED_CALLS = 6


def _packed_loader_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PackedShardLoader"
    ]


def test_every_direct_w1_loader_binds_governed_exclusion_policy():
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    calls = []
    for name in SCRIPT_NAMES:
        path = scripts / name
        assert path.is_file(), path
        calls.extend((path, node) for node in _packed_loader_calls(path))

    assert len(calls) == EXPECTED_CALLS, [
        (str(path), node.lineno) for path, node in calls
    ]
    missing = []
    for path, node in calls:
        kw = next((item for item in node.keywords if item.arg == "excluded_ranges"), None)
        if kw is None:
            missing.append((str(path), node.lineno))
            continue
        assert isinstance(kw.value, ast.Constant) and kw.value.value is None, (
            f"{path}:{node.lineno} must pass excluded_ranges=None so the loader "
            "resolves the ruled exclusion policy; [] would be an opt-out"
        )
    assert not missing, missing


if __name__ == "__main__":
    test_every_direct_w1_loader_binds_governed_exclusion_policy()
    print("TEST_1460_FINEWEB_EXCLUSION_CALLERS_PASS")
