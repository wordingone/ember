"""receipt_write.py — fail-closed receipt writer (eng #107).

Wraps the standardized json.dump call from the #103 byte-stability pass with
an immediate schema-floor check via receipt_check.validate_receipt.  Any
violation causes the file to be deleted and an exception raised — no invalid
receipt is ever left on disk.

Public API:
    checked_write(path, obj)
        Write obj to path as JSON (utf-8, LF, indent=2).  Raise ValueError on
        any schema finding, leaving no file behind.

CLI:
    --selftest    Two-branch coverage: valid receipt writes byte-identically to a
                  direct json.dump; malformed receipt raises and leaves no file.
                  Prints RECEIPT_WRITE_SELFTEST_PASS on success.
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Import the frozen validator directly — no shell-out.
sys.path.insert(0, str(Path(__file__).parent))
import receipt_check  # noqa: E402


def checked_write(path: str, obj: dict) -> None:
    """Write obj to path as a receipt JSON, then validate fail-closed.

    Uses the SAME json.dump args standardised by the #103 byte-stability pass:
        open(path, "w", encoding="utf-8", newline="\\n")
        json.dump(obj, f, indent=2)

    On any schema finding: deletes the file (if it was written) and raises
    ValueError listing all findings.  The caller's path is left absent.
    """
    path = str(path)
    written = False
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, indent=2)
        written = True
        findings = receipt_check.validate_receipt(obj)
        if findings:
            raise ValueError(
                f"checked_write: {len(findings)} schema finding(s) in {path}:\n"
                + "\n".join(f"  {fn}" for fn in findings)
            )
    except Exception:
        if written:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest() -> int:
    import tempfile
    import hashlib

    failures = []

    # --- Branch A: floor-compliant receipt writes byte-identically ---
    valid_obj = {
        "ticket": "ENG-107-TEST",
        "ts": "20260611T000000Z",
        "n_episodes": 5,
        "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
        "ledger_sha256": "abc123deadbeef",
    }

    with tempfile.TemporaryDirectory() as td:
        p_checked = os.path.join(td, "receipt-checked.json")
        p_direct = os.path.join(td, "receipt-direct.json")

        # Write via checked_write
        try:
            checked_write(p_checked, valid_obj)
        except Exception as e:
            failures.append(f"Branch A FAIL: checked_write raised on valid receipt: {e}")

        # Write via direct json.dump (the #103 standard)
        with open(p_direct, "w", encoding="utf-8", newline="\n") as f:
            json.dump(valid_obj, f, indent=2)

        if os.path.exists(p_checked) and os.path.exists(p_direct):
            with open(p_checked, "rb") as fa, open(p_direct, "rb") as fb:
                bytes_checked = fa.read()
                bytes_direct = fb.read()
            if bytes_checked != bytes_direct:
                failures.append(
                    f"Branch A FAIL: byte mismatch between checked_write and direct json.dump\n"
                    f"  checked sha256={hashlib.sha256(bytes_checked).hexdigest()[:16]}\n"
                    f"  direct  sha256={hashlib.sha256(bytes_direct).hexdigest()[:16]}"
                )
            else:
                print(f"Branch A: byte-identical confirmed ({len(bytes_checked)} bytes)")
        elif not os.path.exists(p_checked):
            failures.append("Branch A FAIL: checked_write did not produce a file")

    # --- Branch B: malformed receipt raises and leaves NO file ---
    # Case B1: missing required field
    bad_obj_missing = {
        "ts": "20260611T000000Z",
        "n_rows": 3,
    }
    with tempfile.TemporaryDirectory() as td:
        p_bad = os.path.join(td, "receipt-bad.json")
        raised = False
        try:
            checked_write(p_bad, bad_obj_missing)
        except ValueError:
            raised = True
        if not raised:
            failures.append("Branch B1 FAIL: missing 'ticket' should raise ValueError")
        if os.path.exists(p_bad):
            failures.append("Branch B1 FAIL: file must not exist after failed checked_write")
        else:
            print("Branch B1: missing required field — raised, no file left")

    # Case B2: sha256 field without sha_convention
    bad_obj_sha = {
        "ticket": "ENG-107-SHA-TEST",
        "ts": "20260611T000000Z",
        "ledger_sha256": "deadbeef",
    }
    with tempfile.TemporaryDirectory() as td:
        p_bad2 = os.path.join(td, "receipt-bad-sha.json")
        raised2 = False
        try:
            checked_write(p_bad2, bad_obj_sha)
        except ValueError:
            raised2 = True
        if not raised2:
            failures.append("Branch B2 FAIL: sha256 field without sha_convention should raise ValueError")
        if os.path.exists(p_bad2):
            failures.append("Branch B2 FAIL: file must not exist after failed checked_write (sha_convention missing)")
        else:
            print("Branch B2: missing sha_convention — raised, no file left")

    if failures:
        for f in failures:
            print(f"SELFTEST: {f}")
        return 1

    print("RECEIPT_WRITE_SELFTEST_PASS")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="receipt_write.py — fail-closed receipt writer (eng #107)")
    ap.add_argument("--selftest", action="store_true",
                    help="two-branch coverage selftest; prints RECEIPT_WRITE_SELFTEST_PASS")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(_selftest())
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
