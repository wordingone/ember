# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""conv_c03_muon_split_fast_live.py — live-dispatch wrapper for the muon_split_fast throughput smoke.

Sets EMBER_GATE_AUTHORIZED=1 and EMBER_SHARD_DIR, then delegates to conv_c03_muon_split_fast.py.
Follows the established pattern of conv_c03_muon_split_live.py.

Dispatcher: train_start with script=conv_c03_muon_split_fast_live.py

Provenance: landed from stage dryrun-20260704T211712Z (ember issue #210 Tier 2)
with a portability fix -- see conv_c03_muon_ns3_live.py's provenance note
(same class, same fix) and receipts/ember-c-scale/land210g-*.
"""
import os
import sys

os.environ["EMBER_GATE_AUTHORIZED"] = "1"
# Convergence MEASUREMENT run (not v0-pretrain launch) — exempt from the pretrain
# deadline budget gate. Matches conv_c03_muon_split_live.py.
os.environ["EMBER_CONV_BUDGET_GATE_EXEMPT"] = "1"
os.environ.setdefault("EMBER_SHARD_DIR", "")
# Reduce allocator fragmentation (OOM fix — see conv_c03_muon_ns3_live.py).
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

# Delegate to the main conv script (which reads EMBER_SHARD_DIR from env)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import conv_c03_muon_split_fast  # noqa: F401  (runs on import via module-level code)
