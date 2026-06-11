"""t2r2w_viewsha_selftest.py — eng #150: t2_r2w receipt carries the
sha256 of every view it writes.

Pins, with NO GPU and NO ledger access:
  1. file_sha256 == hashlib.sha256 over raw on-disk bytes (CRLF bytes
     preserved — no line-ending normalization).
  2. _view_entry returns {path, rows, sha256} with the sha taken from
     the file as written.
  3. Source-position asserts: each _view_entry call sits AFTER the
     write that produces its file (write_view / the sft view's
     vf.write loop), so the sha is post-write by construction.
  4. Receipt wiring: "views_written" + top-level "sha_convention" land
     in the receipt dict; build_sft_examples returns the views dict.
  5. No new CLI args (args surface unchanged → dispatch fps unaffected).
  6. checked_write PASS on a fixture receipt shaped like the new
     t2-r2w receipt (sha256 keys present + top-level sha_convention —
     the receipt_check contract for sha-bearing receipts).

Run: python scripts/t2r2w_viewsha_selftest.py
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

# t2_r2w's module-level launch interlock parses sys.argv at import and
# exits without a gate token — shim argv BEFORE the import. The token
# value is inert here: nothing below builds views or trains.
sys.argv = ["t2r2w_viewsha_selftest.py", "--leo-gate-token", "selftest"]
import t2_r2w  # noqa: E402

from receipt_write import checked_write  # noqa: E402


def main():
    checks = {}

    # 1+2. file_sha256 / _view_entry over raw bytes, CRLF preserved
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "view.jsonl")
        payload = b'{"task":"a"}\r\n{"task":"b"}\n'
        with open(p, "wb") as f:
            f.write(payload)
        want = hashlib.sha256(payload).hexdigest()
        assert t2_r2w.file_sha256(p) == want, "file_sha256 != hashlib raw"
        entry = t2_r2w._view_entry(p, 2)
        assert entry == {"path": p, "rows": 2, "sha256": want}
        assert isinstance(entry["rows"], int)
        # rewrite with different bytes -> sha follows the on-disk state
        with open(p, "wb") as f:
            f.write(b'{"task":"a"}\n')
        assert t2_r2w._view_entry(p, 1)["sha256"] == \
            hashlib.sha256(b'{"task":"a"}\n').hexdigest()
    checks["sha_over_raw_bytes"] = True

    src = open(os.path.join(HERE, "t2_r2w.py"), encoding="utf-8").read()

    # 3. sha computed AFTER the write, for every view the runner writes
    build_src = src.split("def build_sft_examples")[1].split("def main")[0]
    pos_wcode_write = build_src.index('write_view(LEDGER, f"{VIEWS}/wcode-r2.jsonl")')
    pos_wcode_entry = build_src.index('views = {"wcode-r2.jsonl"')
    assert pos_wcode_write < pos_wcode_entry, \
        "wcode-r2 sha must be computed after write_view"
    pos_sft_write = build_src.index("vf.write(json.dumps(r)")
    pos_sft_entry = build_src.index('views["wcode-r2-sft.jsonl"] = _view_entry')
    assert pos_sft_write < pos_sft_entry, \
        "sft view sha must be computed after the vf.write loop"
    main_src = src.split("def main():")[1]
    pos_ctrl_write = main_src.index("write_view(CONTROL_POOL")
    pos_ctrl_entry = main_src.index('views["wcode-r2-control.jsonl"] = _view_entry')
    assert pos_ctrl_write < pos_ctrl_entry, \
        "control view sha must be computed after write_view"
    checks["sha_post_write_positions"] = True

    # 4. receipt wiring
    assert '"views_written": views' in main_src
    assert '"sha_convention": SHA_CONVENTION' in main_src
    assert "return examples, counts, info, views" in build_src
    assert "sft_examples, sft_counts, info, views = build_sft_examples" \
        in main_src
    checks["receipt_wiring"] = True

    # 5. args surface unchanged: exactly the 6 pre-eng-150 arguments
    arg_names = ["--leo-gate-token", "--arm", "--model", "--tag-suffix",
                 "--license-allow", "--dry-run"]
    assert main_src.count("ap.add_argument") == len(arg_names)
    for a in arg_names:
        assert f'"{a}"' in main_src, f"expected arg {a} present"
    checks["args_surface_unchanged"] = True

    # 6. fixture receipt in the new shape passes the receipt contract
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with tempfile.TemporaryDirectory() as td:
        fixture = {
            "ticket": "NC0-T2-R2W", "arm": "sft", "ts": ts, "round": 2,
            "frontier_filter": {"theta": 0.5, "view_rows_after_theta": 2},
            "views_written": {
                "wcode-r2.jsonl": {"path": "x/wcode-r2.jsonl", "rows": 3,
                                   "sha256": "a" * 64},
                "wcode-r2-sft.jsonl": {"path": "x/wcode-r2-sft.jsonl",
                                       "rows": 2, "sha256": "b" * 64},
            },
            "sha_convention": t2_r2w.SHA_CONVENTION,
            "dry_run": True,
        }
        checked_write(os.path.join(td, "fixture.json"), fixture)
    checks["fixture_receipt_check_pass"] = True

    receipt = {
        "ticket": "ENG40-T2R2W-VIEWSHA-SELFTEST", "ts": ts,
        "issue": "wordingone/ember#150",
        "checks": checks,
        "sha_convention": t2_r2w.SHA_CONVENTION,
        "no_network": True, "no_gpu": True,
        "note": ("append-only: existing certified t2-r2w receipts are "
                 "untouched; views_written lands on the NEXT run"),
    }
    out = os.path.join(REPO, "receipts",
                       f"eng40-t2r2w-viewsha-selftest-{ts}.json")
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"[selftest] receipt: {out}")
    print("ENG40_T2R2W_VIEWSHA_SELFTEST_PASS")


if __name__ == "__main__":
    main()
