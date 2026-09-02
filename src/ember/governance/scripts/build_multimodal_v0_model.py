# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""build_multimodal_v0_model.py — B3 runner helper for EmberModelV0Multimodal.

Returns: (model, vocab, hidden)
  - model: EmberModelV0Multimodal instance
  - vocab, hidden: production values from cfg["model"] (always; not tiny dims)

live=False: tiny dims (hidden=32, heads=2, head_dim=16, vocab=64, n_layers=1), CPU float32.
live=True:  production dims from cfg["model"] including layers=20, CUDA bf16.
"""

import os
import sys

SCRIPTS = os.path.dirname(__file__)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

# issue2015 exact-local-import:src/ember/governance/scripts/ember_model_v0_multimodal.py
import importlib.util as _ember_2cfe4d529b68f0f8_importlib
import sys as _ember_2cfe4d529b68f0f8_sys
from pathlib import Path as _ember_2cfe4d529b68f0f8_Path
_ember_2cfe4d529b68f0f8_path = _ember_2cfe4d529b68f0f8_Path(__file__).resolve().parents[4].joinpath('scripts', 'ember_model_v0_multimodal.py')
if not _ember_2cfe4d529b68f0f8_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_model_v0_multimodal.py')
_ember_2cfe4d529b68f0f8_aliases = ('_ember_issue2015_2cfe4d529b68f0f8', 'ember_model_v0_multimodal', 'src.ember.governance.scripts.ember_model_v0_multimodal')
_ember_2cfe4d529b68f0f8_existing = []
for _ember_2cfe4d529b68f0f8_alias in _ember_2cfe4d529b68f0f8_aliases:
    _ember_2cfe4d529b68f0f8_candidate = _ember_2cfe4d529b68f0f8_sys.modules.get(_ember_2cfe4d529b68f0f8_alias)
    if _ember_2cfe4d529b68f0f8_candidate is not None and all(_ember_2cfe4d529b68f0f8_candidate is not item for item in _ember_2cfe4d529b68f0f8_existing):
        _ember_2cfe4d529b68f0f8_existing.append(_ember_2cfe4d529b68f0f8_candidate)
if len(_ember_2cfe4d529b68f0f8_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_model_v0_multimodal.py')
if _ember_2cfe4d529b68f0f8_existing:
    _ember_2cfe4d529b68f0f8_module = _ember_2cfe4d529b68f0f8_existing[0]
    _ember_2cfe4d529b68f0f8_observed = getattr(_ember_2cfe4d529b68f0f8_module, '__file__', None)
    if _ember_2cfe4d529b68f0f8_observed is None or _ember_2cfe4d529b68f0f8_Path(_ember_2cfe4d529b68f0f8_observed).resolve() != _ember_2cfe4d529b68f0f8_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_model_v0_multimodal.py')
else:
    _ember_2cfe4d529b68f0f8_spec = _ember_2cfe4d529b68f0f8_importlib.spec_from_file_location('_ember_issue2015_2cfe4d529b68f0f8', _ember_2cfe4d529b68f0f8_path)
    if _ember_2cfe4d529b68f0f8_spec is None or _ember_2cfe4d529b68f0f8_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_model_v0_multimodal.py')
    _ember_2cfe4d529b68f0f8_module = _ember_2cfe4d529b68f0f8_importlib.module_from_spec(_ember_2cfe4d529b68f0f8_spec)
    for _ember_2cfe4d529b68f0f8_alias in _ember_2cfe4d529b68f0f8_aliases:
        _ember_2cfe4d529b68f0f8_prior = _ember_2cfe4d529b68f0f8_sys.modules.get(_ember_2cfe4d529b68f0f8_alias)
        if _ember_2cfe4d529b68f0f8_prior is not None and _ember_2cfe4d529b68f0f8_prior is not _ember_2cfe4d529b68f0f8_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_model_v0_multimodal.py')
        _ember_2cfe4d529b68f0f8_sys.modules[_ember_2cfe4d529b68f0f8_alias] = _ember_2cfe4d529b68f0f8_module
    try:
        _ember_2cfe4d529b68f0f8_spec.loader.exec_module(_ember_2cfe4d529b68f0f8_module)
    except BaseException:
        for _ember_2cfe4d529b68f0f8_alias in _ember_2cfe4d529b68f0f8_aliases:
            if _ember_2cfe4d529b68f0f8_sys.modules.get(_ember_2cfe4d529b68f0f8_alias) is _ember_2cfe4d529b68f0f8_module:
                _ember_2cfe4d529b68f0f8_sys.modules.pop(_ember_2cfe4d529b68f0f8_alias, None)
        raise
for _ember_2cfe4d529b68f0f8_alias in _ember_2cfe4d529b68f0f8_aliases:
    _ember_2cfe4d529b68f0f8_prior = _ember_2cfe4d529b68f0f8_sys.modules.get(_ember_2cfe4d529b68f0f8_alias)
    if _ember_2cfe4d529b68f0f8_prior is not None and _ember_2cfe4d529b68f0f8_prior is not _ember_2cfe4d529b68f0f8_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_model_v0_multimodal.py')
    _ember_2cfe4d529b68f0f8_sys.modules[_ember_2cfe4d529b68f0f8_alias] = _ember_2cfe4d529b68f0f8_module
EmberModelV0Multimodal = getattr(_ember_2cfe4d529b68f0f8_module, 'EmberModelV0Multimodal')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_model_v0_multimodal.py


def build_multimodal_v0_model(cfg: dict, live: bool = False):
    """Build EmberModelV0Multimodal from config.

    Returns (model, vocab, hidden). vocab and hidden are always the
    production values from cfg['model'] so callers can size loss/projections.
    When live=False the model itself uses tiny dims for fast CPU testing.
    """
    m = cfg.get("model", {})
    vocab = m.get("vocab", 32000)
    hidden = m.get("hidden", 1024)
    heads = m.get("heads", 16)
    head_dim = m.get("head_dim", hidden // heads)  # 64 for hidden=1024/heads=16
    n_layers = m.get("layers", 20)

    # Extend vocab for Lock-1 reserved band (32000-32007 → 32008 total).
    # Without this, DELIM_START/DELIM_END (32000/32001) are OOB for embed_tokens.
    mm = cfg.get("multimodal", {})
    if mm.get("enabled"):
        band = mm.get("lock1_reserved_vocab_band", {})
        ids = band.get("ids", [32000, 32001, 32002, 32003, 32004, 32005, 32006, 32007])
        if ids:
            vocab = max(vocab, max(ids) + 1)

    if not live:
        model = EmberModelV0Multimodal(
            hidden=32,
            n_heads=2,
            head_dim=16,
            vocab=64,
            n_layers=1,
        )
        return model, vocab, hidden

    import torch
    model = EmberModelV0Multimodal(
        hidden=hidden,
        n_heads=heads,
        head_dim=head_dim,
        vocab=vocab,
        n_layers=n_layers,
    )
    # EmberModelV0Multimodal is not nn.Module — move all leaves via nn_modules().
    dtype = torch.bfloat16
    for mod in model.nn_modules():
        mod.to(device="cuda", dtype=dtype)
    return model, vocab, hidden
