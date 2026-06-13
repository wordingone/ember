"""
fp33_a_legs_prestage.py — A-leg receipt-emitter pre-stage for fp33 surpass-verdict.

Symmetric to fp33_b_legs_prestage.py. Emits A1/A2/A3 receipts consumed by
fp33_surpass_verdict.py --receipts (discriminated by the 'leg' field).

Schemas (Leo mail 15353):
  A1: density-bench leg — per-task pass arrays + compute budget.
  A2: three-test transfer leg — held_out_transfer, matched_control, deletion per seat.
  A3: slice-bench leg — mbpp + gsm8k200 per-task arrays + MDE.

A1/A2 are pre-staged pending ember data (emit on synthetic; dry_run guards real write).
A3-ii: can emit a real E2B-seat GSM8K receipt now (one seat, synthetic ember slot).

Usage:
    python fp33_a_legs_prestage.py --selftest
    python fp33_a_legs_prestage.py --emit-a1 EMBER_JSON E2B_JSON COMPUTE_JSON
    python fp33_a_legs_prestage.py --emit-a2 EMBER_JSON E2B_JSON DELTA_JSON COMPUTE_JSON
    python fp33_a_legs_prestage.py --emit-a3 MBPP_JSON GSM8K_JSON COMPUTE_JSON
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
NC   = HERE.parent
RECEIPTS = NC / "receipts"


# ── timestamp ──────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ── A1 ────────────────────────────────────────────────────────────────────────

def emit_a1_receipt(
    per_task_ember: list[float],
    per_task_e2b: list[float],
    compute_ember: dict,
    compute_e2b: dict,
    *,
    harness_sha: str = "",
    dry_run: bool = False,
) -> Path:
    """Emit A1 receipt: density-bench per-task pass arrays + compute budget.

    Args:
        per_task_ember: list of float scores (0/1 or continuous) for ember seat.
        per_task_e2b:   same-length list for e2b seat.
        compute_ember:  dict with wall_s (float), gpu_s (float), tokens (int).
        compute_e2b:    same structure for e2b seat.
    """
    if len(per_task_ember) != len(per_task_e2b):
        raise ValueError(f"A1 length mismatch: ember={len(per_task_ember)} e2b={len(per_task_e2b)}")
    _validate_compute(compute_ember, "compute_ember")
    _validate_compute(compute_e2b, "compute_e2b")

    receipt = {
        "ticket": "FP33-A1",
        "ts": _ts(),
        "leg": "A1",
        "per_task_ember": [float(x) for x in per_task_ember],
        "per_task_e2b":   [float(x) for x in per_task_e2b],
        "compute": {
            "ember": dict(compute_ember),
            "e2b":   dict(compute_e2b),
        },
        "harness_sha": harness_sha,
        "dry_run": dry_run,
    }
    return _write_receipt("a1", receipt, dry_run=dry_run)


# ── A2 ────────────────────────────────────────────────────────────────────────

def emit_a2_receipt(
    ember_three_test: dict,
    e2b_three_test: dict,
    per_task_delta: list[float],
    compute_ember: dict,
    compute_e2b: dict,
    *,
    harness_sha: str = "",
    dry_run: bool = False,
) -> Path:
    """Emit A2 receipt: three-test transfer leg.

    Args:
        ember_three_test: dict with held_out_transfer, matched_control, deletion (float scores).
        e2b_three_test:   same structure for e2b seat.
        per_task_delta:   transfer Δ per task (float list).
        compute_ember:    wall_s, gpu_s, tokens for ember seat.
        compute_e2b:      same for e2b.
    """
    _validate_three_test(ember_three_test, "ember_three_test")
    _validate_three_test(e2b_three_test, "e2b_three_test")
    _validate_compute(compute_ember, "compute_ember")
    _validate_compute(compute_e2b, "compute_e2b")

    receipt = {
        "ticket": "FP33-A2",
        "ts": _ts(),
        "leg": "A2",
        "ember_three_test": {
            "held_out_transfer": float(ember_three_test["held_out_transfer"]),
            "matched_control":   float(ember_three_test["matched_control"]),
            "deletion":          float(ember_three_test["deletion"]),
        },
        "e2b_three_test": {
            "held_out_transfer": float(e2b_three_test["held_out_transfer"]),
            "matched_control":   float(e2b_three_test["matched_control"]),
            "deletion":          float(e2b_three_test["deletion"]),
        },
        "per_task_delta": [float(x) for x in per_task_delta],
        "compute": {
            "ember": dict(compute_ember),
            "e2b":   dict(compute_e2b),
        },
        "harness_sha": harness_sha,
        "dry_run": dry_run,
    }
    return _write_receipt("a2", receipt, dry_run=dry_run)


# ── A3 ────────────────────────────────────────────────────────────────────────

def emit_a3_receipt(
    mbpp_ember: list[float],
    mbpp_e2b: list[float],
    mbpp_mde: float,
    gsm8k_ember: list[float],
    gsm8k_e2b: list[float],
    gsm8k_mde: float,
    compute_ember: dict,
    compute_e2b: dict,
    *,
    battery_sha: str = "",
    harness_sha: str = "",
    dry_run: bool = False,
) -> Path:
    """Emit A3 receipt: slice-bench leg (mbpp + gsm8k200).

    Args:
        mbpp_ember/e2b:   per-task pass lists for MBPP slice.
        mbpp_mde:         minimum detectable effect for MBPP slice.
        gsm8k_ember/e2b:  per-task pass lists for GSM8K-200 slice.
        gsm8k_mde:        minimum detectable effect for GSM8K-200 slice.
        compute_ember/e2b: wall_s, gpu_s, tokens per seat.
    """
    if len(mbpp_ember) != len(mbpp_e2b):
        raise ValueError(f"A3 mbpp length mismatch: ember={len(mbpp_ember)} e2b={len(mbpp_e2b)}")
    if len(gsm8k_ember) != len(gsm8k_e2b):
        raise ValueError(f"A3 gsm8k length mismatch: ember={len(gsm8k_ember)} e2b={len(gsm8k_e2b)}")
    _validate_compute(compute_ember, "compute_ember")
    _validate_compute(compute_e2b, "compute_e2b")

    receipt = {
        "ticket": "FP33-A3",
        "ts": _ts(),
        "leg": "A3",
        "slices": {
            "mbpp": {
                "per_task_ember": [float(x) for x in mbpp_ember],
                "per_task_e2b":   [float(x) for x in mbpp_e2b],
                "mde":            float(mbpp_mde),
            },
            "gsm8k200": {
                "per_task_ember": [float(x) for x in gsm8k_ember],
                "per_task_e2b":   [float(x) for x in gsm8k_e2b],
                "mde":            float(gsm8k_mde),
            },
        },
        "compute": {
            "ember": dict(compute_ember),
            "e2b":   dict(compute_e2b),
        },
        "battery_sha": battery_sha,
        "harness_sha": harness_sha,
        "dry_run": dry_run,
    }
    return _write_receipt("a3", receipt, dry_run=dry_run)


# ── internal helpers ───────────────────────────────────────────────────────────

def _validate_compute(c: dict, name: str) -> None:
    for key in ("wall_s", "gpu_s", "tokens"):
        if key not in c:
            raise ValueError(f"{name} missing '{key}'")


def _validate_three_test(t: dict, name: str) -> None:
    for key in ("held_out_transfer", "matched_control", "deletion"):
        if key not in t:
            raise ValueError(f"{name} missing '{key}'")


def _write_receipt(leg_tag: str, receipt: dict, *, dry_run: bool) -> Path:
    ts = receipt["ts"]
    fname = f"fp33-{leg_tag}-{ts}.json"
    path = RECEIPTS / fname
    if not dry_run:
        RECEIPTS.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt, indent=2))
    return path


# ── schema verifiers ───────────────────────────────────────────────────────────

def _verify_a1(r: dict) -> None:
    assert r["leg"] == "A1", f"leg={r['leg']!r}"
    assert isinstance(r["per_task_ember"], list), "per_task_ember must be list"
    assert isinstance(r["per_task_e2b"], list),   "per_task_e2b must be list"
    assert len(r["per_task_ember"]) == len(r["per_task_e2b"]), "A1 length mismatch"
    assert len(r["per_task_ember"]) > 0, "A1 per_task arrays must be non-empty"
    c = r["compute"]
    for seat in ("ember", "e2b"):
        for key in ("wall_s", "gpu_s", "tokens"):
            assert key in c[seat], f"A1 compute.{seat} missing '{key}'"


def _verify_a2(r: dict) -> None:
    assert r["leg"] == "A2", f"leg={r['leg']!r}"
    for seat in ("ember_three_test", "e2b_three_test"):
        for key in ("held_out_transfer", "matched_control", "deletion"):
            assert key in r[seat], f"A2 {seat} missing '{key}'"
    assert isinstance(r["per_task_delta"], list), "per_task_delta must be list"
    assert len(r["per_task_delta"]) > 0, "A2 per_task_delta must be non-empty"
    c = r["compute"]
    for seat in ("ember", "e2b"):
        for key in ("wall_s", "gpu_s", "tokens"):
            assert key in c[seat], f"A2 compute.{seat} missing '{key}'"


def _verify_a3(r: dict) -> None:
    assert r["leg"] == "A3", f"leg={r['leg']!r}"
    assert "slices" in r, "A3 missing 'slices'"
    for slice_name in ("mbpp", "gsm8k200"):
        s = r["slices"][slice_name]
        for key in ("per_task_ember", "per_task_e2b", "mde"):
            assert key in s, f"A3 slices.{slice_name} missing '{key}'"
        assert isinstance(s["per_task_ember"], list), f"A3 {slice_name} per_task_ember must be list"
        assert isinstance(s["per_task_e2b"], list),   f"A3 {slice_name} per_task_e2b must be list"
        assert len(s["per_task_ember"]) == len(s["per_task_e2b"]), f"A3 {slice_name} length mismatch"
        assert len(s["per_task_ember"]) > 0, f"A3 {slice_name} arrays must be non-empty"
    c = r["compute"]
    for seat in ("ember", "e2b"):
        for key in ("wall_s", "gpu_s", "tokens"):
            assert key in c[seat], f"A3 compute.{seat} missing '{key}'"


_VERIFIERS = {"A1": _verify_a1, "A2": _verify_a2, "A3": _verify_a3}


def verify_receipt(path: Path) -> dict:
    """Load and schema-verify an A-leg receipt. Returns the dict on success."""
    r = json.loads(Path(path).read_text())
    leg = r.get("leg")
    if leg not in _VERIFIERS:
        raise ValueError(f"Unknown leg {leg!r} (expected A1/A2/A3)")
    _VERIFIERS[leg](r)
    return r


# ── selftest ──────────────────────────────────────────────────────────────────

_COMPUTE_SYN = {"wall_s": 12.5, "gpu_s": 10.0, "tokens": 50000}


def selftest() -> None:
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        global RECEIPTS
        orig_receipts = RECEIPTS
        RECEIPTS = Path(tmpdir)

        try:
            # A1 — 10 tasks per seat
            ember_10  = [1, 1, 1, 0, 1, 1, 1, 1, 0, 1]
            e2b_10    = [1, 0, 1, 0, 1, 0, 1, 0, 0, 1]
            p_a1 = emit_a1_receipt(
                ember_10, e2b_10, _COMPUTE_SYN, _COMPUTE_SYN, dry_run=True
            )
            r_a1 = json.loads(
                emit_a1_receipt(ember_10, e2b_10, _COMPUTE_SYN, _COMPUTE_SYN, dry_run=False).read_text()
            )
            _verify_a1(r_a1)
            e_pass = sum(ember_10); e2b_pass = sum(e2b_10)
            print(f"  A1: ember={e_pass}/10, e2b={e2b_pass}/10 ~ PASS")

            # A2 — 8 delta tasks
            three_syn = {"held_out_transfer": 0.72, "matched_control": 0.65, "deletion": 0.58}
            delta_8   = [0.05, -0.02, 0.08, 0.01, 0.10, -0.01, 0.06, 0.03]
            r_a2 = json.loads(
                emit_a2_receipt(
                    three_syn, three_syn, delta_8, _COMPUTE_SYN, _COMPUTE_SYN, dry_run=False
                ).read_text()
            )
            _verify_a2(r_a2)
            print(f"  A2: three_test ember={three_syn['held_out_transfer']}, delta_n={len(delta_8)} ~ PASS")

            # A3 — mbpp 12, gsm8k200 200
            mbpp_e  = [1]*9 + [0]*3
            mbpp_b  = [1]*7 + [0]*5
            gsm8k_e = [1]*120 + [0]*80
            gsm8k_b = [1]*100 + [0]*100
            r_a3 = json.loads(
                emit_a3_receipt(
                    mbpp_e, mbpp_b, 0.15,
                    gsm8k_e, gsm8k_b, 0.10,
                    _COMPUTE_SYN, _COMPUTE_SYN,
                    dry_run=False,
                ).read_text()
            )
            _verify_a3(r_a3)
            mbpp_pass = sum(mbpp_e); gsm_pass = sum(gsm8k_e)
            print(f"  A3: mbpp ember={mbpp_pass}/12, gsm8k200 ember={gsm_pass}/200 ~ PASS")

            # length-mismatch guard (A1)
            try:
                emit_a1_receipt([1, 0], [1], _COMPUTE_SYN, _COMPUTE_SYN, dry_run=True)
                raise AssertionError("A1 length-guard did not fire")
            except ValueError:
                print("  length-mismatch guard (A1): PASS")

            # missing compute key guard (A3)
            try:
                emit_a3_receipt(
                    [1], [1], 0.1, [1], [1], 0.1,
                    {"wall_s": 1.0, "gpu_s": 0.5},  # missing tokens
                    _COMPUTE_SYN, dry_run=True,
                )
                raise AssertionError("compute-key guard did not fire")
            except ValueError:
                print("  compute-key guard: PASS")

            # missing three_test key guard (A2)
            try:
                emit_a2_receipt(
                    {"held_out_transfer": 0.5, "matched_control": 0.5},  # missing deletion
                    three_syn, [0.1], _COMPUTE_SYN, _COMPUTE_SYN, dry_run=True,
                )
                raise AssertionError("three_test key guard did not fire")
            except ValueError:
                print("  three_test key guard (A2): PASS")

            # verify_receipt dispatch
            path_a3 = emit_a3_receipt(
                mbpp_e, mbpp_b, 0.15, gsm8k_e, gsm8k_b, 0.10,
                _COMPUTE_SYN, _COMPUTE_SYN, dry_run=False,
            )
            verify_receipt(path_a3)
            print("  verify_receipt dispatch (A3): PASS")

        finally:
            RECEIPTS = orig_receipts

    print("FP33_A_LEGS_PRESTAGE_SELFTEST_PASS")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="fp33 A-leg receipt emitter")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--emit-a1", nargs=2, metavar=("EMBER_JSON", "E2B_JSON"))
    ap.add_argument("--emit-a2", nargs=3, metavar=("EMBER_JSON", "E2B_JSON", "COMPUTE_JSON"))
    ap.add_argument("--emit-a3", nargs=2, metavar=("MBPP_JSON", "GSM8K_JSON"))
    ap.add_argument("--compute", metavar="COMPUTE_JSON", help="compute JSON for both seats")
    ap.add_argument("--harness-sha", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        print("[fp33-a-legs] selftest: emit + verify all A-legs (synthetic, dry_run=True/False)")
        selftest()
        return

    if args.emit_a1:
        ember = json.loads(Path(args.emit_a1[0]).read_text())
        e2b   = json.loads(Path(args.emit_a1[1]).read_text())
        comp  = json.loads(Path(args.compute).read_text()) if args.compute else _COMPUTE_SYN
        p = emit_a1_receipt(ember, e2b, comp, comp, harness_sha=args.harness_sha, dry_run=args.dry_run)
        print(f"A1 receipt: {p}")
        return

    if args.emit_a2:
        ember_tt  = json.loads(Path(args.emit_a2[0]).read_text())
        e2b_tt    = json.loads(Path(args.emit_a2[1]).read_text())
        delta     = json.loads(Path(args.emit_a2[2]).read_text())
        comp      = json.loads(Path(args.compute).read_text()) if args.compute else _COMPUTE_SYN
        p = emit_a2_receipt(ember_tt, e2b_tt, delta, comp, comp,
                            harness_sha=args.harness_sha, dry_run=args.dry_run)
        print(f"A2 receipt: {p}")
        return

    if args.emit_a3:
        mbpp    = json.loads(Path(args.emit_a3[0]).read_text())
        gsm8k   = json.loads(Path(args.emit_a3[1]).read_text())
        comp    = json.loads(Path(args.compute).read_text()) if args.compute else _COMPUTE_SYN
        p = emit_a3_receipt(
            mbpp["per_task_ember"], mbpp["per_task_e2b"], mbpp["mde"],
            gsm8k["per_task_ember"], gsm8k["per_task_e2b"], gsm8k["mde"],
            comp, comp,
            battery_sha=mbpp.get("battery_sha", ""),
            harness_sha=args.harness_sha,
            dry_run=args.dry_run,
        )
        print(f"A3 receipt: {p}")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
