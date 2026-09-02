#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Receipt chain-continuity verification for ember totality receipts.

Implements issue #467: walk receipts-totality/ember-totality-*.json in timestamp
order and verify each receipt's prev_totality_receipt_sha256 matches the sha256
of its predecessor file. Detects gaps, forks, orphans, and historical breaks.

The chain_verify function is wired into the board run so every receipt carries
"chain_ok" (bool) and "chain_break" (detail str when false).

Historical receipts lacking prev_totality_receipt_sha256 field are treated as
"pre-chain epoch" boundaries rather than failures.
"""

import hashlib
import json
import os
import re
from typing import Optional, List, Dict, Any, Tuple

# Match canonical receipt filename format: ember-totality-YYYYMMDDTHHMMSSZ.json
_RECEIPT_NAME_RE = re.compile(r"^ember-totality-(\d{8}T\d{6}Z)\.json$")


def _sha256_file(path: str) -> str:
    """Compute sha256 of a file's entire contents (bytes)."""
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except (OSError, IOError) as e:
        raise ValueError(f"Cannot read file {path}: {e}")


def _parse_receipt(path: str) -> Tuple[Dict[str, Any], Optional[str]]:
    """Load and parse a receipt JSON file.

    Returns (parsed_dict, error_msg). error_msg is None on success.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data, None
    except (OSError, IOError, json.JSONDecodeError) as e:
        return {}, f"Cannot parse receipt {path}: {e}"


def extract_ts_from_filename(name: str) -> Optional[str]:
    """Extract YYYYMMDDTHHMMSSZ timestamp from receipt filename, or None."""
    m = _RECEIPT_NAME_RE.match(name)
    return m.group(1) if m else None


def list_receipts_in_order(receipts_dir: str) -> List[Tuple[str, str]]:
    """Return sorted list of (filename, path) tuples for all receipts in directory.

    Sorted by canonical timestamp extracted from filename (YYYYMMDDTHHMMSSZ),
    not mtime, to match the authority established in receipt_ts_authority.py.

    Returns empty list if directory doesn't exist.
    """
    if not os.path.isdir(receipts_dir):
        return []

    receipts = []
    for name in os.listdir(receipts_dir):
        if _RECEIPT_NAME_RE.match(name):
            ts = extract_ts_from_filename(name)
            path = os.path.join(receipts_dir, name)
            if ts:
                receipts.append((ts, name, path))

    # Sort by timestamp
    receipts.sort(key=lambda x: x[0])
    return [(name, path) for ts, name, path in receipts]


def chain_verify(receipts_dir: str, verbose: bool = False) -> Dict[str, Any]:
    """Verify receipt chain continuity in receipts_dir.

    Walks receipts in timestamp order and verifies each receipt's
    prev_totality_receipt_sha256 matches the sha256 of its predecessor file.

    Args:
        receipts_dir: path to receipts-totality/ directory
        verbose: if True, include all receipt details in output

    Returns dict with structure:
        {
            "chain_ok": bool,  # True if entire chain is valid
            "receipt_count": int,
            "receipts": [
                {
                    "name": "ember-totality-YYYYMMDDTHHMMSSZ.json",
                    "chain_ok": bool,
                    "chain_break": str or None,  # Detail when chain_ok=false
                    "prev_expected_sha256": str or None,
                    "prev_actual_sha256": str or None,
                    "file_sha256": str,  # sha256 of this receipt file itself
                    "epoch_boundary": bool,  # True if pre-chain epoch
                    "has_prev_field": bool,
                    "issue": str or None,  # Error reading/parsing receipt
                }
                ...
            ],
            "summary": {
                "total_receipts": int,
                "chain_valid": int,  # Receipts with valid chain links
                "epoch_boundaries": int,  # Receipts starting new chain epoch
                "chain_breaks": int,  # Receipts with detected chain breaks
                "parse_errors": int,  # Receipts that failed to parse
                "details": str or None,  # Human-readable summary
            }
        }
    """
    receipts_list = list_receipts_in_order(receipts_dir)
    receipt_details = []
    parse_errors = 0
    chain_breaks = 0
    epoch_boundaries = 0

    for idx, (name, path) in enumerate(receipts_list):
        data, parse_err = _parse_receipt(path)

        detail = {
            "name": name,
            "chain_ok": False,
            "chain_break": None,
            "prev_expected_sha256": None,
            "prev_actual_sha256": None,
            "file_sha256": None,
            "epoch_boundary": False,
            "has_prev_field": False,
            "issue": parse_err,
        }

        # Compute this receipt's file sha256 for next receipt's verification
        try:
            detail["file_sha256"] = _sha256_file(path)
        except ValueError as e:
            detail["issue"] = str(e)
            parse_errors += 1
            receipt_details.append(detail)
            continue

        if parse_err:
            parse_errors += 1
            receipt_details.append(detail)
            continue

        # Check if receipt has prev_totality_receipt_sha256 field
        prev_sha_field = data.get("prev_totality_receipt_sha256")

        if prev_sha_field is None:
            # Receipt lacks the field entirely -> pre-chain epoch boundary
            detail["epoch_boundary"] = True
            detail["chain_ok"] = True  # Not a break, just a boundary
            epoch_boundaries += 1
            receipt_details.append(detail)
            continue

        detail["has_prev_field"] = True
        detail["prev_expected_sha256"] = prev_sha_field

        if idx == 0:
            # First receipt in chain should have prev sha of 0*64 (no predecessor)
            if prev_sha_field == "0" * 64:
                detail["chain_ok"] = True
            else:
                detail["chain_ok"] = False
                detail["chain_break"] = (
                    f"First receipt should reference 0*64 as predecessor "
                    f"(chain epoch), got {prev_sha_field[:16]}..."
                )
                chain_breaks += 1
        else:
            # Verify against previous receipt
            prev_name, prev_path = receipts_list[idx - 1]
            prev_data, _ = _parse_receipt(prev_path)
            prev_has_field = "prev_totality_receipt_sha256" in prev_data

            # If previous receipt is an epoch boundary (no prev field), this receipt
            # can either reference 0*64 (start new chain) or link to prev file (continue)
            if not prev_has_field:
                # Epoch boundary allows starting a new chain with 0*64 OR linking to the file
                if prev_sha_field == "0" * 64:
                    detail["chain_ok"] = True
                else:
                    # Try to link to the previous file
                    prev_actual_sha = _sha256_file(prev_path)
                    detail["prev_actual_sha256"] = prev_actual_sha
                    if prev_sha_field == prev_actual_sha:
                        detail["chain_ok"] = True
                    else:
                        detail["chain_ok"] = False
                        detail["chain_break"] = (
                            f"After epoch boundary (previous receipt has no prev field), "
                            f"expected either 0*64 or prev file sha, got {prev_sha_field[:16]}..."
                        )
                        chain_breaks += 1
            else:
                # Normal chain link: must match previous file's sha256
                prev_actual_sha = _sha256_file(prev_path)
                detail["prev_actual_sha256"] = prev_actual_sha

                if prev_sha_field == prev_actual_sha:
                    detail["chain_ok"] = True
                else:
                    detail["chain_ok"] = False
                    detail["chain_break"] = (
                        f"Expected prev sha256={prev_sha_field[:16]}... "
                        f"(from {prev_name}), "
                        f"but actual prev file sha256={prev_actual_sha[:16]}... -- "
                        f"chain link broken"
                    )
                    chain_breaks += 1

        receipt_details.append(detail)

    # Compute overall chain status
    chain_valid = sum(1 for r in receipt_details if r["chain_ok"])
    overall_chain_ok = (
        chain_breaks == 0 and
        parse_errors == 0 and
        all(r["chain_ok"] for r in receipt_details)
    )

    summary_lines = []
    summary_lines.append(f"Total receipts: {len(receipts_list)}")
    summary_lines.append(f"  Chain valid: {chain_valid}")
    summary_lines.append(f"  Epoch boundaries (pre-chain): {epoch_boundaries}")
    summary_lines.append(f"  Chain breaks detected: {chain_breaks}")
    summary_lines.append(f"  Parse errors: {parse_errors}")
    if overall_chain_ok:
        summary_lines.append(f"  Status: CHAIN OK")
    else:
        summary_lines.append(f"  Status: CHAIN BROKEN")

    return {
        "chain_ok": overall_chain_ok,
        "receipt_count": len(receipts_list),
        "receipts": receipt_details if verbose else None,
        "summary": {
            "total_receipts": len(receipts_list),
            "chain_valid": chain_valid,
            "epoch_boundaries": epoch_boundaries,
            "chain_breaks": chain_breaks,
            "parse_errors": parse_errors,
            "details": "\n".join(summary_lines),
        }
    }


def add_chain_verification_to_receipt(receipt: Dict[str, Any],
                                       receipts_dir: str) -> Dict[str, Any]:
    """Add chain_ok and chain_break fields to a receipt after board run.

    This is called AFTER the receipt is written to disk, so we can compute
    its sha256 and verify the chain.

    Args:
        receipt: the receipt dict (must already contain prev_totality_receipt_sha256)
        receipts_dir: path to receipts-totality/

    Returns the receipt with added chain_verification block.
    """
    receipt_name = f"ember-totality-{receipt.get('ts')}.json"
    receipt_path = os.path.join(receipts_dir, receipt_name)

    verification = {
        "chain_ok": False,
        "chain_break": None,
        "note": "chain verification requires receipt written to disk",
    }

    # Sanity check: receipt should exist at this point
    if not os.path.isfile(receipt_path):
        verification["chain_break"] = f"Receipt not found at {receipt_path}"
        receipt["chain_verification"] = verification
        return receipt

    # Compute this receipt's sha256
    try:
        receipt_sha = _sha256_file(receipt_path)
    except ValueError as e:
        verification["chain_break"] = str(e)
        receipt["chain_verification"] = verification
        return receipt

    # Check prev_sha field
    prev_sha_field = receipt.get("prev_totality_receipt_sha256")
    if prev_sha_field is None:
        verification["chain_ok"] = True
        verification["note"] = "pre-chain epoch (no prev field)"
        receipt["chain_verification"] = verification
        return receipt

    # Verify chain link: load predecessor and check
    receipts_list = list_receipts_in_order(receipts_dir)
    receipt_names = [name for name, _ in receipts_list]

    if receipt_name not in receipt_names:
        verification["chain_break"] = f"Receipt {receipt_name} not in chronological list"
        receipt["chain_verification"] = verification
        return receipt

    idx = receipt_names.index(receipt_name)

    if idx == 0:
        # First receipt
        if prev_sha_field == "0" * 64:
            verification["chain_ok"] = True
        else:
            verification["chain_break"] = (
                f"First receipt should reference 0*64, got {prev_sha_field[:16]}..."
            )
    else:
        # Verify previous receipt
        prev_name, prev_path = receipts_list[idx - 1]
        try:
            prev_actual_sha = _sha256_file(prev_path)
            if prev_sha_field == prev_actual_sha:
                verification["chain_ok"] = True
            else:
                verification["chain_break"] = (
                    f"Expected prev sha {prev_sha_field[:16]}..., "
                    f"actual {prev_actual_sha[:16]}... from {prev_name}"
                )
        except ValueError as e:
            verification["chain_break"] = f"Cannot verify predecessor: {e}"

    receipt["chain_verification"] = verification
    return receipt
