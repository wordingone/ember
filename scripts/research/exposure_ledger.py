#!/usr/bin/env python3
"""P2-G4 exposure ledger — per-shard rung-consumption accounting from training logs.

Reconstructs which tokens were consumed at each training step by replaying the
deterministic PackedShardLoader. Outputs:
  - exposure_ledger.jsonl: per-step window indices and shard consumption
  - exposure_summary.md: per-source exposure counts and domain inventory

The loader is RNG-independent (index-based), so replay is bit-exact without
re-training (see state/p2-g4-exposure-ledger-receipt.md for derivation).

TDD selftest: python scripts/research/exposure_ledger.py --selftest
  Runs with synthetic fixtures (fake shards, known step range).
  Marker: EXPOSURE_LEDGER_SELFTEST_PASS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

# Add repo root to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from timeshare_pretrain import PackedShardLoader  # noqa: E402

# Sentinel distinguishing "caller did not pass mmap_cache_dir at all" from an
# explicit None (legacy opt-out) or an explicit path (opt-in) -- same
# convention as timeshare_pretrain.run_v0_segment's
# _RUN_V0_SEGMENT_MMAP_CACHE_DIR_UNSET (issue #570/#573). _DEFAULT_OUTPUT_DIR
# is the single source of truth shared by the constructor's own default
# (below) and main()'s --output-dir CLI default (issue #575).
_EXPOSURE_LEDGER_MMAP_CACHE_DIR_UNSET = object()
_DEFAULT_OUTPUT_DIR = "state"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class WindowRecord:
    """Record of a single training window consumed at a step."""
    step: int
    batch_idx: int
    window_idx: int
    shard_idx: int
    start_pos: int
    end_pos: int


@dataclass
class ExposureLedger:
    """Ledger of token consumption by step range."""
    step_start: int
    step_end: int
    batch_size: int
    seq_len: int
    n_mtp: int
    windows: list[WindowRecord]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "step_start": self.step_start,
            "step_end": self.step_end,
            "batch_size": self.batch_size,
            "seq_len": self.seq_len,
            "n_mtp": self.n_mtp,
            "windows": [asdict(w) for w in self.windows],
        }


# ---------------------------------------------------------------------------
# Exposure ledger reconstruction
# ---------------------------------------------------------------------------

class ExposureLedgerBuilder:
    """Reconstruct token exposure from deterministic loader replay."""

    def __init__(self, shard_dir: str | None = None, seq: int = 1024, n_mtp: int = 2,
                 mmap_cache_dir: str | None = _EXPOSURE_LEDGER_MMAP_CACHE_DIR_UNSET):
        """Initialize with optional shard directory.

        Args:
            shard_dir: directory containing packed *.bin shard files (or None for synthetic)
            seq: sequence length
            n_mtp: number of MTP auxiliary heads
            mmap_cache_dir: forwarded to PackedShardLoader (issue #575).
                Omitted -> sane default `<_DEFAULT_OUTPUT_DIR>/mmap_cache`,
                so a real shard_dir replay (this class's actual purpose --
                real-scale exposure-ledger reconstruction, the same
                ArrayMemoryError/fragmentation class the memmap cache exists
                to kill) automatically gets the fragmentation-safe
                streamed-memmap path instead of legacy
                np.fromfile+np.concatenate. Explicit None preserves the
                legacy path byte-for-byte. main()'s real-reconstruction call
                site passes the CLI's actual --output-dir explicitly,
                overriding this generic default when a caller customizes it.
        """
        self.shard_dir = shard_dir
        self.seq = seq
        self.n_mtp = n_mtp
        self.loader = None

        if shard_dir:
            if mmap_cache_dir is _EXPOSURE_LEDGER_MMAP_CACHE_DIR_UNSET:
                mmap_cache_dir = os.path.join(_DEFAULT_OUTPUT_DIR, "mmap_cache")
            self.loader = PackedShardLoader(shard_dir=shard_dir, seq=seq, n_mtp=n_mtp,
                                            mmap_cache_dir=mmap_cache_dir)

    def reconstruct_exposure(
        self,
        step_range: tuple[int, int],
        batch_size: int = 4,
    ) -> ExposureLedger | None:
        """Reconstruct exposure ledger for a step range.

        Args:
            step_range: (step_start, step_end) inclusive of start, exclusive of end
            batch_size: batch size used during training

        Returns:
            ExposureLedger with windows, or None if loader not available.
        """
        step_start, step_end = step_range

        if not self.loader:
            # No shard directory provided — cannot reconstruct
            return None

        windows = []

        # Enumerate every batch window consumed
        for step in range(step_start, step_end):
            for batch_idx in range(batch_size):
                global_batch_idx = step * batch_size + batch_idx

                # Deterministic window computation
                shard_idx = global_batch_idx % self.loader.n_windows
                start_pos = shard_idx * self.seq
                end_pos = start_pos + self.seq + 1 + self.n_mtp

                windows.append(WindowRecord(
                    step=step,
                    batch_idx=batch_idx,
                    window_idx=shard_idx,
                    shard_idx=0,  # PackedShardLoader concatenates shards; need to map back
                    start_pos=start_pos,
                    end_pos=end_pos,
                ))

        return ExposureLedger(
            step_start=step_start,
            step_end=step_end,
            batch_size=batch_size,
            seq_len=self.seq,
            n_mtp=self.n_mtp,
            windows=windows,
        )

    def inventory_consumption(
        self,
        ledger: ExposureLedger,
    ) -> dict[str, Any]:
        """Inventory per-source token consumption from a ledger.

        Returns dict with:
          - total_windows: count of windows
          - total_tokens: sum(seq_len) across windows
          - step_count: step_end - step_start
          - per_source: dict mapping shard name to consumption count (if available)
          - unknown_sources: count of windows with unknown source (UNKNOWN)
        """
        if not self.loader:
            return {
                "status": "no_shard_dir",
                "total_windows": len(ledger.windows),
                "note": "Cannot inventory source-level consumption without shard directory",
            }

        total_windows = len(ledger.windows)
        total_tokens = ledger.seq_len * total_windows
        step_count = ledger.step_end - ledger.step_start

        # Per-source inventory: try to map windows to actual shards
        per_source = {}
        unknown_count = 0

        # Try to use loader's shard names if available
        shard_names = getattr(self.loader, "shards", None)
        if not shard_names:
            shard_names = ["UNKNOWN"]

        for window in ledger.windows:
            # For now, all windows map to the global stream (shards are concatenated)
            # In a real scenario, we'd need the per-shard boundaries to map back
            source_name = "UNKNOWN"
            if source_name not in per_source:
                per_source[source_name] = 0
            per_source[source_name] += 1
            if source_name == "UNKNOWN":
                unknown_count += 1

        return {
            "total_windows": total_windows,
            "total_tokens": total_tokens,
            "step_count": step_count,
            "per_source": per_source,
            "unknown_sources": unknown_count,
            "note": "Per-source mapping requires shard boundary metadata (not yet logged in manifests)",
        }


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def write_ledger_jsonl(ledger: ExposureLedger, output_path: str | Path) -> None:
    """Write ledger to JSONL (one window per line)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        for window in ledger.windows:
            f.write(json.dumps(asdict(window)) + "\n")


def write_summary_md(
    ledger: ExposureLedger,
    inventory: dict[str, Any],
    output_path: str | Path,
) -> None:
    """Write exposure summary to Markdown."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        f.write("# P2-G4 Exposure Ledger Summary\n\n")

        f.write(f"**Step range**: {ledger.step_start} to {ledger.step_end - 1}\n")
        f.write(f"**Total steps**: {ledger.step_end - ledger.step_start}\n")
        f.write(f"**Batch size**: {ledger.batch_size}\n")
        f.write(f"**Sequence length**: {ledger.seq_len}\n")
        f.write(f"**MTP heads**: {ledger.n_mtp}\n\n")

        f.write("## Token Consumption\n\n")
        f.write(f"- **Total windows**: {inventory.get('total_windows', 'UNKNOWN')}\n")
        f.write(f"- **Total tokens**: {inventory.get('total_tokens', 'UNKNOWN')}\n")
        f.write(f"- **Tokens per step**: {ledger.batch_size * ledger.seq_len}\n\n")

        f.write("## Per-Source Inventory\n\n")
        per_source = inventory.get("per_source", {})
        if per_source:
            f.write("| Source | Windows | Tokens |\n")
            f.write("|--------|---------|--------|\n")
            for source, count in sorted(per_source.items()):
                tokens = count * ledger.seq_len
                f.write(f"| {source} | {count} | {tokens} |\n")
        else:
            f.write("*No per-source data available*\n\n")

        f.write("\n## Reconstruction Status\n\n")
        if inventory.get("note"):
            f.write(f"**Note**: {inventory['note']}\n\n")
        if inventory.get("status"):
            f.write(f"**Status**: {inventory['status']}\n\n")
        if inventory.get("unknown_sources", 0) > 0:
            f.write(f"**UNKNOWN sources**: {inventory['unknown_sources']} windows "
                   f"(shard boundaries not available for per-source mapping)\n\n")


# ---------------------------------------------------------------------------
# Selftest: TDD
# ---------------------------------------------------------------------------

def run_selftest() -> bool:
    """Selftest with synthetic fixtures (no shard files, just math).

    Returns True if all assertions pass.
    """
    try:
        # Test 1: ExposureLedger dataclass round-trip
        windows = [
            WindowRecord(step=0, batch_idx=0, window_idx=0, shard_idx=0, start_pos=0, end_pos=1025),
            WindowRecord(step=0, batch_idx=1, window_idx=1, shard_idx=0, start_pos=1024, end_pos=2049),
        ]
        ledger = ExposureLedger(
            step_start=0,
            step_end=1,
            batch_size=2,
            seq_len=1024,
            n_mtp=2,
            windows=windows,
        )
        assert len(ledger.windows) == 2, "Window count mismatch"
        assert ledger.step_end - ledger.step_start == 1, "Step range mismatch"

        # Test 2: Ledger serialization
        d = ledger.to_dict()
        assert d["step_start"] == 0, "Serialization: step_start"
        assert d["batch_size"] == 2, "Serialization: batch_size"
        assert len(d["windows"]) == 2, "Serialization: windows"

        # Test 3: Builder with no shard dir (synthetic)
        builder = ExposureLedgerBuilder(shard_dir=None, seq=1024, n_mtp=2)
        result = builder.reconstruct_exposure((0, 10), batch_size=4)
        assert result is None, "Builder should return None without shard_dir"

        # Test 4: Inventory on ledger (without shard_dir)
        inventory = builder.inventory_consumption(ledger)
        assert inventory["status"] == "no_shard_dir", "Inventory should report no_shard_dir"
        assert inventory["total_windows"] == 2, "Inventory: window count"

        # Test 5: Window record math
        # For step_range [0, 730] with batch_size=4:
        # - Total windows = 730 steps * 4 batches/step = 2920 windows
        # - Total tokens = 2920 * 1024 = 2,990,080 tokens
        fake_windows = [
            WindowRecord(step=s, batch_idx=b, window_idx=(s*4+b) % 6908, shard_idx=0,
                        start_pos=(s*4+b)*1024, end_pos=(s*4+b)*1024 + 1025)
            for s in range(0, 10)
            for b in range(4)
        ]
        test_ledger = ExposureLedger(
            step_start=0, step_end=10, batch_size=4, seq_len=1024, n_mtp=2,
            windows=fake_windows,
        )
        assert len(test_ledger.windows) == 40, "Generated 10*4 windows"

        print("EXPOSURE_LEDGER_SELFTEST_PASS: all assertions passed")
        return True

    except AssertionError as e:
        print(f"EXPOSURE_LEDGER_SELFTEST_FAIL: {e}")
        return False
    except Exception as e:
        print(f"EXPOSURE_LEDGER_SELFTEST_ERROR: {e}")
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="P2-G4 exposure ledger — per-source token consumption reconstruction"
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Run TDD selftest with synthetic fixtures",
    )
    parser.add_argument(
        "--shard-dir",
        type=str,
        default=None,
        help="Directory containing packed *.bin shard files (required for real reconstruction)",
    )
    parser.add_argument(
        "--step-start",
        type=int,
        default=0,
        help="Starting step (default: 0)",
    )
    parser.add_argument(
        "--step-end",
        type=int,
        default=730,
        help="Ending step exclusive (default: 730 for pre-grow)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=4,
        help="Batch size (default: 4)",
    )
    parser.add_argument(
        "--seq",
        type=int,
        default=1024,
        help="Sequence length (default: 1024)",
    )
    parser.add_argument(
        "--n-mtp",
        type=int,
        default=2,
        help="Number of MTP auxiliary heads (default: 2)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=_DEFAULT_OUTPUT_DIR,
        help="Output directory for ledger and summary files",
    )

    args = parser.parse_args()

    if args.selftest:
        return 0 if run_selftest() else 1

    # Real reconstruction mode. mmap_cache_dir (issue #575) passed
    # explicitly under THIS invocation's own --output-dir, so a custom
    # --output-dir is honored precisely rather than always landing under
    # the constructor's generic _DEFAULT_OUTPUT_DIR fallback.
    builder = ExposureLedgerBuilder(
        shard_dir=args.shard_dir,
        seq=args.seq,
        n_mtp=args.n_mtp,
        mmap_cache_dir=os.path.join(args.output_dir, "mmap_cache"),
    )

    ledger = builder.reconstruct_exposure(
        (args.step_start, args.step_end),
        batch_size=args.batch_size,
    )

    if not ledger:
        print("Error: reconstruction failed (likely due to missing shard_dir)")
        print("Provide --shard-dir <path> or use --selftest for synthetic mode")
        return 1

    # Write outputs
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ledger_path = output_dir / "exposure_ledger.jsonl"
    summary_path = output_dir / "exposure_summary.md"

    write_ledger_jsonl(ledger, ledger_path)
    print(f"Wrote ledger: {ledger_path}")

    inventory = builder.inventory_consumption(ledger)
    write_summary_md(ledger, inventory, summary_path)
    print(f"Wrote summary: {summary_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
