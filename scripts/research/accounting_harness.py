#!/usr/bin/env python3
"""P2-G3 3-axis accounting harness — FLOP/token/wall-clock ledger + matched-budget comparison.

Implements §4 C3 accounting protocol (3-axis receipts) and §5 P2-G3 gate.
Emits per-step FLOPs from model config, accumulates 3-axis ledger from training logs,
and produces matched-budget comparison receipts for two arms (delta per axis, % mismatch).

TDD selftest: python scripts/research/accounting_harness.py --selftest
  Runs with synthetic fixtures (two fake runs, known FLOPs).
  Marker: ACCOUNTING_HARNESS_SELFTEST_PASS.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# FLOP computation: derive formula from timeshare_pretrain.py model config
# ---------------------------------------------------------------------------
# Source: scripts/timeshare_pretrain.py, lines 531-536 (LlamaConfig for c03):
#   vocab_size=32000, hidden_size=1024, intermediate_size=4096,
#   num_hidden_layers=20, num_attention_heads=16, max_position_embeddings=1024
#
# FLOPs per step formula (dense transformer, Chinchilla estimate):
# FLOPs = 6 * B * T * d_model * (d_model + 4 * d_ffn)
# Where:
#   B = batch size
#   T = sequence length
#   d_model = hidden_size (1024)
#   d_ffn = intermediate_size (4096)
#
# Breakdown per token per layer:
#   - Self-attention: 4 * T * d_model^2 (Q, K, V, O projections + matmuls)
#   - Feed-forward: 2 * d_model * d_ffn (forward + backward equivalent in FLOPs)
# Total per token, all layers: 6 * L * T * d_model * (d_model + 4*d_ffn/3)
# Approximate (Chinchilla form): 6 * B * T * d_model * (d_model + 4*d_ffn)

def compute_flops_per_step(
    batch_size: int,
    seq_len: int,
    hidden_size: int,
    intermediate_size: int,
    num_layers: int,
) -> int:
    """Compute FLOPs per training step from model config.

    Formula (Chinchilla): 6 * B * T * d_model * (d_model + 4 * d_ffn)
    Multiplied by num_layers for the full model.

    Args:
        batch_size: batch size
        seq_len: sequence length
        hidden_size: d_model (hidden dimension)
        intermediate_size: d_ffn (feed-forward intermediate dimension)
        num_layers: number of transformer layers

    Returns:
        Total FLOPs per step (forward + backward).
    """
    # Per-token FLOPs: 6 * d_model * (d_model + 4 * d_ffn)
    per_token_per_layer = 6 * hidden_size * (hidden_size + 4 * intermediate_size)
    # Total: multiply by batch * seq_len * num_layers
    flops = batch_size * seq_len * num_layers * per_token_per_layer
    return int(flops)


# ---------------------------------------------------------------------------
# 3-axis ledger accumulator
# ---------------------------------------------------------------------------

@dataclass
class AxisLedger:
    """3-axis receipt for a training run: FLOPs, tokens, wall-clock."""
    flops_total: int  # Total FLOPs computed
    tokens_consumed: int  # Total tokens processed
    wall_clock_s: float  # Wall-clock time in seconds


class AccountingHarness:
    """Compute and compare 3-axis ledgers for training runs.

    The harness reads from existing logs/receipts, inventories which axes
    are available, and emits matched-budget comparison receipts.
    """

    def __init__(self, model_config: dict[str, Any] | None = None):
        """Initialize with optional model config for FLOP computation.

        Default model_config is c03 (from timeshare_pretrain.py).
        """
        self.model_config = model_config or {
            "batch_size": 4,  # c03 typical batch
            "seq_len": 1024,
            "hidden_size": 1024,
            "intermediate_size": 4096,
            "num_layers": 20,
        }

    def compute_flops(self, batch_size: int | None = None) -> int:
        """Compute per-step FLOPs using current model config (optionally override batch)."""
        cfg = self.model_config
        bs = batch_size if batch_size is not None else cfg["batch_size"]
        return compute_flops_per_step(
            batch_size=bs,
            seq_len=cfg["seq_len"],
            hidden_size=cfg["hidden_size"],
            intermediate_size=cfg["intermediate_size"],
            num_layers=cfg["num_layers"],
        )

    def accumulate_ledger_from_logs(
        self,
        log_data: dict[str, Any],
    ) -> tuple[AxisLedger, dict[str, str]]:
        """Accumulate 3-axis ledger from a training run's logs/receipts.

        Inventory what IS logged. If an axis is not derivable, report it
        rather than fabricate.

        Args:
            log_data: dictionary with keys like 'num_steps', 'elapsed_s', 'tokens_total'

        Returns:
            (AxisLedger, inventory_dict) where inventory_dict maps each axis to
            'available', 'derived', or 'missing'.
        """
        inventory = {}

        # FLOP axis: compute from model config + num steps
        flops_available = "num_steps" in log_data
        if flops_available:
            flops = self.compute_flops() * log_data["num_steps"]
            inventory["flops"] = "derived"
        else:
            flops = 0
            inventory["flops"] = "missing"

        # Token axis: check logs
        tokens_available = "tokens_total" in log_data
        if tokens_available:
            tokens = log_data["tokens_total"]
            inventory["tokens"] = "available"
        else:
            tokens = 0
            inventory["tokens"] = "missing"

        # Wall-clock axis: check logs
        wall_available = "elapsed_s" in log_data
        if wall_available:
            wall_s = log_data["elapsed_s"]
            inventory["wall_clock"] = "available"
        else:
            wall_s = 0.0
            inventory["wall_clock"] = "missing"

        return AxisLedger(flops_total=flops, tokens_consumed=tokens, wall_clock_s=wall_s), inventory

    def compare_arms(
        self,
        arm_a: AxisLedger,
        arm_b: AxisLedger,
        tolerance_pct: float = 5.0,
    ) -> dict[str, Any]:
        """Emit matched-budget comparison receipt for two arms.

        Args:
            arm_a: first ledger (e.g., control)
            arm_b: second ledger (e.g., treatment)
            tolerance_pct: acceptable % mismatch

        Returns:
            Receipt dict with delta per axis, % mismatch, PASS/FAIL.
        """
        receipt = {
            "ticket": "ACCOUNTING-COMPARISON",
            "arm_a": asdict(arm_a),
            "arm_b": asdict(arm_b),
            "axes": {},
        }

        all_pass = True

        # FLOP axis
        if arm_a.flops_total > 0 and arm_b.flops_total > 0:
            pct_diff = abs(arm_a.flops_total - arm_b.flops_total) / arm_a.flops_total * 100
            receipt["axes"]["flops"] = {
                "delta": arm_b.flops_total - arm_a.flops_total,
                "pct_mismatch": round(pct_diff, 2),
                "pass": pct_diff <= tolerance_pct,
            }
            all_pass = all_pass and receipt["axes"]["flops"]["pass"]
        else:
            receipt["axes"]["flops"] = {"status": "insufficient_data"}

        # Token axis
        if arm_a.tokens_consumed > 0 and arm_b.tokens_consumed > 0:
            pct_diff = abs(arm_a.tokens_consumed - arm_b.tokens_consumed) / arm_a.tokens_consumed * 100
            receipt["axes"]["tokens"] = {
                "delta": arm_b.tokens_consumed - arm_a.tokens_consumed,
                "pct_mismatch": round(pct_diff, 2),
                "pass": pct_diff <= tolerance_pct,
            }
            all_pass = all_pass and receipt["axes"]["tokens"]["pass"]
        else:
            receipt["axes"]["tokens"] = {"status": "insufficient_data"}

        # Wall-clock axis
        if arm_a.wall_clock_s > 0 and arm_b.wall_clock_s > 0:
            pct_diff = abs(arm_a.wall_clock_s - arm_b.wall_clock_s) / arm_a.wall_clock_s * 100
            receipt["axes"]["wall_clock"] = {
                "delta": round(arm_b.wall_clock_s - arm_a.wall_clock_s, 2),
                "pct_mismatch": round(pct_diff, 2),
                "pass": pct_diff <= tolerance_pct,
            }
            all_pass = all_pass and receipt["axes"]["wall_clock"]["pass"]
        else:
            receipt["axes"]["wall_clock"] = {"status": "insufficient_data"}

        receipt["tolerance_pct"] = tolerance_pct
        receipt["pass"] = all_pass

        return receipt


# ---------------------------------------------------------------------------
# Selftest: TDD (red then green)
# ---------------------------------------------------------------------------

def run_selftest() -> bool:
    """Selftest with synthetic fixtures: two fake runs with known FLOPs.

    Returns True if all assertions pass, False otherwise.
    """
    harness = AccountingHarness()

    # Known fixture: compute FLOPs for c03 config
    flops_per_step = compute_flops_per_step(
        batch_size=4,
        seq_len=1024,
        hidden_size=1024,
        intermediate_size=4096,
        num_layers=20,
    )

    # Synthetic run A: 100 steps
    run_a_log = {
        "num_steps": 100,
        "tokens_total": 100 * 4 * 1024,  # batch * seq * steps
        "elapsed_s": 50.0,
    }
    ledger_a, inv_a = harness.accumulate_ledger_from_logs(run_a_log)

    # Synthetic run B: 100 steps (identical)
    run_b_log = {
        "num_steps": 100,
        "tokens_total": 100 * 4 * 1024,
        "elapsed_s": 50.0,
    }
    ledger_b, inv_b = harness.accumulate_ledger_from_logs(run_b_log)

    # Assertions
    try:
        # Assert ledger computation
        assert ledger_a.flops_total == flops_per_step * 100, \
            f"FLOPs mismatch: {ledger_a.flops_total} != {flops_per_step * 100}"
        assert ledger_a.tokens_consumed == 100 * 4 * 1024, \
            f"Tokens mismatch: {ledger_a.tokens_consumed}"
        assert ledger_a.wall_clock_s == 50.0, \
            f"Wall-clock mismatch: {ledger_a.wall_clock_s}"

        # Assert inventory
        assert inv_a["flops"] == "derived", f"FLOP inventory: {inv_a['flops']}"
        assert inv_a["tokens"] == "available", f"Token inventory: {inv_a['tokens']}"
        assert inv_a["wall_clock"] == "available", f"Wall-clock inventory: {inv_a['wall_clock']}"

        # Assert comparison (identical runs)
        receipt = harness.compare_arms(ledger_a, ledger_b, tolerance_pct=1.0)
        assert receipt["pass"], f"Comparison failed: {receipt}"
        assert receipt["axes"]["flops"]["pct_mismatch"] == 0.0, \
            f"FLOP mismatch non-zero: {receipt['axes']['flops']}"
        assert receipt["axes"]["tokens"]["pct_mismatch"] == 0.0, \
            f"Token mismatch non-zero: {receipt['axes']['tokens']}"
        assert receipt["axes"]["wall_clock"]["pct_mismatch"] == 0.0, \
            f"Wall-clock mismatch non-zero: {receipt['axes']['wall_clock']}"

        # Test with missing data
        incomplete_log = {"num_steps": 50}  # missing tokens and elapsed_s
        ledger_c, inv_c = harness.accumulate_ledger_from_logs(incomplete_log)
        assert inv_c["flops"] == "derived", "Should derive FLOPs from num_steps"
        assert inv_c["tokens"] == "missing", "Should report missing tokens"
        assert inv_c["wall_clock"] == "missing", "Should report missing wall_clock"

        # Test comparison with partial data
        receipt_partial = harness.compare_arms(ledger_c, ledger_b, tolerance_pct=5.0)
        assert "insufficient_data" in str(receipt_partial["axes"]["tokens"]), \
            "Should report insufficient_data for tokens"

        print("ACCOUNTING_HARNESS_SELFTEST_PASS: all assertions passed")
        return True

    except AssertionError as e:
        print(f"ACCOUNTING_HARNESS_SELFTEST_FAIL: {e}")
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="P2-G3 3-axis accounting harness (FLOP/token/wall-clock ledger + comparison)"
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Run TDD selftest with synthetic fixtures",
    )
    parser.add_argument(
        "--log-a",
        type=str,
        help="Path to first run's log/receipt JSON",
    )
    parser.add_argument(
        "--log-b",
        type=str,
        help="Path to second run's log/receipt JSON",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=5.0,
        help="Acceptable % mismatch between arms (default: 5.0)",
    )
    parser.add_argument(
        "--model-config",
        type=str,
        help="Path to model config JSON (default: c03)",
    )

    args = parser.parse_args()

    if args.selftest:
        return 0 if run_selftest() else 1

    # If no selftest, require both logs
    if not args.log_a or not args.log_b:
        print("Error: either --selftest or both --log-a and --log-b required")
        return 1

    # Load logs
    try:
        with open(args.log_a) as f:
            log_a = json.load(f)
        with open(args.log_b) as f:
            log_b = json.load(f)
    except Exception as e:
        print(f"Error loading logs: {e}")
        return 1

    # Load optional model config
    model_config = None
    if args.model_config:
        try:
            with open(args.model_config) as f:
                model_config = json.load(f)
        except Exception as e:
            print(f"Error loading model config: {e}")
            return 1

    # Compute ledgers and comparison
    harness = AccountingHarness(model_config=model_config)
    ledger_a, inv_a = harness.accumulate_ledger_from_logs(log_a)
    ledger_b, inv_b = harness.accumulate_ledger_from_logs(log_b)

    receipt = harness.compare_arms(ledger_a, ledger_b, tolerance_pct=args.tolerance)

    # Output
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
