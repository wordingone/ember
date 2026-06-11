"""t2_mtp_viewpath_selftest.py — eng #140 view-path plumb wiring receipt.

Kai's live r2 audit (mails 14509/14508): t2_r2_mtp installed its
frontier-filtered view at wcode-r1.jsonl, but t2_mtp regenerated that file
from the full ledger before building — the filtered set never reached
training. The fix makes the caller's view explicit (--view-path) and the
terminal receipt honest (round / gate presence / wrapper linkage / view
hash / named dataset-identity claim). This selftest pins the closure.

Checks (pure logic + source-wiring asserts; no GPU, no torch):
  1. load_view_records round-trips a temp JSONL and refuses empty files;
  2. file_sha256 matches hashlib over raw bytes;
  3. t2_mtp source: new argparse surface present; ledger regeneration
     (write_view) only on the no-view-path branch; receipt carries round /
     gate_token_present / wrapper_receipt / view block / claim-dict
     identity (no unconditional identical_to_arm_A literal);
  4. t2_r2_mtp source (text-only — importing it trips the gate-token
     interlock): no copy onto wcode-r1.jsonl, no backup machinery,
     delegation argv carries --view-path/--round/--wrapper-receipt/
     --gate-token-present.

Writes receipts/eng140-viewpath-selftest-<ts>.json. Sentinel:
T2_MTP_VIEWPATH_SELFTEST_PASS.
"""
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def main():
    checks = {}
    import t2_mtp as tm

    # 1. load_view_records round-trip + empty refusal
    rows = [{"task": "mbpp:1", "src": "def f(): pass"},
            {"task": "mbpp:2", "src": "def g(): pass"}]
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "view.jsonl")
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
            f.write("\n")  # trailing blank line must be ignored
        got = tm.load_view_records(p)
        assert got == rows, "round-trip mismatch"
        empty = os.path.join(td, "empty.jsonl")
        open(empty, "w").close()
        try:
            tm.load_view_records(empty)
            raise AssertionError("empty view must refuse")
        except SystemExit:
            pass
    checks["load_view_records"] = True

    # 2. file_sha256 over raw bytes
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "blob.bin")
        with open(p, "wb") as f:
            f.write(b"abc\r\ndef\n")
        assert tm.file_sha256(p) == hashlib.sha256(b"abc\r\ndef\n").hexdigest()
    checks["file_sha256"] = True

    # 3. t2_mtp source wiring
    src = open(os.path.join(HERE, "t2_mtp.py"), encoding="utf-8").read()
    for flag in ("--view-path", "--round", "--wrapper-receipt",
                 "--gate-token-present"):
        assert f'"{flag}"' in src, f"argparse missing {flag}"
    main_src = src.split("def main():")[1]
    branch_pos = main_src.index("if args.view_path:")
    regen_pos = main_src.index("write_view(")
    assert branch_pos < regen_pos, \
        "ledger regeneration must be guarded by the view-path branch"
    # regeneration sits in the else arm: between the branch and write_view
    # there must be an `else:`
    assert "else:" in main_src[branch_pos:regen_pos], \
        "write_view must live in the else (no --view-path) arm"
    for field in ('"round": args.round',
                  '"gate_token_present": args.gate_token_present',
                  '"wrapper_receipt": args.wrapper_receipt',
                  '"view": view_block',
                  '"identical_to_arm_A": identity_claim'):
        assert field in main_src, f"receipt field wiring missing: {field}"
    assert '"identical_to_arm_A": True' not in src, \
        "unconditional identity literal must be gone"
    checks["t2_mtp_wiring"] = True

    # 4. wrapper source (text-only)
    wsrc = open(os.path.join(HERE, "t2_r2_mtp.py"), encoding="utf-8").read()
    assert "shutil.copy2" not in wsrc, "r1-path install copy must be gone"
    assert "wcode-r1.jsonl.r2-backup" not in wsrc, "backup machinery gone"
    for flag in ("--view-path", "--round", "--wrapper-receipt",
                 "--gate-token-present"):
        assert f'"{flag}"' in wsrc, f"delegation argv missing {flag}"
    # the only r1-view mentions left are documentation, never an open(...,"w")
    assert 'os.path.join(VIEWS, "wcode-r1.jsonl")' not in wsrc, \
        "wrapper must not construct the r1 view path"
    checks["wrapper_wiring"] = True

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "ENG140-VIEWPATH-SELFTEST", "ts": ts,
        "issue": "wordingone/ember#140",
        "checks": checks,
        "sha_convention": ("sha256 over on-disk raw bytes "
                           "(binary read, no line-ending normalization) — "
                           "the convention file_sha256 is pinned against"),
        "default_path_unchanged": ("no --view-path = legacy round-1 "
                                   "behavior (regenerate wcode-r1.jsonl "
                                   "from ledger, arm-A-identical build)"),
        "quarantine_note": ("adapter r2-q3-mtp stays PRE-GATE/QUARANTINED "
                            "until rerun on the explicit view or "
                            "relabeled exploratory — dispatch is the "
                            "gate-holder's call"),
    }
    out = os.path.join(REPO, "receipts", f"eng140-viewpath-selftest-{ts}.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"[selftest] receipt: {out}")
    print("T2_MTP_VIEWPATH_SELFTEST_PASS")


if __name__ == "__main__":
    main()
