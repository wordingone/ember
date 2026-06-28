"""fp14_pacing_selftest.py — pacing meter correctness + wiring receipt (#88).

The fp-14 instrumentation half: t1_probe gains a PACING meter (throttle +
decode-pacer sleep accumulation) and t2_round receipts carry
`pacing_snapshot()` at WRITE time. The settlement half (resolving fp-9's
"as operated under the governor" qualifier with MEASURED numbers) fires on
the first instrumented sampling run — round-2 (fp-20 mints at #88 close).

Checks (pure logic + source-wiring asserts; no GPU, no model import):
  1. meter math: record/reset/snapshot, totals, rounding;
  2. snapshot purity (copy, not the live dict) + convention note present;
  3. source wiring: every governor sleep site in t1_probe is immediately
     followed by its _pace_record call; t2_round snapshots at write time
     (after sampling), not at receipt-creation time.

Writes receipts/fp14-pacing-selftest-<ts>.json. Sentinel:
FP14_PACING_SELFTEST_PASS.
"""
import json
import os
import re
import sys
import types
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# Windows test-shim (declared): t1_probe imports POSIX `resource` at module
# level for the sandbox rlimits; the pacing meter never touches it. Shimming
# ONLY makes the import succeed here — sandbox behavior is not under test.
if os.name == "nt":
    sys.modules.setdefault("resource", types.ModuleType("resource"))


def main():
    checks = {}

    import t1_probe as tp
    # 1. meter math
    tp.pacing_reset()
    assert tp.PACING == {"throttle_s": 0.0, "throttle_sleeps": 0,
                         "pacer_s": 0.0, "pacer_sleeps": 0}
    tp._pace_record("throttle", 0.6)
    tp._pace_record("throttle", 0.6)
    tp._pace_record("pacer", 0.5)
    snap = tp.pacing_snapshot()
    assert snap["throttle_s"] == 1.2 and snap["throttle_sleeps"] == 2
    assert snap["pacer_s"] == 0.5 and snap["pacer_sleeps"] == 1
    assert snap["pacing_total_s"] == 1.7
    assert "convention" in snap and "compute-only" in snap["convention"]
    checks["meter_math"] = True

    # 2. snapshot purity — mutating the snapshot must not touch the meter
    snap["throttle_s"] = 999
    assert tp.PACING["throttle_s"] == 1.2
    tp.pacing_reset()
    assert tp.pacing_snapshot()["pacing_total_s"] == 0.0
    checks["snapshot_purity"] = True

    # 3a. wiring: each sleep site immediately followed by its record call
    src = open(os.path.join(HERE, "t1_probe.py"), encoding="utf-8").read()
    assert re.search(
        r"time\.sleep\(PACE_S\)\s*\n\s*_pace_record\(\"pacer\", PACE_S\)",
        src), "decode-pacer sleep not metered"
    assert re.search(
        r"time\.sleep\(THROTTLE_S\)[^\n]*\n\s*_pace_record\(\"throttle\", "
        r"THROTTLE_S\)", src), "throttle sleep not metered"
    n_sleeps = len(re.findall(r"time\.sleep\(", src))
    assert n_sleeps == 2, f"unmetered sleep sites appeared: {n_sleeps}"
    checks["t1_probe_wiring"] = True

    # 3b. t2_round snapshots at WRITE time (after the sampling block).
    # Write-site assert tolerates both the pre-#107 direct json.dump form
    # and the #107 checked_write form (same pattern as w1_pacing_selftest)
    # — eng-31 swaps the write line, the ordering invariant is unchanged.
    src2 = open(os.path.join(HERE, "t2_round.py"), encoding="utf-8").read()
    snap_pos = src2.index('receipt["pacing"] = pacing_snapshot()')
    write_m = re.search(r"json\.dump\(receipt, f, indent=2\)"
                        r"|checked_write\(path, receipt\)", src2)
    assert write_m, "t2_round receipt write site not found"
    write_pos = write_m.start()
    sample_pos = src2.index('receipt["sampling"]')
    assert sample_pos < snap_pos < write_pos, \
        "pacing snapshot must be taken after sampling, before write"
    assert "pacing_snapshot" in src2.split("from t1_probe import")[1] \
        .split(")")[0], "import wiring missing"
    checks["t2_round_wiring_write_time"] = True

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP14-PACING-SELFTEST", "ts": ts,
        "checks": checks,
        "settlement_leg": "fires on the first instrumented sampling run "
                          "(round-2); fp-20 mints at #88 close to carry it",
        "fp11_tie": "fp-11 modeled pacing by reconstruction; this meter "
                    "replaces the model with measurement on every future "
                    "t2 receipt",
    }
    out = os.path.join(NC, "receipts", f"fp14-pacing-selftest-{ts}.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print("FP14_PACING_SELFTEST_PASS")


if __name__ == "__main__":
    main()
