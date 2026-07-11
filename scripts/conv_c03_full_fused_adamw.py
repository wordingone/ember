"""conv_c03_full_fused_adamw.py — 60M-token convergence run, full_fused_adamw variant.

Full live run: c03-h1024-d20, batch=16, seq=1024, FP8 dtype, compile on,
governor active (VRAM 0.80 / margin 1.5 GiB / pace 0.05 s).
Requires EMBER_GATE_AUTHORIZED=1 in the daemon environment and a real
--shard-dir of packed uint16 shards.

Optimizer: single torch.optim.AdamW(fused=True) over ALL trainable params.
Seed: 42. Data order: deterministic (pure-function loader, sorted shards).

Loss log: models/conv-full_fused_adamw-seed42/loss_log.jsonl
Receipt:  receipts/conv-full_fused_adamw-<ts>.json

Marker: CONV_SEGMENT_DONE opt_variant=full_fused_adamw

Provenance: landed from stage dryrun-20260704T211712Z (ember issue #210 Tier 2)
with a portability fix -- the EMBER_SHARD_DIR fallback carried an absolute
drive-letter-rooted literal pointing at an operator-local shard cache outside
this repo (no repo-relative default applies). Dropped to an empty-string
fallback; EMBER_SHARD_DIR (already the primary source) is unaffected, and a
caller relying on the old fallback now gets a clear downstream refusal
instead of a machine-specific path. See receipts/ember-c-scale/land210g-*.
"""
import sys, os
SHARD_DIR = os.environ.get("EMBER_SHARD_DIR", "")
sys.argv = [
    "timeshare_pretrain.py",
    "--conv",
    "--opt-variant", "full_fused_adamw",
    "--token-budget", "60000000",
    "--loss-log-every", "3000000",
    "--seed", "42",
    "--live",
    "--shard-dir", SHARD_DIR,
    "--segment-id", "conv-full-fused-adamw-60m",
]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timeshare_pretrain import main
main()
