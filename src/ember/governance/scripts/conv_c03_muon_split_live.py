# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
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
# issue2015 exact-local-import:src/ember/governance/scripts/conv_c03_muon_split.py
import importlib.util as _ember_4f6e4e71fb94cfc4_importlib
import sys as _ember_4f6e4e71fb94cfc4_sys
from pathlib import Path as _ember_4f6e4e71fb94cfc4_Path
_ember_4f6e4e71fb94cfc4_path = _ember_4f6e4e71fb94cfc4_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'conv_c03_muon_split.py')
if not _ember_4f6e4e71fb94cfc4_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/conv_c03_muon_split.py')
_ember_4f6e4e71fb94cfc4_aliases = ('_ember_issue2015_4f6e4e71fb94cfc4', 'conv_c03_muon_split', 'scripts.conv_c03_muon_split')
_ember_4f6e4e71fb94cfc4_existing = []
for _ember_4f6e4e71fb94cfc4_alias in _ember_4f6e4e71fb94cfc4_aliases:
    _ember_4f6e4e71fb94cfc4_candidate = _ember_4f6e4e71fb94cfc4_sys.modules.get(_ember_4f6e4e71fb94cfc4_alias)
    if _ember_4f6e4e71fb94cfc4_candidate is not None and all(_ember_4f6e4e71fb94cfc4_candidate is not item for item in _ember_4f6e4e71fb94cfc4_existing):
        _ember_4f6e4e71fb94cfc4_existing.append(_ember_4f6e4e71fb94cfc4_candidate)
if len(_ember_4f6e4e71fb94cfc4_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/conv_c03_muon_split.py')
if _ember_4f6e4e71fb94cfc4_existing:
    _ember_4f6e4e71fb94cfc4_module = _ember_4f6e4e71fb94cfc4_existing[0]
    _ember_4f6e4e71fb94cfc4_observed = getattr(_ember_4f6e4e71fb94cfc4_module, '__file__', None)
    if _ember_4f6e4e71fb94cfc4_observed is None or _ember_4f6e4e71fb94cfc4_Path(_ember_4f6e4e71fb94cfc4_observed).resolve() != _ember_4f6e4e71fb94cfc4_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/conv_c03_muon_split.py')
else:
    _ember_4f6e4e71fb94cfc4_spec = _ember_4f6e4e71fb94cfc4_importlib.spec_from_file_location('_ember_issue2015_4f6e4e71fb94cfc4', _ember_4f6e4e71fb94cfc4_path)
    if _ember_4f6e4e71fb94cfc4_spec is None or _ember_4f6e4e71fb94cfc4_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/conv_c03_muon_split.py')
    _ember_4f6e4e71fb94cfc4_module = _ember_4f6e4e71fb94cfc4_importlib.module_from_spec(_ember_4f6e4e71fb94cfc4_spec)
    for _ember_4f6e4e71fb94cfc4_alias in _ember_4f6e4e71fb94cfc4_aliases:
        _ember_4f6e4e71fb94cfc4_prior = _ember_4f6e4e71fb94cfc4_sys.modules.get(_ember_4f6e4e71fb94cfc4_alias)
        if _ember_4f6e4e71fb94cfc4_prior is not None and _ember_4f6e4e71fb94cfc4_prior is not _ember_4f6e4e71fb94cfc4_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/conv_c03_muon_split.py')
        _ember_4f6e4e71fb94cfc4_sys.modules[_ember_4f6e4e71fb94cfc4_alias] = _ember_4f6e4e71fb94cfc4_module
    try:
        _ember_4f6e4e71fb94cfc4_spec.loader.exec_module(_ember_4f6e4e71fb94cfc4_module)
    except BaseException:
        for _ember_4f6e4e71fb94cfc4_alias in _ember_4f6e4e71fb94cfc4_aliases:
            if _ember_4f6e4e71fb94cfc4_sys.modules.get(_ember_4f6e4e71fb94cfc4_alias) is _ember_4f6e4e71fb94cfc4_module:
                _ember_4f6e4e71fb94cfc4_sys.modules.pop(_ember_4f6e4e71fb94cfc4_alias, None)
        raise
for _ember_4f6e4e71fb94cfc4_alias in _ember_4f6e4e71fb94cfc4_aliases:
    _ember_4f6e4e71fb94cfc4_prior = _ember_4f6e4e71fb94cfc4_sys.modules.get(_ember_4f6e4e71fb94cfc4_alias)
    if _ember_4f6e4e71fb94cfc4_prior is not None and _ember_4f6e4e71fb94cfc4_prior is not _ember_4f6e4e71fb94cfc4_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/conv_c03_muon_split.py')
    _ember_4f6e4e71fb94cfc4_sys.modules[_ember_4f6e4e71fb94cfc4_alias] = _ember_4f6e4e71fb94cfc4_module
conv_c03_muon_split = _ember_4f6e4e71fb94cfc4_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/conv_c03_muon_split.py  # noqa: F401  (runs on import via module-level code)
