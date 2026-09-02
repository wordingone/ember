# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""conv_c03_muon_split_bf16ns5.py — convergence / throughput-smoke run, muon_split_bf16ns5 variant.

ADDITIVE variant: identical to muon_split (NS5, seed=42, shards-v0, c03-h1024-d20,
batch=16, BF16, grad-ckpt) except:
  (1) NS5 orthogonalization matmuls run in BF16 (tensor-core path) instead of FP32.
  (2) AdamW half (embed/norms/head) is built with fused=fused_ok.

Smoke cap (replicates conv_c03_muon_split_fast_live.py / job 2ce1983b):
  Set EMBER_SMOKE_TOKENS=10000000 in the daemon environment (or any positive int)
  to cap at that many tokens.  Leave unset (or 0) for the full 60M run.

Dispatcher: train_start with script=conv_c03_muon_split_bf16ns5_live.py

Marker: CONV_SEGMENT_DONE opt_variant=muon_split_bf16ns5

Provenance: landed from stage dryrun-20260704T211712Z (ember issue #210 Tier 2)
with a portability fix -- see conv_c03_full_fused_adamw.py's provenance note
(same class, same fix) and receipts/ember-c-scale/land210g-*.
"""
import os
import sys
import types

# ---------------------------------------------------------------------------
# Resolve token budget from env (smoke cap or full run).
# EMBER_SMOKE_TOKENS mirrors the cap mechanism used by muon_split_fast (which
# hard-coded --token-budget 10000000 in sys.argv for job 2ce1983b).
# ---------------------------------------------------------------------------
_smoke_tokens_env = int(os.environ.get("EMBER_SMOKE_TOKENS", "0") or "0")
_TOKEN_BUDGET = _smoke_tokens_env if _smoke_tokens_env > 0 else 60_000_000

SHARD_DIR = os.environ.get("EMBER_SHARD_DIR", "")

# ---------------------------------------------------------------------------
# Import timeshare_pretrain BEFORE patching so its module object exists.
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import timeshare_pretrain as ts  # noqa: E402

# ---------------------------------------------------------------------------
# BF16 Newton-Schulz5 — ADDITIVE; the original _zeropower_via_newtonschulz5
# is NOT modified.
#
# External contract preserved:
#   - Accepts G (any 2D CUDA tensor).
#   - Returns orthogonalized update with the same shape as G.
#   - Returned dtype is G.dtype (bfloat16 on the live path; callers do
#     p.add_(upd, alpha=...) which handles any dtype combination).
#   - ns_steps=5, eps=1e-7 — identical to the original NS5.
#
# Only change: X = G.to(torch.bfloat16) instead of G.to(torch.float32).
# This routes all three matmuls per NS iteration through the BF16 tensor-core
# path (~330 TFLOPS on 4090 vs ~20-40 TFLOPS for FP32 matmuls).
# Precision loss is self-correcting across the 5 iterations (Keller Jordan /
# modern Muon precedent).
# ---------------------------------------------------------------------------
def _zeropower_bf16(G, steps: int = 5, eps: float = 1e-7):
    """BF16 Newton-Schulz5 orthogonalization (tensor-core path).

    Identical to timeshare_pretrain._zeropower_via_newtonschulz5 except
    the internal matmuls run in bfloat16 instead of float32.
    External contract: same shape returned; dtype = G.dtype."""
    import torch
    assert G.ndim == 2, "Newton-Schulz operates on 2D matrices only"
    a, b, c = 3.4445, -4.7750, 2.0315
    orig_dtype = G.dtype
    X = G.to(torch.bfloat16)          # BF16 cast — tensor-core path
    transposed = False
    if X.shape[0] > X.shape[1]:
        X = X.T
        transposed = True
    X = X / (X.norm() + eps)
    for _ in range(steps):
        A = X @ X.T
        B = b * A + c * (A @ A)
        X = a * X + B @ X
    if transposed:
        X = X.T
    return X.to(orig_dtype)            # restore caller's dtype


# ---------------------------------------------------------------------------
# Build the _MuonBF16NS5 subclass — mirrors _MuonFast but calls _zeropower_bf16.
# ---------------------------------------------------------------------------
def _muon_bf16ns5_class():
    MuonBase = ts._muon_class()
    import torch

    class _MuonBF16NS5(MuonBase):
        """Muon with BF16 NS5 orthogonalization + fused AdamW half."""

        @torch.no_grad()
        def step(self, closure=None):
            loss = None
            if closure is not None:
                with torch.enable_grad():
                    loss = closure()
            for group in self.param_groups:
                lr = group["lr"]
                mom = group["momentum"]
                nesterov = group["nesterov"]
                ns_steps = group["ns_steps"]
                wd = group["weight_decay"]
                for p in group["params"]:
                    if p.grad is None:
                        continue
                    g = p.grad
                    if g.ndim != 2:
                        raise ValueError(
                            "_MuonBF16NS5 received a non-2D parameter — "
                            "split-routing invariant violated")
                    state = self.state[p]
                    if "momentum_buffer" not in state:
                        state["momentum_buffer"] = torch.zeros_like(g)
                    buf = state["momentum_buffer"]
                    buf.mul_(mom).add_(g)
                    upd = g.add(buf, alpha=mom) if nesterov else buf
                    upd = _zeropower_bf16(upd, steps=ns_steps)   # BF16 NS5
                    scale = max(1.0, p.shape[0] / p.shape[1]) ** 0.5
                    if wd != 0.0:
                        p.mul_(1.0 - lr * wd)
                    p.add_(upd, alpha=-lr * scale)
            return loss

    return _MuonBF16NS5


# ---------------------------------------------------------------------------
# Monkey-patch timeshare_pretrain to accept "muon_split_bf16ns5" as a valid
# opt_variant.  We extend the tuple and inject the dispatch branch.
# ---------------------------------------------------------------------------

# 1. Extend the accepted-variants tuple.
ts._CONV_OPT_VARIANTS = ts._CONV_OPT_VARIANTS + ("muon_split_bf16ns5",)

# 2. Wrap _build_conv_model_and_opts to handle the new variant; all other
#    variants pass through unchanged.
_orig_build = ts._build_conv_model_and_opts


def _build_conv_model_and_opts_patched(
    opt_variant,
    *,
    live,
    tiny_dims=None,
    ns_steps_override=None,
):
    if opt_variant != "muon_split_bf16ns5":
        return _orig_build(
            opt_variant,
            live=live,
            tiny_dims=tiny_dims,
            ns_steps_override=ns_steps_override,
        )

    # --- muon_split_bf16ns5 dispatch ----------------------------------------
    # Delegate to the original muon_split build to get the model + routing,
    # then replace the muon optimizer with _MuonBF16NS5 and rebuild AdamW
    # with fused=fused_ok.  This reuses all model-build / dedup logic without
    # duplicating it.
    import torch
    model, vocab, hidden, n_mtp, _orig_opts = _orig_build(
        "muon_split",
        live=live,
        tiny_dims=tiny_dims,
        ns_steps_override=ns_steps_override,
    )

    # Extract LRs / WD from the original optimizers (they came from the
    # contract, which _orig_build already loaded — mirror them exactly).
    cfg = ts.load_contract()
    lr_muon  = cfg["optimizer"]["lr_muon"]
    lr_adamw = cfg["optimizer"]["lr_adamw"]
    wd       = cfg["optimizer"]["weight_decay"]
    fused_ok = live  # fused AdamW requires CUDA

    # Collect param groups from the original split.
    muon_p, adamw_p = [], []
    for opt_key, opt in _orig_opts.items():
        for group in opt.param_groups:
            if opt_key == "muon":
                muon_p.extend(group["params"])
            else:
                adamw_p.extend(group["params"])

    # Build the BF16-NS5 Muon.
    MuonBF16NS5 = _muon_bf16ns5_class()

    opts = {}
    if muon_p:
        opts["muon"] = MuonBF16NS5(
            muon_p, lr=lr_muon, weight_decay=wd, ns_steps=5,
        )
    if adamw_p:
        # (2) fused=fused_ok — the free secondary win (absent in muon_split).
        opts["adamw"] = torch.optim.AdamW(
            adamw_p, lr=lr_adamw, weight_decay=wd,
            fused=fused_ok,
        )

    return model, vocab, hidden, n_mtp, opts


ts._build_conv_model_and_opts = _build_conv_model_and_opts_patched

# Also update the argparse choices list that timeshare_pretrain.main() reads
# (it uses the module-level _CONV_OPT_VARIANTS already extended above, which
# the choices=list(...) call in ap.add_argument sees because it evaluates at
# parse time via a reference to the module-level name — confirmed: the choices
# list is built as list(_CONV_OPT_VARIANTS) inside main() after import).

# ---------------------------------------------------------------------------
# Assemble sys.argv and hand off to timeshare_pretrain.main().
# All settings are identical to muon_split: seed=42, --live, shards-v0,
# batch=16 (default for c03-h1024-d20), BF16, grad-ckpt.
# ---------------------------------------------------------------------------
sys.argv = [
    "timeshare_pretrain.py",
    "--conv",
    "--opt-variant", "muon_split_bf16ns5",
    "--token-budget", str(_TOKEN_BUDGET),
    "--loss-log-every", "3000000",
    "--seed", "42",
    "--live",
    "--shard-dir", SHARD_DIR,
    "--segment-id", "conv-muon-split-bf16ns5",
]

ts.main()
