"""w4_eval_taskfilter_selftest.py — CPU-only self-test of the --task-ids-file filter.

Tests:
  (a) no file → all problems pass through
  (b) subset file → exactly that subset
  (c) absent id in file → SystemExit
"""

import sys
import tempfile
import os


def filter_problems_by_ids(problems, task_ids_file):
    """Filter problems to exact task ids from file (one per line, stripped).
    If file given, returns filtered list (fail-closed on absent ids).
    If file is None, returns problems unchanged (backward-compatible).
    Expects each line to be 'NNN' or 'mbpp:NNN'; strips 'mbpp:' prefix.
    """
    if task_ids_file is None:
        return problems

    requested_ids = set()
    with open(task_ids_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                # Strip 'mbpp:' prefix if present
                if line.startswith("mbpp:"):
                    line = line[5:]
                try:
                    requested_ids.add(int(line))
                except ValueError:
                    raise SystemExit(
                        f"w4: bad task id in {task_ids_file}: {line!r} "
                        f"(want NNN or mbpp:NNN)")

    # Check all requested ids are present
    problem_ids = {p["id"] for p in problems}
    missing = requested_ids - problem_ids
    if missing:
        raise SystemExit(
            f"w4: requested task ids not in split: {sorted(missing)}")

    # Filter to exact subset
    filtered = [p for p in problems if p["id"] in requested_ids]
    return filtered


def test_no_file():
    """Test (a): no file → all problems pass through."""
    problems = [
        {"id": 1, "prompt": "test 1"},
        {"id": 2, "prompt": "test 2"},
        {"id": 3, "prompt": "test 3"},
    ]
    result = filter_problems_by_ids(problems, None)
    assert len(result) == 3, f"Expected 3 problems, got {len(result)}"
    assert result == problems, "Problems should be unchanged"
    print("✓ (a) no file → all problems")


def test_subset_file():
    """Test (b): subset file → exactly that subset."""
    problems = [
        {"id": 1, "prompt": "test 1"},
        {"id": 2, "prompt": "test 2"},
        {"id": 3, "prompt": "test 3"},
        {"id": 4, "prompt": "test 4"},
    ]
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt',
                                      encoding='utf-8') as f:
        f.write("2\n")
        f.write("mbpp:4\n")
        f.write("1\n")
        fname = f.name
    try:
        result = filter_problems_by_ids(problems, fname)
        result_ids = sorted([p["id"] for p in result])
        assert result_ids == [1, 2, 4], \
            f"Expected [1, 2, 4], got {result_ids}"
        print("✓ (b) subset file → exact subset (order preserved in results)")
    finally:
        os.unlink(fname)


def test_absent_id():
    """Test (c): absent id in file → SystemExit."""
    problems = [
        {"id": 1, "prompt": "test 1"},
        {"id": 2, "prompt": "test 2"},
    ]
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt',
                                      encoding='utf-8') as f:
        f.write("1\n")
        f.write("999\n")  # absent
        fname = f.name
    try:
        try:
            filter_problems_by_ids(problems, fname)
            print("✗ (c) absent id should have raised SystemExit")
            sys.exit(1)
        except SystemExit as e:
            if "requested task ids not in split" in str(e):
                print("✓ (c) absent id → SystemExit (fail-closed)")
            else:
                raise
    finally:
        os.unlink(fname)


if __name__ == "__main__":
    test_no_file()
    test_subset_file()
    test_absent_id()
    print("\nW4_TASKFILTER_SELFTEST_PASS")
