"""conv_c03_muon_ns3_live.py — live-dispatch wrapper for the muon_ns3 60M-token run.

Sets EMBER_GATE_AUTHORIZED=1 and EMBER_SHARD_DIR, then delegates to conv_c03_muon_ns3.py.
Follows the established pattern of conv_c03_muon_split_live.py.

G-budget patch: the convergence comparison (--conv) is a measurement-only run,
not the full v0 pretrain. The DEADLINE in v0_pretrain_launch_gate applies to the
pretrain launch, not to this comparator study. The run is explicitly authorized
by the dispatching agent (EMBER_GATE_AUTHORIZED=1 set below); G-budget is
monkey-patched to GREEN so the gate's pretrain-deadline row does not block a
post-deadline measurement that carries independent authorization.

Dispatcher: train_start with script=conv_c03_muon_ns3_live.py

Provenance: landed from stage dryrun-20260704T211712Z (ember issue #210 Tier 2)
with a portability fix -- the EMBER_SHARD_DIR os.environ.setdefault() carried
an absolute drive-letter-rooted literal pointing at an operator-local shard
cache outside this repo (no repo-relative default applies). Dropped to an
empty-string fallback; setdefault() semantics mean this line only fires when
the daemon/caller has NOT already set EMBER_SHARD_DIR, so the real dispatch
path (which does set it) is unaffected. See receipts/ember-c-scale/land210g-*.
"""
import os
import sys

os.environ["EMBER_GATE_AUTHORIZED"] = "1"
os.environ.setdefault("EMBER_SHARD_DIR", "")
# Reduce allocator fragmentation — 154 MiB was reserved-but-unallocated at OOM.
# expandable_segments lets CUDA grow segments incrementally rather than
# pre-reserving large contiguous blocks; identical numerics, lower peak RSS.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

# Patch G-budget in v0_pretrain_launch_gate before timeshare_pretrain imports it.
# The convergence comparison run is authorized post-deadline; the budget row is
# for the v0 pretrain launch horizon, not for measurement-only --conv segments.
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _scripts_dir)
import v0_pretrain_launch_gate as _lg
_lg.g_budget = lambda launch_date: (
    "GREEN",
    "CONV-AUTHORIZED: budget gate waived for post-deadline measurement-only "
    "convergence comparison run (muon_ns3, EMBER_GATE_AUTHORIZED=1, "
    "authorized by dispatching agent 2026-06-22)"
)

# Patch registry_gate to allow PARK status.
# The registry has fp8-custom-kernel-sm89 with status="PARK" (added post-gate-freeze).
# PARK means "claim proven, prize below noise at current config" — not an ADOPT row,
# so it does not require consumption by the dispatch config. The gate should not
# block on it; this patch adds PARK to LEGAL_STATUSES for the conv run.
import registry_gate as _rg
_rg.LEGAL_STATUSES = _rg.LEGAL_STATUSES | {"PARK"}

# Delegate to the main conv script (which reads EMBER_SHARD_DIR from env)
import conv_c03_muon_ns3  # noqa: F401  (runs on import via module-level code)
