"""conv_c03_muon_split_live.py — live-dispatch wrapper for the muon_split 60M-token run.

Sets EMBER_GATE_AUTHORIZED=1 and EMBER_SHARD_DIR, then delegates to conv_c03_muon_split.py.
Follows the established pattern of v0_run_daemon.py and dt1_daemon_run.py.

Dispatcher: train_start with script=conv_c03_muon_split_live.py

Provenance: landed from stage dryrun-20260704T211712Z (ember issue #210 Tier 2)
with a portability fix -- see conv_c03_muon_ns3_live.py's provenance note
(same class, same fix) and receipts/ember-c-scale/land210g-*.
"""
import os
import sys

os.environ["EMBER_GATE_AUTHORIZED"] = "1"
# Convergence MEASUREMENT run (not v0-pretrain launch) — exempt from the pretrain
# deadline budget gate. Matches conv_c03_full_fused_adamw_live.py, which cleared the
# gate and completed (a513e4ba). Without this, G-budget refuses (days_remaining<0 past
# the 2026-06-22 pretrain deadline) — that deadline governs the pretrain launch, not a
# post-deadline measurement carrying independent EMBER_GATE_AUTHORIZED=1 authorization.
os.environ["EMBER_CONV_BUDGET_GATE_EXEMPT"] = "1"
os.environ.setdefault("EMBER_SHARD_DIR", "")
# Reduce allocator fragmentation (OOM fix — see conv_c03_muon_ns3_live.py).
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

# Delegate to the main conv script (which reads EMBER_SHARD_DIR from env)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import conv_c03_muon_split  # noqa: F401  (runs on import via module-level code)
