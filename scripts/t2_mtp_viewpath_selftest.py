"""t2_mtp_viewpath_selftest.py — eng #140 view-path plumb wiring receipt.

Kai's live r2 audit (mails 14509/14508): t2_r2_mtp installed its
frontier-filtered view at wcode-r1.jsonl, but t2_mtp regenerated that file
from the full ledger before building — the filtered set never reached
training. The first fix had the wrapper build its OWN theta view, which
skipped ext_clean (row-level confound vs the sft arm — gate finding on
PR #143). Final shape (gate option b): the wrapper consumes the sft arm's
EXACT view (wcode-r2-sft.jsonl) sha-pinned, t2_mtp consumes it READ-ONLY
(zero-drop ext-clean guard, no rewrite), asserts the build-time hash
equals the dispatch pin, cross-checks rows + n_examples against the
certified sft receipt, and claims identity TRUE in both receipts.
This selftest pins the closure.

Checks (pure logic + source-wiring asserts; no GPU, no torch):
  1. load_view_records round-trips a temp JSONL and refuses empty files;
  2. file_sha256 matches hashlib over raw bytes;
  3. t2_mtp source: argparse surface (incl. --license-allow /
     --sft-receipt / --expected-view-sha256); view-path arm is read-only
     (no view rewrite, no caps_from_records, sft-mirror build, fail-closed
     guard + identity asserts); ledger regeneration (write_view) and the
     view rewrite live only on the legacy arm; receipt carries round /
     gate_token_present / wrapper_receipt / view block / claim-dict
     identity with the sha-pinned TRUE branch;
  4. t2_r2_mtp source (text-only — importing it trips the gate-token
     interlock): consumes wcode-r2-sft.jsonl, builds no view, applies no
     filter (frontier_filter gone), resolves the certified sft receipt
     fail-closed, refuses --theta/--all-verified, delegation argv carries
     the full identity-anchor surface.

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
                 "--gate-token-present", "--license-allow",
                 "--sft-receipt", "--expected-view-sha256"):
        assert f'"{flag}"' in src, f"argparse missing {flag}"
    main_src = src.split("def main():")[1]
    branch_pos = main_src.index("if args.view_path:")
    regen_pos = main_src.index("write_view(")
    assert branch_pos < regen_pos, \
        "ledger regeneration must be guarded by the view-path branch"
    else_pos = main_src.index("\n    else:", branch_pos)
    assert else_pos < regen_pos, \
        "write_view must live in the else (no --view-path) arm"
    checks["t2_mtp_branch_guard"] = True

    # 3a. view-path arm is READ-ONLY + sft-mirror + fail-closed identity
    ifarm = main_src[branch_pos:else_pos]
    assert 'with open(view_path, "w"' not in ifarm, \
        "view-path arm must never rewrite the caller's view"
    assert "caps_from_records(" not in ifarm, \
        "view-path arm must use the sft build shape, not bits-caps"
    assert "build_dataset(view_path, license_allow=allow)" in ifarm, \
        "view-path arm must mirror the sft build call exactly"
    assert "ext-clean guard" in ifarm, "zero-drop ext-clean guard missing"
    assert "view sha mismatch" in ifarm, "dispatch-pin sha assert missing"
    assert ifarm.count("identity assert failed") == 2, \
        "rows + n_examples asserts against the sft receipt missing"
    checks["t2_mtp_viewpath_arm_readonly_identity"] = True

    # 3b. legacy arm keeps the round-1 behavior (regenerate, rewrite, caps)
    legacy = main_src[else_pos:main_src.index("view_block = {")]
    assert "write_view(" in legacy and "caps_from_records(" in legacy, \
        "legacy arm must keep regeneration + bits-caps"
    assert 'with open(view_path, "w"' in legacy, \
        "legacy arm must keep the in-place ext-clean rewrite"
    checks["t2_mtp_legacy_arm_unchanged"] = True

    # 3c. receipt fields + identity claim branches
    for field in ('"round": args.round',
                  '"gate_token_present": args.gate_token_present',
                  '"wrapper_receipt": args.wrapper_receipt',
                  '"view": view_block',
                  '"identity_claim": identity_claim'):
        assert field in main_src, f"receipt field wiring missing: {field}"
    assert '"identical_to_arm_A": True' not in src, \
        "unconditional identity literal must be gone"
    assert ("if args.view_path and sft_anchor and "
            "args.expected_view_sha256:") in main_src, \
        "anchored TRUE-claim branch missing"
    assert "sha-pinned to sft arm view wcode-r2-sft.jsonl" in main_src, \
        "TRUE-claim basis must name the sha pin"
    checks["t2_mtp_receipt_identity"] = True

    # 4. wrapper source (text-only)
    wsrc = open(os.path.join(HERE, "t2_r2_mtp.py"), encoding="utf-8").read()
    assert "shutil.copy2" not in wsrc, "r1-path install copy must be gone"
    assert "wcode-r1.jsonl.r2-backup" not in wsrc, "backup machinery gone"
    assert 'os.path.join(VIEWS, "wcode-r1.jsonl")' not in wsrc, \
        "wrapper must not construct the r1 view path"
    # gate option b: consume the sft view, build nothing, filter nothing
    assert 'os.path.join(VIEWS, "wcode-r2-sft.jsonl")' in wsrc, \
        "wrapper must consume the sft arm's exact view"
    assert "frontier_filter" not in wsrc, \
        "wrapper must not compute its own frontier filter"
    assert "solve_rates_from_ledger" not in wsrc, \
        "wrapper must not read solve rates"
    assert "wcode-r2.jsonl" not in wsrc, \
        "wrapper must not touch t2_r2w's pre-theta intermediate"
    assert "sft view not found" in wsrc, \
        "fail-closed on missing sft view required"
    assert "no certified sft receipt" in wsrc, \
        "fail-closed sft-receipt resolution required"
    assert "no longer applies a frontier filter" in wsrc, \
        "--theta/--all-verified refusal required"
    for flag in ("--view-path", "--round", "--wrapper-receipt",
                 "--gate-token-present", "--sft-receipt",
                 "--expected-view-sha256"):
        assert f'"{flag}"' in wsrc, f"delegation argv missing {flag}"
    checks["wrapper_wiring"] = True

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "ENG140-VIEWPATH-SELFTEST", "ts": ts,
        "issue": "wordingone/ember#140",
        "checks": checks,
        "sha_convention": ("sha256 over on-disk raw bytes "
                           "(binary read, no line-ending normalization) — "
                           "the convention file_sha256 is pinned against"),
        "gate_rework": ("PR #143 changes-requested (option b): wrapper "
                        "consumes the sft arm's exact view sha-pinned; "
                        "t2_mtp read-only consume + build-time pin assert "
                        "+ certified-sft-receipt cross-check (rows, "
                        "n_examples) -> identity claim TRUE in both "
                        "receipts, by construction"),
        "default_path_unchanged": ("no --view-path = legacy round-1 "
                                   "behavior (regenerate wcode-r1.jsonl "
                                   "from ledger, arm-A-identical build)"),
        "quarantine_note": ("adapter r2-q3-mtp stays PRE-GATE/QUARANTINED "
                            "until rerun on the sft-identical view — "
                            "dispatch is the gate-holder's call"),
    }
    out = os.path.join(REPO, "receipts", f"eng140-viewpath-selftest-{ts}.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"[selftest] receipt: {out}")
    print("T2_MTP_VIEWPATH_SELFTEST_PASS")


if __name__ == "__main__":
    main()
