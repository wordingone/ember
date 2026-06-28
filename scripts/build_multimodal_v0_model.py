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

from ember_model_v0_multimodal import EmberModelV0Multimodal


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
