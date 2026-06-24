"""ember_tally.py — completeness tally over docs/ember-completeness.md (#337).

Parses the manifest table, validates receipt pointers via receipt_check,
classifies rows, emits receipts/tally-<ts>.json.

Row classification (authoritative):
  implemented  — status=DONE and receipt validates
  part         — status=PART (regardless of receipt; partial evidence)
  gated        — status starts with GATED:
  open         — all others (OPEN, or status advisory + missing/failing receipt)

Receipt validation (for rows with a locatable receipt):
  A receipt pointer is locatable if it contains a token that exists as
  receipts/<token>.json (exact name with or without .json extension).
  Validated via receipt_check.validate_receipt() (fail-closed).
  Missing or failing receipt on a DONE row downgrades to 'open'.

--selftest : run on a synthetic manifest; exits nonzero on any failure.
--run      : run on the real docs/ember-completeness.md (dry output).
--emit     : --run + write tally receipt to receipts/.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from receipt_check import validate_receipt
from receipt_write import checked_write

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"

_TABLE_ROW_RE = re.compile(
    r"^\|\s*(C\d+)\s*\|"      # id
    r"\s*([^|]*?)\s*\|"       # subgoal
    r"\s*([^|]*?)\s*\|"       # piece
    r"\s*([^|]*?)\s*\|"       # AC/test
    r"\s*([^|]*?)\s*\|"       # receipt
    r"\s*([^|]*?)\s*\|"       # status
)

# Tokens in receipt column that may be actual filenames in receipts/
_FILENAME_CHARS = re.compile(r"[a-zA-Z0-9_\-]+(?:\.json)?")


def _find_receipt(nc_dir: str, pointer: str) -> str | None:
    """Return path to receipt JSON if any token in pointer resolves to one."""
    receipts_dir = os.path.join(nc_dir, "receipts")
    for token in _FILENAME_CHARS.findall(pointer):
        for suffix in ("", ".json"):
            candidate = os.path.join(receipts_dir, token + suffix)
            if os.path.isfile(candidate):
                return candidate
    return None


def _validate_receipt_path(path: str) -> list[str]:
    """Return receipt_check findings (empty = clean)."""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return [f"parse error: {e}"]
    return validate_receipt(d)


def parse_manifest(text: str) -> list[dict]:
    """Parse the markdown table. Returns list of row dicts."""
    rows = []
    for line in text.splitlines():
        m = _TABLE_ROW_RE.match(line)
        if not m:
            continue
        row_id, subgoal, piece, ac, receipt, status = (g.strip() for g in m.groups())
        rows.append({
            "id": row_id,
            "subgoal": subgoal,
            "piece": piece,
            "ac": ac,
            "receipt_pointer": receipt,
            "status_advisory": status,
        })
    return rows


def classify_row(row: dict, nc_dir: str) -> dict:
    """Classify a single row. Returns enriched dict with 'classification'."""
    r = dict(row)
    status = row["status_advisory"].upper()
    pointer = row["receipt_pointer"]
    em_dash = pointer in ("—", "-", "", "–")

    if status.startswith("GATED"):
        r["classification"] = "gated"
        r["gated_on"] = row["status_advisory"][len("GATED:"):].strip() if ":" in row["status_advisory"] else ""
        return r

    if status.startswith("DONE"):
        receipt_path = _find_receipt(nc_dir, pointer)
        if receipt_path:
            findings = _validate_receipt_path(receipt_path)
            if findings:
                r["classification"] = "open"
                r["receipt_findings"] = findings
                r["receipt_path"] = receipt_path
            else:
                r["classification"] = "implemented"
                r["receipt_path"] = receipt_path
        else:
            r["classification"] = "open"
            r["receipt_missing"] = pointer
        return r

    if status.startswith("PART"):
        r["classification"] = "part"
        receipt_path = _find_receipt(nc_dir, pointer)
        if receipt_path:
            r["receipt_path"] = receipt_path
        return r

    # OPEN or unrecognized
    r["classification"] = "open"
    if em_dash:
        r["receipt_missing"] = None
    else:
        receipt_path = _find_receipt(nc_dir, pointer)
        if receipt_path:
            findings = _validate_receipt_path(receipt_path)
            if not findings:
                r["classification"] = "part"
                r["receipt_path"] = receipt_path
    return r


def tally(rows: list[dict], nc_dir: str) -> dict:
    """Classify all rows and produce summary counts."""
    classified = [classify_row(r, nc_dir) for r in rows]
    total = len(classified)
    implemented = [r for r in classified if r["classification"] == "implemented"]
    part = [r for r in classified if r["classification"] == "part"]
    gated = [r for r in classified if r["classification"] == "gated"]
    open_ = [r for r in classified if r["classification"] == "open"]
    pct = round(len(implemented) / total * 100, 1) if total else 0.0

    # per-subgoal breakdown
    subgoals = {}
    for r in classified:
        sg = r["subgoal"]
        if sg not in subgoals:
            subgoals[sg] = {"implemented": 0, "part": 0, "gated": 0, "open": 0}
        subgoals[sg][r["classification"]] += 1

    missing = [{"id": r["id"], "reason": r.get("receipt_missing", "open")} for r in open_]

    return {
        "total": total,
        "implemented": len(implemented),
        "part": len(part),
        "gated": len(gated),
        "open": len(open_),
        "pct_implemented": pct,
        "missing": missing,
        "per_subgoal": subgoals,
        "classified_rows": classified,
    }


def _load_manifest(nc_dir: str) -> str:
    path = os.path.join(nc_dir, "docs", "ember-completeness.md")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _run_tally(nc_dir: str) -> dict:
    text = _load_manifest(nc_dir)
    rows = parse_manifest(text)
    if not rows:
        raise SystemExit("EMBER_TALLY: no rows parsed from manifest — parse drift?")
    return tally(rows, nc_dir)


def _print_summary(result: dict):
    print(f"EMBER_TALLY: {result['implemented']}/{result['total']} implemented "
          f"({result['pct_implemented']}%), "
          f"{result['part']} part, {result['gated']} gated, {result['open']} open")
    if result["missing"]:
        for m in result["missing"]:
            print(f"  OPEN: {m['id']} ({m['reason']})")
    print("Per subgoal:")
    for sg, counts in sorted(result["per_subgoal"].items()):
        print(f"  {sg}: {counts}")


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

_SYNTHETIC_MANIFEST = """\
# Synthetic test manifest

| id | subgoal | piece | AC | receipt | status |
|----|---------|-------|----|---------|--------|
| C1 | S1 | done piece | receipt validates | REPLACE_DONE_RECEIPT | DONE |
| C2 | S2 | part piece | partial | some-reference | PART |
| C3 | S3 | open piece | nothing | — | OPEN |
| C4 | S4 | gated piece | needs C1 | — | GATED:C1 |
| C5 | S5 | done missing | no file | nonexistent-file-xyz | DONE |
"""

_MALFORMED_MANIFEST = """\
# Malformed manifest — no table rows

Just text, no pipe rows.
"""


def _selftest():
    import tempfile
    failures = []

    # Create a temp NC dir with receipts/
    tmpdir = tempfile.mkdtemp()
    receipts_dir = os.path.join(tmpdir, "receipts")
    os.makedirs(receipts_dir)
    docs_dir = os.path.join(tmpdir, "docs")
    os.makedirs(docs_dir)

    # Write a valid receipt
    good_receipt = {
        "ticket": "SELFTEST-DONE-RECEIPT",
        "ts": "20260612T000000Z",
    }
    good_receipt_name = "selftest-done-receipt-20260612T000000Z.json"
    good_path = os.path.join(receipts_dir, good_receipt_name)
    with open(good_path, "w", newline="\n", encoding="utf-8") as f:
        json.dump(good_receipt, f)

    synthetic = _SYNTHETIC_MANIFEST.replace(
        "REPLACE_DONE_RECEIPT", good_receipt_name.replace(".json", ""))

    # Case 1: Parse synthetic manifest
    rows = parse_manifest(synthetic)
    if len(rows) != 5:
        failures.append(f"Case 1: expected 5 rows, got {len(rows)}")

    # Case 2: Tally produces correct counts
    result = tally(rows, tmpdir)
    if result["total"] != 5:
        failures.append(f"Case 2: total should be 5, got {result['total']}")
    if result["implemented"] != 1:
        failures.append(f"Case 2: implemented should be 1, got {result['implemented']}")
    if result["part"] != 1:
        failures.append(f"Case 2: part should be 1, got {result['part']}")
    if result["gated"] != 1:
        failures.append(f"Case 2: gated should be 1, got {result['gated']}")
    if result["open"] != 2:
        failures.append(f"Case 2: open should be 2 (OPEN + DONE-missing), got {result['open']}")

    # Case 3: DONE with missing receipt downgrades to 'open'
    c5 = next(r for r in result["classified_rows"] if r["id"] == "C5")
    if c5["classification"] != "open":
        failures.append(f"Case 3: C5 (DONE with missing receipt) should be open, got {c5['classification']}")

    # Case 4: GATED row is gated
    c4 = next(r for r in result["classified_rows"] if r["id"] == "C4")
    if c4["classification"] != "gated":
        failures.append(f"Case 4: C4 should be gated, got {c4['classification']}")

    # Case 5: parse-drift detection (malformed manifest -> 0 rows -> SystemExit)
    import tempfile as _tf
    import shutil as _shutil2
    mal_tmpdir = _tf.mkdtemp()
    os.makedirs(os.path.join(mal_tmpdir, "docs"))
    os.makedirs(os.path.join(mal_tmpdir, "receipts"))
    with open(os.path.join(mal_tmpdir, "docs", "ember-completeness.md"), "w", newline="\n", encoding="utf-8") as f:
        f.write(_MALFORMED_MANIFEST)
    try:
        _run_tally(mal_tmpdir)
        failures.append("Case 5: malformed manifest should raise SystemExit")
    except SystemExit:
        pass  # expected — parse drift detected
    finally:
        _shutil2.rmtree(mal_tmpdir, ignore_errors=True)

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        raise SystemExit("EMBER_TALLY_SELFTEST: failures found")

    print("EMBER_TALLY_SELFTEST_PASS")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="ember completeness tally (#337)")
    ap.add_argument("--selftest", action="store_true",
                    help="run on synthetic manifest; exits nonzero on any failure")
    ap.add_argument("--run", action="store_true",
                    help="tally over real docs/ember-completeness.md (dry)")
    ap.add_argument("--emit", action="store_true",
                    help="--run + write tally receipt to receipts/")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return

    if not (args.run or args.emit):
        print(
            "EMBER_TALLY_STAGED\n"
            "  --selftest: synthetic manifest test\n"
            "  --run:      dry tally over real manifest\n"
            "  --emit:     --run + write receipt"
        )
        return

    result = _run_tally(NC)
    _print_summary(result)

    if args.emit:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        receipt = {
            "ticket": "EMBER-COMPLETENESS-TALLY",
            "ts": ts,
            "issue": 337,
            "total": result["total"],
            "implemented": result["implemented"],
            "part": result["part"],
            "gated": result["gated"],
            "open": result["open"],
            "pct_implemented": result["pct_implemented"],
            "missing": result["missing"],
            "per_subgoal": result["per_subgoal"],
            "sha_convention": SHA_CONVENTION,
            "no_gpu": True,
        }
        findings = validate_receipt(receipt)
        if findings:
            raise SystemExit(f"tally receipt fails receipt_check: {findings}")
        out = os.path.join(NC, "receipts", f"tally-{ts}.json")
        checked_write(out, receipt)
        print(f"\nRECEIPT: {out}")


if __name__ == "__main__":
    main()
