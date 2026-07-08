#!/usr/bin/env python3
"""
Verify that on-disk eval suite datasets match the pinned receipt hashes.

Exit codes:
  0: All datasets match their receipt hashes
  1: One or more datasets do not match
  2: Receipt not found or unreadable
"""

import sys
import json
import hashlib
from pathlib import Path

RECEIPT_PATH = Path("receipts/eval-suite-freeze/eval-suite-freeze-v1.json")

def hash_file(path: Path) -> str:
    """Compute SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def verify():
    """Verify all datasets match receipt."""
    # Load receipt
    if not RECEIPT_PATH.exists():
        print(f"[ERROR] Receipt not found: {RECEIPT_PATH}")
        return 2

    with open(RECEIPT_PATH, "r") as f:
        receipt = json.load(f)

    storage_root = Path(receipt["storage_root"])
    all_match = True

    print(f"[INFO] Verifying {len(receipt['datasets'])} datasets against receipt...")
    print(f"[INFO] Storage root: {storage_root}\n")

    for dataset_entry in receipt["datasets"]:
        name = dataset_entry["name"]
        expected_hash = dataset_entry.get("test_split_sha256")
        row_count = dataset_entry.get("row_count")
        size_bytes = dataset_entry.get("size_bytes")

        # Check if dataset is PIN-PENDING
        if dataset_entry.get("pin_status") == "PIN-PENDING":
            print(f"[PENDING] {name}: PIN-PENDING (blocker: {dataset_entry.get('blocker', 'unknown')})")
            continue

        if expected_hash == "PIN-PENDING":
            print(f"[PENDING] {name}: PIN-PENDING")
            continue

        # Locate dataset file
        dataset_dir = storage_root / name.replace(" ", "_").replace("+", "plus")
        test_file = dataset_dir / "test.jsonl"

        if not test_file.exists():
            print(f"[ERROR] {name}: File not found at {test_file}")
            all_match = False
            continue

        # Compute hash
        actual_hash = hash_file(test_file)

        # Compare
        if actual_hash == expected_hash:
            print(f"[OK] {name}: {row_count} rows, {size_bytes} bytes, hash OK")
        else:
            print(f"[ERROR] {name}: Hash mismatch!")
            print(f"   Expected: {expected_hash}")
            print(f"   Actual:   {actual_hash}")
            all_match = False

    print()
    if all_match:
        print("[SUCCESS] All datasets verified successfully.")
        return 0
    else:
        print("[ERROR] One or more datasets failed verification.")
        return 1

if __name__ == "__main__":
    sys.exit(verify())
