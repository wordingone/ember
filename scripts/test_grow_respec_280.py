#!/usr/bin/env python3
"""Unit tests for the #280 K1 respec (antisymmetric out-proj perturbation
grow-operator cure) at CPU/toy-fixture scale. Written FIRST per the TDD
floor (team-lead ratification, garmbuild113 lane, issue #113/#280).

Covers, at toy scale (no GPU, no real checkpoint, no training launch):
  1. widen_state_dict(eps_sigma=0.0) is BYTE-IDENTICAL to the pre-respec
     exact-duplication operator -- the positive control that reproduces
     #280's capacity-null finding (backward compatibility for every
     existing caller that has not opted into the cure).
  2. Under exact duplication, twin cosine == 1.0 exactly (down_proj AND
     gate/up) -- the null finding, reproduced structurally, not asserted.
  3. Under eps_sigma > 0, down_proj twin cosine measurably breaks below the
     capacity-null point and matches the derived closed-form band; gate/up
     rows stay EXACTLY tied at construction (perturbation is down_proj-only
     -- ties break via gradient divergence from step 1, never at t=0).
  4. A second, larger eps_sigma (the tick-6-mandated sensitivity grid cell)
     pushes the cosine further down, monotonically.
  5. Function preservation holds EXACTLY (fp_diff within PASS_TOL) on a
     real tiny transformer forward pass, for BOTH eps_sigma=0 and eps_sigma>0
     -- the load-bearing correctness claim of the antisymmetric mechanism.
  6. checkpoint_identity() never collapses two distinct checkpoints that
     happen to share a step number into the same reference (closes the
     #280-comment-1-cited step-00000730 collision class structurally).
  7. schedule_position_block() reuses timeshare_pretrain.wsd_lr_frac
     directly (reuse, never reimplement) and reports a step_fraction, never
     a bare step; sanity-checked against rung-1's own disclosed schedule
     position (steps 730-766 of total_steps=449651, ~16-17% base LR).
  8. expected_twin_cosine() is a pure closed-form function of eps_sigma
     alone (no torch import needed to test it) with the correct limits.

Usage:
  python scripts/test_grow_respec_280.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import torch  # noqa: E402

from grow_respec_280 import (  # noqa: E402
    twin_cosine_audit, expected_twin_cosine, checkpoint_identity,
    schedule_position_block,
)
from cbase_grow_dryrun import widen_state_dict  # noqa: E402


def _toy_state_dict(n_layers: int, hidden: int, ff_seed: int, seed: int = 0) -> dict:
    g = torch.Generator().manual_seed(seed)
    sd = {}
    for i in range(n_layers):
        p = f"backbone_model.layers.{i}.mlp."
        sd[p + "gate_proj.weight"] = torch.randn(ff_seed, hidden, generator=g)
        sd[p + "up_proj.weight"] = torch.randn(ff_seed, hidden, generator=g)
        sd[p + "down_proj.weight"] = torch.randn(hidden, ff_seed, generator=g)
    return sd


def test_eps_zero_is_byte_identical_to_pre_respec_operator():
    print("Test 1: eps_sigma=0.0 backward-compat (byte-identical to exact duplication)...")
    sd = _toy_state_dict(n_layers=2, hidden=16, ff_seed=6, seed=1)
    n_layers = 2

    grown_new = widen_state_dict(sd, n_layers, eps_sigma=0.0)

    # Reference: the ORIGINAL (pre-respec) surgery math, reimplemented here
    # ONLY as an independent oracle for this test -- never imported as
    # production code.
    ref = dict(sd)
    for i in range(n_layers):
        p = f"backbone_model.layers.{i}.mlp."
        g_, u_, d_ = sd[p + "gate_proj.weight"], sd[p + "up_proj.weight"], sd[p + "down_proj.weight"]
        ref[p + "gate_proj.weight"] = torch.cat([g_, g_], dim=0)
        ref[p + "up_proj.weight"] = torch.cat([u_, u_], dim=0)
        ref[p + "down_proj.weight"] = torch.cat([d_ * 0.5, d_ * 0.5], dim=1)

    for k in ref:
        assert torch.equal(ref[k], grown_new[k]), f"eps=0.0 diverged from exact-dup oracle at {k}"
    print("  PASS: eps_sigma=0.0 reproduces the exact-duplication operator bit-for-bit.")


def test_exact_duplication_twin_cosine_is_exactly_one():
    print("Test 2: exact duplication (eps_sigma=0.0) -> twin cosine == 1.0 (the null finding)...")
    n_layers, hidden, ff_seed = 2, 16, 6
    sd = _toy_state_dict(n_layers, hidden, ff_seed, seed=2)
    grown = widen_state_dict(sd, n_layers, eps_sigma=0.0)

    audit = twin_cosine_audit(grown, n_layers, ff_seed)
    assert abs(audit["down_proj_twin_cosine"]["median"] - 1.0) < 1e-6, audit["down_proj_twin_cosine"]
    assert abs(audit["down_proj_twin_cosine"]["min"] - 1.0) < 1e-6, audit["down_proj_twin_cosine"]
    assert abs(audit["gate_up_twin_cosine"]["median"] - 1.0) < 1e-6, audit["gate_up_twin_cosine"]
    print(f"  PASS: median down_proj twin cosine={audit['down_proj_twin_cosine']['median']:.8f}, "
          f"gate/up={audit['gate_up_twin_cosine']['median']:.8f} (ties never broken -- reproduces #280).")


def test_eps_perturbation_breaks_symmetry_and_matches_derived_band():
    print("Test 3: eps_sigma>0 breaks down_proj twin symmetry, gate/up stay exact at t=0...")
    n_layers, hidden, ff_seed = 3, 32, 10
    sd = _toy_state_dict(n_layers, hidden, ff_seed, seed=3)
    eps_sigma = 0.08
    grown = widen_state_dict(sd, n_layers, eps_sigma=eps_sigma, eps_seed=42)

    audit = twin_cosine_audit(grown, n_layers, ff_seed)
    measured = audit["down_proj_twin_cosine"]["median"]
    expected = expected_twin_cosine(eps_sigma)

    assert measured < 0.999, f"down_proj twin cosine did not break below capacity-null band: {measured}"
    rel_err = abs(measured - expected) / abs(1.0 - expected)
    assert rel_err < 0.35, (
        f"measured cosine {measured:.6f} too far from derived band {expected:.6f} "
        f"(rel_err={rel_err:.3f}, tolerance 0.35 -- leading-order approximation)")
    # gate/up rows are the IN-PROJ side; the mechanism is down_proj-only, so
    # ties there must remain EXACT at construction (t=0) -- divergence there
    # is a gradient-time effect, never a construction-time one.
    assert abs(audit["gate_up_twin_cosine"]["median"] - 1.0) < 1e-6, audit["gate_up_twin_cosine"]
    print(f"  PASS: measured down_proj median cosine={measured:.6f}, "
          f"derived band={expected:.6f} (rel_err={rel_err:.3f}); gate/up exact at t=0.")


def test_second_noise_scale_sensitivity_grid_cell():
    print("Test 4: sensitivity grid -- larger eps_sigma pushes cosine further down (tick-6 item 2)...")
    n_layers, hidden, ff_seed = 3, 32, 10
    sd = _toy_state_dict(n_layers, hidden, ff_seed, seed=4)

    eps_a, eps_b = 0.03, 0.12
    grown_a = widen_state_dict(sd, n_layers, eps_sigma=eps_a, eps_seed=7)
    grown_b = widen_state_dict(sd, n_layers, eps_sigma=eps_b, eps_seed=7)

    cos_a = twin_cosine_audit(grown_a, n_layers, ff_seed)["down_proj_twin_cosine"]["median"]
    cos_b = twin_cosine_audit(grown_b, n_layers, ff_seed)["down_proj_twin_cosine"]["median"]

    assert cos_b < cos_a, f"larger eps_sigma ({eps_b}) did not push cosine lower: {cos_a=} {cos_b=}"
    for eps, cos in ((eps_a, cos_a), (eps_b, cos_b)):
        expected = expected_twin_cosine(eps)
        rel_err = abs(cos - expected) / abs(1.0 - expected)
        assert rel_err < 0.35, f"eps_sigma={eps}: measured={cos:.6f} expected={expected:.6f} rel_err={rel_err:.3f}"
    print(f"  PASS: eps_sigma={eps_a}->cos={cos_a:.6f}, eps_sigma={eps_b}->cos={cos_b:.6f} (monotone, both banded).")


def test_function_preservation_exact_with_and_without_eps():
    print("Test 5: function preservation holds exactly, eps_sigma=0 AND eps_sigma>0 (real tiny model)...")
    from cbase_grow_dryrun import build_model

    cfg_model = {"vocab": 64, "hidden": 16, "layers": 2, "heads": 2, "seq": 32, "tied_embeddings": False}
    n_mtp = 1
    ff_seed = 8
    ff_grown = ff_seed * 2
    torch.manual_seed(123)

    seed_model = build_model(cfg_model, n_mtp, ff_seed)
    sd = {k: v.clone() for k, v in seed_model.state_dict().items()}

    ids = torch.randint(0, cfg_model["vocab"], (2, 6), generator=torch.Generator().manual_seed(9))

    seed_model.eval()
    logits_pre = seed_model.logits(ids)

    for label, eps_sigma in (("eps=0.0", 0.0), ("eps=0.05", 0.05)):
        grown_sd = widen_state_dict(sd, cfg_model["layers"], eps_sigma=eps_sigma, eps_seed=11)
        grown_model = build_model(cfg_model, n_mtp, ff_grown)
        missing, unexpected = grown_model.load_state_dict(grown_sd, strict=False)
        real_missing = [k for k in missing if k != "head.weight"]
        assert not real_missing and not unexpected, f"{label}: load mismatch missing={real_missing} unexpected={unexpected}"
        grown_model.eval()
        logits_post = grown_model.logits(ids)
        fp_diff = float((logits_post - logits_pre).abs().max())
        assert fp_diff <= 1e-4, f"{label}: function preservation FAILED fp_diff={fp_diff:.3e}"
        print(f"  PASS ({label}): fp_diff={fp_diff:.3e} <= 1e-4")


def test_checkpoint_identity_no_collision(tmp_path_factory=None):
    print("Test 6: checkpoint_identity never collapses two same-step checkpoints (collision class)...")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ckpt_a = tmp / "live-20260703T053225Z" / "post" / "checkpoints" / "step-00000730"
        ckpt_b = tmp / "rung1-20260703T155447Z" / "checkpoints" / "step-00000730"
        ckpt_a.mkdir(parents=True)
        ckpt_b.mkdir(parents=True)
        (ckpt_a / "model.pt").write_bytes(b"live-run-bytes-AAAA")
        (ckpt_b / "model.pt").write_bytes(b"rung1-seed-bytes-BBBB")

        id_a = checkpoint_identity(ckpt_a, segment_id="cbase-grow-live-post", step=730)
        id_b = checkpoint_identity(ckpt_b, segment_id="cbase-grow-rung1-seed", step=730)

        assert id_a["step"] == id_b["step"] == 730, "test setup: both must share the colliding step number"
        assert id_a["model_pt_sha256"] != id_b["model_pt_sha256"], "sha256 must disambiguate same-step checkpoints"
        assert id_a["segment_id"] != id_b["segment_id"]
        assert id_a["path"] != id_b["path"]
        # every identity must carry BOTH path and sha256 -- never a bare step
        for ident in (id_a, id_b):
            assert ident["path"] and ident["model_pt_sha256"] and ident["segment_id"]
        print(f"  PASS: step=730 collision disambiguated -- sha_a={id_a['model_pt_sha256'][:12]}... "
              f"sha_b={id_b['model_pt_sha256'][:12]}...")


def test_schedule_position_reuses_wsd_lr_frac():
    print("Test 7: schedule_position_block reuses timeshare_pretrain.wsd_lr_frac (reuse, never reimplement)...")
    from timeshare_pretrain import wsd_lr_frac

    step, total_steps = 750, 449651
    warmup_frac, stable_frac, decay_floor_frac = 0.01, 0.85, 0.10

    block = schedule_position_block(step, total_steps, warmup_frac, stable_frac, decay_floor_frac)
    direct = wsd_lr_frac(step, total_steps, warmup_frac, stable_frac, decay_floor_frac)

    assert block["wsd_lr_frac"] == direct, "schedule_position_block must call wsd_lr_frac directly, not reimplement it"
    assert block["step_fraction"] == step / total_steps, "must report a step FRACTION, never a bare step"
    assert "step" in block and "total_steps" in block

    # sanity-check against rung-1's own disclosed schedule position (tick-6
    # item 6: "the executed rung-1 event ran at 16-17% base LR (steps
    # 730-766 of total_steps=449651, deep warmup)")
    rung1_block = schedule_position_block(730, 449651, warmup_frac, stable_frac, decay_floor_frac)
    assert 0.10 <= rung1_block["wsd_lr_frac"] <= 0.20, (
        f"rung-1's own disclosed 16-17% base-LR position not reproduced: {rung1_block['wsd_lr_frac']}")
    print(f"  PASS: step_fraction={block['step_fraction']:.6f}, wsd_lr_frac={block['wsd_lr_frac']:.4f}; "
          f"rung-1 sanity check wsd_lr_frac={rung1_block['wsd_lr_frac']:.4f} in [0.10, 0.20].")


def test_expected_twin_cosine_pure_math_limits():
    print("Test 8: expected_twin_cosine closed-form limits (no torch needed)...")
    assert expected_twin_cosine(0.0) == 1.0
    prev = 1.0
    for s in (0.01, 0.05, 0.1, 0.2, 0.4):
        v = expected_twin_cosine(s)
        assert v < prev, f"expected_twin_cosine must be strictly decreasing in eps_sigma: {prev} -> {v} at sigma={s}"
        assert -1.0 <= v <= 1.0, f"expected_twin_cosine out of cosine range at sigma={s}: {v}"
        prev = v
    print("  PASS: expected_twin_cosine(0)=1.0, strictly decreasing, stays within [-1, 1].")


def main() -> int:
    tests = [
        test_eps_zero_is_byte_identical_to_pre_respec_operator,
        test_exact_duplication_twin_cosine_is_exactly_one,
        test_eps_perturbation_breaks_symmetry_and_matches_derived_band,
        test_second_noise_scale_sensitivity_grid_cell,
        test_function_preservation_exact_with_and_without_eps,
        test_checkpoint_identity_no_collision,
        test_schedule_position_reuses_wsd_lr_frac,
        test_expected_twin_cosine_pure_math_limits,
    ]
    try:
        for t in tests:
            t()
        print("=" * 70)
        print(f"ALL {len(tests)} TESTS PASSED")
        print("=" * 70)
        return 0
    except Exception as e:
        print()
        print("=" * 70)
        print(f"TEST FAILED: {e}")
        print("=" * 70)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
