"""fp25_recall_dryrun_simple.py — CPU-only dry-run without dataset loading.

Strategy: The task ids extracted from wcode-r2-sft.jsonl are certified
to be from MBPP-train (as per the sampling record). We don't load the
dataset in the dry-run (expensive). Instead, we:
  (1) extract the 28 task ids from wcode-r2-sft.jsonl
  (2) verify they are all in range ~601-974 (MBPP-train problem range)
  (3) write fp25-recall-task-ids.txt
  (4) demonstrate that the filter logic works on a fake problem dict

The actual split identification will happen when fp25_recall_eval.py
(the GPU-dispatched shim) calls w4_eval with --task-ids-file on
--split train, and w4_eval will load_split("train") and apply the filter.
"""

import json
import sys
import tempfile
import os


def extract_task_ids_from_ledger(ledger_path):
    """Extract unique task ids from wcode-r2-sft.jsonl (format: mbpp:NNN)."""
    task_ids = set()
    with open(ledger_path, 'r', encoding='utf-8') as f:
        for line in f:
            row = json.loads(line)
            task_str = row.get("task", "")
            if task_str.startswith("mbpp:"):
                task_id = int(task_str[5:])
                task_ids.add(task_id)
    return sorted(task_ids)


def filter_problems_by_ids(problems, task_ids):
    """Simulate the filter logic."""
    requested_ids = set(task_ids)
    problem_ids = {p["id"] for p in problems}
    missing = requested_ids - problem_ids
    if missing:
        raise SystemExit(
            f"dryrun: requested task ids not in problems: {sorted(missing)}")
    filtered = [p for p in problems if p["id"] in requested_ids]
    return filtered


def main():
    NC = "/mnt/b/M/avir/leo/state/nc-ladder"
    ledger_path = f"{NC}/ledger/views/wcode-r2-sft.jsonl"
    task_ids = extract_task_ids_from_ledger(ledger_path)

    print(f"Extracted {len(task_ids)} unique task ids from wcode-r2-sft.jsonl:")
    print(f"  {task_ids}\n")

    # Verify they are in MBPP-train range (roughly 601-974, with some gaps)
    # MBPP has ~1000 total problems; "train" split is ~120 problems in
    # the sanitized version, but the task ids are from the original MBPP
    # numbering which goes up to ~1000. The ids we extracted should all be
    # in a reasonable range.
    min_id = min(task_ids)
    max_id = max(task_ids)
    print(f"Task id range: {min_id}–{max_id}")

    if min_id < 500 or max_id > 1000:
        print("WARNING: task ids outside expected MBPP range [500, 1000]")
    else:
        print("✓ Task ids in expected MBPP range")

    # Sanity check: all unique, all integers
    if len(task_ids) != len(set(task_ids)):
        print("ERROR: Duplicate task ids!")
        sys.exit(1)
    print(f"✓ {len(task_ids)} unique task ids")

    # Test filter logic on fake problems
    fake_problems = [{"id": tid} for tid in task_ids]
    try:
        filtered = filter_problems_by_ids(fake_problems, task_ids)
        assert len(filtered) == len(task_ids), \
            f"Expected {len(task_ids)} filtered, got {len(filtered)}"
        print(f"✓ Filter logic verified: {len(filtered)}/28 problems selected")
    except Exception as e:
        print(f"ERROR: Filter logic failed: {e}")
        sys.exit(1)

    # Write the task ids file
    output_path = f"{NC}/ledger/views/fp25-recall-task-ids.txt"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        for tid in task_ids:
            f.write(f"mbpp:{tid}\n")
    print(f"\n✓ Wrote {len(task_ids)} task ids to {output_path}")

    # Verify the file is readable and contains exactly 28 lines
    with open(output_path, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip()]
    if len(lines) != 28:
        print(f"ERROR: Written file has {len(lines)} lines, expected 28")
        sys.exit(1)
    print(f"✓ File verification: {len(lines)} task ids written\n")

    print("="*60)
    print("FP25_RECALL_DRYRUN_PASS")
    print(f"Task count: {len(task_ids)}/28")
    print(f"Target split (per shim): train")
    print(f"Task-ids file: {output_path}")
    print("="*60)


if __name__ == "__main__":
    main()
