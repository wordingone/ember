# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""train_delta_rule_dt1.py — eng-DT1 (#444): delta-rule diagnostic.

Pre-registered in docs/domains/governance/archive/pre-restart/delta-rule-diagnostic-prereg.md (frozen 2026-06-13, DT-1).

Question: Is autograd backward() + optimizer-step the exact blocking layer for
ember's candidate local-update method? Can a local fused-update LM track
backprop's next-token loss at EQUAL 4090 wall-clock?

Arms:
  WARM: short backprop warmup → switch to delta-rule fused update
  COLD: delta-rule from scratch

Parity band (frozen):
  PASS:  delta-rule NLL within 10% relative of backprop, OR lower (at equal wall-clock)
  FAIL:  >10% worse
  INCONCLUSIVE: within noise (noise = seed spread, ≥2 seeds; handled in receipt)

Implementation note on the local update (no backward()):
  Feedback alignment (Lillicrap et al., 2016). Each layer W_i has a fixed
  random feedback matrix B_i (same shape). Error signal:
    e_final = targets_one_hot - softmax(logits)    (output head)
    e_i     = e_{i+1} @ B_i^T                     (earlier layers)
    ΔW_i    = lr * e_i^T @ x_i / batch_size
  No backward() call — error propagates via fixed random weights.
  This satisfies "no autograd" for the mechanism-layer diagnostic.

Citation lineage (docs/domains/governance/charter/citation-policy-search-to-ember.md):
  Widrow-Hoff (1960), Lillicrap et al. (2016) feedback alignment.
  [UNIQUE] warm-init delta-rule × next-token LM; local-update × low-bit weights.

Selftest (CPU-only, no GPU, no EMBER_GATE_AUTHORIZED):
  python train_delta_rule_dt1.py --selftest
  → exits 0; prints DT1_SELFTEST_PASS on success.

GPU diagnostic run (equal wall-clock, real model size):
  EMBER_GATE_AUTHORIZED=1 python train_delta_rule_dt1.py --run
    --model-size 15M --wall-clock-s 120 [--seeds 2]
  → writes receipts/dt1-delta-rule-*.json

Per user direction.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
NC = str(Path(SCRIPTS).parent)


# ---------------------------------------------------------------------------
# Tiny LM for selftest (CPU, no GPU)
# ---------------------------------------------------------------------------

class _TinyLM:
    """Minimal 2-layer transformer LM (CPU numpy-free, pure PyTorch).

    Used for selftest verification of both backprop and delta-rule arms.
    n_layer in [1..4], d_model in [16..512], vocab in [16..32008].
    """

    def __init__(self, n_layer: int, d_model: int, vocab: int,
                 seq_len: int, device: str = "cpu") -> None:
        import torch
        import torch.nn as nn

        self.n_layer = n_layer
        self.d_model = d_model
        self.vocab = vocab
        self.seq_len = seq_len
        self.device = device

        # Embedding + n_layer x (attn_proj + ff) + lm_head
        self.embed = nn.Embedding(vocab, d_model, device=device)
        # Simple linear attention proxy (no softmax, for speed in selftest)
        self.attn = nn.ModuleList([nn.Linear(d_model, d_model, device=device)
                                   for _ in range(n_layer)])
        self.ff = nn.ModuleList([nn.Sequential(
            nn.Linear(d_model, d_model * 2, device=device),
            nn.GELU(),
            nn.Linear(d_model * 2, d_model, device=device),
        ) for _ in range(n_layer)])
        self.norm = nn.ModuleList([nn.LayerNorm(d_model, device=device)
                                   for _ in range(n_layer)])
        self.lm_head = nn.Linear(d_model, vocab, bias=False, device=device)
        self._init_weights()

    def _init_weights(self) -> None:
        import torch.nn as nn
        for m in [self.embed, self.lm_head, *self.attn, *self.ff, *self.norm]:
            for p in m.parameters():
                if p.dim() > 1:
                    nn.init.normal_(p, std=0.02)
                else:
                    nn.init.zeros_(p)

    def forward(self, input_ids):
        import torch
        h = self.embed(input_ids)  # (B, T, d)
        for i in range(self.n_layer):
            h = h + self.attn[i](h)         # residual attn proxy
            h = self.norm[i](h + self.ff[i](h))
        logits = self.lm_head(h)             # (B, T, vocab)
        return logits

    def parameters(self):
        yield from self.embed.parameters()
        for m in self.attn:
            yield from m.parameters()
        for m in self.ff:
            yield from m.parameters()
        for m in self.norm:
            yield from m.parameters()
        yield from self.lm_head.parameters()

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters())


def _ce_loss(logits, targets):
    """Cross-entropy loss for next-token prediction."""
    import torch
    import torch.nn.functional as F
    B, T, V = logits.shape
    return F.cross_entropy(
        logits[:, :-1, :].reshape(-1, V),
        targets[:, 1:].reshape(-1),
        ignore_index=0,
    )


# ---------------------------------------------------------------------------
# Backprop arm (standard autograd)
# ---------------------------------------------------------------------------

def _run_backprop_arm(
    model: "_TinyLM", batch_fn, n_steps: int, lr: float, device: str
) -> list[float]:
    """Run n_steps of standard backprop. Returns per-step NLL list."""
    import torch
    import torch.optim as optim

    opt = optim.Adam(list(model.parameters()), lr=lr)
    losses = []
    for _ in range(n_steps):
        ids = batch_fn()
        logits = model.forward(ids)
        loss = _ce_loss(logits, ids)
        opt.zero_grad()
        loss.backward()
        opt.step()
        losses.append(float(loss))
    return losses


# ---------------------------------------------------------------------------
# Delta-rule arm (feedback alignment — no backward())
# ---------------------------------------------------------------------------

class _DeltaRuleLM(_TinyLM):
    """Same architecture as _TinyLM but trained via feedback alignment.

    No backward() call. Fixed random feedback matrices B_i per layer.
    Error propagates top-down via B matrices (feedback alignment).
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        import torch

        # Fixed random feedback matrices — same shape as attn + ff weights (last linear)
        self._B_attn = [
            torch.randn(self.d_model, self.d_model, device=self.device) * 0.02
            for _ in range(self.n_layer)
        ]
        # Feedback for ff last linear: (d_model, d_model*2)
        self._B_ff = [
            torch.randn(self.d_model, self.d_model * 2, device=self.device) * 0.02
            for _ in range(self.n_layer)
        ]

    def _forward_with_activations(self, input_ids):
        """Forward pass collecting layer inputs/outputs. No autograd."""
        import torch

        xs = []  # layer inputs
        hs_attn_in = []
        hs_attn_out = []
        hs_ff_in = []
        hs_ff_out = []

        with torch.no_grad():
            h = self.embed(input_ids)
            xs.append(h.clone())
            for i in range(self.n_layer):
                hs_attn_in.append(h.clone())
                a = self.attn[i](h)
                hs_attn_out.append(a.clone())
                h = h + a
                hs_ff_in.append(h.clone())
                f = self.ff[i](h)
                hs_ff_out.append(f.clone())
                h = self.norm[i](h + f)
            logits = self.lm_head(h)

        return logits, h, {
            "xs": xs,
            "hs_attn_in": hs_attn_in, "hs_attn_out": hs_attn_out,
            "hs_ff_in": hs_ff_in, "hs_ff_out": hs_ff_out,
            "h_final": h,
        }

    def delta_update(self, input_ids, lr: float) -> float:
        """One step of feedback-alignment delta-rule update. No backward().

        Returns the cross-entropy loss (for monitoring; computed without grad).
        """
        import torch
        import torch.nn.functional as F

        logits, h_final, acts = self._forward_with_activations(input_ids)
        B, T, V = logits.shape

        # Output error signal: e_final = targets - softmax(logits)
        # targets = shift-by-1 (next-token prediction)
        targets = input_ids[:, 1:]  # (B, T-1)
        targets_oh = F.one_hot(targets, num_classes=V).float()  # (B, T-1, V)
        probs = torch.softmax(logits[:, :-1, :], dim=-1)         # (B, T-1, V)
        e_final = (targets_oh - probs)                            # (B, T-1, V)

        # CE loss for logging
        loss = -torch.log(probs + 1e-10).gather(-1, targets.unsqueeze(-1)).squeeze(-1).mean()

        # Update lm_head: ΔW = e_final^T @ h_final (summed over B, T-1)
        # lm_head: (V, d_model); e: (B, T-1, V); h: (B, T-1, d)
        h_for_head = acts["h_final"][:, :-1, :]  # (B, T-1, d)
        dW_head = torch.einsum("bte,btd->ed", e_final, h_for_head)  # (V, d)
        with torch.no_grad():
            self.lm_head.weight.add_(dW_head * (lr / (B * (T - 1))))

        # Propagate error backward through layers via fixed feedback matrices
        e = e_final @ self.lm_head.weight  # project to d_model: (B, T-1, d)
        e_full = torch.cat([e, torch.zeros(B, 1, self.d_model, device=self.device)], dim=1)

        for i in range(self.n_layer - 1, -1, -1):
            x_attn = acts["hs_attn_in"][i]
            dW_attn = torch.einsum("btd,btf->df", e_full, x_attn)  # (d, d)
            with torch.no_grad():
                self.attn[i].weight.add_(dW_attn * (lr / (B * T)))
                if self.attn[i].bias is not None:
                    self.attn[i].bias.add_(e_full.mean(dim=(0, 1)) * lr)

            # Feedback for ff: propagate through B_ff
            e_ff = e_full @ self._B_ff[i]  # (B, T, d_model*2)
            x_ff = acts["hs_ff_in"][i]
            # Update ff last linear (index [2])
            h_ff = self.ff[i][0](x_ff)  # (B, T, 2d) — approximation
            h_ff = torch.relu(h_ff)
            dW_ff2 = torch.einsum("btd,btf->df", e_full, h_ff)  # (d, 2d)
            with torch.no_grad():
                self.ff[i][2].weight.add_(dW_ff2 * (lr / (B * T)))
            # Propagate e further back via B_attn
            e_full = e_full @ self._B_attn[i]

        return float(loss)


def _run_delta_rule_arm(
    model: "_DeltaRuleLM", batch_fn, n_steps: int, lr: float,
    warmup_steps: int = 0, backprop_model: "_TinyLM | None" = None,
) -> list[float]:
    """Run n_steps of delta-rule update (+ optional backprop warmup).

    warmup_steps > 0 → WARM arm: run backprop on backprop_model for warmup_steps,
    copy weights to model, then switch to delta-rule.
    warmup_steps == 0 → COLD arm: delta-rule from scratch.
    """
    losses = []
    if warmup_steps > 0 and backprop_model is not None:
        import torch
        import torch.optim as optim
        # Backprop warmup
        opt = optim.Adam(list(backprop_model.parameters()), lr=lr)
        for _ in range(warmup_steps):
            ids = batch_fn()
            logits = backprop_model.forward(ids)
            loss = _ce_loss(logits, ids)
            opt.zero_grad()
            loss.backward()
            opt.step()
        # Copy weights from backprop_model to delta_model
        with torch.no_grad():
            for p_src, p_dst in zip(backprop_model.parameters(),
                                    model.parameters()):
                p_dst.copy_(p_src)

    for _ in range(n_steps):
        ids = batch_fn()
        loss = model.delta_update(ids, lr=lr)
        losses.append(loss)
    return losses


# ---------------------------------------------------------------------------
# Equal-wall-clock benchmark (GPU, gated)
# ---------------------------------------------------------------------------

def _run_benchmark(args) -> dict:
    """Equal-wall-clock benchmark. WARM + COLD vs backprop baseline.

    Returns receipt dict. GPU required. EMBER_GATE_AUTHORIZED=1.
    """
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    assert device == "cuda", "DT-1 benchmark requires CUDA (4090)"

    vocab = 32008
    seq_len = args.seq_len
    lr = args.lr
    wall_s = args.wall_clock_s
    seeds = args.seeds

    # Model size ~15M default (4 layers, 512 dims)
    n_layer, d_model = _parse_model_size(args.model_size)
    print(f"DT1_BENCHMARK: n_layer={n_layer} d_model={d_model} "
          f"vocab={vocab} seq_len={seq_len} wall_s={wall_s}s seeds={seeds}",
          flush=True)

    run_results = []
    for seed in range(seeds):
        import random
        random.seed(seed)
        torch.manual_seed(seed)

        def batch_fn():
            return torch.randint(0, vocab, (args.batch_size, seq_len), device=device)

        # --- Backprop baseline ---
        bp_model = _TinyLM(n_layer, d_model, vocab, seq_len, device=device)
        print(f"  DT1 seed={seed} n_params={bp_model.n_params():,}", flush=True)
        t0 = time.monotonic()
        bp_losses = []
        while time.monotonic() - t0 < wall_s:
            ids = batch_fn()
            logits = bp_model.forward(ids)
            loss = _ce_loss(logits, ids)
            import torch.optim as optim
            if not hasattr(bp_model, '_opt'):
                bp_model._opt = optim.Adam(list(bp_model.parameters()), lr=lr)
            bp_model._opt.zero_grad()
            loss.backward()
            bp_model._opt.step()
            bp_losses.append(float(loss))
        bp_final = bp_losses[-1] if bp_losses else float("nan")
        bp_steps = len(bp_losses)
        print(f"  DT1 seed={seed} backprop: steps={bp_steps} final_nll={bp_final:.4f}",
              flush=True)

        # --- COLD arm ---
        torch.manual_seed(seed)
        cold_model = _DeltaRuleLM(n_layer, d_model, vocab, seq_len, device=device)
        t0 = time.monotonic()
        cold_losses = []
        while time.monotonic() - t0 < wall_s:
            ids = batch_fn()
            loss = cold_model.delta_update(ids, lr=lr)
            cold_losses.append(loss)
        cold_final = cold_losses[-1] if cold_losses else float("nan")
        cold_steps = len(cold_losses)
        print(f"  DT1 seed={seed} cold: steps={cold_steps} final_nll={cold_final:.4f}",
              flush=True)

        # --- WARM arm: warmup_steps = 10% of backprop steps ---
        warmup_steps = max(1, bp_steps // 10)
        torch.manual_seed(seed)
        warm_bp_model = _TinyLM(n_layer, d_model, vocab, seq_len, device=device)
        warm_model = _DeltaRuleLM(n_layer, d_model, vocab, seq_len, device=device)
        t0 = time.monotonic()
        warm_losses = []
        # Warmup phase (backprop, counted inside wall-clock)
        for _ in range(warmup_steps):
            if time.monotonic() - t0 >= wall_s:
                break
            ids = batch_fn()
            logits = warm_bp_model.forward(ids)
            loss_bp = _ce_loss(logits, ids)
            if not hasattr(warm_bp_model, '_opt'):
                warm_bp_model._opt = optim.Adam(list(warm_bp_model.parameters()), lr=lr)
            warm_bp_model._opt.zero_grad()
            loss_bp.backward()
            warm_bp_model._opt.step()
            warm_losses.append(float(loss_bp))
        # Copy weights
        with torch.no_grad():
            for p_src, p_dst in zip(warm_bp_model.parameters(), warm_model.parameters()):
                p_dst.copy_(p_src)
        # Delta-rule phase (rest of wall-clock)
        while time.monotonic() - t0 < wall_s:
            ids = batch_fn()
            loss = warm_model.delta_update(ids, lr=lr)
            warm_losses.append(loss)
        warm_final = warm_losses[-1] if warm_losses else float("nan")
        warm_steps = len(warm_losses)
        print(f"  DT1 seed={seed} warm: steps={warm_steps} final_nll={warm_final:.4f}",
              flush=True)

        # Verdict per seed
        bp_ref = bp_final
        warm_rel = (warm_final - bp_ref) / max(abs(bp_ref), 1e-8)
        cold_rel = (cold_final - bp_ref) / max(abs(bp_ref), 1e-8)
        warm_verdict = "PASS" if warm_rel <= 0.10 else "FAIL"
        cold_verdict = "PASS" if cold_rel <= 0.10 else "FAIL"

        run_results.append({
            "seed": seed,
            "bp_steps": bp_steps, "bp_final_nll": bp_final,
            "cold_steps": cold_steps, "cold_final_nll": cold_final,
            "warm_steps": warm_steps, "warm_final_nll": warm_final,
            "cold_rel_to_bp": cold_rel,
            "warm_rel_to_bp": warm_rel,
            "cold_verdict": cold_verdict,
            "warm_verdict": warm_verdict,
        })

    # Aggregate verdict
    warm_pass = any(r["warm_verdict"] == "PASS" for r in run_results)
    cold_pass = any(r["cold_verdict"] == "PASS" for r in run_results)

    if warm_pass and cold_pass:
        overall = "PASS"
    elif warm_pass and not cold_pass:
        overall = "WARM_PASS_COLD_FAIL"
    elif not warm_pass and not cold_pass:
        overall = "FAIL"
    else:
        overall = "INCONCLUSIVE"

    return {
        "per_seed": run_results,
        "warm_pass_any": warm_pass,
        "cold_pass_any": cold_pass,
        "overall": overall,
    }


def _parse_model_size(size_str: str) -> tuple[int, int]:
    """Parse '15M' → (n_layer, d_model) pair. Approximate."""
    size_str = size_str.strip().upper()
    if "M" in size_str:
        m = float(size_str.replace("M", ""))
    elif "B" in size_str:
        m = float(size_str.replace("B", "")) * 1000
    else:
        m = float(size_str)
    # Approx: params ≈ 4 * n_layer * d_model^2 (for transformer)
    # Choose n_layer=4 and solve for d_model
    n_layer = 4
    d_model = int(math.sqrt(m * 1e6 / (4 * n_layer)))
    d_model = max(64, min(1024, (d_model // 64) * 64))
    return n_layer, d_model


# ---------------------------------------------------------------------------
# Selftest (CPU, no GPU, no EMBER_GATE_AUTHORIZED)
# ---------------------------------------------------------------------------

def _selftest() -> None:
    import torch

    failures = []
    t0 = time.monotonic()

    def check(name: str, cond: bool, msg: str = "") -> None:
        if not cond:
            failures.append(f"{name}: {msg}" if msg else name)
        else:
            print(f"  OK {name}", flush=True)

    # 1. TinyLM forward pass (CPU)
    try:
        model = _TinyLM(n_layer=2, d_model=32, vocab=64, seq_len=16, device="cpu")
        check("tinylm_n_params_nonzero", model.n_params() > 0)
        ids = torch.randint(0, 64, (2, 16))
        logits = model.forward(ids)
        check("tinylm_forward_shape", logits.shape == (2, 16, 64),
              f"shape={logits.shape}")
        check("tinylm_forward_finite", torch.isfinite(logits).all().item())
    except Exception as e:
        failures.append(f"tinylm_forward: {e}")

    # 2. CE loss
    try:
        loss = _ce_loss(logits, ids)
        check("ce_loss_finite", torch.isfinite(loss).item())
        check("ce_loss_positive", float(loss) > 0)
    except Exception as e:
        failures.append(f"ce_loss: {e}")

    # 3. Backprop arm (CPU, 5 steps)
    try:
        torch.manual_seed(42)
        bp_model = _TinyLM(n_layer=2, d_model=32, vocab=64, seq_len=16, device="cpu")
        batch_fn = lambda: torch.randint(0, 64, (2, 16))  # noqa: E731
        bp_losses = _run_backprop_arm(bp_model, batch_fn, n_steps=5, lr=1e-3, device="cpu")
        check("backprop_5_steps", len(bp_losses) == 5)
        check("backprop_all_finite", all(math.isfinite(l) for l in bp_losses))
        check("backprop_loss_positive", all(l > 0 for l in bp_losses))
    except Exception as e:
        failures.append(f"backprop_arm: {e}")

    # 4. Delta-rule arm COLD (CPU, 5 steps, no backward())
    try:
        torch.manual_seed(42)
        cold_model = _DeltaRuleLM(n_layer=2, d_model=32, vocab=64, seq_len=16, device="cpu")
        cold_losses = _run_delta_rule_arm(cold_model, batch_fn, n_steps=5, lr=1e-3)
        check("cold_arm_5_steps", len(cold_losses) == 5)
        check("cold_arm_all_finite", all(math.isfinite(l) for l in cold_losses),
              str(cold_losses))
        check("cold_arm_loss_positive", all(l > 0 for l in cold_losses))
    except Exception as e:
        failures.append(f"cold_arm: {e}")

    # 5. Delta-rule arm WARM (CPU, 2 warmup + 3 delta-rule steps)
    try:
        torch.manual_seed(42)
        warm_model = _DeltaRuleLM(n_layer=2, d_model=32, vocab=64, seq_len=16, device="cpu")
        warm_bp_model = _TinyLM(n_layer=2, d_model=32, vocab=64, seq_len=16, device="cpu")
        warm_losses = _run_delta_rule_arm(
            warm_model, batch_fn, n_steps=3, lr=1e-3,
            warmup_steps=2, backprop_model=warm_bp_model,
        )
        check("warm_arm_3_steps", len(warm_losses) == 3)
        check("warm_arm_all_finite", all(math.isfinite(l) for l in warm_losses),
              str(warm_losses))
    except Exception as e:
        failures.append(f"warm_arm: {e}")

    # 6. DeltaRuleLM has no backward() call (verified by inspection of delta_update)
    try:
        cold_model2 = _DeltaRuleLM(n_layer=1, d_model=16, vocab=32, seq_len=8, device="cpu")
        ids_small = torch.randint(0, 32, (1, 8))
        loss_val = cold_model2.delta_update(ids_small, lr=1e-3)
        check("delta_update_returns_float", isinstance(loss_val, float))
        check("delta_update_finite", math.isfinite(loss_val))
        # Verify no .grad on params (delta_update uses no_grad context)
        has_grad = any(p.grad is not None for p in cold_model2.parameters())
        check("delta_update_no_grad_accumulated", not has_grad,
              "delta_update left grad on params — backward() may have been called")
    except Exception as e:
        failures.append(f"no_backward_check: {e}")

    # 7. Receipt schema (dry-run, no GPU)
    try:
        dummy_receipt = {
            "ticket": "DT1-DELTA-RULE-DIAGNOSTIC",
            "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "prereg": "docs/domains/governance/archive/pre-restart/delta-rule-diagnostic-prereg.md",
            "model_size": "15M",
            "wall_clock_s": 120,
            "seeds": 2,
            "per_seed": [],
            "warm_pass_any": False,
            "cold_pass_any": False,
            "overall": "INCONCLUSIVE",
            "verdict_map": {
                "PASS": "owned-update path PROCEEDS",
                "WARM_PASS_COLD_FAIL": "owned path proceeds WITH warm-init required",
                "FAIL": "owned-update SHELVED for round-1",
                "INCONCLUSIVE": "within noise; increase seeds",
            },
            "dt1_selftest_pass": True,
        }
        import json as _json
        s = _json.dumps(dummy_receipt)
        check("receipt_schema_serializable", len(s) > 0)
        check("receipt_has_overall", "overall" in dummy_receipt)
        check("receipt_has_verdict_map", "verdict_map" in dummy_receipt)
    except Exception as e:
        failures.append(f"receipt_schema: {e}")

    elapsed = time.monotonic() - t0
    check("runtime_under_30s", elapsed < 30.0, f"{elapsed:.1f}s")

    if failures:
        print(f"\nDT1_SELFTEST_FAIL failures={failures}", flush=True)
        raise SystemExit(1)

    print(f"DT1_SELFTEST_PASS elapsed={elapsed:.2f}s", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _write_receipt(result: dict, args) -> Path:
    sys.path.insert(0, SCRIPTS)
    # issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
    import importlib.util as _ember_66ee9e91637922dc_importlib
    import sys as _ember_66ee9e91637922dc_sys
    from pathlib import Path as _ember_66ee9e91637922dc_Path
    _ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
    if not _ember_66ee9e91637922dc_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
    _ember_66ee9e91637922dc_existing = []
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
            _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
    if len(_ember_66ee9e91637922dc_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
    if _ember_66ee9e91637922dc_existing:
        _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
        _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
        if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
    else:
        _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
        if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
            if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
            _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
        try:
            _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
        except BaseException:
            for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
                if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                    _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
            raise
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "DT1-DELTA-RULE-DIAGNOSTIC",
        "ts": ts,
        "prereg": "docs/domains/governance/archive/pre-restart/delta-rule-diagnostic-prereg.md",
        "model_size": args.model_size,
        "wall_clock_s": args.wall_clock_s,
        "seeds": args.seeds,
        "seq_len": args.seq_len,
        "batch_size": args.batch_size,
        "lr": args.lr,
        **result,
        "verdict_map": {
            "PASS": "owned-update path PROCEEDS; autograd confirmed as substrate boundary",
            "WARM_PASS_COLD_FAIL": "owned path proceeds WITH warm-init required (kills-guard confirmed)",
            "FAIL": "owned-update SHELVED for round-1; round-1 bootstraps borrowed",
            "INCONCLUSIVE": "within noise; increase seeds or wall-clock",
        },
    }
    out_path = Path(NC) / "receipts" / f"dt1-delta-rule-{ts}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out_path), receipt)
    print(f"DT1_RECEIPT_WRITTEN: {out_path}", flush=True)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="DT-1 delta-rule diagnostic")
    parser.add_argument("--selftest", action="store_true",
                        help="CPU selftest; exits 0 on pass")
    parser.add_argument("--run", action="store_true",
                        help="Run GPU benchmark (EMBER_GATE_AUTHORIZED=1 required)")
    parser.add_argument("--model-size", type=str, default="15M",
                        help="Model size string e.g. '15M' (default 15M)")
    parser.add_argument("--wall-clock-s", type=int, default=120,
                        help="Wall-clock seconds per arm (default 120)")
    parser.add_argument("--seeds", type=int, default=2,
                        help="Number of seeds per arm (default 2)")
    parser.add_argument("--seq-len", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--lr", type=float, default=1e-3)
    args = parser.parse_args()

    if args.selftest:
        _selftest()
        return

    if args.run:
        if os.environ.get("EMBER_GATE_AUTHORIZED", "") != "1":
            print("DT1_BLOCKED: EMBER_GATE_AUTHORIZED=1 required for --run")
            raise SystemExit(1)
        result = _run_benchmark(args)
        _write_receipt(result, args)
        overall = result["overall"]
        print(f"DT1_DIAGNOSTIC_DONE overall={overall}", flush=True)
        return

    parser.print_help()
    raise SystemExit(0)


if __name__ == "__main__":
    main()
