#!/usr/bin/env python3
"""#552 Component C: compute ledger receipt block (Q7).

Per-run compute metrics emission + backfill utility for existing receipts.

The compute_ledger block should be added to every training-run receipt at the
receipt-write site (same as #544 <ROOT> substitution).

Block schema:
  {tokens_seen, optimizer_steps, wall_seconds, sec_per_step_mean, tflops_est,
   peak_vram_gib, watts_series_ref}

Backfill: fills fields derivable from present data, UNKNOWN otherwise.
Never estimates silently.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def compute_ledger_from_receipt(receipt: dict) -> dict:
    """Extract compute_ledger block from a training receipt.

    Derives metrics from receipt fields where available.
    Non-derivable fields are marked UNKNOWN.
    """

    tokens_seen = receipt.get("tokens_this_segment")
    steps = receipt.get("steps")
    wall_s = receipt.get("wall_s")

    # Compute derived fields
    sec_per_step_mean = None
    if steps and steps > 0 and wall_s and wall_s > 0:
        sec_per_step_mean = round(wall_s / steps, 4)

    # TFLOPS estimate
    # Formula: TFLOPS = (tokens * param_count * flops_per_token) / (wall_s * 1e12)
    # For now, stub as UNKNOWN (requires model config which isn't always in receipt)
    tflops_est = None
    tflops_formula = (
        "TFLOPS = (tokens_seen * model_params * flops_per_token_forward) / "
        "(wall_seconds * 1e12)"
    )

    # Peak VRAM — check governor or components for vram usage
    peak_vram_gib = None
    gov = receipt.get("governor") or {}
    if "peak_vram_used_gib" in gov:
        peak_vram_gib = gov["peak_vram_used_gib"]
    elif "vram_usage_peak_gib" in gov:
        peak_vram_gib = gov["vram_usage_peak_gib"]

    # Watts series reference — check if #118 instrumentation is present
    watts_series_ref = None
    if "power_instrumentation" in receipt or "watts_series" in receipt:
        watts_series_ref = receipt.get("watts_series", "power_instrumentation_present")

    ledger = {
        "tokens_seen": tokens_seen if tokens_seen else "UNKNOWN",
        "optimizer_steps": steps if steps else "UNKNOWN",
        "wall_seconds": wall_s if wall_s else "UNKNOWN",
        "sec_per_step_mean": sec_per_step_mean if sec_per_step_mean else "UNKNOWN",
        "tflops_est": tflops_est or "UNKNOWN",
        "tflops_formula": tflops_formula,
        "peak_vram_gib": peak_vram_gib or "UNKNOWN",
        "watts_series_ref": watts_series_ref,
    }

    return ledger


def backfill_compute_ledger(receipt_paths: list[str]) -> list[dict]:
    """Backfill compute_ledger for existing receipts.

    Returns list of {receipt_path, original_sha256, add_status, ledger}
    Only fills derivable fields; marks others UNKNOWN.
    Never modifies receipts on disk.
    """

    results = []

    for receipt_path in receipt_paths:
        try:
            with open(receipt_path, 'r') as f:
                receipt = json.load(f)
        except Exception as e:
            results.append({
                "receipt_path": receipt_path,
                "status": "UNREADABLE",
                "error": str(e),
            })
            continue

        # Skip if already has compute_ledger
        if "compute_ledger" in receipt:
            results.append({
                "receipt_path": receipt_path,
                "status": "ALREADY_PRESENT",
            })
            continue

        # Compute ledger
        ledger = compute_ledger_from_receipt(receipt)

        results.append({
            "receipt_path": receipt_path,
            "status": "BACKFILLED",
            "compute_ledger": ledger,
        })

    return results


def add_compute_ledger_to_receipt(receipt: dict) -> dict:
    """Add compute_ledger block to a fresh receipt.

    This function should be called at the receipt-write site in timeshare_pretrain.py
    before json.dump().
    """
    receipt["compute_ledger"] = compute_ledger_from_receipt(receipt)
    return receipt


def _selftest() -> None:
    """Unit test: fixture receipt with compute fields."""

    fixture_receipt = {
        "ticket": "TIMESHARE-V0-SEGMENT",
        "ts": "20260709T000000Z",
        "steps": 100,
        "tokens_this_segment": 2560000,
        "wall_s": 250.5,
        "governor": {
            "peak_vram_used_gib": 12.5,
        },
    }

    ledger = compute_ledger_from_receipt(fixture_receipt)

    # Verify computed fields
    assert ledger["tokens_seen"] == 2560000, "tokens_seen should match"
    assert ledger["optimizer_steps"] == 100, "optimizer_steps should match"
    assert ledger["wall_seconds"] == 250.5, "wall_seconds should match"
    assert ledger["sec_per_step_mean"] == 2.505, "sec_per_step_mean should be computed"
    assert ledger["peak_vram_gib"] == 12.5, "peak_vram_gib should match"
    assert ledger["tflops_est"] == "UNKNOWN", "tflops_est should be UNKNOWN without model params"

    # Verify full receipt can be extended
    receipt_with_ledger = add_compute_ledger_to_receipt(fixture_receipt.copy())
    assert "compute_ledger" in receipt_with_ledger, "compute_ledger should be added"
    assert receipt_with_ledger["compute_ledger"]["sec_per_step_mean"] == 2.505

    print("[PASS] SELFTEST: fixture receipt compute_ledger validated")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute ledger utilities")
    parser.add_argument("--selftest", action="store_true",
                        help="Run unit test (fixture receipt)")
    parser.add_argument("--backfill", type=str, nargs='+',
                        help="Receipt paths to backfill")
    parser.add_argument("--write", type=str,
                        help="Write backfill results to file")
    args = parser.parse_args()

    if args.selftest:
        _selftest()
    elif args.backfill:
        results = backfill_compute_ledger(args.backfill)

        if args.write:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            output_path = args.write if args.write.endswith('.json') else f"{args.write}-{ts}.json"
            with open(output_path, 'w') as f:
                json.dump({
                    "timestamp": ts,
                    "results": results,
                }, f, indent=2)
            print(f"Backfill results written to {output_path}")
        else:
            print(json.dumps(results, indent=2))
    else:
        parser.print_help()
