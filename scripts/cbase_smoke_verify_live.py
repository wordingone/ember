"""cbase_smoke_verify_live.py — daemon-launched smoke of the REAL C-BASE production path.

Purpose (decisive keystone-on-production measurement): run run_v0_segment with the
actual C-BASE recipe (c03-h1024-d20, batch16, muon_split, WSD, MTP, grad-ckpt, bf16,
eager) on the 40/10/50 mixture for a short governed segment, and record:
  1. measured steady-state tok/s  (does the bench 19874.8 transfer to the eager-bf16
     production path? this is the §8 're-measure throughput' for what actually runs)
  2. data loads from the mixture (mixture-00000.bin), not shards-v0
  3. a checkpoint + manifest.json is written under output_dir/checkpoints
This wrapper is the proven self-contained pattern (cf. conv_c03_muon_split_bf16ns5_live.py):
the train daemon execs it with NO args and only its own env, so the wrapper bakes its
config into os.environ at module level BEFORE importing the segment runner.

Provenance: landed from stage dryrun-20260704T211712Z (ember issue #210 Tier 2)
with a portability fix -- EMBER_SHARD_DIR and EMBER_RUN_DIR were unconditionally
FORCED to absolute drive-letter-rooted / WSL-mount literals pointing at an
operator-local tree outside this repo (no repo-relative default applies).
Both switched from `= "<literal>"` (always overwrite) to `.setdefault(..., "")`
(respect any value the daemon/caller already set; empty only when genuinely
unset, which downstream refuses cleanly rather than silently pointing at a
machine-specific path). See receipts/ember-c-scale/land210g-*.
"""
import os

os.environ["EMBER_GATE_AUTHORIZED"] = "1"
# Smoke segment: ~10M tokens -> enough steady-state entries to compute tok/s, short (~9 min @ ~19k).
os.environ["EMBER_SEGMENT_TOKENS"] = "10000000"
# Full WSD denominator (the real C-BASE budget step count) so LR schedule is representative.
os.environ["EMBER_TOTAL_STEPS"] = "449651"
# The 40/10/50 C-BASE mixture (WSL path).
os.environ.setdefault("EMBER_SHARD_DIR", "")
# Stable run_dir so the checkpoint + manifest land in a known location (not
# tempfile.mkdtemp), making checkpoint-write verification and the resume probe
# possible. cbase_v0_segment_live reads EMBER_RUN_DIR -> --run-dir.
os.environ.setdefault("EMBER_RUN_DIR", "")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

# cbase_v0_segment_live reads these env vars at module level, builds sys.argv, and calls
# ts.main() on import (the --live path -> run_v0_segment).
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import cbase_v0_segment_live  # noqa: F401  (runs on import)
