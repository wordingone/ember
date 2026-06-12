"""fp_verdict_chain_rehearsal.py — end-to-end dress rehearsal for the 2B verdict chain.

Drives synthetic probe receipts through the full fp24 -> fp29 -> fp36
pipeline to prove wiring is correct BEFORE the real 1B checkpoint
(~step 244k, ~1 day) materializes. Covers all verdict/gate branches.

Chains exercised:
  A. 2B PASS          fp24 PASS -> fp29 PASS-THROUGH
  B. 2B RETRY + 4B KILL, synthesis absent  -> fp29 KILL-REFUSED-UNRECEIPTED
  C. 4B KILL, synthesis malformed          -> fp29 KILL-REFUSED-MALFORMED
  D. 4B KILL, synthesis valid              -> fp29 KILL-VALID
  E. 2B RETRY + 4B late-onset PASS        -> fp29 PASS-THROUGH
  F. fp36_consistency pre-data guard       -> FP36_CONSISTENCY_PASS

`--selftest`: exercises all branches, asserts outcomes, prints
  FP_VERDICT_CHAIN_REHEARSAL_SELFTEST_PASS.
`--emit`: runs selftest + writes dress rehearsal receipt to receipts/.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import fp24_verdict as fp24                        # noqa: E402
import fp29_kill_synthesis_gate as fp29gate        # noqa: E402
from receipt_write import checked_write            # noqa: E402
from receipt_check import validate_receipt         # noqa: E402

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"

# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

_FAKE_SHA40 = "a" * 40
_FAKE_SHA64 = "b" * 64
_FAKE_CORPUS_SHA = "c" * 64
_FAKE_PROBE_SET_SHA = "d" * 64


def _probe_receipt(checkpoint_tokens, l1_verified, l1_minutes, step=244000):
    """Minimal well-formed fp23-schema probe receipt for dress rehearsal."""
    return {
        "ticket": f"DRESS-REHEARSAL-PROBE-{checkpoint_tokens // 1_000_000_000}B-SYNTHETIC",
        "ts": "20260612T000000Z",
        "checkpoint_tokens": checkpoint_tokens,
        "step": step,
        "tokenizer_sha256": _FAKE_SHA64,
        "corpus_manifest_sha256": _FAKE_CORPUS_SHA,
        "adapter_none_assert": True,
        "pacing": "timed",
        "governor": "fp23-timed",
        "probe_seed": 23,
        "probe_set_sha256": _FAKE_PROBE_SET_SHA,
        "l1_verified_episodes": l1_verified,
        "l1_governed_minutes": l1_minutes,
        "l1_tasks_any_verified": max(0, l1_verified),
        "l1_tasks_total": 100,
        "l2_verified_episodes": 0,
        "mbpp43_verified_samples": 0,
        "protocol_sha": _FAKE_SHA40,
        "harness_sha": _FAKE_SHA40,
        "sha_convention": SHA_CONVENTION,
    }


def _synthesis_receipt_valid(manifest_sha):
    return {
        "ticket": "CURRICULUM-SYNTHESIS-2B4B",
        "ts": "20260612T000000Z",
        "window": "2B->4B",
        "episodes_generated": 120,
        "bucket_range_assert": True,
        "ops_in_grammar_assert": True,
        "probe_buckets_untouched_assert": True,
        "ingestion_manifest_sha256": "e" * 64,
        "episodes_manifest_sha256": manifest_sha,
        "sha_convention": SHA_CONVENTION,
    }


def _synthesis_receipt_malformed():
    return {
        "ticket": "CURRICULUM-SYNTHESIS-2B4B",
        "ts": "20260612T000000Z",
        # window missing intentionally
        "episodes_generated": 0,  # invalid: must be > 0
        "bucket_range_assert": True,
        "ops_in_grammar_assert": True,
        "probe_buckets_untouched_assert": True,
        "ingestion_manifest_sha256": "f" * 64,
        "episodes_manifest_sha256": "g" * 64,
        "sha_convention": SHA_CONVENTION,
    }


# ---------------------------------------------------------------------------
# Rehearsal
# ---------------------------------------------------------------------------

def _manifest_sha_from_fp29_dryrun():
    """Read episodes_manifest_sha256 from the fp29 dry-run receipt if present."""
    import glob
    pattern = os.path.join(NC, "receipts", "fp29-curriculum-dryrun-*.json")
    hits = sorted(glob.glob(pattern))
    if not hits:
        return "0" * 64
    with open(hits[-1]) as f:
        r = json.load(f)
    return r.get("episodes_manifest_sha256", "0" * 64)


def run_rehearsal():
    """Run all chains. Returns (outcomes_dict, errors_list).

    errors_list is empty on full success; each entry names the failing check.
    """
    errors = []
    outcomes = {}

    manifest_sha = _manifest_sha_from_fp29_dryrun()

    # ---- Chain A: 2B PASS ------------------------------------------------
    probe_2b_pass = _probe_receipt(2_000_000_000, l1_verified=30, l1_minutes=20.0)
    v_a = fp24.run_verdict("2B", probe_2b_pass)
    outcomes["A_2B_PASS_verdict"] = v_a.get("verdict")
    if v_a.get("verdict") != "PASS":
        errors.append(f"Chain A: expected PASS, got {v_a.get('verdict')!r} ({v_a})")
    gate_a = fp29gate.validate_kill(v_a)
    outcomes["A_fp29_gate"] = gate_a.get("gate")
    if gate_a.get("gate") != "PASS-THROUGH":
        errors.append(f"Chain A: fp29 gate expected PASS-THROUGH, got {gate_a.get('gate')!r}")

    # ---- Chain B: 2B RETRY -> 4B KILL, no synthesis ----------------------
    probe_2b_fail = _probe_receipt(2_000_000_000, l1_verified=5, l1_minutes=20.0)
    v_b_2b = fp24.run_verdict("2B", probe_2b_fail)
    outcomes["B_2B_RETRY_verdict"] = v_b_2b.get("verdict")
    if v_b_2b.get("verdict") != "RETRY-AT-4B":
        errors.append(f"Chain B: expected RETRY-AT-4B, got {v_b_2b.get('verdict')!r}")

    probe_4b_kill = _probe_receipt(4_000_000_000, l1_verified=5, l1_minutes=20.0)
    # run_verdict expects prior_2b_verdict as the verdict STRING, not the full dict
    # (main() extracts via pv.get("result", pv).get("verdict") from the receipt file)
    v_b_4b = fp24.run_verdict("4B", probe_4b_kill, prior_2b_verdict=v_b_2b.get("verdict"))
    outcomes["B_4B_KILL_verdict"] = v_b_4b.get("verdict")
    if v_b_4b.get("verdict") != "KILL":
        errors.append(f"Chain B: expected KILL, got {v_b_4b.get('verdict')!r}")

    gate_b = fp29gate.validate_kill(v_b_4b, synthesis_receipt=None)
    outcomes["B_fp29_gate"] = gate_b.get("gate")
    if gate_b.get("gate") != "KILL-REFUSED-SYNTHESIS-UNRECEIPTED":
        errors.append(f"Chain B: expected KILL-REFUSED-SYNTHESIS-UNRECEIPTED, "
                      f"got {gate_b.get('gate')!r}")

    # ---- Chain C: 4B KILL, synthesis malformed ----------------------------
    sr_bad = _synthesis_receipt_malformed()
    gate_c = fp29gate.validate_kill(v_b_4b, synthesis_receipt=sr_bad)
    outcomes["C_fp29_gate"] = gate_c.get("gate")
    if gate_c.get("gate") != "KILL-REFUSED-SYNTHESIS-MALFORMED":
        errors.append(f"Chain C: expected KILL-REFUSED-SYNTHESIS-MALFORMED, "
                      f"got {gate_c.get('gate')!r}")

    # ---- Chain D: 4B KILL, synthesis valid --------------------------------
    sr_good = _synthesis_receipt_valid(manifest_sha)
    gate_d = fp29gate.validate_kill(v_b_4b, synthesis_receipt=sr_good)
    outcomes["D_fp29_gate"] = gate_d.get("gate")
    if gate_d.get("gate") != "KILL-VALID":
        errors.append(f"Chain D: expected KILL-VALID, got {gate_d.get('gate')!r}")

    # ---- Chain E: 2B RETRY -> 4B late-onset PASS -------------------------
    probe_4b_pass = _probe_receipt(4_000_000_000, l1_verified=30, l1_minutes=20.0)
    v_e_4b = fp24.run_verdict("4B", probe_4b_pass, prior_2b_verdict=v_b_2b.get("verdict"))
    outcomes["E_4B_LATE_PASS_verdict"] = v_e_4b.get("verdict")
    if v_e_4b.get("verdict") != "PASS":
        errors.append(f"Chain E: expected late-onset PASS, got {v_e_4b.get('verdict')!r}")
    gate_e = fp29gate.validate_kill(v_e_4b)
    outcomes["E_fp29_gate"] = gate_e.get("gate")
    if gate_e.get("gate") != "PASS-THROUGH":
        errors.append(f"Chain E: fp29 gate expected PASS-THROUGH, got {gate_e.get('gate')!r}")

    # ---- Chain F: fp36_consistency pre-data guard -------------------------
    script = os.path.join(HERE, "fp36_consistency.py")
    result = subprocess.run(
        [sys.executable, script],
        capture_output=True, text=True, cwd=NC
    )
    fp36_ok = result.returncode == 0 and "FP36_CONSISTENCY_PASS" in result.stdout
    outcomes["F_fp36_consistency"] = "PASS" if fp36_ok else "FAIL"
    if not fp36_ok:
        errors.append(f"Chain F: fp36_consistency failed: {result.stdout.strip()} "
                      f"/ {result.stderr.strip()}")

    return outcomes, errors


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def _selftest():
    outcomes, errors = run_rehearsal()
    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        raise SystemExit("FP_VERDICT_CHAIN_REHEARSAL: wiring breaks found")
    print("FP_VERDICT_CHAIN_REHEARSAL_SELFTEST_PASS")
    for k, v in sorted(outcomes.items()):
        print(f"  {k}: {v}")


def main():
    ap = argparse.ArgumentParser(
        description="fp verdict-chain dress rehearsal — 2B->4B end-to-end wiring check"
    )
    ap.add_argument("--selftest", action="store_true",
                    help="run all chains, assert outcomes")
    ap.add_argument("--emit", action="store_true",
                    help="run selftest + write rehearsal receipt to receipts/")
    args = ap.parse_args()

    if not (args.selftest or args.emit):
        print(
            "FP_VERDICT_CHAIN_REHEARSAL_STAGED\n"
            "  --selftest: exercise all verdict/gate branches\n"
            "  --emit: selftest + write receipt"
        )
        return

    outcomes, errors = run_rehearsal()
    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        raise SystemExit("FP_VERDICT_CHAIN_REHEARSAL: wiring breaks found")

    print("FP_VERDICT_CHAIN_REHEARSAL_SELFTEST_PASS")
    for k, v in sorted(outcomes.items()):
        print(f"  {k}: {v}")

    if args.emit:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        receipt = {
            "ticket": "FP-VERDICT-CHAIN-REHEARSAL",
            "ts": ts,
            "chains_exercised": list(sorted(outcomes.keys())),
            "outcomes": outcomes,
            "errors": errors,
            "all_chains_pass": not errors,
            "fp36_consistency": outcomes.get("F_fp36_consistency"),
            "manifest_sha_used": _manifest_sha_from_fp29_dryrun(),
            "wiring_breaks": len(errors),
            "note": (
                "Dress rehearsal for 2B verdict chain (fp24 -> fp29 -> fp36). "
                "Synthetic probe receipts cover all verdict/gate branches. "
                "No GPU. No real checkpoint consumed. "
                "Executed before real 1B checkpoint (~step 244k). "
                "WIRING-GUIDANCE: run_verdict() prior_2b_verdict arg is a "
                "verdict STRING ('RETRY-AT-4B'), not the full dict — "
                "callers using a prior verdict dict must extract "
                ".get('verdict') or .get('result',{}).get('verdict') first "
                "(as main() does via pv.get('result',pv).get('verdict'))."
            ),
            "sha_convention": SHA_CONVENTION,
            "no_gpu": True,
        }
        findings = validate_receipt(receipt)
        if findings:
            raise SystemExit(f"receipt_check FAIL on rehearsal receipt: {findings}")
        out = os.path.join(NC, "receipts", f"fp-verdict-chain-rehearsal-{ts}.json")
        checked_write(out, receipt)
        print(f"\nRECEIPT: {out}")


if __name__ == "__main__":
    main()
