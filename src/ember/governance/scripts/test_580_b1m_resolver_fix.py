#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU tests for issue #580 site 4: cbase_grow_rung2_event.py's phase_b1m
had its OWN independent, hand-rolled GLOBAL-indexed-into-MUON-LOCAL lookup
for the gate_proj pre-grow momentum buffer (line ~751, prior to this fix),
never routed through the shared resolve_gate_momentum_buffer /
build_optimizer_id_maps helper PR #587 landed for #580's other two sites.

Follows the #587 test template (test_p5_513_resolver_fix.py): loads the
real on-disk checkpoint directly, no model construction / forward passes,
CPU-only, gracefully skips if the (gitignored, ~GB-scale) checkpoint tree
isn't present on this box.

Defect (site 4, found by the #580 corrected-buffered-re-run lane tracing
what B3's TRANSPLANT arm actually consumes -- not just B3's own diagnostic
field): phase_b1m computed
  gate_param_id = seed_param_names.index(gate_key)   # GLOBAL model-state id
  pre_momentum = seed_optimizer_state["muon"]["state"][gate_param_id][...]
On the b1-snapshot checkpoint this aliases gate_proj's correct muon-local id
(4) to global id 5 (one AdamW-routed param interposes ahead of it in the
global ordering), silently resolving up_proj's momentum buffer instead
(rms 3.6057e-4) rather than gate_proj's real buffer (rms 3.815260e-04).
Direct proof this was live: the b1m cache this fed (b513-b4rerun run,
predates PR #587) measured rms=3.6057e-4 on disk -- the aliased value.

Fix: phase_b1m now calls resolve_gate_momentum_buffer(seed_model_state,
seed_optimizer_state, gate_key) directly -- the same call B3's own
pre_buffer_rms_consumed diagnostic field already used, so both are now
provably the same value by construction, not by coincidence.
"""
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

GATE_KEY = "backbone_model.layers.0.mlp.gate_proj.weight"

# Real on-disk checkpoint (gitignored, models/ tree) -- the intact
# 2026-07-08 rung2-event 'real' run's b1-snapshot (grow-rung2-20260708-real),
# NOT b513-b4rerun (its cache is poisoned and its snapshot's optimizer.pt is
# gone -- dead for measurement per the 2026-07-10 ruling, kept only as
# evidence). Relative suffix only (leak-gate discipline).
REAL_CKPT_RELATIVE = os.path.join(
    "models", "cbase-grow-rung", "rung2-event-grow-rung2-20260708-real", "b1-snapshot")
EXPECTED_CORRECT_RMS = 3.815260e-04  # PR #587's own flagged value; #580 forensic receipt confirms it
EXPECTED_ALIASED_RMS = 3.6057e-4     # the OLD bug's silently-wrong result (up_proj, not gate_proj)
TOLERANCE = 3e-7


def _real_ckpt_dir():
    root = os.environ.get("EMBER_MODELS_ROOT", REPO_ROOT)
    d = os.path.join(root, REAL_CKPT_RELATIVE)
    if os.path.isfile(os.path.join(d, "model.pt")) and os.path.isfile(os.path.join(d, "optimizer.pt")):
        return d
    return None


def test_a_b1m_resolver_matches_shared_helper_not_the_old_alias():
    """phase_b1m's fixed pre_momentum resolution (now literally
    resolve_gate_momentum_buffer(seed_model_state, seed_optimizer_state,
    gate_key), mirrored here rather than importing the whole phase function
    to avoid a full model construction / forward-pass cost) returns the
    correct nonzero gate_proj buffer, matching PR #587's own value -- and
    is DIFFERENT from what the OLD site-4 inline global-indexed lookup
    would have silently returned (the up_proj alias)."""
    ckpt_dir = _real_ckpt_dir()
    if ckpt_dir is None:
        print("[test_a] SKIP: real checkpoint tree not present on this box "
              f"(gitignored models/ tree; looked under {REAL_CKPT_RELATIVE!r})")
        return True

    import torch
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
    resolve_gate_momentum_buffer = getattr(_ember_ba82af0721d80c9f_module, 'resolve_gate_momentum_buffer')
    rms = getattr(_ember_ba82af0721d80c9f_module, 'rms')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py

    seed_model_state = torch.load(os.path.join(ckpt_dir, "model.pt"), map_location="cpu", weights_only=True)
    seed_optimizer_state = torch.load(os.path.join(ckpt_dir, "optimizer.pt"), map_location="cpu", weights_only=True)

    # FIXED path: exactly what phase_b1m now calls.
    fixed_pre_momentum = resolve_gate_momentum_buffer(seed_model_state, seed_optimizer_state, GATE_KEY)
    assert fixed_pre_momentum is not None, "[test_a] FAIL: fixed resolver returned None against the real checkpoint"
    fixed_rms = rms(fixed_pre_momentum)
    print(f"[test_a] fixed phase_b1m resolution rms={fixed_rms:.6e} (expected ~{EXPECTED_CORRECT_RMS:.6e})")
    assert abs(fixed_rms - EXPECTED_CORRECT_RMS) < TOLERANCE, (
        f"[test_a] FAIL: fixed rms {fixed_rms:.6e} does not match the corrected reference "
        f"{EXPECTED_CORRECT_RMS:.6e} within tolerance")

    # OLD (site-4-defective) path, replicated verbatim from before this fix,
    # for contrast -- must resolve to a DIFFERENT (wrong, aliased) tensor,
    # never silently equal to the fixed path's result.
    seed_param_names = list(seed_model_state.keys())
    old_gate_param_id = seed_param_names.index(GATE_KEY) if GATE_KEY in seed_param_names else None
    old_pre_momentum = None
    if old_gate_param_id is not None:
        old_pre_momentum = seed_optimizer_state.get("muon", {}).get("state", {}).get(
            old_gate_param_id, {}).get("momentum_buffer")
    assert old_pre_momentum is not None, "[test_a] FAIL: OLD path unexpectedly found nothing (fixture drift?)"
    old_rms = rms(old_pre_momentum)
    print(f"[test_a] OLD (pre-fix) site-4 resolution rms={old_rms:.6e} (expected the up_proj alias ~{EXPECTED_ALIASED_RMS:.4e})")
    assert abs(old_rms - EXPECTED_ALIASED_RMS) < TOLERANCE, (
        f"[test_a] FAIL: OLD path rms {old_rms:.6e} does not match the known aliased reference "
        f"{EXPECTED_ALIASED_RMS:.4e} -- the regression fixture itself may have drifted")
    assert abs(fixed_rms - old_rms) > 1e-6, (
        "[test_a] FAIL: fixed and OLD resolutions coincide -- the regression guard is not "
        "distinguishing the two paths (fixture no longer has an AdamW param interposing "
        "ahead of gate_proj in the global ordering)")

    print("[test_a] PASS: fixed path == corrected reference, OLD site-4 path == known aliased "
          "(wrong) value, and the two are provably different")
    return True


def _b1m_none_handling(model_state, opt_state, gate_key, snapshot_dir):
    """Mirrors cbase_grow_rung2_event.py's phase_b1m None-handling verbatim
    (gate-review amendment, 2026-07-10): the fixed block no longer
    silently substitutes torch.zeros_like on a None resolution -- it fails
    closed immediately, naming gate_key + snapshot_dir. Synthetic, no
    real checkpoint needed, so this test never skips."""
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
    resolve_gate_momentum_buffer = getattr(_ember_ba82af0721d80c9f_module, 'resolve_gate_momentum_buffer')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py
    pre_momentum = resolve_gate_momentum_buffer(model_state, opt_state, gate_key)
    if pre_momentum is None:
        raise SystemExit(
            f"CBASE-GROW-RUNG2-EVENT-B1M: fail-closed refusal -- resolve_gate_momentum_buffer "
            f"found no momentum buffer for {gate_key!r} in {snapshot_dir}'s optimizer.pt. Never "
            f"silently substitutes zeros_like for a missing resolution. If this checkpoint "
            f"genuinely has no prior optimizer momentum (initial training, no prior optimizer "
            f"state), that IS a real N/A for the transplant arm (structural impossibility, not a "
            f"defect) -- but it must surface as this explicit refusal, never an implicit "
            f"fallback. See issue #466 / #449 / #452 / #580.")
    return pre_momentum


def test_b_none_resolution_fails_closed_never_zeros():
    """A synthetic checkpoint where gate_key's muon entry is missing (the
    real on-disk shape of 'no prior momentum', e.g. initial training)
    resolves to None, and phase_b1m's fixed None-handling raises
    SystemExit naming the gate key -- never silently substitutes
    torch.zeros_like and lets the caller proceed with a fabricated
    zero-momentum tensor (the exact landmine the #580 gate review flagged:
    a silent zero-momentum transplant that looks like a real measurement).
    """
    import torch

    gate_key = "backbone_model.layers.0.mlp.gate_proj.weight"
    up_key = "backbone_model.layers.0.mlp.up_proj.weight"
    model_state = {
        gate_key: torch.randn(8, 4),
        up_key: torch.randn(8, 4),
    }
    # opt_state has NO entry for gate_key's muon-local id at all (the
    # on-disk shape of "this parameter never accumulated momentum" --
    # resolve_gate_momentum_buffer's own None-returning path).
    opt_state = {"muon": {"state": {}}}

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
    resolve_gate_momentum_buffer = getattr(_ember_ba82af0721d80c9f_module, 'resolve_gate_momentum_buffer')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py
    pre_check = resolve_gate_momentum_buffer(model_state, opt_state, gate_key)
    assert pre_check is None, "[test_b] FAIL: fixture does not actually produce a None resolution"

    raised = False
    try:
        _b1m_none_handling(model_state, opt_state, gate_key, "models/fake-snapshot")
    except SystemExit as e:
        raised = True
        msg = str(e)
        assert gate_key in msg, f"[test_b] FAIL: SystemExit message does not name gate_key: {msg}"
        assert "zeros_like" in msg or "Never silently substitutes" in msg, (
            f"[test_b] FAIL: SystemExit message does not disclose the never-zeros-fallback "
            f"guarantee: {msg}")
    assert raised, "[test_b] FAIL: None resolution did not raise SystemExit -- silent fallback regression"
    print("[test_b] PASS: None resolution raised SystemExit naming the gate key, no zeros_like fallback")
    return True


if __name__ == "__main__":
    tests = [
        test_a_b1m_resolver_matches_shared_helper_not_the_old_alias,
        test_b_none_resolution_fails_closed_never_zeros,
    ]
    failures = []
    for t in tests:
        try:
            ok = t()
            if not ok:
                failures.append(t.__name__)
        except Exception as e:
            print(f"[{t.__name__}] ERROR: {e}")
            import traceback
            traceback.print_exc()
            failures.append(t.__name__)

    if failures:
        print(f"\nTEST_580_B1M_RESOLVER_FIX_FAIL: {failures}")
        sys.exit(1)
    print("\nTEST_580_B1M_RESOLVER_FIX_PASS")
    sys.exit(0)
