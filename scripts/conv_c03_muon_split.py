"""conv_c03_muon_split.py — 60M-token convergence run, muon_split variant.

Full live run: c03-h1024-d20, batch=16, seq=1024, FP8 dtype, compile on,
governor active (VRAM 0.80 / margin 1.5 GiB / pace 0.05 s).
Requires EMBER_GATE_AUTHORIZED=1 in the daemon environment and a real
--shard-dir of packed uint16 shards.

Optimizer: Muon NS5 over 2D hidden weights + AdamW over embed/norm/head.
Seed: 42. Data order: deterministic (pure-function loader, sorted shards).

Loss log: models/conv-muon_split-seed42/loss_log.jsonl
Receipt:  receipts/conv-muon_split-<ts>.json

Marker: CONV_SEGMENT_DONE opt_variant=muon_split

Provenance: landed from stage dryrun-20260704T211712Z (ember issue #210 Tier 2)
with a portability fix -- see conv_c03_full_fused_adamw.py's provenance note
(same class, same fix) and receipts/ember-c-scale/land210g-*.
"""
import sys, os
# SHARD_DIR must point to the real packed uint16 shard directory.
# Override by setting the EMBER_SHARD_DIR environment variable before dispatch,
# or edit this constant.
SHARD_DIR = os.environ.get("EMBER_SHARD_DIR", "")
sys.argv = [
    "timeshare_pretrain.py",
    "--conv",
    "--opt-variant", "muon_split",
    "--token-budget", "60000000",
    "--loss-log-every", "3000000",
    "--seed", "42",
    "--live",
    "--shard-dir", SHARD_DIR,
    "--segment-id", "conv-muon-split-60m",
]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timeshare_pretrain import main
main()
