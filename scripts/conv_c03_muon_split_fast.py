"""conv_c03_muon_split_fast.py — 10M-token throughput smoke, muon_split_fast variant.

Short run to measure steady-state BF16 tok/s after torch.compile warm-up.
c03-h1024-d20, batch=16, seq=1024, BF16, governor active.
Requires EMBER_GATE_AUTHORIZED=1 in the daemon environment and a real
--shard-dir of packed uint16 shards.

Optimizer: Muon NS5 (torch.compile'd) over 2D hidden weights +
           AdamW(fused=True) over embed/norm/head.
Seed: 42. Data order: deterministic (pure-function loader, sorted shards).

Loss log: models/conv-muon_split_fast-seed42/loss_log.jsonl
Receipt:  receipts/conv-muon_split_fast-<ts>.json

Marker: CONV_SEGMENT_DONE opt_variant=muon_split_fast

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
    "--opt-variant", "muon_split_fast",
    "--token-budget", "10000000",
    "--loss-log-every", "3000000",
    "--seed", "42",
    "--live",
    "--shard-dir", SHARD_DIR,
    "--segment-id", "conv-muon-split-fast-60m",
]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timeshare_pretrain import main
main()
