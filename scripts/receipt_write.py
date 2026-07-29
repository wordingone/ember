"""receipt_write.py — fail-closed receipt writer (eng #107).

Stages the standardized json.dump bytes from the #103 byte-stability pass,
flushes and fsyncs them, validates the candidate, then atomically publishes
with same-directory os.replace. Any violation QUARANTINES only the staged
candidate at <path>.INVALID.quarantine. Existing canonical bytes remain
unchanged, and partial serialization is never visible at the canonical path.
If publication itself fails, complete candidate bytes are retained at a
recovery path instead of being destroyed.

ember #702 (2026-07-11): the prior delete-on-finding behavior destroyed the
ONLY copy of two separate full-compute runs' results on the same morning — a
434M-cpu microbench (missing sha_convention for invariant_sha256, commit
9ab5e5f) and a 52-minute 2.2B GPU continuation rerun (missing sha_convention
for the checkpoint/manifest sha256 fields). Both runs completed their full
compute; only the receipt-write step failed; the deletion — not the schema
defect — is what actually destroyed the results. Quarantine, never delete.

Public API:
    checked_write(path, obj)
        Stage obj as JSON (utf-8, LF, indent=2), validate it, and atomically
        publish it. On a schema finding, quarantine the staged bytes and
        preserve any existing canonical receipt.

CLI:
    --selftest    Coverage: valid receipt writes byte-identically to a
                  direct json.dump; malformed receipt raises, leaves the
                  ORIGINAL path absent, and quarantines the bytes.
                  Prints RECEIPT_WRITE_SELFTEST_PASS on success.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import argparse
import json
import os
import tempfile
import sys
from pathlib import Path

# Import the frozen validator directly — no shell-out.
sys.path.insert(0, str(Path(__file__).parent))
import receipt_check  # noqa: E402


def checked_write(path: str, obj: dict) -> None:
    """Stage and validate receipt bytes, then publish them atomically.

    The staging file is created in the destination directory, flushed and
    fsynced, then schema-validated before one same-volume os.replace publishes
    it. A partial serialization or invalid candidate is therefore never
    observable at the canonical path and cannot overwrite a last-known-good
    receipt.

    Schema-invalid bytes move from staging to <path>.INVALID.quarantine.
    Existing canonical bytes remain unchanged. Serialization or publication
    failures leave the canonical path unchanged. Partial serialization is
    removed; complete candidates that cannot be published or quarantined are
    retained at an explicit recovery path.
    """
    path = os.path.abspath(os.fspath(path))
    parent = os.path.dirname(path) or os.curdir
    fd, staging_path = tempfile.mkstemp(
        dir=parent,
        prefix=f".{os.path.basename(path)}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        findings = receipt_check.validate_receipt(obj)
        if findings:
            quarantine_path = path + ".INVALID.quarantine"
            try:
                os.replace(staging_path, quarantine_path)
            except OSError as exc:
                retained_path = staging_path
                staging_path = ""
                raise type(exc)(
                    f"{exc}\n  INVALID candidate staging retained: "
                    f"{retained_path}"
                ) from exc
            staging_path = ""
            raise ValueError(
                f"checked_write: {len(findings)} schema finding(s) in {path}:\n"
                + "\n".join(f"  {fn}" for fn in findings)
                + "\n  QUARANTINED (bytes preserved, never deleted): "
                + quarantine_path
            )
        try:
            os.replace(staging_path, path)
        except OSError as publish_exc:
            recovery_path = path + ".PUBLISH_FAILED.quarantine"
            try:
                os.replace(staging_path, recovery_path)
            except OSError as recovery_exc:
                retained_path = staging_path
                staging_path = ""
                raise type(recovery_exc)(
                    f"{recovery_exc}\n  PUBLISH_FAILED candidate staging "
                    f"retained: {retained_path}"
                ) from recovery_exc
            staging_path = ""
            raise type(publish_exc)(
                f"{publish_exc}\n  PUBLISH_FAILED candidate preserved: "
                f"{recovery_path}"
            ) from publish_exc
        staging_path = ""
    finally:
        if staging_path:
            try:
                os.unlink(staging_path)
            except FileNotFoundError:
                pass


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

    # --- Branch B: malformed receipt raises, original path absent, bytes
    # QUARANTINED (never deleted) at <path>.INVALID.quarantine ---
    # Case B1: missing required field
    bad_obj_missing = {
        "ts": "20260611T000000Z",
        "n_rows": 3,
    }
    with tempfile.TemporaryDirectory() as td:
        p_bad = os.path.join(td, "receipt-bad.json")
        q_bad = p_bad + ".INVALID.quarantine"
        raised = False
        err_msg = ""
        try:
            checked_write(p_bad, bad_obj_missing)
        except ValueError as e:
            raised = True
            err_msg = str(e)
        if not raised:
            failures.append("Branch B1 FAIL: missing 'ticket' should raise ValueError")
        if os.path.exists(p_bad):
            failures.append("Branch B1 FAIL: original path must not exist after checked_write")
        elif not os.path.exists(q_bad):
            failures.append("Branch B1 FAIL: quarantine file was not created")
        elif "QUARANTINED" not in err_msg or q_bad not in err_msg:
            failures.append("Branch B1 FAIL: exception message must name the quarantine path")
        else:
            with open(q_bad, encoding="utf-8") as f:
                if json.load(f) != bad_obj_missing:
                    failures.append("Branch B1 FAIL: quarantined bytes do not match the original object")
            print("Branch B1: missing required field — raised, quarantined, bytes verified")

    # Case B2: sha256 field without sha_convention
    bad_obj_sha = {
        "ticket": "ENG-107-SHA-TEST",
        "ts": "20260611T000000Z",
        "ledger_sha256": "deadbeef",
    }
    with tempfile.TemporaryDirectory() as td:
        p_bad2 = os.path.join(td, "receipt-bad-sha.json")
        q_bad2 = p_bad2 + ".INVALID.quarantine"
        raised2 = False
        err_msg2 = ""
        try:
            checked_write(p_bad2, bad_obj_sha)
        except ValueError as e:
            raised2 = True
            err_msg2 = str(e)
        if not raised2:
            failures.append("Branch B2 FAIL: sha256 field without sha_convention should raise ValueError")
        if os.path.exists(p_bad2):
            failures.append("Branch B2 FAIL: original path must not exist after checked_write")
        elif not os.path.exists(q_bad2):
            failures.append("Branch B2 FAIL: quarantine file was not created (sha_convention missing)")
        elif "QUARANTINED" not in err_msg2 or q_bad2 not in err_msg2:
            failures.append("Branch B2 FAIL: exception message must name the quarantine path")
        else:
            with open(q_bad2, encoding="utf-8") as f:
                if json.load(f) != bad_obj_sha:
                    failures.append("Branch B2 FAIL: quarantined bytes do not match the original object")
            print("Branch B2: missing sha_convention — raised, quarantined, bytes verified")

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
