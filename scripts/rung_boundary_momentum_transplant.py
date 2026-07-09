#!/usr/bin/env python3
"""rung_boundary_momentum_transplant.py — Branch-A boundary-policy wiring
(issue #524, cell M4).

Branch A is the ADJUDICATED law, not a proposal: docs/spec/rung2-stabilize-
config-respec-v1.md section 5 pre-registered the P-2 decision rule (transplant
cos_alignment >= 0.82 AND reset cos_alignment in ~[0.70, 0.78] => Branch A
PASSES) BEFORE the b4 receipt landed. It landed:
receipts/cbase-grow-rung2-event-b513-b4rerun-b3.json --
arms.transplant.d_comm_fields.cos_alignment=0.9536 (>= 0.82),
arms.reset.d_comm_fields.cos_alignment=0.7397 (in [0.70, 0.78]).
Branch A: rung-2 stabilize and all rung-3 grow events adopt
transplant-with-verified-buffer as boundary policy going forward.

Gap this module fills: neither production grow runner
(scripts/cbase_grow_live.py, scripts/cbase_grow_rung.py) has ANY momentum
transplant wiring at all -- cbase_grow_live.py's own docstring says so
explicitly ("The pre-grow optimizer state cannot be replayed into the
post-grow optimizer ... reset_optimizer_on_resume=True skips that load").
Production defaults to Branch B (reset) by omission, not by adjudicated
law. The only existing transplant + fail-closed code
(scripts/cbase_grow_rung2_event.py's `_pushforward_gate_momentum` +
scripts/p5_ratio_audit/run_p5_audit.py's `EngagementFailure`) lives in the
FORENSIC/measurement path (the b3/b4 d_comm arms comparison), not in a
form a production stabilize launcher can call. This module is that
reusable, production-callable form -- reusing both pieces, not
reimplementing either.

Generalizes the private `_pushforward_gate_momentum` (single gate_proj,
one layer, synthetic-dict trick) to ALL Muon-routed FF tensors across ALL
layers in one call: since `widen_state_dict` already iterates n_layers and
applies the declared rule (gate/up: row-duplication; down: half-split-
duplication) generically by key name, assembling a momentum-only state
dict for every layer's gate/up/down_proj and widening it ONCE reproduces
the private helper's per-tensor result exactly, without the synthetic-
dict workaround.

Fail-closed (EngagementFailure, imported from p5_ratio_audit.run_p5_audit,
never reimplemented): every one of the 60 (n_layers * 3) FF momentum
buffers being transplanted must resolve to a real, non-near-zero tensor.
Missing buffer (resolve_gate_momentum_buffer returns None) or near-zero
buffer (rms < 1e-10, the same threshold cbase_grow_rung2_event.py's own
gate-only forensic check uses) both raise -- never a silent zeros_like
substitution, which is exactly the #513 defect class this whole boundary
policy exists to never repeat.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cbase_grow_dryrun import widen_state_dict  # noqa: E402 -- reused, never reimplemented
from p5_ratio_audit.run_p5_audit import (  # noqa: E402 -- reused, never reimplemented
    EngagementFailure, resolve_gate_momentum_buffer, rms,
)

MOMENTUM_RMS_FAIL_CLOSED_THRESHOLD = 1e-10  # matches cbase_grow_rung2_event.py's own gate-only check

MOMENTUM_PUSHFORWARD_RULE_DECLARED = (
    "gate_proj/up_proj momentum buffers: row-duplication pushforward (same G as weights; "
    "eps-invariant, since only down_proj receives the #280 antisymmetric perturbation). "
    "down_proj momentum buffers: half-split-duplication pushforward at eps_sigma=0 (a "
    "momentum buffer is not itself perturbed by the #280 operator; only weights are). "
    "AdamW-routed params (embeddings/norms/head/mtp_heads): shape-invariant across the grow, "
    "no pushforward needed (net2net widening only touches Muon-routed FF tensors). "
    "Verbatim from scripts/cbase_grow_rung2_event.py's MOMENTUM_PUSHFORWARD_RULE_DECLARED."
)

BOUNDARY_POLICY = (
    "transplant-with-verified-buffer (Branch A, adjudicated: "
    "receipts/cbase-grow-rung2-event-b513-b4rerun-b3.json, transplant "
    "cos_alignment=0.9536 >= 0.82, reset cos_alignment=0.7397 in [0.70,0.78] "
    "per docs/spec/rung2-stabilize-config-respec-v1.md section 5's "
    "pre-registered rule)"
)


def transplant_muon_ff_momentum(pre_model_state: dict, pre_opt_state: dict, *,
                                 n_layers: int, lr_muon: float,
                                 eps_sigma: float = 0.0, eps_seed: int = 0) -> dict:
    """Branch-A momentum transplant for a rung boundary: resolves every
    Muon-routed FF momentum buffer (gate/up/down_proj x n_layers) from the
    real pre-grow optimizer.pt, fail-closes (EngagementFailure) on any
    missing or near-zero buffer, then pushes every resolved buffer forward
    through the SAME net2net widen_state_dict production surgery weights
    use (imported, not reimplemented).

    pre_model_state: pre-grow model state_dict (for resolve_gate_momentum_
        buffer's param-id lookup -- param id = index into this dict's keys,
        the same convention #513's fix and cbase_grow_rung2_event.py's B1M
        path both use).
    pre_opt_state: pre-grow optimizer.pt's loaded dict (Muon optimizer
        state; real on-disk convention {'muon': {'state': {int_id: {...}}}}
        or the flat {'state': {int_id: {...}}} tolerant form).
    n_layers: number of transformer layers (the same value passed to
        widen_state_dict for the weight-side surgery -- must match).
    lr_muon: the resolved (never hardcoded) Muon LR the caller's config
        actually used -- threaded straight into the return dict's
        resolved_lr_muon field, per the spec's mandatory-field requirement.
    eps_sigma, eps_seed: #280 K1 respec passthrough to widen_state_dict;
        default 0.0/0 preserves exact duplication (this rung's frozen
        production default; see widen_state_dict's own docstring).

    Returns a dict with post_grow_momentum_state_dict (the widened
    momentum buffers, same key convention as a model state_dict, ready for
    the caller to seed into the post-grow CPUOffloadOptimizer/Muon state),
    plus the two receipt fields docs/spec/rung2-stabilize-config-respec-v1.md
    section 5 makes MANDATORY: pre_buffer_rms_consumed (aggregate rms over
    every consumed pre-grow buffer, flattened+concatenated) and
    resolved_lr_muon (passthrough, never a script constant).

    Raises EngagementFailure (never returns a partial/zeroed result) if any
    buffer is missing or near-zero -- the caller writes a FAILED-ENGAGEMENT
    receipt on that raise and falls back to Branch B (reset) for that
    boundary, per the spec's own disclosed escape hatch for initial-
    training runs with no prior momentum.
    """
    import torch

    momentum_sd: dict = {}
    per_tensor_rms: dict = {}
    for i in range(n_layers):
        prefix = f"backbone_model.layers.{i}.mlp."
        for suffix in ("gate_proj.weight", "up_proj.weight", "down_proj.weight"):
            key = prefix + suffix
            buf = resolve_gate_momentum_buffer(pre_model_state, pre_opt_state, key)
            if buf is None:
                raise EngagementFailure(
                    f"rung_boundary_momentum_transplant: missing momentum buffer for "
                    f"{key!r} in the pre-grow optimizer state -- fail-closed per Branch-A "
                    f"boundary policy ({BOUNDARY_POLICY}), never a silent reset/zeros "
                    f"substitution. Caller should fall back to Branch B (explicit, "
                    f"asserted reset) for this boundary, not proceed with a partial "
                    f"transplant."
                )
            b_rms = rms(buf)
            if b_rms < MOMENTUM_RMS_FAIL_CLOSED_THRESHOLD:
                raise EngagementFailure(
                    f"rung_boundary_momentum_transplant: near-zero momentum buffer for "
                    f"{key!r} (rms={b_rms:.3e} < {MOMENTUM_RMS_FAIL_CLOSED_THRESHOLD:.0e}) "
                    f"-- fail-closed. Transplanting near-zero buffers produces a "
                    f"transplant arm indistinguishable from reset, defeating the point "
                    f"of adopting Branch A over Branch B for this boundary."
                )
            momentum_sd[key] = buf
            per_tensor_rms[key] = b_rms

    grown_momentum_sd = widen_state_dict(
        momentum_sd, n_layers=n_layers, eps_sigma=eps_sigma, eps_seed=eps_seed)

    consumed_concat = torch.cat(
        [momentum_sd[k].flatten().to(torch.float32) for k in sorted(momentum_sd)])
    pre_buffer_rms_consumed = float(torch.sqrt(torch.mean(consumed_concat ** 2)))

    return {
        "post_grow_momentum_state_dict": grown_momentum_sd,
        "pre_buffer_rms_consumed": pre_buffer_rms_consumed,
        "per_tensor_pre_buffer_rms": per_tensor_rms,
        "resolved_lr_muon": lr_muon,
        "n_layers_transplanted": n_layers,
        "n_tensors_transplanted": len(momentum_sd),
        "momentum_pushforward_rule": MOMENTUM_PUSHFORWARD_RULE_DECLARED,
        "boundary_policy": BOUNDARY_POLICY,
    }
