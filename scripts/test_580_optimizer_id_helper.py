#!/usr/bin/env python3
# EMBER_ARTIFACT_CLASS=historical_only
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU tests for issue #580 (PR A): the authoritative bidirectional
name<->id optimizer-state mapping helper (timeshare_pretrain.
build_optimizer_id_maps / split_param_groups_from_state_dict) and its two
shared-module consumers in scripts/p5_ratio_audit/run_p5_audit.py --
resolve_gate_momentum_buffer and enumerate_missing_optimizer_state_ids.

Defect class (ground-truthed via #577): GLOBAL model-state-dict ordering
(185 names) used as keys into MUON-LOCAL-keyed optimizer state dicts (140
entries, split_param_groups muon-only construction order). Fix: ONE mapping
helper, exported from the module owning split_param_groups
(timeshare_pretrain.py); both shared consumers re-implemented on it. No
site computes .index() against a state-dict key list anymore.

AC1 (property test, real model on CPU, no GPU):
  test_ac1_roundtrip_all_140_muon_entries -- builds the real v0 model,
    confirms split_param_groups produces exactly 140 muon entries, and
    round-trips name<->muon_local_id identity for all of them -- both
    directions, and confirms the ground-truth model-construction path
    (build_optimizer_id_maps(model=...)) agrees EXACTLY with the cheap
    state-dict-derived path (build_optimizer_id_maps(model_state=...),
    what every real caller -- resolve_gate_momentum_buffer,
    enumerate_missing_optimizer_state_ids -- actually uses, since none of
    them has a live model handy).
  test_ac1_ff_momentum_shape_match -- every FF tensor's (gate/up/down_proj
    x 20 layers = 60) momentum slot resolves via resolve_gate_momentum_
    buffer to a shape-matching buffer, against the REAL rung-2 seed
    checkpoint's optimizer.pt.

AC2 (0-missing verdict against the measured ground truth, #577):
  test_ac2_zero_missing_against_real_seed_checkpoint -- enumerate_missing_
    optimizer_state_ids(model_state, opt_state) against the same real seed
    checkpoint reports 0 missing (the measured ground truth: all 60 FF
    source momentum buffers present and nonzero, rms 2e-5-2e-3; the prior
    checker's 45-tensor "truncation" was a mechanical artifact of comparing
    two LOCAL id spaces against one GLOBAL-sized range, never a real gap).

Memory discipline (GPU tenanted by a live training leg; CPU-only here,
never stack multi-GB loads): the real v0 model is constructed fresh on CPU
and its OWN .state_dict() supplies model_state -- model.pt is never loaded
from disk (zero extra multi-GB file read). Only the seed checkpoint's
optimizer.pt (~2.5GB) is read from disk, exactly once, cached at module
level so AC1's shape-match test and AC2's checker test share one load.

Checkpoint (real, on-disk, read-only, gitignored models/ tree): the rung-1
seed checkpoint cbase_grow_rung2_stabilize.py's --seed-ckpt points at --
models/cbase-grow-rung/rung1-20260703T155447Z/stabilize/checkpoints/
step-00000766 -- resolved via EMBER_MODELS_ROOT (env), never guessed or
hardcoded to an absolute path (leak-gate discipline). The tests that need
it skip gracefully if it is not present on this box; the pure round-trip
property test never depends on it.
"""
from __future__ import annotations

import gc
import json
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/ -> repo root
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

try:
    import timeshare_pretrain as ts  # noqa: E402
except SystemExit as exc:
    # Current policy deliberately denies execution/import of the historical
    # sub-3B cbase trainer. Preserve that denial and report the data-dependent
    # ACs as unavailable; never let an import refusal become a false PASS.
    ts = None
    _TIMESHARE_UNAVAILABLE = str(exc)
else:
    _TIMESHARE_UNAVAILABLE = None

SEED_CKPT_RELATIVE = os.path.join(
    "models", "cbase-grow-rung", "rung1-20260703T155447Z", "stabilize", "checkpoints", "step-00000766")
SEED_FF = 16384  # pre-grow shape this checkpoint was written at (--seed-ckpt help text)
N_LAYERS = 20
N_MUON_EXPECTED = 140

_MODEL_CACHE: dict = {}
_OPT_CACHE: dict = {}


def _require_timeshare_available():
    if ts is None:
        raise unittest.SkipTest(
            "historical trainer import is execution-denied by current policy: "
            f"{_TIMESHARE_UNAVAILABLE}"
        )


def _seed_ckpt_dir():
    root = os.environ.get("EMBER_MODELS_ROOT", REPO_ROOT)
    d = os.path.join(root, SEED_CKPT_RELATIVE)
    if os.path.isfile(os.path.join(d, "optimizer.pt")):
        return d
    return None


def _ff_tensor_names():
    names = []
    for i in range(N_LAYERS):
        for part in ("gate_proj", "up_proj", "down_proj"):
            names.append(f"backbone_model.layers.{i}.mlp.{part}.weight")
    return names


def _get_model_state_and_maps():
    """Cached: construct the real v0 model on CPU once (seed FF shape),
    return (model_state, id_maps_model). Never touches disk -- the model is
    built fresh from configs/v0-pretrain-config.json, so this never depends
    on the gitignored real-checkpoint tree being present."""
    _require_timeshare_available()
    if "result" in _MODEL_CACHE:
        return _MODEL_CACHE["result"]
    with open(os.path.join(REPO_ROOT, "configs", "v0-pretrain-config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    model, _vocab, _hidden, _n_mtp = ts.build_v0_model(
        cfg, live=True, device="cpu", intermediate_override=SEED_FF)
    id_maps_model = ts.build_optimizer_id_maps(model=model)
    model_state = model.state_dict()  # never loads model.pt from disk -- zero extra file I/O
    del model
    gc.collect()
    _MODEL_CACHE["result"] = (model_state, id_maps_model)
    return _MODEL_CACHE["result"]


def _get_seed_opt_state():
    """Cached: load the real seed checkpoint's optimizer.pt once (~2.5GB),
    or None if the gitignored models/ tree is not present on this box."""
    if "result" in _OPT_CACHE:
        return _OPT_CACHE["result"]
    ckpt_dir = _seed_ckpt_dir()
    if ckpt_dir is None:
        _OPT_CACHE["result"] = None
        return None
    import torch
    opt_state = torch.load(os.path.join(ckpt_dir, "optimizer.pt"), map_location="cpu", weights_only=True)
    _OPT_CACHE["result"] = opt_state
    return opt_state


def test_ac1_roundtrip_all_140_muon_entries():
    """AC1 (property test): construct the real model on CPU, confirm
    split_param_groups produces exactly 140 muon entries, and round-trip
    name<->muon_local_id identity for all of them -- and confirm the
    ground-truth model-construction path agrees exactly with the cheap
    state-dict-derived path every real caller actually uses."""
    model_state, id_maps_model = _get_model_state_and_maps()

    n_muon = len(id_maps_model["muon_name_to_id"])
    assert n_muon == N_MUON_EXPECTED, (
        f"[ac1-roundtrip] FAIL: split_param_groups produced {n_muon} muon entries, "
        f"expected {N_MUON_EXPECTED}")

    id_maps_state = ts.build_optimizer_id_maps(model_state=model_state)
    assert id_maps_model["muon_name_to_id"] == id_maps_state["muon_name_to_id"], (
        "[ac1-roundtrip] FAIL: ground-truth model-path muon_name_to_id diverges from the "
        "cheap state-dict-derived path -- the two conventions are not provably identical")

    for name, local_id in id_maps_model["muon_name_to_id"].items():
        assert id_maps_model["muon_id_to_name"][local_id] == name, (
            f"[ac1-roundtrip] FAIL: round-trip broken for {name!r} -> id {local_id} -> "
            f"{id_maps_model['muon_id_to_name'][local_id]!r}")
    for local_id, name in id_maps_model["muon_id_to_name"].items():
        assert id_maps_model["muon_name_to_id"][name] == local_id, (
            f"[ac1-roundtrip] FAIL: reverse round-trip broken for id {local_id} -> {name!r}")

    print(f"[ac1-roundtrip] round-trip name<->muon_local_id identity verified for all "
          f"{n_muon} muon entries; model-construction path == state-dict-derived path")
    print("[ac1-roundtrip] PASS")
    return True


def test_ac1_ff_momentum_shape_match():
    """AC1 (second half): every FF tensor's (gate/up/down_proj x 20 layers =
    60) momentum slot resolves via resolve_gate_momentum_buffer to a
    shape-matching buffer, against the real rung-2 seed checkpoint."""
    opt_state = _get_seed_opt_state()
    if opt_state is None:
        raise unittest.SkipTest(
            "real seed checkpoint not present on this box "
            f"(gitignored models/ tree; looked under {SEED_CKPT_RELATIVE!r}, "
            "set EMBER_MODELS_ROOT to override)")

    from p5_ratio_audit.run_p5_audit import resolve_gate_momentum_buffer

    model_state, _id_maps_model = _get_model_state_and_maps()
    checked = 0
    for name in _ff_tensor_names():
        assert name in model_state, f"[ac1-ff-shape] FAIL: expected FF tensor {name!r} missing from model_state"
        buf = resolve_gate_momentum_buffer(model_state, opt_state, name)
        assert buf is not None, f"[ac1-ff-shape] FAIL: {name!r} momentum buffer did not resolve (None)"
        expected_shape = tuple(model_state[name].shape)
        assert tuple(buf.shape) == expected_shape, (
            f"[ac1-ff-shape] FAIL: {name!r} momentum buffer shape {tuple(buf.shape)} != "
            f"model shape {expected_shape}")
        checked += 1
    assert checked == 60, f"[ac1-ff-shape] FAIL: expected 60 FF tensors checked, got {checked}"
    print(f"[ac1-ff-shape] all {checked} FF tensors (gate/up/down_proj x {N_LAYERS} layers) "
          f"resolve to shape-matching momentum buffers against the real seed checkpoint")
    print("[ac1-ff-shape] PASS")
    return True


def test_ac2_zero_missing_against_real_seed_checkpoint():
    """AC2: enumerate_missing_optimizer_state_ids re-implemented on the
    helper, run against the real rung-2 seed checkpoint, reports 0 missing
    -- the measured ground truth (#577: all 60 FF source momentum buffers
    present and nonzero, rms 2e-5-2e-3; the prior checker's 45-tensor
    "truncation" was a mechanical artifact of the id-space mismatch, never
    a real gap)."""
    opt_state = _get_seed_opt_state()
    if opt_state is None:
        raise unittest.SkipTest(
            "real seed checkpoint not present on this box "
            f"(gitignored models/ tree; looked under {SEED_CKPT_RELATIVE!r}, "
            "set EMBER_MODELS_ROOT to override)")

    from p5_ratio_audit.run_p5_audit import enumerate_missing_optimizer_state_ids

    model_state, _id_maps_model = _get_model_state_and_maps()
    missing = enumerate_missing_optimizer_state_ids(model_state, opt_state)
    print(f"[ac2] enumerate_missing_optimizer_state_ids reports {len(missing)} missing "
          f"(sample={sorted(missing)[:10]})")
    assert missing == set(), (
        f"[ac2] FAIL: expected 0 missing, got {len(missing)}: {sorted(missing)[:10]}")
    print("[ac2] PASS")
    return True


if __name__ == "__main__":
    tests = [
        test_ac1_roundtrip_all_140_muon_entries,
        test_ac1_ff_momentum_shape_match,
        test_ac2_zero_missing_against_real_seed_checkpoint,
    ]
    failures = []
    skips = []
    for t in tests:
        try:
            ok = t()
            if not ok:
                failures.append(t.__name__)
        except unittest.SkipTest as e:
            print(f"[{t.__name__}] SKIP: {e}")
            skips.append(t.__name__)
        except Exception as e:
            print(f"[{t.__name__}] ERROR: {e}")
            import traceback
            traceback.print_exc()
            failures.append(t.__name__)

    if failures:
        print(f"\nISSUE_580_OPTIMIZER_ID_HELPER_TEST_FAIL: {failures}")
        sys.exit(1)
    if skips:
        print(f"\nISSUE_580_OPTIMIZER_ID_HELPER_TEST_INCOMPLETE: skipped={skips}")
        sys.exit(2)
    print("\nISSUE_580_OPTIMIZER_ID_HELPER_TEST_PASS")
    sys.exit(0)
