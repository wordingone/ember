#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
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
(src/ember/governance/scripts/cbase_grow_live.py, scripts/cbase_grow_rung.py) has ANY momentum
transplant wiring at all -- cbase_grow_live.py's own docstring says so
explicitly ("The pre-grow optimizer state cannot be replayed into the
post-grow optimizer ... reset_optimizer_on_resume=True skips that load").
Production defaults to Branch B (reset) by omission, not by adjudicated
law. The only existing transplant + fail-closed code
(src/ember/governance/scripts/cbase_grow_rung2_event.py's `_pushforward_gate_momentum` +
src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py's `EngagementFailure`) lives in the
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
# issue2015 exact-local-import:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py
import importlib.util as _ember_ba82af0721d80c9f_importlib
import sys as _ember_ba82af0721d80c9f_sys
from pathlib import Path as _ember_ba82af0721d80c9f_Path
_ember_ba82af0721d80c9f_path = _ember_ba82af0721d80c9f_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'p5_ratio_audit', 'run_p5_audit.py')
if not _ember_ba82af0721d80c9f_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
_ember_ba82af0721d80c9f_aliases = ('_ember_issue2015_ba82af0721d80c9f', 'p5_ratio_audit.run_p5_audit', 'run_p5_audit', 'scripts.p5_ratio_audit.run_p5_audit')
_ember_ba82af0721d80c9f_existing = []
for _ember_ba82af0721d80c9f_alias in _ember_ba82af0721d80c9f_aliases:
    _ember_ba82af0721d80c9f_candidate = _ember_ba82af0721d80c9f_sys.modules.get(_ember_ba82af0721d80c9f_alias)
    if _ember_ba82af0721d80c9f_candidate is not None and all(_ember_ba82af0721d80c9f_candidate is not item for item in _ember_ba82af0721d80c9f_existing):
        _ember_ba82af0721d80c9f_existing.append(_ember_ba82af0721d80c9f_candidate)
if len(_ember_ba82af0721d80c9f_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
if _ember_ba82af0721d80c9f_existing:
    _ember_ba82af0721d80c9f_module = _ember_ba82af0721d80c9f_existing[0]
    _ember_ba82af0721d80c9f_observed = getattr(_ember_ba82af0721d80c9f_module, '__file__', None)
    if _ember_ba82af0721d80c9f_observed is None or _ember_ba82af0721d80c9f_Path(_ember_ba82af0721d80c9f_observed).resolve() != _ember_ba82af0721d80c9f_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
else:
    _ember_ba82af0721d80c9f_spec = _ember_ba82af0721d80c9f_importlib.spec_from_file_location('_ember_issue2015_ba82af0721d80c9f', _ember_ba82af0721d80c9f_path)
    if _ember_ba82af0721d80c9f_spec is None or _ember_ba82af0721d80c9f_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
    _ember_ba82af0721d80c9f_module = _ember_ba82af0721d80c9f_importlib.module_from_spec(_ember_ba82af0721d80c9f_spec)
    for _ember_ba82af0721d80c9f_alias in _ember_ba82af0721d80c9f_aliases:
        _ember_ba82af0721d80c9f_prior = _ember_ba82af0721d80c9f_sys.modules.get(_ember_ba82af0721d80c9f_alias)
        if _ember_ba82af0721d80c9f_prior is not None and _ember_ba82af0721d80c9f_prior is not _ember_ba82af0721d80c9f_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
        _ember_ba82af0721d80c9f_sys.modules[_ember_ba82af0721d80c9f_alias] = _ember_ba82af0721d80c9f_module
    try:
        _ember_ba82af0721d80c9f_spec.loader.exec_module(_ember_ba82af0721d80c9f_module)
    except BaseException:
        for _ember_ba82af0721d80c9f_alias in _ember_ba82af0721d80c9f_aliases:
            if _ember_ba82af0721d80c9f_sys.modules.get(_ember_ba82af0721d80c9f_alias) is _ember_ba82af0721d80c9f_module:
                _ember_ba82af0721d80c9f_sys.modules.pop(_ember_ba82af0721d80c9f_alias, None)
        raise
for _ember_ba82af0721d80c9f_alias in _ember_ba82af0721d80c9f_aliases:
    _ember_ba82af0721d80c9f_prior = _ember_ba82af0721d80c9f_sys.modules.get(_ember_ba82af0721d80c9f_alias)
    if _ember_ba82af0721d80c9f_prior is not None and _ember_ba82af0721d80c9f_prior is not _ember_ba82af0721d80c9f_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
    _ember_ba82af0721d80c9f_sys.modules[_ember_ba82af0721d80c9f_alias] = _ember_ba82af0721d80c9f_module
EngagementFailure = getattr(_ember_ba82af0721d80c9f_module, 'EngagementFailure')
resolve_gate_momentum_buffer = getattr(_ember_ba82af0721d80c9f_module, 'resolve_gate_momentum_buffer')
rms = getattr(_ember_ba82af0721d80c9f_module, 'rms')
# issue2015 exact-local-import-end:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py

MOMENTUM_RMS_FAIL_CLOSED_THRESHOLD = 1e-10  # matches cbase_grow_rung2_event.py's own gate-only check

MOMENTUM_PUSHFORWARD_RULE_DECLARED = (
    "gate_proj/up_proj momentum buffers: row-duplication pushforward (same G as weights; "
    "eps-invariant, since only down_proj receives the #280 antisymmetric perturbation). "
    "down_proj momentum buffers: half-split-duplication pushforward at eps_sigma=0 (a "
    "momentum buffer is not itself perturbed by the #280 operator; only weights are). "
    "AdamW-routed params (embeddings/norms/head/mtp_heads): shape-invariant across the grow, "
    "no pushforward needed (net2net widening only touches Muon-routed FF tensors). "
    "Verbatim from src/ember/governance/scripts/cbase_grow_rung2_event.py's MOMENTUM_PUSHFORWARD_RULE_DECLARED."
)

BOUNDARY_POLICY = (
    "transplant-with-verified-buffer (Branch A, adjudicated: "
    "receipts/cbase-grow-rung2-event-b513-b4rerun-b3.json, transplant "
    "cos_alignment=0.9536 >= 0.82, reset cos_alignment=0.7397 in [0.70,0.78] "
    "per docs/domains/governance/spec/rung2-stabilize-config-respec-v1.md section 5's "
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
    plus the two receipt fields docs/domains/governance/spec/rung2-stabilize-config-respec-v1.md
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
