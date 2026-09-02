#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression coverage for issue #1372 pinned control fixtures.

The controls driver may read committed fixtures, but it must not regenerate
them in place. In particular, a controls run must preserve the hardened C7
receipt-returning fixture and the checkout's exact line endings.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUN_CONTROLS_PATH = HERE / "run_controls.py"
PINNED_ROOTS = (
    HERE / "fixtures" / "c7_pos",
    HERE / "fixtures" / "c7_neg",
    HERE / "fixtures" / "cure5_legib_pos",
    HERE / "fixtures" / "cure5_legib_neg",
)
PINNED_FILES = (
    PINNED_ROOTS[0] / "scripts" / "ember_phase5_c7" / "c7_selftest.py",
    PINNED_ROOTS[0] / "scripts" / "ember_phase5_c7" / "regime_operator.py",
    PINNED_ROOTS[1] / "scripts" / "ember_phase5_c7" / "c7_selftest.py",
    PINNED_ROOTS[1] / "scripts" / "ember_phase5_c7" / "regime_operator.py",
    PINNED_ROOTS[2] / "scripts" / "check_goal_citations.py",
    PINNED_ROOTS[3] / "scripts" / "check_goal_citations.py",
)
GENERATED_PATHS = (
    PINNED_ROOTS[0] / "receipts",
    PINNED_ROOTS[1] / "receipts",
    PINNED_ROOTS[2] / ".pytest_cache",
    PINNED_ROOTS[2] / "AGENTS.md",
    PINNED_ROOTS[2] / "docs",
    PINNED_ROOTS[2] / "receipts",
    PINNED_ROOTS[2] / "unmapped_real_dir",
    PINNED_ROOTS[3] / ".pytest_cache",
    PINNED_ROOTS[3] / "AGENTS.md",
    PINNED_ROOTS[3] / "docs",
    PINNED_ROOTS[3] / "receipts",
    PINNED_ROOTS[3] / "unmapped_real_dir",
)


def _load_run_controls():
    spec = importlib.util.spec_from_file_location(
        "run_controls_issue1372_under_test", RUN_CONTROLS_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(HERE))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(HERE))
    return module


def _restore(snapshot: dict[Path, bytes]) -> None:
    for path, contents in snapshot.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)


def _clean_generated_paths() -> None:
    for path in GENERATED_PATHS:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def test_issue1372_pinned_fixtures_are_byte_stable() -> None:
    _clean_generated_paths()
    before = {path: path.read_bytes() for path in PINNED_FILES}
    run_controls = _load_run_controls()

    try:
        c7_pos, c7_neg = run_controls.build_c7()
        legib_pos = run_controls.build_cure5_c_legib("pos")
        legib_neg = run_controls.build_cure5_c_legib("neg")
        returned = tuple(Path(path).resolve() for path in (c7_pos, c7_neg, legib_pos, legib_neg))
        assert returned == tuple(root.resolve() for root in PINNED_ROOTS)

        after = {path: path.read_bytes() for path in PINNED_FILES}
        assert after == before, "controls builders changed committed fixture bytes"
    finally:
        _restore(before)
        _clean_generated_paths()

    for fixture_path in PINNED_FILES[:4:2]:
        source = before[fixture_path].decode("utf-8")
        assert "def assert_c7_deletion_test(corpus: C7Corpus, n_cycles: int) -> DeletionTestReceipt:" in source
        assert "    return receipt\n" in source


def test_issue1372_pinned_fixtures_keep_control_semantics() -> None:
    _clean_generated_paths()
    before = {path: path.read_bytes() for path in PINNED_FILES}
    run_controls = _load_run_controls()

    try:
        c7_pos, c7_neg = run_controls.build_c7()
        legib_pos = run_controls.build_cure5_c_legib("pos")
        legib_neg = run_controls.build_cure5_c_legib("neg")
        assert run_controls.run_probe("test_c7.py", c7_pos)[0] == "GREEN"
        assert run_controls.run_probe("test_c7.py", c7_neg)[0] == "RED"
        assert run_controls.run_probe("test_c_legib.py", legib_pos)[0] == "GREEN"
        assert run_controls.run_probe("test_c_legib.py", legib_neg)[0] == "RED"
    finally:
        _restore(before)
        _clean_generated_paths()


if __name__ == "__main__":
    test_issue1372_pinned_fixtures_are_byte_stable()
    test_issue1372_pinned_fixtures_keep_control_semantics()
    print("ISSUE1372_FIXTURE_STABILITY_PASS")
