"""receipt_check.py — fail-closed receipt-schema floor validator (eng #103).

Validates receipts/*.json against the minimum schema floor:

  REQUIRED fields: ticket, ts
  SHA-CONVENTION rule: any field whose name matches *sha256* or *_sha256*
    or any sha_convention-adjacent hash claim (sha256_before, sha256_after,
    sha256, etc.) requires sha_convention to be present in the receipt.
  INTEGER rule: flip/count-like fields (n_*, *_count, guard_flips, rows,
    and counters inside flips arrays) must be ints, not strings.

Modes:
  --all         report-only over every receipt in receipts/ (exit 0 always;
                legacy receipts get findings listed by violation class)
  --file X      fail-closed on a single receipt (exit non-zero on any violation)
  --selftest    pure-logic test using constructed temp receipts; prints
                RECEIPT_CHECK_SELFTEST_PASS on success; exits non-zero on failure

sha_convention for this receipt (when written by the --backfill path or any
  artifact writer): "bytes on disk as-is (binary read, no line-ending
  normalization)".
"""
import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Legacy-exempt list (Row 8 — receipt hygiene triage 2026-06-12)
#
# Files in receipts/ that predate the R1 (ticket/ts required) schema floor.
# --all mode skips them silently; --file remains strict (fail-closed on demand).
# To add a new entry: append the basename + one-line reason. Never remove.
# ---------------------------------------------------------------------------

LEGACY_EXEMPT: frozenset[str] = frozenset({
    "eng105-verify-20260611T023239Z.json",       # pre-R1: no ticket/ts
    "grpo-attempts-fail-20260610.json",           # pre-R1: no ticket
    "native-smoke-20260610T230236Z.json",         # pre-R1: no ticket/ts
    "native-smoke-20260610T230645Z.json",         # pre-R1: no ticket/ts
    "probe-meminfo-20260610T043457Z.json",        # pre-R1: no ticket
    "c10-resident-live-20260612T213002Z.json",   # superseded by 213133Z emission (ticket field added there; bounce 15069)
    "sp6b-tooling-dryrun-20260612T155736Z.json", # superseded by 192300Z emission (ticket field added there; kai flag 14982)
    "t4-r1-q15-arc1-seed14-progress.json",       # pre-R1: training progress artifact, no ticket/ts
    "t4-r1-q3-arc1-seed14-progress.json",        # pre-R1: training progress artifact, no ticket/ts
    "t4-r1-q3-arc1-seed15-progress.json",        # pre-R1: training progress artifact, no ticket/ts
    "train_config.json",                          # not a receipt — training harness config in receipts/
    "wsl9p-probe-2026-06-10T225917Z.json",       # pre-R1: no ticket/ts
})

# ---------------------------------------------------------------------------
# Schema rules
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {"ticket", "ts"}

# Fields whose names indicate sha256 hash values — when any of these exist,
# sha_convention must be present.
_SHA_PATTERN = re.compile(
    r"sha256|sha_256|sha256_before|sha256_after|sha256_initial|sha256_final",
    re.IGNORECASE,
)

# Fields that must be int (not str) — top-level fields
_COUNT_TOP_PATTERN = re.compile(
    r"^(n_|.*_count$|guard_flips$|rows$)",
    re.IGNORECASE,
)


def _has_sha_field(d: dict) -> bool:
    """Return True if any key in the dict (recursively, up to depth 3) matches
    a sha256 field name."""
    def _check(obj, depth):
        if depth == 0 or not isinstance(obj, dict):
            return False
        for k, v in obj.items():
            if _SHA_PATTERN.search(k):
                return True
            if isinstance(v, dict) and _check(v, depth - 1):
                return True
        return False
    return _check(d, 3)


def _count_violations(d: dict) -> list[str]:
    """Return list of violation descriptions for integer-type fields that have
    string values."""
    violations = []
    for k, v in d.items():
        if _COUNT_TOP_PATTERN.match(k) and isinstance(v, str):
            violations.append(f"field '{k}' should be int, got str: {v!r}")
    # Check inside 'flips' array if present
    flips = d.get("flips")
    if isinstance(flips, list):
        for i, item in enumerate(flips):
            if isinstance(item, dict):
                for k, v in item.items():
                    if _COUNT_TOP_PATTERN.match(k) and isinstance(v, str):
                        violations.append(
                            f"flips[{i}].{k!r} should be int, got str: {v!r}")
    return violations


def validate_receipt(d: dict) -> list[str]:
    """Validate a parsed receipt dict. Returns list of finding strings (empty = clean)."""
    findings = []

    # R1: required fields
    for field in sorted(REQUIRED_FIELDS):
        if field not in d:
            findings.append(f"MISSING_REQUIRED: '{field}' not present")

    # R2: sha_convention required when any sha256 field exists
    if _has_sha_field(d) and "sha_convention" not in d:
        findings.append(
            "MISSING_SHA_CONVENTION: receipt contains sha256 field(s) but "
            "sha_convention is absent"
        )

    # R3: integer fields must be int not str
    int_violations = _count_violations(d)
    for v in int_violations:
        findings.append(f"INT_AS_STRING: {v}")

    return findings


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def _load_json(path: str) -> tuple[dict | None, str | None]:
    """Load a JSON file. Returns (dict, None) on success or (None, error_msg)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"
    except OSError as e:
        return None, f"OS error: {e}"


def run_all(receipts_dir: str) -> int:
    """Report-only mode over all receipts in receipts_dir. Always exits 0."""
    dir_path = Path(receipts_dir)
    files = sorted(dir_path.glob("*.json"))
    if not files:
        print(f"receipt_check --all: no .json files in {receipts_dir}")
        return 0

    violation_counts: dict[str, int] = {}
    total_files = 0
    files_with_findings = 0

    grandfathered = 0
    for fpath in files:
        total_files += 1
        if fpath.name in LEGACY_EXEMPT:
            grandfathered += 1
            continue
        d, err = _load_json(str(fpath))
        if err:
            print(f"  PARSE_ERROR {fpath.name}: {err}")
            violation_counts["PARSE_ERROR"] = violation_counts.get("PARSE_ERROR", 0) + 1
            files_with_findings += 1
            continue

        findings = validate_receipt(d)
        if findings:
            files_with_findings += 1
            print(f"  {fpath.name}: {len(findings)} finding(s)")
            for f in findings:
                category = f.split(":")[0]
                violation_counts[category] = violation_counts.get(category, 0) + 1
                print(f"    {f}")

    print(f"\nreceipt_check --all: {total_files} receipts scanned, "
          f"{grandfathered} grandfathered (LEGACY_EXEMPT), "
          f"{files_with_findings} with findings")
    if violation_counts:
        print("  Violation counts by class:")
        for cls, cnt in sorted(violation_counts.items()):
            print(f"    {cls}: {cnt}")
    else:
        print("  No violations found.")

    return 0


def run_file(path: str) -> int:
    """Fail-closed mode on a single receipt. Returns non-zero on any violation."""
    d, err = _load_json(path)
    if err:
        print(f"receipt_check --file: FAIL (parse error) {path}")
        print(f"  {err}")
        return 1

    findings = validate_receipt(d)
    if findings:
        print(f"receipt_check --file: FAIL ({len(findings)} finding(s)) {path}")
        for f in findings:
            print(f"  {f}")
        return 1

    print(f"receipt_check --file: PASS {path}")
    return 0


# ---------------------------------------------------------------------------
# Selftest (pure-logic, no external files)
# ---------------------------------------------------------------------------

def _selftest() -> int:
    """Construct pass/fail receipts via temp files and verify validator behavior.
    Returns 0 on success, 1 on failure.
    """
    failures = []

    def _write_temp(obj: dict) -> str:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f)
        return path

    def _cleanup(*paths):
        for p in paths:
            try:
                os.unlink(p)
            except OSError:
                pass

    # --- Case 1: conforming receipt must PASS --file ---
    p1 = _write_temp({
        "ticket": "TEST-1",
        "ts": "20260611T000000Z",
        "n_episodes": 10,
        "sha_convention": "bytes on disk as-is",
        "ledger_sha256": "abc123",
    })
    result1 = run_file(p1)
    if result1 != 0:
        failures.append("Case 1 FAIL: conforming receipt should pass --file")
    _cleanup(p1)

    # --- Case 2: missing ticket must FAIL --file ---
    p2 = _write_temp({
        "ts": "20260611T000000Z",
        "n_rows": 5,
    })
    result2 = run_file(p2)
    if result2 == 0:
        failures.append("Case 2 FAIL: missing 'ticket' should fail --file")
    _cleanup(p2)

    # --- Case 3: hash field without sha_convention must FAIL --file ---
    p3 = _write_temp({
        "ticket": "TEST-3",
        "ts": "20260611T000000Z",
        "view_sha256_before": "deadbeef",
    })
    result3 = run_file(p3)
    if result3 == 0:
        failures.append("Case 3 FAIL: hash field without sha_convention should fail --file")
    _cleanup(p3)

    # --- Case 4: string count field must FAIL --file ---
    p4 = _write_temp({
        "ticket": "TEST-4",
        "ts": "20260611T000000Z",
        "n_episodes": "42",  # should be int
    })
    result4 = run_file(p4)
    if result4 == 0:
        failures.append("Case 4 FAIL: n_episodes as string should fail --file")
    _cleanup(p4)

    # --- Case 5: report-only --all mode exits 0 on the same failures ---
    # Write all three failing receipts into a temp dir; --all should exit 0
    tmpdir = tempfile.mkdtemp()
    try:
        for i, obj in enumerate([
            {"ts": "20260611T000000Z"},  # missing ticket
            {"ticket": "T", "ts": "20260611T000000Z", "sha256_before": "x"},  # missing sha_convention
            {"ticket": "T", "ts": "20260611T000000Z", "n_count": "5"},  # string count
        ]):
            p = os.path.join(tmpdir, f"receipt-{i}.json")
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                json.dump(obj, f)
        result5 = run_all(tmpdir)
        if result5 != 0:
            failures.append("Case 5 FAIL: --all mode should exit 0 even with findings")
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    if failures:
        for f in failures:
            print(f"SELFTEST: {f}")
        return 1

    print("RECEIPT_CHECK_SELFTEST_PASS")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="receipt_check.py — receipt schema floor validator (eng #103)")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", metavar="DIR", nargs="?",
                       const="receipts",
                       help="report-only scan of all receipts in DIR (default: receipts/)")
    group.add_argument("--file", metavar="PATH",
                       help="fail-closed check on a single receipt file")
    group.add_argument("--selftest", action="store_true",
                       help="pure-logic selftest")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(_selftest())
    elif args.file:
        sys.exit(run_file(args.file))
    else:
        receipts_dir = args.all if args.all else "receipts"
        sys.exit(run_all(receipts_dir))


if __name__ == "__main__":
    main()
