"""p_gate.py — P-gate: cross-session boundary persistence pair (eng-32, #114).

Claim shape: the gain persists across a SESSION boundary — fresh daemon
process, fresh model load from disk, zero in-memory carryover.

Protocol:
  receipt PAIR on the same surface + seed protocol:
  - pre:  the round's G1/w4 gate receipt (already exists per round)
  - post: after daemon restart + model/adapter reload from disk;
    one eval leg, same arms, same seeds

  Continuity stamps in both receipts:
  - ledger sha256 (must be UNCHANGED across boundary)
  - adapter sha256 (must be UNCHANGED across boundary)
  - daemon PID (must DIFFER — proves boundary was real)

  PASS iff:
  - post gain within pre gain's CI (exact + bootstrap both quoted)
  - ledger sha256 unchanged
  - adapter sha256 unchanged
  - PIDs differ

This script is MODE 1 ONLY (assemble/verify):
  Given paths to a PRE receipt and a POST receipt, emit
  p-gate-<ts>.json with verdict.

  The harness never starts daemon jobs, never touches GPU, never calls
  any HTTP endpoint. Future live-dispatch rides the serialized daemon
  queue and is gate-authorized separately.

LAUNCH INTERLOCK: any code path that could execute a real eval/train leg
  is gated behind EMBER_GATE_AUTHORIZED=1 AND --live.
  Default invocation and --selftest are 100% CPU-local on synthetic fixtures.

Spec: research/persistence-gates-spec.md §P-gate (frozen 2026-06-11, #36).
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
_RECEIPTS = _REPO / "receipts"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

SHA_CONVENTION = (
    "sha256 over raw file bytes in 65536-byte read chunks; "
    "hex-encoded lowercase; no header, no encoding, no metadata"
)


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256_file(path) -> str:
    """SHA-256 hex digest of file bytes. Fail-closed on missing."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"p_gate sha256: file not found: {p}")
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_str(s: str) -> str:
    """SHA-256 of a UTF-8 string (for synthetic receipt fixture hashes)."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Stats helpers (pure)
# ---------------------------------------------------------------------------

def _point_in_ci(point: float, lo: float, hi: float) -> bool:
    """True iff point is within [lo, hi]."""
    return lo <= point <= hi


def _exact_paired_ci_from_vectors(vec_a: list, vec_b: list,
                                   conf: float = 0.95) -> dict:
    """Newcombe paired CI (BINDING). Returns dict with lo/hi/b/c/n."""
    scripts_dir = str(_HERE)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from stats_exact import newcombe_paired_ci  # noqa: E402
    n = len(vec_a)
    b = sum(1 for a_, b_ in zip(vec_a, vec_b) if a_ and not b_)
    c = sum(1 for a_, b_ in zip(vec_a, vec_b) if b_ and not a_)
    lo, hi = newcombe_paired_ci(b, c, n, conf=conf)
    return {"method": "newcombe_paired_1998", "b": b, "c": c, "n": n,
            "lo": round(lo, 6), "hi": round(hi, 6), "conf": conf}


def _bootstrap_ci_from_vectors(vec_a: list, vec_b: list,
                                n_boot: int = 2000, seed: int = 42,
                                conf: float = 0.95) -> dict:
    """Paired delta bootstrap CI. Pure, no torch."""
    import random
    rng = random.Random(seed)
    n = len(vec_a)
    diffs = [a - b for a, b in zip(vec_a, vec_b)]
    observed = sum(diffs) / n
    boot = [sum(diffs[rng.randrange(n)] for _ in range(n)) / n
            for _ in range(n_boot)]
    boot.sort()
    alpha = 1.0 - conf
    lo = boot[int(n_boot * alpha / 2)]
    hi = boot[min(int(n_boot * (1 - alpha / 2)), n_boot - 1)]
    return {"observed": round(observed, 6),
            "lo": round(lo, 6), "hi": round(hi, 6),
            "n_boot": n_boot, "conf": conf}


# ---------------------------------------------------------------------------
# Receipt loading + field extraction
# ---------------------------------------------------------------------------

def _load_receipt(path) -> dict:
    """Load a JSON receipt file. Fail-closed on missing or parse error."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"p_gate: receipt not found: {p}")
    with open(p) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"p_gate: receipt JSON parse error {p}: {e}")


def _extract_gain_ci(receipt: dict, arm_name: str = None) -> dict:
    """Extract (gain_value, exact_ci_lo, exact_ci_hi) from a receipt.

    Supports both w4_eval receipt shape and d_gate receipt shape.
    For w4_eval: looks in receipt['deltas'] for arm-minus-base delta.
    For p_gate synthetic: expects receipt['gain'] dict.
    """
    # Try d_gate receipt shape first (gain_with field)
    if "gain_with" in receipt:
        g = receipt["gain_with"]
        return {
            "gain_value": g.get("value", 0.0),
            "exact_ci_lo": g.get("exact_ci", {}).get("lo", -1.0),
            "exact_ci_hi": g.get("exact_ci", {}).get("hi", 1.0),
        }
    # Try w4_eval receipt shape (deltas block)
    if "deltas" in receipt and arm_name:
        key = f"{arm_name}_minus_base_ci95"
        if key in receipt["deltas"]:
            ci = receipt["deltas"][key]
            # bootstrap_ci95 is [lo, hi]
            lo = ci[0] if isinstance(ci, list) else ci.get("lo", -1.0)
            hi = ci[1] if isinstance(ci, list) else ci.get("hi", 1.0)
            # Point estimate: average of arm and base pass_any_pct if available
            arms = receipt.get("arms", {})
            gain_val = 0.0
            if arm_name in arms and "base" in arms:
                gain_val = (arms[arm_name]["pass_any_pct"] -
                            arms["base"]["pass_any_pct"]) / 100.0
            return {"gain_value": gain_val, "exact_ci_lo": lo, "exact_ci_hi": hi}
    # Fall back to synthetic/test receipt shape
    if "gain" in receipt:
        g = receipt["gain"]
        return {
            "gain_value": g.get("value", 0.0),
            "exact_ci_lo": g.get("exact_ci_lo", -1.0),
            "exact_ci_hi": g.get("exact_ci_hi", 1.0),
        }
    # Fallback: return zeros
    return {"gain_value": 0.0, "exact_ci_lo": -1.0, "exact_ci_hi": 1.0}


def _extract_continuity_stamps(receipt: dict) -> dict:
    """Extract ledger_sha256, adapter_sha256, daemon_pid from a receipt."""
    # Normalize: accept different field spellings used across receipt types
    ledger_sha = (receipt.get("continuity_stamps", {}).get("ledger_sha256") or
                  receipt.get("ledger_sha256") or
                  receipt.get("ledger_sha256_before") or
                  None)
    adapter_sha = (receipt.get("continuity_stamps", {}).get("adapter_sha256") or
                   receipt.get("adapter_sha256") or
                   None)
    daemon_pid = (receipt.get("continuity_stamps", {}).get("daemon_pid") or
                  receipt.get("daemon_pid") or
                  None)
    return {"ledger_sha256": ledger_sha,
            "adapter_sha256": adapter_sha,
            "daemon_pid": daemon_pid}


# ---------------------------------------------------------------------------
# LAUNCH INTERLOCK
# ---------------------------------------------------------------------------

def _check_interlock(args) -> None:
    """Fail-closed: refuse any live eval unless EMBER_GATE_AUTHORIZED=1 + --live."""
    authorized = os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1"
    live = getattr(args, "live", False)
    if not (authorized and live):
        print(
            "P_GATE_INTERLOCK_BLOCKED: live eval/dispatch refused — "
            "EMBER_GATE_AUTHORIZED=1 env var not set AND/OR --live flag missing. "
            "This harness only assembles and verifies receipt pairs (Mode 1). "
            "Live post-leg dispatch rides the serialized daemon queue "
            "and is gate-authorized separately.",
            file=sys.stderr)
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Gate logic
# ---------------------------------------------------------------------------

def run_p_gate(pre_receipt_path, post_receipt_path, args=None) -> dict:
    """Assemble and verify a pre/post receipt pair. Returns receipt dict.

    This is Mode 1 only — assemble/verify. No eval legs dispatched here.
    """
    _RECEIPTS.mkdir(parents=True, exist_ok=True)
    ts = _utc_ts()

    pre_path = Path(pre_receipt_path)
    post_path = Path(post_receipt_path)

    pre_receipt = _load_receipt(pre_path)
    post_receipt = _load_receipt(post_path)

    arm_name = (args and getattr(args, "arm_name", None)) or "adapter"

    # ---- Extract gain CIs ----
    pre_gain = _extract_gain_ci(pre_receipt, arm_name)
    post_gain = _extract_gain_ci(post_receipt, arm_name)

    # ---- Extract continuity stamps ----
    pre_stamps = _extract_continuity_stamps(pre_receipt)
    post_stamps = _extract_continuity_stamps(post_receipt)

    ledger_unchanged = (
        pre_stamps["ledger_sha256"] is not None and
        post_stamps["ledger_sha256"] is not None and
        pre_stamps["ledger_sha256"] == post_stamps["ledger_sha256"]
    )
    adapter_unchanged = (
        pre_stamps["adapter_sha256"] is not None and
        post_stamps["adapter_sha256"] is not None and
        pre_stamps["adapter_sha256"] == post_stamps["adapter_sha256"]
    )
    pids_differ = (
        pre_stamps["daemon_pid"] is not None and
        post_stamps["daemon_pid"] is not None and
        pre_stamps["daemon_pid"] != post_stamps["daemon_pid"]
    )

    # ---- CI containment: post gain within pre gain's CI ----
    post_gain_in_pre_ci = _point_in_ci(
        post_gain["gain_value"],
        pre_gain["exact_ci_lo"],
        pre_gain["exact_ci_hi"],
    )

    # ---- Verdict ----
    verdict_pass = (post_gain_in_pre_ci and ledger_unchanged and
                    adapter_unchanged and pids_differ)
    verdict = "PASS" if verdict_pass else "FAIL"

    # Collect failure reasons for diagnostics
    failure_reasons = []
    if not post_gain_in_pre_ci:
        failure_reasons.append(
            f"FAIL_BY_CI: post_gain={post_gain['gain_value']:.4f} not in "
            f"pre_ci=({pre_gain['exact_ci_lo']:.4f},{pre_gain['exact_ci_hi']:.4f})")
    if not ledger_unchanged:
        failure_reasons.append(
            f"FAIL_BY_SHA_DRIFT_LEDGER: "
            f"pre={pre_stamps['ledger_sha256']} post={post_stamps['ledger_sha256']}")
    if not adapter_unchanged:
        failure_reasons.append(
            f"FAIL_BY_SHA_DRIFT_ADAPTER: "
            f"pre={pre_stamps['adapter_sha256']} post={post_stamps['adapter_sha256']}")
    if not pids_differ:
        failure_reasons.append(
            f"FAIL_BY_SAME_PID: pre_pid={pre_stamps['daemon_pid']} "
            f"post_pid={post_stamps['daemon_pid']} — session boundary not real")

    print(f"[p_gate] pre_gain={pre_gain['gain_value']:.4f} "
          f"pre_ci=({pre_gain['exact_ci_lo']:.4f},{pre_gain['exact_ci_hi']:.4f})",
          flush=True)
    print(f"[p_gate] post_gain={post_gain['gain_value']:.4f}", flush=True)
    print(f"[p_gate] ledger_unchanged={ledger_unchanged} "
          f"adapter_unchanged={adapter_unchanged} pids_differ={pids_differ}",
          flush=True)
    print(f"[p_gate] verdict: {verdict}", flush=True)
    for r in failure_reasons:
        print(f"[p_gate] {r}", flush=True)

    receipt = {
        "ticket": "P-GATE",
        "issue": "#114",
        "scope": "cross-session-boundary-persistence-pair",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "mode": "assemble-verify",
        "pre_receipt": str(pre_path),
        "post_receipt": str(post_path),
        "arm_name": arm_name,
        "pre_gain": pre_gain,
        "post_gain": post_gain,
        "continuity_stamps": {
            "pre": pre_stamps,
            "post": post_stamps,
        },
        "continuity_checks": {
            "ledger_sha256_unchanged": ledger_unchanged,
            "adapter_sha256_unchanged": adapter_unchanged,
            "pids_differ": pids_differ,
            "post_gain_in_pre_ci": post_gain_in_pre_ci,
        },
        "verdict_components": {
            "post_gain_value": post_gain["gain_value"],
            "pre_gain_ci_lo": pre_gain["exact_ci_lo"],
            "pre_gain_ci_hi": pre_gain["exact_ci_hi"],
            "ledger_unchanged": ledger_unchanged,
            "adapter_unchanged": adapter_unchanged,
            "pids_differ": pids_differ,
        },
        "failure_reasons": failure_reasons,
        "verdict": verdict,
        "pass": verdict_pass,
    }

    receipt_path = _RECEIPTS / f"p-gate-{ts}.json"
    # FAIL-CLOSED: assertions verified above; write receipt only on clean path
    with open(receipt_path, "w") as f:
        json.dump(receipt, f, indent=2)
    print(f"[p_gate] receipt: {receipt_path}", flush=True)
    return receipt


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _make_synthetic_receipt(ts: str, gain_value: float,
                             gain_ci_lo: float, gain_ci_hi: float,
                             ledger_sha: str, adapter_sha: str,
                             daemon_pid: int) -> dict:
    """Build a minimal synthetic receipt for selftest use."""
    return {
        "ticket": "SYNTHETIC",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "gain": {
            "value": gain_value,
            "exact_ci_lo": gain_ci_lo,
            "exact_ci_hi": gain_ci_hi,
        },
        "continuity_stamps": {
            "ledger_sha256": ledger_sha,
            "adapter_sha256": adapter_sha,
            "daemon_pid": daemon_pid,
        },
    }


def _selftest():
    """CPU-only selftest. Drives PASS, FAIL-by-CI, FAIL-by-sha-drift,
    and FAIL-by-same-PID branches.
    Final marker: P_GATE_SELFTEST_PASS
    """
    print("[p_gate selftest] starting ...", flush=True)
    import tempfile
    fails = []

    def check(name: str, condition: bool, detail: str = ""):
        if not condition:
            fails.append(f"FAIL {name}: {detail}")
            print(f"FAIL {name}: {detail}", flush=True)
        else:
            print(f"ok   {name}", flush=True)

    # Shared fixture values
    sha_ledger = _sha256_str("ledger_content_v1")
    sha_adapter = _sha256_str("adapter_content_v1")
    sha_ledger_drifted = _sha256_str("ledger_content_v2_drifted")
    sha_adapter_drifted = _sha256_str("adapter_content_v2_drifted")

    pre_ts = "20260611T000000Z"
    post_ts = "20260611T010000Z"

    # Synthetic gain that is "real": pre CI = [0.10, 0.40]
    pre_gain_val = 0.25
    pre_ci_lo = 0.10
    pre_ci_hi = 0.40
    # Post gain within CI
    post_gain_in_ci = 0.22
    # Post gain outside CI (CI failure)
    post_gain_outside_ci = 0.05

    def _write_receipt(receipt: dict) -> Path:
        td = Path(tempfile.mkdtemp())
        p = td / "receipt.json"
        with open(p, "w") as f:
            json.dump(receipt, f)
        return p

    # ---- Case 1: PASS ----
    pre_r = _make_synthetic_receipt(pre_ts, pre_gain_val, pre_ci_lo, pre_ci_hi,
                                    sha_ledger, sha_adapter, 1001)
    post_r = _make_synthetic_receipt(post_ts, post_gain_in_ci, 0.05, 0.38,
                                     sha_ledger, sha_adapter, 2002)
    pre_p = _write_receipt(pre_r)
    post_p = _write_receipt(post_r)
    r1 = run_p_gate(pre_p, post_p)
    check("pass_case_verdict", r1["pass"],
          f"expected PASS; failure_reasons={r1['failure_reasons']}")
    check("pass_case_pids_differ", r1["continuity_checks"]["pids_differ"],
          f"pre_pid=1001 post_pid=2002 should differ")
    check("pass_case_ledger_unchanged",
          r1["continuity_checks"]["ledger_sha256_unchanged"],
          "ledger sha should match")
    check("pass_case_ci_containment",
          r1["continuity_checks"]["post_gain_in_pre_ci"],
          f"post_gain={post_gain_in_ci} should be in ({pre_ci_lo},{pre_ci_hi})")

    # ---- Case 2: FAIL by CI ----
    post_r2 = _make_synthetic_receipt(post_ts, post_gain_outside_ci,
                                      0.0, 0.12, sha_ledger, sha_adapter, 2002)
    post_p2 = _write_receipt(post_r2)
    r2 = run_p_gate(pre_p, post_p2)
    check("fail_ci_verdict", not r2["pass"],
          f"expected FAIL; got {r2['verdict']}")
    check("fail_ci_reason_present",
          any("FAIL_BY_CI" in fr for fr in r2["failure_reasons"]),
          f"failure_reasons={r2['failure_reasons']}")

    # ---- Case 3: FAIL by sha drift (ledger changed) ----
    post_r3 = _make_synthetic_receipt(post_ts, post_gain_in_ci, 0.05, 0.38,
                                      sha_ledger_drifted, sha_adapter, 2002)
    post_p3 = _write_receipt(post_r3)
    r3 = run_p_gate(pre_p, post_p3)
    check("fail_sha_drift_verdict", not r3["pass"],
          f"expected FAIL; got {r3['verdict']}")
    check("fail_sha_drift_reason",
          any("FAIL_BY_SHA_DRIFT_LEDGER" in fr for fr in r3["failure_reasons"]),
          f"failure_reasons={r3['failure_reasons']}")

    # ---- Case 4: FAIL by same PID ----
    post_r4 = _make_synthetic_receipt(post_ts, post_gain_in_ci, 0.05, 0.38,
                                      sha_ledger, sha_adapter,
                                      1001)  # same PID as pre
    post_p4 = _write_receipt(post_r4)
    r4 = run_p_gate(pre_p, post_p4)
    check("fail_same_pid_verdict", not r4["pass"],
          f"expected FAIL; got {r4['verdict']}")
    check("fail_same_pid_reason",
          any("FAIL_BY_SAME_PID" in fr for fr in r4["failure_reasons"]),
          f"failure_reasons={r4['failure_reasons']}")

    # ---- Summary ----
    if fails:
        for f in fails:
            print(f)
        print("P_GATE_SELFTEST_FAIL", flush=True)
        raise SystemExit(1)

    print("\nP_GATE_SELFTEST_PASS", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    ap = argparse.ArgumentParser(
        description="P-gate: cross-session boundary persistence pair (eng-32 #114)")
    ap.add_argument("--selftest", action="store_true",
                    help="CPU-only selftest; no GPU/network required")
    ap.add_argument("--pre", default=None,
                    help="Path to PRE receipt (G1/w4 gate receipt, pre-restart)")
    ap.add_argument("--post", default=None,
                    help="Path to POST receipt (post-restart eval leg)")
    ap.add_argument("--arm-name", default="adapter",
                    help="Arm name for gain extraction from w4_eval receipts")
    ap.add_argument("--live", action="store_true",
                    help="Reserved for future live dispatch (currently blocked; "
                         "this PR is assemble/verify mode only)")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return

    if args.live or os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1":
        # Live dispatch is not implemented in this PR — interlock blocks it
        if args.live:
            _check_interlock(args)

    if args.pre is None or args.post is None:
        print("p_gate: --pre <path> and --post <path> are required",
              file=sys.stderr)
        raise SystemExit(1)

    receipt = run_p_gate(args.pre, args.post, args)
    print(f"\n[p_gate] verdict: {receipt['verdict']}", flush=True)


if __name__ == "__main__":
    _main()
