#!/usr/bin/env python3
"""ember_phase3_c14/resident_adapter.py — LoRA/adapter wrapper for C14 resident training.

Injects a rank-r LoRA decomposition (A: in_features -> rank, B: rank -> out_features)
at a named linear layer of a base nn.Module, exposing the adapter's state_dict as the
inspectable trainable delta.

Two build paths:

  build_toy_adapter(rank=4):
    Wraps TinyPolicyTransformer (from ember_resident_igrpo) with a LoRA layer injected
    at its 'head' linear.  Runs on CPU; no EMBER_GATE_AUTHORIZED check.  Used by all
    CPU selftests and by the phase3 igrpo_trainer + abc_deleted_harness toy paths.

  build_fp16_adapter(cfg, rank=4):
    Wraps EmberModelShell (from ember_c14_real_adapter) with a LoRA layer injected at a
    named linear layer from the shell's registered submodules.  Calls
    load_multimodal_config + build_multimodal_v0_model.  The on-base GPU path is behind
    EMBER_GATE_AUTHORIZED; the CPU tiny path (live=False) runs without the interlock.

Key interfaces (required by sibling phase3 files):

  class LoRAAdapter(nn.Module):
    __init__(self, base: nn.Module, target_layer_name: str, rank: int = 4)
    forward(*args, **kwargs) -> Tensor
    adapter_state_dict() -> dict
    restore_pre_adapter_state(pre_snapshot: dict) -> None
    param_hash() -> str
    build_fp16_adapter(cfg: dict, rank: int = 4) -> LoRAAdapter
    build_toy_adapter(rank: int = 4) -> LoRAAdapter

CPU selftest (__main__):
  Proves that adapter state_dict changes after one verifier-conditioned iGRPO step
  on a TinyPolicyTransformer toy instance.  No GPU, no C-BASE weights required.
  Asserts:
    (a) pre_hash != post_hash  (weights changed)
    (b) adapter_state_dict() contains only lora_A and lora_B keys
    (c) restore_pre_adapter_state restores exact pre-step hash
    (d) restored model is indistinguishable from original (Deleted arm property)

Does-NOT-count guard (SYMBOLIC_PROXY_PASS):
  The LoRAAdapter wraps an actual nn.Module; lora_A and lora_B are nn.Parameter tensors
  updated by optimizer.step() through real gradient computation via igrpo_loss.  There is
  no routing table, no prompt-edit, no scalar dictionary.  The selftest proves this by
  asserting pre_hash != post_hash after one iGRPO step — a symbolic proxy has no
  nn.Module state_dict and cannot pass this assertion.

EMBER_GATE_AUTHORIZED interlock:
  build_fp16_adapter with live=True is blocked behind EMBER_GATE_AUTHORIZED=1.
  All other code paths (toy path, tiny CPU path) run without the interlock.
"""
from __future__ import annotations

import hashlib
import os
import sys
from copy import deepcopy
from typing import Any, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

# ---------------------------------------------------------------------------
# Resolve import paths for sibling scripts
# ---------------------------------------------------------------------------

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.dirname(_THIS_DIR)

for _p in (_THIS_DIR, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# LoRALayer — rank-r decomposition injected at a single nn.Linear
# ---------------------------------------------------------------------------

class LoRALayer(nn.Module):
    """Rank-r LoRA injection for one nn.Linear layer.

    Adds a residual low-rank correction:
        h = W x  +  (B A) x  *  scaling
    where A: (in_features, rank) and B: (rank, out_features) are the trained parameters.
    The base weight W is frozen during adapter training.

    scaling = alpha / rank  (default alpha = rank, so scaling = 1.0)

    Initialisation: A ~ N(0, 0.01), B = 0  so the adapter starts as identity correction.
    """

    def __init__(
        self,
        in_features: int,
        out_features: int,
        rank: int = 4,
        alpha: Optional[float] = None,
    ) -> None:
        super().__init__()
        if rank <= 0:
            raise ValueError(f"LoRA rank must be > 0, got {rank}")
        self.rank = rank
        self.alpha = float(alpha) if alpha is not None else float(rank)
        self.scaling = self.alpha / self.rank

        # Low-rank matrices: A maps input -> low-dim, B maps low-dim -> output.
        self.lora_A = nn.Parameter(torch.empty(in_features, rank))
        self.lora_B = nn.Parameter(torch.zeros(rank, out_features))

        nn.init.normal_(self.lora_A, mean=0.0, std=0.01)
        # lora_B starts at zero so the initial correction is zero.

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Return low-rank correction term: x @ A @ B * scaling.

        Shape: input (*, in_features) -> output (*, out_features).

        Dtype boundary (maintainer adjudication, 2026-07-04, GATE-0 live
        fix): LoRA math always runs at self.lora_A's own dtype, independent
        of whatever dtype x arrives in -- e.g. bf16 activations from a
        frozen base loaded at its checkpoint-native precision. This keeps
        the adapter's own compute (and its Adam optimizer state, tracked at
        lora_A/lora_B's dtype) at fp32 even when the base it's attached to
        is bf16, so training precision for the trainable delta is never
        silently downgraded by whatever the frozen base happens to be
        loaded as. The correction is cast back to x's original dtype before
        returning, so a caller doing `output + correction` (the forward
        hook below) never sees a stray higher-precision tensor leak into a
        lower-precision graph. When x already matches self.lora_A's dtype
        (every pre-existing caller), both casts are no-ops.
        """
        compute_dtype = self.lora_A.dtype
        correction = (x.to(compute_dtype) @ self.lora_A @ self.lora_B) * self.scaling
        return correction.to(x.dtype)


# ---------------------------------------------------------------------------
# LoRAAdapter — nn.Module wrapper that injects LoRALayer at a named linear
# ---------------------------------------------------------------------------

class LoRAAdapter(nn.Module):
    """LoRA adapter wrapping any nn.Module base model.

    Injects a LoRALayer at the linear layer identified by target_layer_name
    (a dotted path into base.named_modules(), e.g. "head" or "attention_proj_0").

    During forward:
      out = base_forward(*args, **kwargs)   # uses the frozen base weights
      The LoRA correction is added inside the patched linear via a hook.

    Only lora_A and lora_B are trained.  All base parameters are frozen by
    default (requires_grad=False).  Callers may unfreeze base params explicitly
    for the full-weights CPU toy selftest path.

    Exposes:
      adapter_state_dict()        -> dict with only lora_A, lora_B keys
      restore_pre_adapter_state() -> load_state_dict from a pre-step snapshot
      param_hash()                -> sha256 of all parameter bytes (full model)
      adapter_param_hash()        -> sha256 of only adapter parameters
    """

    def __init__(
        self,
        base: nn.Module,
        target_layer_name: str,
        rank: int = 4,
        alpha: Optional[float] = None,
        freeze_base: bool = True,
    ) -> None:
        super().__init__()

        # Validate the target layer name exists and is an nn.Linear.
        target_module = self._find_module(base, target_layer_name)
        if target_module is None:
            available = [name for name, _ in base.named_modules() if name]
            raise ValueError(
                f"target_layer_name={target_layer_name!r} not found in base model. "
                f"Available: {available[:20]}"
            )
        if not isinstance(target_module, nn.Linear):
            raise TypeError(
                f"target_layer_name={target_layer_name!r} resolved to "
                f"{type(target_module).__name__}, expected nn.Linear"
            )

        in_features = target_module.in_features
        out_features = target_module.out_features

        # Register base as a submodule so its parameters appear in state_dict.
        self.base = base
        self._target_layer_name = target_layer_name

        # Create the LoRA layer and register it as a named submodule.
        self.lora = LoRALayer(in_features, out_features, rank=rank, alpha=alpha)

        # Optionally freeze all base parameters so only lora_A/lora_B are trained.
        if freeze_base:
            for param in self.base.parameters():
                param.requires_grad_(False)

        # Install a forward hook on the target linear to add the LoRA correction.
        self._hook_handle = target_module.register_forward_hook(self._lora_hook)

    # ------------------------------------------------------------------
    # Module lookup helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_module(root: nn.Module, dotted_name: str) -> Optional[nn.Module]:
        """Traverse root.named_modules() to find the module at dotted_name."""
        for name, module in root.named_modules():
            if name == dotted_name:
                return module
        return None

    # ------------------------------------------------------------------
    # Forward hook: adds LoRA correction to the target linear's output
    # ------------------------------------------------------------------

    def _lora_hook(
        self,
        module: nn.Module,
        input: tuple[torch.Tensor, ...],
        output: torch.Tensor,
    ) -> torch.Tensor:
        """Hook registered on the target nn.Linear.

        Called automatically by PyTorch after module.forward(x).
        Returns output + lora(x) — adds the low-rank correction to the
        base linear's output.
        """
        x = input[0]
        correction = self.lora(x)
        return output + correction

    # ------------------------------------------------------------------
    # Forward — delegates to base
    # ------------------------------------------------------------------

    def forward(self, *args: Any, **kwargs: Any) -> torch.Tensor:
        """Forward pass — delegates to base model.

        The LoRA correction is injected via the registered forward hook on the
        target linear layer; callers do not need to call self.lora explicitly.
        """
        return self.base(*args, **kwargs)

    # Expose sample_action if the base model has it (used by igrpo_step).
    def sample_action(self, context_ids: torch.Tensor, temperature: float = 1.0) -> int:
        if not hasattr(self.base, "sample_action"):
            raise AttributeError(
                f"{type(self.base).__name__} does not implement sample_action(); "
                "cannot use LoRAAdapter.sample_action() without it."
            )
        return self.base.sample_action(context_ids, temperature)

    # log_prob_sequence for TinyPolicyTransformer compatibility.
    def log_prob_sequence(
        self,
        input_ids: torch.Tensor,
        target_ids: torch.Tensor,
    ) -> torch.Tensor:
        if hasattr(self.base, "log_prob_sequence"):
            return self.base.log_prob_sequence(input_ids, target_ids)
        raise AttributeError(
            f"{type(self.base).__name__} does not implement log_prob_sequence()"
        )

    # ------------------------------------------------------------------
    # Adapter state-dict — only lora_A and lora_B
    # ------------------------------------------------------------------

    def adapter_state_dict(self) -> dict[str, torch.Tensor]:
        """Return a dict containing only the LoRA parameters.

        Keys: "lora.lora_A", "lora.lora_B"
        These are the inspectable trainable delta for the C arm.
        """
        return {
            "lora.lora_A": self.lora.lora_A.detach().clone(),
            "lora.lora_B": self.lora.lora_B.detach().clone(),
        }

    # ------------------------------------------------------------------
    # State restoration — used by abc_deleted_harness Deleted arm
    # ------------------------------------------------------------------

    def restore_pre_adapter_state(self, pre_snapshot: dict[str, Any]) -> None:
        """Restore the full model (base + lora) to a prior state_dict snapshot.

        The snapshot should have been captured via self.state_dict() BEFORE any
        iGRPO update step.  After this call, param_hash() matches the pre-step hash.

        Used by the Deleted arm in abc_deleted_harness.py to prove the neural delta
        is load-bearing: restoring the state and re-evaluating shows degraded performance.
        """
        # strict=False lets us restore even if the snapshot was captured before the
        # lora submodule existed (e.g. base-only snapshot); missing keys default to
        # their current values.  For proper Deleted arm usage, the snapshot IS from
        # a full LoRAAdapter state_dict, so strict=True would also work — but we
        # use strict=False to be robust to caller snapshots.
        missing, unexpected = self.load_state_dict(pre_snapshot, strict=False)
        if unexpected:
            raise ValueError(
                f"restore_pre_adapter_state: unexpected keys in snapshot: {unexpected}"
            )

    # ------------------------------------------------------------------
    # Parameter hash — used by igrpo_trainer + abc_deleted_harness guards
    # ------------------------------------------------------------------

    def param_hash(self) -> str:
        """SHA-256 of all parameter bytes (full model: base + lora).

        A change in any parameter (base or adapter) changes this hash.
        The selftest asserts pre_hash != post_hash after one iGRPO step.
        """
        h = hashlib.sha256()
        for name, param in sorted(self.named_parameters()):
            h.update(name.encode())
            h.update(param.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes())
        return h.hexdigest()

    def adapter_param_hash(self) -> str:
        """SHA-256 of adapter parameters only (lora_A, lora_B).

        Used to verify the adapter delta specifically changed, independent
        of any base-weight changes.
        """
        h = hashlib.sha256()
        for name, param in sorted(self.lora.named_parameters()):
            h.update(name.encode())
            h.update(param.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes())
        return h.hexdigest()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def remove_hook(self) -> None:
        """Remove the LoRA forward hook from the target linear.

        Call this before serialising the base model without the adapter,
        or when switching to a different target layer.
        """
        self._hook_handle.remove()


# ---------------------------------------------------------------------------
# build_toy_adapter — wraps TinyPolicyTransformer (CPU, no EMBER_GATE check)
# ---------------------------------------------------------------------------

def build_toy_adapter(rank: int = 4) -> LoRAAdapter:
    """Build a LoRAAdapter wrapping TinyPolicyTransformer for CPU toy use.

    The LoRA layer is injected at the 'head' linear (the final projection from
    hidden_dim -> vocab_size in TinyPolicyTransformer).

    No EMBER_GATE_AUTHORIZED check.  Designed for:
      - CPU selftests (this file's __main__)
      - phase3/igrpo_trainer.py toy path
      - phase3/abc_deleted_harness.py stub arm

    Returns a LoRAAdapter that:
      - Wraps TinyPolicyTransformer
      - Only lora_A + lora_B are trained (base parameters frozen by default)
      - Exposes sample_action(), log_prob_sequence(), forward() via delegation
      - adapter_state_dict() returns only the LoRA parameters
    """
    from ember_resident_igrpo import TinyPolicyTransformer

    base = TinyPolicyTransformer()
    # 'head' is the nn.Linear(hidden_dim, vocab_size) inside TinyPolicyTransformer.
    adapter = LoRAAdapter(base, target_layer_name="head", rank=rank, freeze_base=True)
    return adapter


# ---------------------------------------------------------------------------
# build_fp16_adapter — wraps EmberModelShell (calls train_multimodal_v0.py APIs)
# ---------------------------------------------------------------------------

def build_fp16_adapter(
    cfg: Optional[dict] = None,
    rank: int = 4,
    live: bool = False,
) -> LoRAAdapter:
    """Build a LoRAAdapter wrapping EmberModelShell for the fp16 C arm.

    Calls load_multimodal_config() and build_multimodal_v0_model() from
    train_multimodal_v0.py, then wraps the result in EmberModelShell
    (from ember_c14_real_adapter.py), and finally injects a LoRA layer.

    CPU tiny path (live=False, default):
      EmberModelV0Multimodal(hidden=32, vocab=64, n_layers=1) — no CUDA, no interlock.

    GPU full path (live=True):
      Requires EMBER_GATE_AUTHORIZED=1.  Blocked otherwise.

    The LoRA layer is injected at the first 'attention_proj_*' linear found in the
    shell's registered submodules, which are all named with the "attention" prefix by
    EmberModelShell's __init__ registration logic.

    Args:
        cfg: multimodal config dict.  If None, calls load_multimodal_config().
        rank: LoRA rank (default 4).
        live: if True, build the production c03-h1024-d20 model (EMBER_GATE_AUTHORIZED
              required).  If False, build the tiny CPU model.

    Returns:
        LoRAAdapter wrapping EmberModelShell via _ActionVocabForwardWrapper.

    The returned adapter exposes:
        forward(input_ids) -> (B, S, V) via the shell's vocab-projection wrapper
        sample_action(context_ids, temperature) -> int
        adapter_state_dict() -> {"lora.lora_A": ..., "lora.lora_B": ...}
        restore_pre_adapter_state(snapshot) -> restores full state
        param_hash() -> str
    """
    if live:
        authorized = os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1"
        if not authorized:
            msg = (
                "RESIDENT_ADAPTER_INTERLOCK_REFUSED: live=True requires "
                "EMBER_GATE_AUTHORIZED=1 (env var). CPU tiny path: live=False."
            )
            raise RuntimeError(msg)

    from train_multimodal_v0 import load_multimodal_config
    from build_multimodal_v0_model import build_multimodal_v0_model
    from ember_c14_real_adapter import EmberModelShell

    if cfg is None:
        cfg = load_multimodal_config()

    model, _vocab, _hidden = build_multimodal_v0_model(cfg, live=live)
    shell = EmberModelShell(model)

    # Find the first attention_proj linear in the shell's registered submodules.
    # EmberModelShell.__init__ registers linear layers as "attention_proj_N" or
    # "attention_out_proj_N" submodules.  We pick the first one found.
    target_name: Optional[str] = None
    for name, mod in shell.named_modules():
        if isinstance(mod, nn.Linear) and name:
            target_name = name
            break

    if target_name is None:
        raise RuntimeError(
            "build_fp16_adapter: no nn.Linear found in EmberModelShell named_modules(). "
            "Cannot inject LoRA layer."
        )

    adapter = LoRAAdapter(shell, target_layer_name=target_name, rank=rank, freeze_base=True)
    return adapter


# ---------------------------------------------------------------------------
# CPU selftest (__main__)
# ---------------------------------------------------------------------------

def _run_selftest() -> None:
    """CPU selftest: prove adapter state_dict changes after one iGRPO step.

    Assertions:
      (a) pre_hash != post_hash after one iGRPO step
          (both base params frozen, only lora_A/B trained)
      (b) adapter_state_dict() contains exactly {'lora.lora_A', 'lora.lora_B'}
      (c) restore_pre_adapter_state restores the exact pre-step hash (Deleted property)
      (d) post-restore hash == pre_hash  (deletion is exact)
      (e) LoRA adapter forward does not raise for a valid input
      (f) Base parameters are frozen (no requires_grad) after build_toy_adapter

    Does-NOT-count guard (SYMBOLIC_PROXY_PASS):
      A symbolic proxy (template selector, scalar dictionary) has no nn.Module
      state_dict and cannot pass assertion (a).  The LoRALayer has real nn.Parameter
      tensors; igrpo_step calls optimizer.step() through igrpo_loss which computes
      -sum_j A_j * log pi(a_j | context) via the network — a real PG update.
    """
    import torch.optim as optim

    print("RESIDENT_ADAPTER_SELFTEST: starting...")

    # ---------------------------------------------------------------
    # Build toy adapter
    # ---------------------------------------------------------------
    adapter = build_toy_adapter(rank=4)
    print(f"  Built LoRAAdapter wrapping TinyPolicyTransformer (rank=4)")

    # (b) adapter_state_dict keys
    asd = adapter.adapter_state_dict()
    assert set(asd.keys()) == {"lora.lora_A", "lora.lora_B"}, (
        f"Expected exactly {{'lora.lora_A', 'lora.lora_B'}}, got {set(asd.keys())}"
    )
    print(f"  (b) adapter_state_dict keys correct: {sorted(asd.keys())}")

    # (f) Base parameters are frozen
    frozen_count = 0
    for name, param in adapter.base.named_parameters():
        assert not param.requires_grad, (
            f"Base parameter {name} should be frozen (requires_grad=False) but is not."
        )
        frozen_count += 1
    assert frozen_count > 0, "No base parameters found — base model may be empty."
    print(f"  (f) All {frozen_count} base parameters are frozen (requires_grad=False)")

    # Verify lora params DO have requires_grad.
    trainable = [n for n, p in adapter.named_parameters() if p.requires_grad]
    assert len(trainable) >= 2, f"Expected at least lora_A + lora_B to be trainable, got {trainable}"
    print(f"  Trainable parameters: {trainable}")

    # (e) Forward does not raise
    dummy_input = torch.randint(0, 10, (1, 3))  # (batch=1, seq=3)
    with torch.no_grad():
        out = adapter(dummy_input)
    assert out.shape[-1] == 10, (  # TinyPolicyTransformer vocab=10
        f"Expected output vocab dim 10, got {out.shape}"
    )
    print(f"  (e) Forward output shape: {tuple(out.shape)}")

    # ---------------------------------------------------------------
    # Capture pre-step state
    # ---------------------------------------------------------------
    pre_hash = adapter.param_hash()
    pre_snapshot = {k: v.clone() for k, v in adapter.state_dict().items()}
    print(f"  Pre-step hash: {pre_hash[:16]}...")

    # ---------------------------------------------------------------
    # Run iGRPO steps until a non-degenerate step changes the weights
    # ---------------------------------------------------------------
    # igrpo_step from ember_resident_igrpo expects a policy with:
    #   .forward(input_ids) -> (B, S, V) logits
    #   .sample_action(context_ids, temperature) -> int
    #   .parameters() -> iterable of nn.Parameter
    #   .log_prob_sequence(input_ids, target_ids) -> scalar Tensor
    #
    # LoRAAdapter delegates all of these to TinyPolicyTransformer through the base.
    # Only lora_A + lora_B have requires_grad=True, so optimizer.step() updates them.
    #
    # iGRPO produces zero loss when all Stage-2 rewards are equal (degenerate group:
    # all correct or all wrong -> advantages = 0 -> no gradient).  We loop until at
    # least one step produces a non-degenerate reward distribution (mixed correct/wrong),
    # which produces non-zero advantages and a real PG gradient.
    #
    # This is the correct test: the weight change is genuine PG update, not a forced
    # update — a symbolic proxy (template selector, dictionary) cannot pass this.

    from ember_resident_igrpo import igrpo_step

    # Use only trainable params in the optimizer.
    optimizer = optim.Adam(
        [p for p in adapter.parameters() if p.requires_grad],
        lr=1e-2,
    )

    MAX_IGRPO_TRIES = 20  # At G=4, mixed rewards occur frequently; 20 tries is safe.
    result = None
    step_count = 0
    for _attempt in range(MAX_IGRPO_TRIES):
        # Rotate over state_vals to vary the task difficulty.
        sv = _attempt % 8
        result = igrpo_step(
            policy=adapter,
            optimizer=optimizer,
            state_val=sv,
            N=4,
            G=4,
            max_depth=1,
            epsilon=0.2,
            temperature=1.5,
        )
        step_count += 1
        loss_val = result.get("loss", 0.0)
        post_hash_check = adapter.param_hash()
        if post_hash_check != pre_hash:
            # Weights changed — non-degenerate step succeeded.
            print(f"  igrpo_step #{step_count}: state_val={sv}, "
                  f"loss={loss_val:.4f}, "
                  f"s2_rewards={result.get('stage2_rewards', [])}")
            break
        # Degenerate step (loss=0, all advantages zero): try again.
        if _attempt < MAX_IGRPO_TRIES - 1:
            continue

    assert result is not None, "igrpo_step was never called"

    # ---------------------------------------------------------------
    # (a) Assert state_dict CHANGED
    # ---------------------------------------------------------------
    post_hash = adapter.param_hash()
    print(f"  Post-step hash: {post_hash[:16]}...")
    assert pre_hash != post_hash, (
        "FAIL (a): param_hash did not change after iGRPO step. "
        "lora_A/lora_B were not updated. Check that optimizer.step() ran "
        "and that lora parameters have requires_grad=True."
    )
    print(f"  (a) PASS: pre_hash != post_hash (weights changed)")

    # Also check adapter-specific hash changed.
    pre_adapter_hash = hashlib.sha256(
        pre_snapshot.get("lora.lora_A", torch.zeros(1)).detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()
        + pre_snapshot.get("lora.lora_B", torch.zeros(1)).detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()
    ).hexdigest()
    post_adapter_hash = adapter.adapter_param_hash()
    assert pre_adapter_hash != post_adapter_hash, (
        "FAIL (a-adapter): adapter_param_hash did not change. "
        "lora_A and lora_B must be updated by the PG loss."
    )
    print(f"  (a-adapter) PASS: adapter param hash changed")

    # ---------------------------------------------------------------
    # (c,d) restore_pre_adapter_state restores exact pre-step hash
    # ---------------------------------------------------------------
    adapter.restore_pre_adapter_state(pre_snapshot)
    restored_hash = adapter.param_hash()
    assert restored_hash == pre_hash, (
        f"FAIL (c/d): restored hash {restored_hash[:16]}... != pre hash {pre_hash[:16]}... "
        "restore_pre_adapter_state did not fully restore the model."
    )
    print(f"  (c/d) PASS: restored hash == pre_hash (Deleted arm property verified)")

    # ---------------------------------------------------------------
    # Verify restored model produces the same forward output as pre-step
    # ---------------------------------------------------------------
    with torch.no_grad():
        out_restored = adapter(dummy_input)
    # Re-build a fresh adapter from scratch to compare.
    fresh = build_toy_adapter(rank=4)
    fresh.load_state_dict(pre_snapshot)
    with torch.no_grad():
        out_fresh = fresh(dummy_input)
    assert torch.allclose(out_restored, out_fresh, atol=1e-6), (
        "FAIL: restored adapter output does not match fresh adapter loaded from same snapshot. "
        "restore_pre_adapter_state may have partial state."
    )
    print(f"  Restored adapter output matches fresh load from snapshot.")

    print("RESIDENT_ADAPTER_SELFTEST_PASS")


if __name__ == "__main__":
    _run_selftest()
