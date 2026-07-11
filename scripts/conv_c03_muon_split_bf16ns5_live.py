"""conv_c03_muon_split_bf16ns5_live.py — live-dispatch wrapper for the muon_split_bf16ns5 run.

Sets EMBER_GATE_AUTHORIZED=1, EMBER_SHARD_DIR, and optionally EMBER_SMOKE_TOKENS
(for the ~10M-token smoke), then delegates to conv_c03_muon_split_bf16ns5.py.
Follows the established pattern of conv_c03_muon_split_live.py and
conv_c03_muon_split_fast_live.py.

Smoke cap (replicates the cap used for job 2ce1983b):
  Set EMBER_SMOKE_TOKENS=10000000 before dispatching to cap at ~10M tokens.
  Leave unset for the full 60M convergence run.

Dispatcher: train_start with script=conv_c03_muon_split_bf16ns5_live.py

Provenance: landed from stage dryrun-20260704T211712Z (ember issue #210 Tier 2)
with a portability fix -- see conv_c03_muon_ns3_live.py's provenance note
(same class, same fix) and receipts/ember-c-scale/land210g-*.
"""
import os
import sys

os.environ["EMBER_GATE_AUTHORIZED"] = "1"
# Convergence MEASUREMENT run (not v0-pretrain launch) — exempt from the pretrain
# deadline budget gate.  Matches conv_c03_muon_split_live.py.
os.environ["EMBER_CONV_BUDGET_GATE_EXEMPT"] = "1"
os.environ.setdefault("EMBER_SHARD_DIR", "")
# Reduce allocator fragmentation (OOM fix — see conv_c03_muon_ns3_live.py).
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

# Delegate to the bf16ns5 conv script (which monkey-patches timeshare_pretrain
# and calls ts.main() with the muon_split_bf16ns5 variant).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import conv_c03_muon_split_bf16ns5  # noqa: F401  (runs on import via module-level code)
