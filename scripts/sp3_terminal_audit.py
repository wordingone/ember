"""sp3_terminal_audit.py — June-22 terminal-condition audit harness
(#206). The critical-path map commits: "06-22: terminal-condition audit
against THIS table; every row quoted with its receipt or its named gap.
No row blurred." This makes that audit MECHANICAL: rows are frozen
requirement specs; the run binds each to receipts (path + sha +
receipt_check PASS) or emits the named gap verbatim. Zero free-text
verdict words — a row is RECEIPTED or GAP-NAMED, nothing else.

Row requirements are receipt GLOB patterns + minimum counts (+ optional
exact-path sha pins). Globs rather than hardcoded status: the table's
truth changes as receipts land; the REQUIREMENTS are what's frozen.
Tightening a row's requirements before 06-20 is a visible PR diff, never
a run-time judgment call.

`--selftest` pure-logic on temp fixtures (receipted row / gap row /
receipt_check-dirty row / sha-drift row — all branches). `--run` audits
the live tree and emits the audit receipt; intended for 06-22 but
runnable any day (it reports the gaps still open — that IS the signal).
"""
import argparse
import glob as globmod
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from receipt_write import checked_write               # noqa: E402
from receipt_check import validate_receipt             # noqa: E402

SHA_CONVENTION = ("file shas = sha256 over the exact on-disk raw bytes, no "
                  "normalization")

# ---- frozen rows (the §1 persistence-clause table, as requirements) --
# req entry: (glob_relative_to_nc, min_count). Globs may also be exact
# paths. All matched receipts must receipt_check PASS (json files only).
ROWS = (
    {"id": 1, "condition": "Runs locally",
     "requires": (("receipts/t2-*.json", 1),
                  ("receipts/w4-eval-*.json", 1))},
    {"id": 2, "condition": "Generates verified experience",
     "requires": (("receipts/v-soundness-probe-*.json", 1),
                  ("ledger/views/grpo-r2-tasks.json", 1))},
    {"id": 3, "condition": "Trains/updates from it",
     "requires": (("receipts/t2-r2-*.json", 1),
                  ("receipts/r2-*wrapper-*.json", 1))},
    {"id": 4, "condition": "Improves held-out transfer (decomposed: "
                           "in-dist LEARNS + floor-scoped transfer "
                           "ceiling — fp-25 wording)",
     "requires": (("receipts/fp25-indist-*.json", 1),
                  ("receipts/fp25b-surfaceb-*.json", 1),
                  ("receipts/g1-r2w-verdict-*.json", 1))},
    {"id": 5, "condition": "Beats matched control",
     "requires": (("receipts/g1-r2w-verdict-*.json", 1),)},
    {"id": 6, "condition": "Gain disappears on deletion (standing D-gate)",
     "requires": (("receipts/d-gate-*.json", 1),)},
    {"id": 7, "condition": "Persists across sessions (standing P-gate)",
     "requires": (("receipts/p-gate-*.json", 1),)},
    {"id": 8, "condition": "8a loop-machinery: one full round, zero cloud "
                           "calls in the loop path (config-only receipt)",
     "requires": (("receipts/round-local-loop-*.json", 1),)},
    {"id": 9, "condition": "8b owned substrate at v0 scale: launch gate + "
                           "shards + checkpoint floor verdict + owned "
                           "micro-loop receipt",
     "requires": (("receipts/v0-launch-gate-*.json", 1),
                  ("receipts/fp24-verdict-*.json", 1),
                  ("receipts/own-r1-*.json", 1))},
    # ---- B-leg (founder-likeness / E2B-surpass) rows — added 2026-06-12,
    # inside the pre-06-20 tightening window. The goal has TWO legs and
    # rows 1-9 audit only the ember-work leg; without these the 06-22
    # audit could read all-green while silent on the surpass comparison.
    # Non-json evidence binds by tracked-existence + sha (pins the frozen
    # bytes the B-run depends on).
    {"id": 10, "condition": "B-leg instruments frozen: duty battery "
                            "(content + encodings), seat-adapter contract, "
                            "B-run designation rule, frozen episode spec v1",
     "requires": (("docs/sp6-duty-battery.jsonl", 1),
                  ("docs/sp6-duty-battery-encodings.jsonl", 1),
                  ("docs/sp6c-seat-adapter-v0.md", 1),
                  ("docs/sp6b-designation-rule-v0.md", 1),
                  ("docs/sp6b-duty-battery-spec-v1.md", 1))},
    {"id": 11, "condition": "B-leg seats bound: shakedown receipts for "
                            "BOTH seats (E2B + ember), template hash pinned",
     "requires": (("receipts/sp6c-e2b-shakedown-*.json", 1),
                  ("receipts/sp6c-ember-shakedown-*.json", 1))},
    {"id": 12, "condition": "B3 executed: designation receipt (frozen rule, "
                            "in-window) + B-run receipt (paired battery "
                            "both seats, McNemar exact — the surpass "
                            "comparison itself)",
     # field pin (3rd element): spec-v1 §pass/fail freezes "replay rig must
     # record sha256 of THIS file in the receipt; mismatch = run void" — a
     # B-run receipt minted against a tampered/stale battery can NEVER
     # satisfy this row.
     "requires": (("receipts/b-run-designation-*.json", 1),
                  ("receipts/sp6b-b-run-*.json", 1,
                   {"battery_sha256": "docs/sp6b-duty-battery-spec-v1.md"}))},
)


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _tracked(nc):
    """Set of git-tracked relative paths (forward-slash). Evidence that
    is not committed can NEVER satisfy a row — the 132420Z receipt bound
    untracked local files and a clean checkout reproduced a different
    verdict (Kai 14631). Portability is enforced, not remembered."""
    import subprocess
    out = subprocess.run(["git", "-C", nc, "ls-files"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None                      # not a git tree (selftest tmpdir)
    return set(out.stdout.splitlines())


def audit_row(row, nc=NC, tracked=None):
    """RECEIPTED (every requirement satisfied, all matched .json
    receipt_check PASS, every match git-tracked) or GAP-NAMED (each
    unmet requirement quoted)."""
    if tracked is None:
        tracked = _tracked(nc)
    bound, gaps = [], []
    for req in row["requires"]:
        pat, min_count = req[0], req[1]
        field_pins = req[2] if len(req) > 2 else None
        hits = sorted(globmod.glob(f"{nc}/{pat}"))
        if tracked is not None:
            hits = [h for h in hits
                    if os.path.relpath(h, nc).replace("\\", "/") in tracked]
        ok = []
        for h in hits:
            if h.endswith(".json") and "receipts/" in h.replace("\\", "/"):
                try:
                    d = json.load(open(h, encoding="utf-8"))
                except Exception:
                    continue
                if validate_receipt(d):
                    continue            # dirty receipts never satisfy a row
                if field_pins:
                    # receipt field must equal sha256 of the pinned file's
                    # CURRENT bytes; missing field or drift = run void
                    pin_ok = True
                    for field, pinned in field_pins.items():
                        try:
                            want = _sha(os.path.join(nc, pinned))
                        except OSError:
                            pin_ok = False
                            break
                        if d.get(field) != want:
                            pin_ok = False
                            break
                    if not pin_ok:
                        continue
            ok.append(h)
        if len(ok) < min_count:
            pin_note = ""
            if field_pins:
                pin_note = "; field pins: " + ", ".join(
                    f"{f}==sha256({p})" for f, p in field_pins.items())
            gaps.append(f"requires >={min_count} of '{pat}' "
                        f"(receipt_check-clean AND git-tracked{pin_note}); "
                        f"found {len(ok)}")
        else:
            # bind the NEWEST matches (ts-sorted names): a later receipt
            # supersedes an earlier one on the same surface (Kai 14541
            # precedent — binding the earliest quoted a superseded verdict)
            bound.extend({"path": os.path.relpath(p, nc).replace("\\", "/"),
                          "sha256": _sha(p)} for p in ok[-min_count:])
    if gaps:
        return {"id": row["id"], "condition": row["condition"],
                "verdict": "GAP-NAMED", "gaps": gaps}
    return {"id": row["id"], "condition": row["condition"],
            "verdict": "RECEIPTED", "receipts": bound}


def run_audit(nc=NC):
    tracked = _tracked(nc)
    rows = [audit_row(r, nc, tracked=tracked) for r in ROWS]
    return {
        "ticket": "SP3-TERMINAL-AUDIT",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "issue": 206,
        "table": "research/june22-critical-path.md section 1 (+ 8a/8b split)",
        "rows": rows,
        "result": {
            "verdict": ("ALL-RECEIPTED"
                        if all(r["verdict"] == "RECEIPTED" for r in rows)
                        else "GAPS-OPEN"),
            "n_receipted": sum(r["verdict"] == "RECEIPTED" for r in rows),
            "n_gaps": sum(r["verdict"] == "GAP-NAMED" for r in rows),
        },
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }


def _selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(f"{td}/receipts")
        # clean receipt satisfies; dirty receipt does not; ledger file is
        # a non-receipt requirement satisfied by existence
        json.dump({"ticket": "x", "ts": "x"},
                  open(f"{td}/receipts/good-1.json", "w"))
        json.dump({"ts": "x"},                       # missing ticket = dirty
                  open(f"{td}/receipts/dirty-1.json", "w"))
        os.makedirs(f"{td}/ledger")
        open(f"{td}/ledger/view.json", "w").write("{}")
        r_ok = audit_row({"id": 1, "condition": "c",
                          "requires": (("receipts/good-*.json", 1),
                                       ("ledger/view.json", 1))}, nc=td)
        assert r_ok["verdict"] == "RECEIPTED", r_ok
        assert all("sha256" in b for b in r_ok["receipts"])
        r_gap = audit_row({"id": 2, "condition": "c",
                           "requires": (("receipts/absent-*.json", 1),)},
                          nc=td)
        assert r_gap["verdict"] == "GAP-NAMED" and r_gap["gaps"], r_gap
        r_dirty = audit_row({"id": 3, "condition": "c",
                             "requires": (("receipts/dirty-*.json", 1),)},
                            nc=td)
        assert r_dirty["verdict"] == "GAP-NAMED", r_dirty
        # sha binding is byte-true: rewriting the file changes the bound sha
        s1 = audit_row({"id": 4, "condition": "c",
                        "requires": (("receipts/good-1.json", 1),)},
                       nc=td)["receipts"][0]["sha256"]
        json.dump({"ticket": "x", "ts": "y"},
                  open(f"{td}/receipts/good-1.json", "w"))
        s2 = audit_row({"id": 4, "condition": "c",
                        "requires": (("receipts/good-1.json", 1),)},
                       nc=td)["receipts"][0]["sha256"]
        assert s1 != s2, "sha must track bytes"
    # field pin (spec-v1 battery binding): the receipt must carry the
    # pinned file's CURRENT sha256; stale sha or missing field = run void
    with tempfile.TemporaryDirectory() as td3:
        os.makedirs(f"{td3}/receipts")
        os.makedirs(f"{td3}/docs")
        open(f"{td3}/docs/battery.md", "w").write("frozen battery v1")
        good = hashlib.sha256(b"frozen battery v1").hexdigest()
        sc = SHA_CONVENTION
        json.dump({"ticket": "x", "ts": "x", "battery_sha256": good,
                   "sha_convention": sc},
                  open(f"{td3}/receipts/sp6b-b-run-a-1.json", "w"))
        json.dump({"ticket": "x", "ts": "x", "battery_sha256": "0" * 64,
                   "sha_convention": sc},
                  open(f"{td3}/receipts/sp6b-b-run-b-1.json", "w"))
        json.dump({"ticket": "x", "ts": "x"},
                  open(f"{td3}/receipts/sp6b-b-run-c-1.json", "w"))
        pin = {"battery_sha256": "docs/battery.md"}
        r_pin = audit_row(
            {"id": 12, "condition": "c",
             "requires": (("receipts/sp6b-b-run-a-*.json", 1, pin),)}, nc=td3)
        assert r_pin["verdict"] == "RECEIPTED", r_pin
        r_drift = audit_row(
            {"id": 12, "condition": "c",
             "requires": (("receipts/sp6b-b-run-b-*.json", 1, pin),)}, nc=td3)
        assert r_drift["verdict"] == "GAP-NAMED", r_drift
        assert "field pins" in r_drift["gaps"][0], r_drift
        r_nofield = audit_row(
            {"id": 12, "condition": "c",
             "requires": (("receipts/sp6b-b-run-c-*.json", 1, pin),)}, nc=td3)
        assert r_nofield["verdict"] == "GAP-NAMED", r_nofield
    # untracked evidence can never satisfy a row (Kai 14631 class):
    # inject a tracked-set that excludes the only matching receipt
    import tempfile as _tf
    with _tf.TemporaryDirectory() as td2:
        os.makedirs(f"{td2}/receipts")
        json.dump({"ticket": "x", "ts": "x"},
                  open(f"{td2}/receipts/good-1.json", "w"))
        r_untracked = audit_row({"id": 9, "condition": "c",
                                 "requires": (("receipts/good-*.json", 1),)},
                                nc=td2, tracked=set())
        assert r_untracked["verdict"] == "GAP-NAMED", r_untracked
        r_tracked = audit_row({"id": 9, "condition": "c",
                               "requires": (("receipts/good-*.json", 1),)},
                              nc=td2, tracked={"receipts/good-1.json"})
        assert r_tracked["verdict"] == "RECEIPTED", r_tracked
    # live-tree smoke: the audit runs and rows 6/7 (standing gates) bind
    live = run_audit()
    assert validate_receipt(live) == [], validate_receipt(live)
    by_id = {r["id"]: r for r in live["rows"]}
    assert by_id[6]["verdict"] == "RECEIPTED", by_id[6]   # d-gate receipt
    assert by_id[7]["verdict"] == "RECEIPTED", by_id[7]   # p-gate receipt
    assert by_id[8]["verdict"] == "RECEIPTED", by_id[8]   # 8a now run
    assert by_id[9]["verdict"] == "GAP-NAMED", by_id[9]   # 8b open
    assert by_id[12]["verdict"] == "GAP-NAMED", by_id[12] # B3 open
    print("SP3_TERMINAL_AUDIT_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        return
    if not a.run:
        print("SP3_TERMINAL_AUDIT_STAGED (--run audits the live tree; "
              "intended 2026-06-22, runnable any day)")
        return
    receipt = run_audit()
    out = f"{NC}/receipts/sp3-terminal-audit-{receipt['ts']}.json"
    checked_write(out, receipt)
    reloaded = json.load(open(out, encoding="utf-8"))
    f = validate_receipt(reloaded)
    if f:
        raise SystemExit(f"emitted audit receipt FAILS receipt_check: {f}")
    for r in receipt["rows"]:
        tag = ("RECEIPTED" if r["verdict"] == "RECEIPTED"
               else "GAP-NAMED: " + "; ".join(r["gaps"]))
        print(f"row {r['id']}: {tag}")
    print(json.dumps(receipt["result"], indent=2))
    print(f"SP3_TERMINAL_AUDIT_DONE {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
