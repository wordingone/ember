"""ckpt_locality.py — checkpoint write-locality measurement instrument (eng-58 / #231, fp-32 R5).

R5 hypothesis (fp-32 WATCH row): ~5 GB checkpoint state (model + optimizer + RNG)
written synchronously to /mnt/b over 9p ≈ 30–35 s GPU stall per checkpoint; this binds
only if checkpoint cadence < ~10 min.

MEASURE-FIRST is the entire discipline of #231: do NOT build the WSL-ext4 staging
intervention until a MEASUREMENT says it binds. The measurement needs the FIRST real v0
checkpoint, which only exists after the launch — downstream of the whole #195 critical
path. This module is the apparatus that MEASURES and DECIDES at that checkpoint, and it is
fully testable today on synthetic timings:

  classify(ckpt_wall_s, segment_wall_s) -> verdict
    ckpt_frac = ckpt_wall_s / segment_wall_s
    ckpt_frac <= KILL_THRESHOLD (0.05)  -> R5-KILLED-NOOP   (AC2): the synchronous /mnt/b
        write is <=5% of segment wall; staging would buy nothing, R5 flips killed, the
        negative note is recorded.
    ckpt_frac >  KILL_THRESHOLD          -> R5-BINDS         (AC3, the if-binds follow-up):
        stage the checkpoint to WSL-native ext4, async-copy to B:, byte-true sha
        verification AFTER the copy lands; no checkpoint is declared durable before the
        verified copy. The staging ACTION is NOT built here (measure-first); only the
        durability CHECK that would gate it (verify_copy_sha_chain) is provided + tested,
        because that check is the safety rule, not the intervention.

AC4: this instrument NEVER changes checkpoint cadence to dodge the measurement. It reads
timings and decides; the cadence stays the trainer's, untouched.

Downstream wiring (lands with the live run — one timing wrap in save_checkpoint's caller,
no cadence change):
    t = time.time(); ckpt_dir = save_checkpoint(...); ckpt_wall_s = time.time() - t
    manifest["ckpt_wall_s"] = ckpt_wall_s        # segment_wall_s on the segment receipt
Then `ckpt_locality.py --measure --manifest <ckpt>/manifest.json --segment-wall <s>` emits
the R5 verdict receipt (fields land in/alongside the P-own-resume or segment receipt per
AC1).
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from receipt_write import checked_write  # noqa: E402

RECEIPTS = os.path.join(NC, "receipts")
SHA_CONVENTION = ("file shas = sha256 over the exact on-disk raw bytes, no "
                  "normalization")

# R5 kill threshold: checkpoint wall <= 5% of segment wall => write locality does
# not bind (staging is a no-op). Boundary is INCLUSIVE on the kill side (exactly
# 5% => killed): the intervention must clear the bar strictly to be worth its
# complexity. Frozen here as the #231 decision constant.
KILL_THRESHOLD = 0.05

# R5's own stated hypothesis, kept as a sanity anchor for the selftest (not a pin):
# a ~30-35 s synchronous write binds only when cadence < ~10 min.
HYP_CKPT_STALL_S = 35.0
HYP_BINDS_BELOW_CADENCE_S = 600.0   # 10 min


def classify(ckpt_wall_s, segment_wall_s, threshold=KILL_THRESHOLD):
    """Decide whether checkpoint write-locality binds. Pure, model-free."""
    if segment_wall_s <= 0:
        raise ValueError(f"segment_wall_s must be > 0, got {segment_wall_s}")
    if ckpt_wall_s < 0:
        raise ValueError(f"ckpt_wall_s must be >= 0, got {ckpt_wall_s}")
    frac = ckpt_wall_s / segment_wall_s
    binds = frac > threshold
    verdict = "R5-BINDS" if binds else "R5-KILLED-NOOP"
    note = None
    if not binds:
        note = (f"ckpt wall {ckpt_wall_s:.2f}s is {frac*100:.2f}% of segment "
                f"wall {segment_wall_s:.2f}s (<= {threshold*100:.0f}% kill bar) "
                f"— /mnt/b synchronous write does not bind; WSL-ext4 staging "
                f"would buy nothing. R5 flipped KILLED, no-op.")
    return {
        "ckpt_wall_s": round(float(ckpt_wall_s), 4),
        "segment_wall_s": round(float(segment_wall_s), 4),
        "ckpt_frac": round(frac, 6),
        "kill_threshold": threshold,
        "r5_verdict": verdict,
        "binds": binds,
        "negative_note": note,
    }


def verify_copy_sha_chain(stage_sha256, dest_sha256):
    """AC3 durability rule (pure logic, testable without any copy): a staged
    checkpoint is durable on B: ONLY if the destination bytes hash-match the
    staged bytes. Returns True iff the chain holds. The staging COPY itself is
    not built here (measure-first); this is the check that would gate it."""
    return (isinstance(stage_sha256, str) and isinstance(dest_sha256, str)
            and len(stage_sha256) == 64 and stage_sha256 == dest_sha256)


def staging_contract():
    """The AC3 if-binds intervention contract — DOCUMENTATION, not executed.
    Recorded so that, if a measurement flips R5-BINDS, the staging path lands
    against a fixed spec rather than being improvised."""
    return {
        "fires_when": "classify(...) == R5-BINDS (ckpt_frac > kill_threshold)",
        "steps": [
            "1. write checkpoint to WSL-native ext4 (fast local fs), record stage sha256",
            "2. async-copy the checkpoint dir from ext4 to the B:/run_dir location",
            "3. AFTER the copy lands, re-derive dest sha256 from the B: bytes",
            "4. verify_copy_sha_chain(stage_sha256, dest_sha256) must hold",
            "5. ONLY THEN is the checkpoint declared durable (resume-eligible)",
        ],
        "invariants": [
            "no checkpoint is declared durable before the verified copy lands",
            "P-own-resume receipt fields unchanged (sp2b_gate.P_OWN_RESUME_REQUIRED)",
            "cadence unchanged (AC4)",
        ],
        "built": False,  # measure-first: only lands if a measurement says it binds
    }


def emit_receipt(ckpt_wall_s, segment_wall_s, source, threshold=KILL_THRESHOLD):
    c = classify(ckpt_wall_s, segment_wall_s, threshold)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "ENG-58-R5",
        "ts": ts,
        "issue": 231,
        "refs": [225, 210],
        "no_gpu": True,
        "sha_convention": SHA_CONVENTION,
        "script_sha256": _script_sha256(),
        "measurement": c,
        "source": source,
        "staging_contract": staging_contract(),
        "cadence_untouched": True,
    }
    out = os.path.join(RECEIPTS, f"ckpt-locality-{ts}.json")
    checked_write(out, receipt)
    return out, c


def measure_from_manifest(manifest_path, segment_wall_s):
    """Read ckpt_wall_s from a checkpoint manifest (written by the downstream
    save_checkpoint timing wrap) and classify against the segment wall."""
    with open(manifest_path, encoding="utf-8") as f:
        m = json.load(f)
    if "ckpt_wall_s" not in m:
        raise KeyError(
            f"{manifest_path} has no ckpt_wall_s — the save_checkpoint timing "
            f"wrap (downstream wiring) has not landed; nothing to measure yet.")
    return emit_receipt(m["ckpt_wall_s"], segment_wall_s,
                        source=os.path.basename(manifest_path))


def _script_sha256():
    with open(os.path.abspath(__file__), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _selftest():
    import tempfile
    fails = []

    # T-kill: ckpt wall well under the bar -> KILLED-NOOP + negative note.
    k = classify(1.0, 100.0)
    if k["r5_verdict"] != "R5-KILLED-NOOP" or k["binds"]:
        fails.append(f"T-kill verdict {k['r5_verdict']} binds={k['binds']}")
    if not k["negative_note"]:
        fails.append("T-kill missing negative_note")

    # T-binds: ckpt wall over the bar -> BINDS, no negative note.
    b = classify(40.0, 100.0)
    if b["r5_verdict"] != "R5-BINDS" or not b["binds"]:
        fails.append(f"T-binds verdict {b['r5_verdict']} binds={b['binds']}")
    if b["negative_note"] is not None:
        fails.append("T-binds should have no negative_note")

    # T-boundary: exactly 5% is INCLUSIVE on the kill side; 5.01% binds.
    if classify(5.0, 100.0)["binds"]:
        fails.append("T-boundary 5.0% must NOT bind (inclusive kill)")
    if not classify(5.01, 100.0)["binds"]:
        fails.append("T-boundary 5.01% must bind")

    # T-hypothesis: the instrument reproduces R5's own claim — a 35 s write
    # binds at a 10 min cadence (35/600 = 5.83% > 5%) and is killed at 30 min
    # (35/1800 = 1.94% <= 5%).
    if not classify(HYP_CKPT_STALL_S, HYP_BINDS_BELOW_CADENCE_S)["binds"]:
        fails.append("T-hypothesis 35s @ 600s cadence must bind")
    if classify(HYP_CKPT_STALL_S, 1800.0)["binds"]:
        fails.append("T-hypothesis 35s @ 1800s cadence must be killed")

    # T-sha-chain: durability check holds iff dest bytes match staged bytes.
    good = "a" * 64
    if not verify_copy_sha_chain(good, good):
        fails.append("T-sha-chain matching shas must verify")
    if verify_copy_sha_chain(good, "b" * 64):
        fails.append("T-sha-chain mismatched shas must NOT verify")
    if verify_copy_sha_chain("short", "short"):
        fails.append("T-sha-chain non-sha256 (wrong length) must NOT verify")

    # T-guards: invalid timings raise.
    for args in ((1.0, 0.0), (1.0, -5.0), (-1.0, 100.0)):
        try:
            classify(*args)
            fails.append(f"T-guards classify{args} should have raised")
        except ValueError:
            pass

    # T-receipt: both verdict receipts pass the fail-closed schema floor.
    with tempfile.TemporaryDirectory() as td:
        import receipt_check
        for cw, sw in ((1.0, 100.0), (40.0, 100.0)):
            c = classify(cw, sw)
            r = {"ticket": "ENG-58-R5-TEST", "ts": "20260611T000000Z",
                 "sha_convention": SHA_CONVENTION, "measurement": c,
                 "staging_contract": staging_contract()}
            findings = receipt_check.validate_receipt(r)
            if findings:
                fails.append(f"T-receipt schema findings for ({cw},{sw}): {findings}")

    if fails:
        for f in fails:
            print("SELFTEST_FAIL:", f)
        return 1
    print("CKPT_LOCALITY_SELFTEST_PASS")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true",
                    help="pure-logic decision + sha-chain + receipt-schema "
                         "tests; prints CKPT_LOCALITY_SELFTEST_PASS")
    ap.add_argument("--measure", action="store_true",
                    help="emit the R5 verdict receipt from a real checkpoint")
    ap.add_argument("--manifest", help="checkpoint manifest.json with ckpt_wall_s")
    ap.add_argument("--ckpt-wall", type=float, help="checkpoint wall seconds (direct)")
    ap.add_argument("--segment-wall", type=float, help="segment wall seconds")
    ap.add_argument("--contract", action="store_true",
                    help="print the AC3 if-binds staging contract and exit")
    args, _ = ap.parse_known_args()

    if args.selftest:
        sys.exit(_selftest())
    if args.contract:
        print(json.dumps(staging_contract(), indent=2))
        sys.exit(0)
    if args.measure:
        if args.segment_wall is None:
            print("--measure requires --segment-wall", file=sys.stderr)
            sys.exit(2)
        if args.manifest:
            out, c = measure_from_manifest(args.manifest, args.segment_wall)
        elif args.ckpt_wall is not None:
            out, c = emit_receipt(args.ckpt_wall, args.segment_wall,
                                  source="direct-args")
        else:
            print("--measure needs --manifest or --ckpt-wall", file=sys.stderr)
            sys.exit(2)
        print(json.dumps(c, indent=2))
        print(f"receipt: {os.path.basename(out)}")
        print("CKPT_LOCALITY_MEASURE_DONE")
        sys.exit(0)
    ap.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
