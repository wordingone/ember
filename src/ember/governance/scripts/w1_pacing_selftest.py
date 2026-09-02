"""w1_pacing_selftest.py — w1_mbpp pacing-block wiring receipt (#129, eng-37).

fp-14 (#115) wired pacing_snapshot into t2_round only; w1_mbpp generates
through the same paced t1_probe path (decode_pacer + THROTTLE_S) but never
snapshotted at write — the round-2 sampling receipt
(w1-floor-q3-r2mtp-20260611T030332Z) carries NO pacing block. This selftest
pins the closure of that gap, mirroring fp14_pacing_selftest's
source-wiring style.

Checks (pure logic + source-wiring asserts; no GPU, no model import):
  1. import wiring: pacing_reset + pacing_snapshot in w1_mbpp's t1_probe
     import block;
  2. reset at RUN start: pacing_reset() called inside main(), after arg
     parse, before load_model — the block measures THIS run;
  3. write-time ordering: sample (generate_chat) < verify (execute_batch)
     < snapshot < receipt write. The write-site assert tolerates BOTH the
     current `with open(...)` form and eng-31 (#107)'s `checked_write(...)`
     form so it survives either merge order;
  4. per-run semantics on the live meter: reset -> record -> snapshot
     reflects only post-reset accumulation (same convention string as
     t2_round receipts).

Writes receipts/eng129-w1-pacing-selftest-<ts>.json. Sentinel:
W1_PACING_SELFTEST_PASS.
"""
import json
import os
import re
import sys
import types
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# Windows test-shim (declared): t1_probe imports POSIX `resource` at module
# level for the sandbox rlimits; the pacing meter never touches it. Shimming
# ONLY makes the import succeed here — sandbox behavior is not under test.
if os.name == "nt":
    sys.modules.setdefault("resource", types.ModuleType("resource"))


def main():
    checks = {}
    src = open(os.path.join(HERE, "w1_mbpp.py"), encoding="utf-8").read()

    # 1. import wiring
    import_block = src.split("from t1_probe import")[1].split(")")[0]
    assert "pacing_reset" in import_block, "pacing_reset import missing"
    assert "pacing_snapshot" in import_block, "pacing_snapshot import missing"
    checks["import_wiring"] = True

    # 2. reset at RUN start: inside main(), after arg parse, before load_model
    main_src = src.split("def main():")[1]
    parse_pos = main_src.index("parse_known_args()")
    reset_pos = main_src.index("pacing_reset()")
    load_pos = main_src.index("load_model(args.model")
    assert parse_pos < reset_pos < load_pos, \
        "pacing_reset must run after arg parse and before any governed work"
    checks["reset_at_run_start"] = True

    # 3. write-time ordering: sample < verify < snapshot < write
    sample_pos = main_src.index("completions = generate_chat(")
    verify_pos = main_src.index("results = execute_batch(jobs)")
    snap_pos = main_src.index('receipt["pacing"] = pacing_snapshot()')
    write_m = re.search(
        r'(?:with open|checked_write)\(f"\{RECEIPTS\}/w1-floor\{tagpart\}-\{ts\}\.json"',
        main_src)
    assert write_m, "w1 receipt write site not found"
    assert sample_pos < verify_pos < snap_pos < write_m.start(), \
        "pacing snapshot must be taken after sampling+verify, before write"
    checks["write_time_ordering"] = True

    # 4. per-run semantics on the live meter
    import t1_probe as tp
    tp._pace_record("throttle", 0.6)  # pre-run noise
    tp.pacing_reset()
    tp._pace_record("pacer", 0.5)
    snap = tp.pacing_snapshot()
    assert snap["pacing_total_s"] == 0.5, "reset did not isolate this run"
    assert snap["throttle_s"] == 0.0 and snap["throttle_sleeps"] == 0
    assert "convention" in snap and "compute-only" in snap["convention"]
    tp.pacing_reset()
    checks["per_run_semantics"] = True

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "ENG129-W1-PACING-SELFTEST", "ts": ts,
        "issue": "wordingone/ember#129",
        "checks": checks,
        "behavior_change": "none — receipt-only addition; no argparse "
                           "change, so no args_fp shift (w1 receipts carry "
                           "no args_fp field; schema gains top-level "
                           "'pacing' key only)",
        "fp20_tie": "fp-20 is re-pinned to the first instrumented w1 "
                    "receipt; this wiring makes the next w1 run that "
                    "receipt",
    }
    out = os.path.join(REPO, "receipts", f"eng129-w1-pacing-selftest-{ts}.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"[selftest] receipt: {out}")
    print("W1_PACING_SELFTEST_PASS")


if __name__ == "__main__":
    main()
