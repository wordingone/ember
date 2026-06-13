#!/usr/bin/env python3
"""fp33_b_legs_prestage.py — Receipt-emitter pre-stage for fp-33 B-leg instruments.

Defines emit functions for each B-leg (B1-B4) per fp33-surpass-prereg-v1.md.
Each emit function writes a receipt into receipts/ with a 'leg' field.
fp33_surpass_verdict.py --receipts receipts discriminates by 'leg'.

Schemas (Leo mail 15350 + fp33-surpass-verdict-gate.md):
  B1: {leg, ember_probe_pass:[0/1×5], e2b_probe_pass:[0/1×5]}
  B2: {leg, ember_action_done:[0/1×5], e2b_action_done:[0/1×5]}
  B3: {leg, ember_episode_pass:[0/1×20], e2b_episode_pass:[0/1×20]}
  B4: {leg, receipt_exists:bool, dispatched_through_harness:bool}

Usage:
    python fp33_b_legs_prestage.py --selftest   # dry-run: synthetic receipts only
    python fp33_b_legs_prestage.py --emit-b1 EMBER_PASS_JSON E2B_PASS_JSON
    python fp33_b_legs_prestage.py --emit-b2 EMBER_DONE_JSON E2B_DONE_JSON
    python fp33_b_legs_prestage.py --emit-b3 EMBER_PASS_JSON E2B_PASS_JSON
    python fp33_b_legs_prestage.py --emit-b4 --receipt-path PATH [--dispatched]

Selftest marker: FP33_B_LEGS_PRESTAGE_SELFTEST_PASS
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

NC = Path(__file__).resolve().parent.parent
RECEIPTS = NC / "receipts"
RECEIPTS.mkdir(exist_ok=True)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ── Schema constants ─────────────────────────────────────────────────────────

B1_N = 5    # number of mail probes
B2_N = 5    # number of agency events
B3_N = 20   # number of duty episodes


# ── Emit functions ───────────────────────────────────────────────────────────

def emit_b1_receipt(
    ember_probe_pass: list[int],
    e2b_probe_pass: list[int],
    *,
    harness_sha: str = "",
    dry_run: bool = False,
) -> Path:
    """Write B1 (mail round-trip) receipt. Returns path written."""
    if len(ember_probe_pass) != B1_N:
        raise ValueError(f"B1 ember_probe_pass must be length {B1_N}, got {len(ember_probe_pass)}")
    if len(e2b_probe_pass) != B1_N:
        raise ValueError(f"B1 e2b_probe_pass must be length {B1_N}, got {len(e2b_probe_pass)}")
    for v in ember_probe_pass + e2b_probe_pass:
        if v not in (0, 1):
            raise ValueError(f"B1 pass vectors must be 0/1, got {v!r}")

    receipt = {
        "ticket": "FP33-B1",
        "ts": _ts(),
        "leg": "B1",
        "ember_probe_pass": list(ember_probe_pass),
        "e2b_probe_pass": list(e2b_probe_pass),
        "harness_sha": harness_sha,
        "dry_run": dry_run,
    }
    path = RECEIPTS / f"fp33-b1-{receipt['ts']}.json"
    path.write_text(json.dumps(receipt, indent=2))
    return path


def emit_b2_receipt(
    ember_action_done: list[int],
    e2b_action_done: list[int],
    *,
    harness_sha: str = "",
    dry_run: bool = False,
) -> Path:
    """Write B2 (agency battery) receipt. Returns path written."""
    if len(ember_action_done) != B2_N:
        raise ValueError(f"B2 ember_action_done must be length {B2_N}, got {len(ember_action_done)}")
    if len(e2b_action_done) != B2_N:
        raise ValueError(f"B2 e2b_action_done must be length {B2_N}, got {len(e2b_action_done)}")
    for v in ember_action_done + e2b_action_done:
        if v not in (0, 1):
            raise ValueError(f"B2 action_done vectors must be 0/1, got {v!r}")

    receipt = {
        "ticket": "FP33-B2",
        "ts": _ts(),
        "leg": "B2",
        "ember_action_done": list(ember_action_done),
        "e2b_action_done": list(e2b_action_done),
        "harness_sha": harness_sha,
        "dry_run": dry_run,
    }
    path = RECEIPTS / f"fp33-b2-{receipt['ts']}.json"
    path.write_text(json.dumps(receipt, indent=2))
    return path


def emit_b3_receipt(
    ember_episode_pass: list[int],
    e2b_episode_pass: list[int],
    *,
    battery_sha: str = "",
    harness_sha: str = "",
    dry_run: bool = False,
) -> Path:
    """Write B3 (duty battery) receipt. Returns path written."""
    if len(ember_episode_pass) != B3_N:
        raise ValueError(f"B3 ember_episode_pass must be length {B3_N}, got {len(ember_episode_pass)}")
    if len(e2b_episode_pass) != B3_N:
        raise ValueError(f"B3 e2b_episode_pass must be length {B3_N}, got {len(e2b_episode_pass)}")
    for v in ember_episode_pass + e2b_episode_pass:
        if v not in (0, 1):
            raise ValueError(f"B3 episode_pass vectors must be 0/1, got {v!r}")

    receipt = {
        "ticket": "FP33-B3",
        "ts": _ts(),
        "leg": "B3",
        "ember_episode_pass": list(ember_episode_pass),
        "e2b_episode_pass": list(e2b_episode_pass),
        "battery_sha": battery_sha,
        "harness_sha": harness_sha,
        "dry_run": dry_run,
    }
    path = RECEIPTS / f"fp33-b3-{receipt['ts']}.json"
    path.write_text(json.dumps(receipt, indent=2))
    return path


def emit_b4_receipt(
    receipt_exists: bool,
    dispatched_through_harness: bool,
    *,
    harness_sha: str = "",
    dry_run: bool = False,
) -> Path:
    """Write B4 (evals-through-harness) receipt. Returns path written."""
    receipt = {
        "ticket": "FP33-B4",
        "ts": _ts(),
        "leg": "B4",
        "receipt_exists": bool(receipt_exists),
        "dispatched_through_harness": bool(dispatched_through_harness),
        "harness_sha": harness_sha,
        "dry_run": dry_run,
    }
    path = RECEIPTS / f"fp33-b4-{receipt['ts']}.json"
    path.write_text(json.dumps(receipt, indent=2))
    return path


# ── Schema verification ───────────────────────────────────────────────────────

def _verify_b1(r: dict) -> list[str]:
    errors = []
    if r.get("leg") != "B1":
        errors.append(f"leg must be 'B1', got {r.get('leg')!r}")
    ep = r.get("ember_probe_pass", [])
    if len(ep) != B1_N:
        errors.append(f"ember_probe_pass length {len(ep)} != {B1_N}")
    if not all(v in (0, 1) for v in ep):
        errors.append("ember_probe_pass contains non-binary values")
    e2p = r.get("e2b_probe_pass", [])
    if len(e2p) != B1_N:
        errors.append(f"e2b_probe_pass length {len(e2p)} != {B1_N}")
    if not all(v in (0, 1) for v in e2p):
        errors.append("e2b_probe_pass contains non-binary values")
    return errors


def _verify_b2(r: dict) -> list[str]:
    errors = []
    if r.get("leg") != "B2":
        errors.append(f"leg must be 'B2', got {r.get('leg')!r}")
    ea = r.get("ember_action_done", [])
    if len(ea) != B2_N:
        errors.append(f"ember_action_done length {len(ea)} != {B2_N}")
    if not all(v in (0, 1) for v in ea):
        errors.append("ember_action_done contains non-binary values")
    e2a = r.get("e2b_action_done", [])
    if len(e2a) != B2_N:
        errors.append(f"e2b_action_done length {len(e2a)} != {B2_N}")
    if not all(v in (0, 1) for v in e2a):
        errors.append("e2b_action_done contains non-binary values")
    return errors


def _verify_b3(r: dict) -> list[str]:
    errors = []
    if r.get("leg") != "B3":
        errors.append(f"leg must be 'B3', got {r.get('leg')!r}")
    ep = r.get("ember_episode_pass", [])
    if len(ep) != B3_N:
        errors.append(f"ember_episode_pass length {len(ep)} != {B3_N}")
    if not all(v in (0, 1) for v in ep):
        errors.append("ember_episode_pass contains non-binary values")
    e2p = r.get("e2b_episode_pass", [])
    if len(e2p) != B3_N:
        errors.append(f"e2b_episode_pass length {len(e2p)} != {B3_N}")
    if not all(v in (0, 1) for v in e2p):
        errors.append("e2b_episode_pass contains non-binary values")
    return errors


def _verify_b4(r: dict) -> list[str]:
    errors = []
    if r.get("leg") != "B4":
        errors.append(f"leg must be 'B4', got {r.get('leg')!r}")
    if not isinstance(r.get("receipt_exists"), bool):
        errors.append(f"receipt_exists must be bool, got {type(r.get('receipt_exists'))!r}")
    if not isinstance(r.get("dispatched_through_harness"), bool):
        errors.append(f"dispatched_through_harness must be bool, got {type(r.get('dispatched_through_harness'))!r}")
    return errors


_VERIFIERS = {"B1": _verify_b1, "B2": _verify_b2, "B3": _verify_b3, "B4": _verify_b4}


def verify_receipt(path: Path) -> list[str]:
    """Return list of schema errors for a B-leg receipt. Empty = valid."""
    try:
        r = json.loads(path.read_text())
    except Exception as e:
        return [f"failed to parse JSON: {e}"]
    leg = r.get("leg")
    verifier = _VERIFIERS.get(leg)
    if verifier is None:
        return [f"unknown or missing leg field: {leg!r}"]
    errors = verifier(r)
    if "ts" not in r:
        errors.append("missing 'ts' field")
    return errors


# ── Selftest ─────────────────────────────────────────────────────────────────

def selftest() -> None:
    import tempfile, shutil

    tmp = Path(tempfile.mkdtemp())
    receipts_dir = tmp / "receipts"
    receipts_dir.mkdir()

    # Patch RECEIPTS global for this test
    global RECEIPTS
    orig = RECEIPTS
    RECEIPTS = receipts_dir

    try:
        print("[fp33-b-legs] selftest: emit + verify all B-legs (synthetic, dry_run=True)", flush=True)

        # B1: ember 4/5, e2b 2/5
        p1 = emit_b1_receipt([1,1,1,1,0], [1,0,1,0,0], dry_run=True)
        errs = verify_receipt(p1)
        assert not errs, f"B1 schema errors: {errs}"
        r1 = json.loads(p1.read_text())
        assert r1["leg"] == "B1"
        assert r1["ember_probe_pass"] == [1,1,1,1,0]
        assert r1["e2b_probe_pass"] == [1,0,1,0,0]
        assert r1["dry_run"] is True
        print(f"  B1: ember={sum(r1['ember_probe_pass'])}/5, e2b={sum(r1['e2b_probe_pass'])}/5 — PASS", flush=True)

        # B2: ember 4/5, e2b 3/5
        p2 = emit_b2_receipt([1,1,1,1,0], [1,1,0,1,0], dry_run=True)
        errs = verify_receipt(p2)
        assert not errs, f"B2 schema errors: {errs}"
        r2 = json.loads(p2.read_text())
        assert r2["leg"] == "B2"
        assert r2["ember_action_done"] == [1,1,1,1,0]
        assert r2["e2b_action_done"] == [1,1,0,1,0]
        print(f"  B2: ember={sum(r2['ember_action_done'])}/5, e2b={sum(r2['e2b_action_done'])}/5 — PASS", flush=True)

        # B3: ember 16/20, e2b 12/20
        ember_ep = [1]*16 + [0]*4
        e2b_ep   = [1]*12 + [0]*8
        p3 = emit_b3_receipt(ember_ep, e2b_ep, battery_sha="abc123", dry_run=True)
        errs = verify_receipt(p3)
        assert not errs, f"B3 schema errors: {errs}"
        r3 = json.loads(p3.read_text())
        assert r3["leg"] == "B3"
        assert len(r3["ember_episode_pass"]) == 20
        assert len(r3["e2b_episode_pass"]) == 20
        assert r3["battery_sha"] == "abc123"
        print(f"  B3: ember={sum(r3['ember_episode_pass'])}/20, e2b={sum(r3['e2b_episode_pass'])}/20 — PASS", flush=True)

        # B4: positive case
        p4 = emit_b4_receipt(True, True, dry_run=True)
        errs = verify_receipt(p4)
        assert not errs, f"B4 schema errors: {errs}"
        r4 = json.loads(p4.read_text())
        assert r4["leg"] == "B4"
        assert r4["receipt_exists"] is True
        assert r4["dispatched_through_harness"] is True
        print(f"  B4: receipt_exists={r4['receipt_exists']}, dispatched={r4['dispatched_through_harness']} — PASS", flush=True)

        # B4: negative case (receipt not yet)
        p4n = emit_b4_receipt(False, False, dry_run=True)
        errs = verify_receipt(p4n)
        assert not errs, f"B4-negative schema errors: {errs}"
        r4n = json.loads(p4n.read_text())
        assert r4n["receipt_exists"] is False
        print(f"  B4 (negative): receipt_exists=False — PASS", flush=True)

        # Reject wrong lengths
        try:
            emit_b1_receipt([1,1,1], [1,1,1], dry_run=True)
            assert False, "should have raised ValueError"
        except ValueError:
            pass
        try:
            emit_b3_receipt([1]*19, [1]*20, dry_run=True)
            assert False, "should have raised ValueError"
        except ValueError:
            pass
        print("  length-validation guard: PASS", flush=True)

        # Verify non-binary rejection
        try:
            emit_b2_receipt([1,2,1,1,0], [0,1,0,0,1], dry_run=True)
            assert False, "should have raised ValueError"
        except ValueError:
            pass
        print("  non-binary guard: PASS", flush=True)

        print("FP33_B_LEGS_PRESTAGE_SELFTEST_PASS", flush=True)

    finally:
        RECEIPTS = orig
        shutil.rmtree(tmp, ignore_errors=True)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="fp33 B-leg receipt emitter pre-stage")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--emit-b1", metavar=("EMBER_JSON", "E2B_JSON"), nargs=2)
    ap.add_argument("--emit-b2", metavar=("EMBER_JSON", "E2B_JSON"), nargs=2)
    ap.add_argument("--emit-b3", metavar=("EMBER_JSON", "E2B_JSON"), nargs=2)
    ap.add_argument("--emit-b4", action="store_true")
    ap.add_argument("--receipt-path", default="")
    ap.add_argument("--dispatched", action="store_true")
    ap.add_argument("--harness-sha", default="")
    ap.add_argument("--battery-sha", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    if args.emit_b1:
        ember = json.loads(Path(args.emit_b1[0]).read_text())
        e2b   = json.loads(Path(args.emit_b1[1]).read_text())
        p = emit_b1_receipt(ember, e2b, harness_sha=args.harness_sha, dry_run=args.dry_run)
        print(f"B1 receipt: {p}", flush=True)
        return

    if args.emit_b2:
        ember = json.loads(Path(args.emit_b2[0]).read_text())
        e2b   = json.loads(Path(args.emit_b2[1]).read_text())
        p = emit_b2_receipt(ember, e2b, harness_sha=args.harness_sha, dry_run=args.dry_run)
        print(f"B2 receipt: {p}", flush=True)
        return

    if args.emit_b3:
        ember = json.loads(Path(args.emit_b3[0]).read_text())
        e2b   = json.loads(Path(args.emit_b3[1]).read_text())
        p = emit_b3_receipt(ember, e2b, battery_sha=args.battery_sha,
                            harness_sha=args.harness_sha, dry_run=args.dry_run)
        print(f"B3 receipt: {p}", flush=True)
        return

    if args.emit_b4:
        p = emit_b4_receipt(bool(args.receipt_path), args.dispatched,
                            harness_sha=args.harness_sha, dry_run=args.dry_run)
        print(f"B4 receipt: {p}", flush=True)
        return

    ap.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
