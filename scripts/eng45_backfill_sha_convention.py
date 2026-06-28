"""eng45_backfill_sha_convention.py — sanctioned scripted backfill (#172).

Two eng-20 license-view receipts were written BEFORE the emitter learned to
stamp `sha_convention` (eng-43 added the schema-floor rule; the emitter fix in
this same PR adds the field going forward).  Those two pre-enforcement receipts
carry `ledger_sha256_before/after` (and the second also `control_sha256_*`) but
no `sha_convention`, so `receipt_check --all` flags them MISSING_SHA_CONVENTION.

This backfill closes that gap WITHOUT hand-editing bytes:
  * reads each named receipt as JSON (insertion order preserved),
  * asserts sha_convention is ABSENT and at least one sha256 field is PRESENT
    (so it only ever touches the exact pre-enforcement receipts, never a
    re-run target),
  * captures every sha256-bearing value verbatim,
  * inserts `sha_convention` immediately after `ts` — the SAME string and
    position the fixed emitter now uses (imported from ledger_license, so a
    backfill and a fresh re-emit are identical),
  * rewrites through the sanctioned `checked_write` (validates fail-closed;
    leaves no file on a schema finding),
  * re-reads from disk and asserts every captured sha256 value is byte-for-byte
    unchanged (provenance preserved — the AC),
  * records what it did in receipts/eng45-backfill-{ts}.json.

Idempotent: a receipt that already has sha_convention is reported SKIPPED, not
rewritten.  Re-running is a no-op.

CLI:
    --run        perform the backfill over the two named receipts
    --selftest   pure-logic coverage on constructed temp receipts; prints
                 ENG45_BACKFILL_SELFTEST_PASS
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import receipt_check  # noqa: E402
from receipt_write import checked_write  # noqa: E402
from ledger_license import SHA_CONVENTION  # noqa: E402  (single source of truth)

NC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECEIPTS = f"{NC}/receipts"

# The exact pre-enforcement receipts named in #172.  Scoped by name so the
# backfill can never touch anything else.
TARGETS = [
    "eng20-license-view-20260611T002458Z.json",
    "eng20-license-view-20260611T004457Z.json",
]


def _sha_values(d: dict) -> dict:
    """Every top-level sha256-bearing field -> value (the provenance we must
    preserve).  Matches receipt_check's sha pattern at the top level."""
    return {k: v for k, v in d.items() if receipt_check._SHA_PATTERN.search(k)}


def _insert_after_ts(d: dict, key: str, value) -> dict:
    """Return a new dict with `key`:`value` inserted immediately after 'ts',
    preserving all other key order.  Mirrors the emitter, which writes
    sha_convention right after the ticket/ts header."""
    out = {}
    for k, v in d.items():
        out[k] = v
        if k == "ts":
            out[key] = value
    if key not in out:  # no 'ts' (shouldn't happen for these receipts) — append
        out[key] = value
    return out


def backfill_one(path: str) -> dict:
    """Backfill a single receipt.  Returns a per-file record dict for the
    backfill receipt.  Raises on any provenance or schema violation."""
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)

    name = os.path.basename(path)
    sha_before = _sha_values(d)

    if not sha_before:
        raise ValueError(f"{name}: no sha256 field present — not a backfill target")

    if "sha_convention" in d:
        return {"file": name, "action": "SKIPPED",
                "reason": "sha_convention already present",
                "sha_fields": sorted(sha_before.keys())}

    # Insert in the emitter's position and rewrite fail-closed.
    new_d = _insert_after_ts(d, "sha_convention", SHA_CONVENTION)
    checked_write(path, new_d)

    # Re-read from disk and prove every sha value is unchanged.
    with open(path, "r", encoding="utf-8") as f:
        reread = json.load(f)
    sha_after = _sha_values(reread)
    if sha_after != sha_before:
        raise ValueError(
            f"{name}: PROVENANCE VIOLATION — sha values changed by backfill\n"
            f"  before={sha_before}\n  after ={sha_after}")
    if reread.get("sha_convention") != SHA_CONVENTION:
        raise ValueError(f"{name}: sha_convention not present after rewrite")

    return {"file": name, "action": "BACKFILLED",
            "sha_fields": sorted(sha_before.keys()),
            "sha_values_unchanged": True,
            "sha_convention": SHA_CONVENTION}


def run() -> int:
    records = []
    for t in TARGETS:
        path = f"{RECEIPTS}/{t}"
        if not os.path.exists(path):
            raise FileNotFoundError(f"target receipt missing: {path}")
        rec = backfill_one(path)
        records.append(rec)
        print(f"  {rec['action']}: {rec['file']}")

    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    receipt = {
        "ticket": "ENG45-BACKFILL-SHA-CONVENTION",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "issue": "#172",
        "method": "scripted backfill via receipt_write.checked_write; "
                  "sha_convention inserted after 'ts'; sha256 values "
                  "re-read from disk and asserted byte-unchanged",
        "n_targets": len(TARGETS),
        "n_backfilled": sum(1 for r in records if r["action"] == "BACKFILLED"),
        "n_skipped": sum(1 for r in records if r["action"] == "SKIPPED"),
        "files": records,
    }
    out = f"{RECEIPTS}/eng45-backfill-{ts}.json"
    checked_write(out, receipt)
    print(f"  backfill receipt: {os.path.basename(out)}")

    # Final fail-closed gate: every target now validates clean.
    for t in TARGETS:
        findings = receipt_check.validate_receipt(
            json.load(open(f"{RECEIPTS}/{t}", encoding="utf-8")))
        if findings:
            raise ValueError(f"{t} still has findings after backfill: {findings}")
    print("ENG45_BACKFILL_DONE")
    return 0


def _selftest() -> int:
    import tempfile
    failures = []

    with tempfile.TemporaryDirectory() as td:
        # A pre-enforcement receipt: sha fields, no sha_convention.
        pre = {
            "ticket": "ENG20-LICENSE-VIEW",
            "ts": "20260611T002458Z",
            "view_rows": 2865,
            "ledger_sha256_before": "763d785803dfc85b1a6876d8ffc1810134145848"
                                    "f9db4be8a3f6cfe5d4a25368",
            "ledger_sha256_after": "763d785803dfc85b1a6876d8ffc1810134145848"
                                   "f9db4be8a3f6cfe5d4a25368",
            "control_sha256_before": "fa286e4ea77c74b9b1abf40ccf655efbaf120fe5"
                                     "a57fbc9065ef3c3976b61bb9",
        }
        p = os.path.join(td, "pre.json")
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(pre, f, indent=2)

        # Baseline: flagged MISSING_SHA_CONVENTION.
        if "MISSING_SHA_CONVENTION" not in " ".join(
                receipt_check.validate_receipt(pre)):
            failures.append("setup FAIL: pre-receipt should be flagged")

        sha_before = _sha_values(pre)
        rec = backfill_one(p)
        if rec["action"] != "BACKFILLED":
            failures.append(f"FAIL: expected BACKFILLED, got {rec['action']}")

        reread = json.load(open(p, encoding="utf-8"))
        # sha_convention present, after 'ts', and clean now.
        if reread.get("sha_convention") != SHA_CONVENTION:
            failures.append("FAIL: sha_convention not inserted")
        keys = list(reread.keys())
        if keys.index("sha_convention") != keys.index("ts") + 1:
            failures.append("FAIL: sha_convention not positioned right after 'ts'")
        if receipt_check.validate_receipt(reread):
            failures.append("FAIL: backfilled receipt still has findings")
        # Provenance: every sha value identical.
        if _sha_values(reread) != sha_before:
            failures.append("FAIL: sha values changed by backfill")

        # Idempotency: second run SKIPS, bytes unchanged.
        bytes_after_1 = open(p, "rb").read()
        rec2 = backfill_one(p)
        if rec2["action"] != "SKIPPED":
            failures.append(f"FAIL: re-run should SKIP, got {rec2['action']}")
        if open(p, "rb").read() != bytes_after_1:
            failures.append("FAIL: idempotent re-run rewrote bytes")

        # Guard: a receipt with NO sha field is not a target.
        nosha = {"ticket": "X", "ts": "20260611T000000Z", "n_rows": 1}
        q = os.path.join(td, "nosha.json")
        with open(q, "w", encoding="utf-8", newline="\n") as f:
            json.dump(nosha, f, indent=2)
        raised = False
        try:
            backfill_one(q)
        except ValueError:
            raised = True
        if not raised:
            failures.append("FAIL: no-sha receipt should raise (not a target)")

    # Source assert: backfill reuses the emitter's convention, not a literal.
    src = open(__file__, encoding="utf-8").read()
    if "from ledger_license import SHA_CONVENTION" not in src:
        failures.append("FAIL: backfill must import SHA_CONVENTION from emitter")

    if failures:
        for f in failures:
            print(f"SELFTEST: {f}")
        return 1
    print("ENG45_BACKFILL_SELFTEST_PASS")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="eng45 scripted sha_convention backfill (#172)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", action="store_true", help="perform the backfill")
    g.add_argument("--selftest", action="store_true", help="pure-logic selftest")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(_selftest())
    else:
        sys.exit(run())


if __name__ == "__main__":
    main()
