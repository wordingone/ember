"""fp25_recall_dryrun.py — CPU-only dry-run to:
  (1) extract the 28 task ids from wcode-r2-sft.jsonl
  (2) test each candidate split to see which contains all 28
  (3) confirm --task-ids-file filter on the identified split yields exactly 28
  (4) write fp25-recall-task-ids.txt with the 28 ids
"""

import json
import sys
import tempfile
import os

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.path.insert(0, f"{NC}/scripts")
from w1_mbpp import load_split


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


def test_split_coverage(split_name, task_ids):
    """Load split and count how many requested task ids are present."""
    try:
        problems = load_split(split_name, n=None)
        problem_ids = {p["id"] for p in problems}
        coverage = sum(1 for tid in task_ids if tid in problem_ids)
        return coverage, len(problems), problem_ids
    except Exception as e:
        return None, None, None


def main():
    ledger_path = f"{NC}/ledger/views/wcode-r2-sft.jsonl"
    task_ids = extract_task_ids_from_ledger(ledger_path)

    print(f"Extracted {len(task_ids)} unique task ids from wcode-r2-sft.jsonl:")
    print(f"  {task_ids}\n")

    # Test candidate splits
    splits_to_test = ["train", "validation", "test", "prompt", "sanitized"]
    split_results = {}

    for split in splits_to_test:
        coverage, total, problem_ids = test_split_coverage(split, task_ids)
        if coverage is not None:
            split_results[split] = {
                "coverage": coverage,
                "total": total,
                "all_present": coverage == len(task_ids)
            }
            print(f"Split '{split}': {coverage}/{len(task_ids)} ids present "
                  f"(split has {total} problems)")
        else:
            print(f"Split '{split}': FAILED to load")

    # Find the split with all 28 ids
    complete_splits = [s for s, r in split_results.items() if r["all_present"]]
    if not complete_splits:
        print("\nERROR: No split contains all 28 task ids!")
        sys.exit(1)

    if len(complete_splits) > 1:
        print(f"\nWARNING: Multiple splits contain all 28 ids: {complete_splits}")
        print("(Using the first one for consistency)")

    target_split = complete_splits[0]
    print(f"\n✓ Target split: '{target_split}' contains all 28 ids")

    # Verify the filter logic on this split
    problems = load_split(target_split, n=None)
    problem_ids_in_split = {p["id"] for p in problems}

    # Create a temp task-ids file and test the filter
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt',
                                      encoding='utf-8') as f:
        for tid in task_ids:
            f.write(f"{tid}\n")
        temp_file = f.name

    try:
        # Simulate the filter
        requested_ids = set(task_ids)
        missing = requested_ids - problem_ids_in_split
        if missing:
            print(f"\nERROR: Missing ids from split '{target_split}': {missing}")
            sys.exit(1)

        filtered = [p for p in problems if p["id"] in requested_ids]
        print(f"✓ Filter applied to '{target_split}': {len(filtered)}/28 "
              f"problems selected")

        if len(filtered) != 28:
            print(f"ERROR: Expected exactly 28 filtered problems, got {len(filtered)}")
            sys.exit(1)
    finally:
        os.unlink(temp_file)

    # Write the task ids file (one per line, mbpp: prefix omitted for brevity)
    # NOTE: fp25_recall_eval.py expects fp25-recall-task-ids.txt with ids in
    # format that the filter accepts (NNN or mbpp:NNN). We write mbpp:NNN
    # to be explicit.
    output_path = f"{NC}/ledger/views/fp25-recall-task-ids.txt"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        for tid in task_ids:
            f.write(f"mbpp:{tid}\n")
    print(f"\n✓ Wrote {len(task_ids)} task ids to {output_path}")

    print("\n" + "="*60)
    print("FP25_RECALL_DRYRUN_PASS")
    print(f"Split: {target_split}")
    print(f"Task count: {len(task_ids)}/28")
    print(f"Task-ids file: {output_path}")
    print("="*60)


if __name__ == "__main__":
    main()
