# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""loop_econ_gate.py — DT-6 loop-economics gate checker.

Per docs/archive/pre-restart/dt6-loop-economics-gate-amendment.md:

A PASS verdict is valid only if it reports verified signal-per-GPU-hour
exceeding the equal-wall-clock band. Three ACs:

  AC1: verdict JSON with "verdict":"PASS" but MISSING signal_per_gpu_hour
       → REJECT (malformed)
  AC2: all three fields + exceeds_band:true → ACCEPT (exit 0)
  AC3: fields present but signal_per_gpu_hour <= equal_wallclock_band
       → REJECT-as-within-floor (power statement, not PASS)

Usage:
  python loop_econ_gate.py --selftest
  python loop_econ_gate.py --check path/to/verdict.json
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECEIPTS = ROOT / "receipts"
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.lib.invariant import stamp as _stamp_invariant, verify as _verify_invariant  # noqa: E402 -- gh #625 point 1

# receipt_check.py's R2 rule requires any *sha256*-named field to carry a
# disclosed sha_convention; matches exactly what scripts/lib/invariant.py's
# stamp() does (Path.read_bytes() + sha256, no normalization).
INVARIANT_SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"

REQUIRED_FIELDS = ("signal_per_gpu_hour", "equal_wallclock_band", "exceeds_band")


def check_econ_gate(verdict: dict) -> dict:
    """Pure checker. Returns dict with keys: decision, reason, ac."""
    if verdict.get("verdict") != "PASS":
        return {"decision": "SKIP", "reason": "verdict is not PASS — gate applies to PASS verdicts only", "ac": None}

    missing = [f for f in REQUIRED_FIELDS if f not in verdict]
    if missing:
        return {
            "decision": "REJECT",
            "reason": f"PASS verdict missing required field(s): {missing}",
            "ac": "AC1",
        }

    sig = verdict["signal_per_gpu_hour"]
    band = verdict["equal_wallclock_band"]
    exceeds = verdict["exceeds_band"]

    if not isinstance(exceeds, bool):
        return {
            "decision": "REJECT",
            "reason": f"exceeds_band must be bool, got {type(exceeds).__name__}",
            "ac": "AC1",
        }

    if sig <= band:
        return {
            "decision": "REJECT",
            "reason": (
                f"signal_per_gpu_hour={sig} <= equal_wallclock_band={band} "
                "— within-floor (power statement, not PASS)"
            ),
            "ac": "AC3",
        }

    if not exceeds:
        return {
            "decision": "REJECT",
            "reason": "exceeds_band=false — verdict claims PASS but does not exceed band",
            "ac": "AC3",
        }

    return {
        "decision": "ACCEPT",
        "reason": (
            f"signal_per_gpu_hour={sig} > equal_wallclock_band={band} "
            f"and exceeds_band=true"
        ),
        "ac": "AC2",
    }


def run_selftest() -> bool:
    failures = []

    def check(name, cond, detail=""):
        if not cond:
            failures.append(f"{name}: {detail}" if detail else name)
            print(f"FAIL {name}: {detail}")
        else:
            print(f"ok   {name}")

    # AC1: PASS verdict missing signal_per_gpu_hour
    verdict_ac1 = {"verdict": "PASS", "equal_wallclock_band": 0.5, "exceeds_band": True}
    r1 = check_econ_gate(verdict_ac1)
    check("ac1_decision_reject", r1["decision"] == "REJECT",
          f"got {r1['decision']!r}, expected REJECT")
    check("ac1_ac_label", r1["ac"] == "AC1",
          f"got {r1['ac']!r}, expected AC1")
    check("ac1_reason_mentions_missing", "missing" in r1["reason"].lower(),
          f"reason: {r1['reason']!r}")

    # AC2: all three fields, exceeds_band=True, sig > band
    verdict_ac2 = {
        "verdict": "PASS",
        "signal_per_gpu_hour": 1.2,
        "equal_wallclock_band": 0.5,
        "exceeds_band": True,
    }
    r2 = check_econ_gate(verdict_ac2)
    check("ac2_decision_accept", r2["decision"] == "ACCEPT",
          f"got {r2['decision']!r}, expected ACCEPT")
    check("ac2_ac_label", r2["ac"] == "AC2",
          f"got {r2['ac']!r}, expected AC2")

    # AC3: fields present but sig <= band
    verdict_ac3 = {
        "verdict": "PASS",
        "signal_per_gpu_hour": 0.4,
        "equal_wallclock_band": 0.5,
        "exceeds_band": True,
    }
    r3 = check_econ_gate(verdict_ac3)
    check("ac3_decision_reject", r3["decision"] == "REJECT",
          f"got {r3['decision']!r}, expected REJECT")
    check("ac3_ac_label", r3["ac"] == "AC3",
          f"got {r3['ac']!r}, expected AC3")
    check("ac3_reason_within_floor", "within-floor" in r3["reason"] or "floor" in r3["reason"],
          f"reason: {r3['reason']!r}")

    passed = len(failures) == 0
    cases_checked = 3

    # gh #625 point 1, fail-closed: verify BEFORE the receipt is written --
    # an unresolvable invariant means this selftest must not write anything.
    _verify_invariant(str(ROOT))

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    RECEIPTS.mkdir(exist_ok=True)
    receipt_path = RECEIPTS / f"loop-econ-gate-selftest-{ts}.json"

    try:
        from receipt_write import checked_write
        write = lambda p, d: checked_write(str(p), d)
    except ImportError:
        def write(p, d):
            Path(p).write_text(json.dumps(d, indent=2), encoding="utf-8")

    receipt = {
        "ticket": "DT6-LOOP-ECON-GATE-SELFTEST",
        "ts": ts,
        "cases_checked": cases_checked,
        "ac1": {"verdict": r1["decision"], "ac": r1["ac"]},
        "ac2": {"verdict": r2["decision"], "ac": r2["ac"]},
        "ac3": {"verdict": r3["decision"], "ac": r3["ac"]},
        "failures": failures,
        "pass": passed,
    }
    _stamp_invariant(receipt, repo_root=str(ROOT))
    receipt["sha_convention"] = INVARIANT_SHA_CONVENTION
    write(receipt_path, receipt)
    print(f"receipt: {receipt_path}")

    if passed:
        print(f"LOOP_ECON_GATE_SELFTEST_PASS cases={cases_checked}/3")
    else:
        for f in failures:
            print(f"FAIL: {f}")

    return passed


def run_check(path: str) -> bool:
    verdict_path = Path(path)
    if not verdict_path.exists():
        print(f"REJECT: file not found: {path}")
        return False

    try:
        verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"REJECT: could not parse JSON: {e}")
        return False

    result = check_econ_gate(verdict)
    print(f"{result['decision']} [{result.get('ac', '-')}]: {result['reason']}")
    return result["decision"] == "ACCEPT"


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    if args[0] == "--selftest":
        ok = run_selftest()
        sys.exit(0 if ok else 1)

    if args[0] == "--check" and len(args) >= 2:
        ok = run_check(args[1])
        sys.exit(0 if ok else 1)

    print(f"unknown args: {args}")
    print(__doc__)
    sys.exit(1)


if __name__ == "__main__":
    main()
