from __future__ import annotations
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import importlib.util
import sys
from pathlib import Path

import pytest
import torch

ROOT = Path(__file__).resolve().parents[3]
RUNNER_DIR = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"
sys.path.insert(0, str(RUNNER_DIR))

import training_acceleration  # noqa: E402
from src.ember.model.model import RestartDecoderConfig, UnifiedDecoder  # noqa: E402


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, RUNNER_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load("issue2167_w5_runner", "issue2167_w5_upgate_canary_v1.py")


def _fake_scaled_mm(activation, weight_transposed, scale_a, scale_b, *, out_dtype, use_fast_accum):
    del use_fast_accum
    return (activation.float().matmul(weight_transposed.float()) * scale_a.float() * scale_b.float()).to(out_dtype)


def _model() -> UnifiedDecoder:
    config = RestartDecoderConfig.small_for_tests(hidden_size=8, layers=14, attention_heads=2, vocab_size=16)
    return UnifiedDecoder(config, genesis_seed=2167).to(dtype=torch.bfloat16)


@pytest.fixture(autouse=True)
def _reset_state():
    MODULE._STATE["installation"] = None
    MODULE._STATE["arm_fp8_dispatches"] = {"control": 0, "treatment": 0}
    MODULE._STATE["arm_updates"] = {"control": 0, "treatment": 0}
    yield


def test_wrapper_binds_the_w5_scope_and_arm_kernels():
    assert MODULE.W5_SCOPE == training_acceleration._FP8_W5_INSTALLATION_SCOPE
    assert MODULE.arm_kernel("control") == "bf16"
    assert MODULE.arm_kernel("treatment") == "fp8"
    with pytest.raises(ValueError, match="W5_ARM_REFUSED:warm"):
        MODULE.arm_kernel("warm")


def test_install_parks_fourteen_sites_on_the_bf16_arm():
    model = _model()
    receipt = MODULE.install_w5(model, acceleration=training_acceleration, kernel=_fake_scaled_mm, allow_test_device=True)
    assert receipt["installed_sites"] == 14 and receipt["scope"] == MODULE.W5_SCOPE
    sites = training_acceleration.iter_fp8_down_projections(model)
    assert len(sites) == 14 and {site.arm for site in sites} == {"bf16"}
    assert MODULE._STATE["installation"] == receipt


def test_update_switches_arms_refreshes_and_accounts_dispatches():
    model = _model()
    MODULE.install_w5(model, acceleration=training_acceleration, kernel=_fake_scaled_mm, allow_test_device=True)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    tokens = torch.randint(0, 16, (1, 6))

    def base_update(**kwargs):
        loss = model(tokens, active_expert="shared").float().square().mean()
        loss.backward()
        optimizer.step()
        optimizer.zero_grad()
        return {"arm": kwargs["arm"]}, {"cursor": 1}

    row, _cursor = MODULE.run_update_w5(acceleration=training_acceleration, base_update=base_update, arm="control", model=model)
    assert row == {"arm": "control"}
    assert MODULE._STATE["arm_fp8_dispatches"] == {"control": 0, "treatment": 0}
    # the master weights moved; the treatment update must refresh before its FP8 forward
    row, _cursor = MODULE.run_update_w5(acceleration=training_acceleration, base_update=base_update, arm="treatment", model=model)
    assert row == {"arm": "treatment"}
    treatment_dispatches = MODULE._STATE["arm_fp8_dispatches"]["treatment"]
    # one dispatch per site per up+gate call; the shared SwiGLU path calls its up+gate more
    # than once per step, so the count is a positive multiple of the 14 sites
    assert treatment_dispatches > 0 and treatment_dispatches % 14 == 0
    assert MODULE._STATE["arm_updates"] == {"control": 1, "treatment": 1}
    block = MODULE.bind_w5_receipt({"issue": 2081, "schema_version": "x"})
    assert block["issue"] == 2167 and block["w5_fp8"]["arm_fp8_dispatches"] == {"control": 0, "treatment": treatment_dispatches}
    assert len(block["w5_fp8"]["wrapper_source_sha256"]) == 64


def test_update_refuses_fp8_dispatch_in_the_control_arm_and_uninstalled_sites():
    model = _model()
    with pytest.raises(RuntimeError, match="W5_SITES_NOT_INSTALLED_REFUSED"):
        MODULE.run_update_w5(acceleration=training_acceleration, base_update=lambda **_k: ({}, {}), arm="control", model=model)
    MODULE.install_w5(model, acceleration=training_acceleration, kernel=_fake_scaled_mm, allow_test_device=True)

    def leaking_update(**kwargs):
        # a base update that flips the sites to fp8 behind the wrapper's back
        training_acceleration.set_fp8_arm(kwargs["model"], "fp8")
        kwargs["model"](torch.randint(0, 16, (1, 4)), active_expert="shared")
        return {}, {}

    with pytest.raises(RuntimeError, match="W5_CONTROL_ARM_DISPATCHED_FP8_REFUSED:"):
        MODULE.run_update_w5(acceleration=training_acceleration, base_update=leaking_update, arm="control", model=model)

    def silent_update(**kwargs):
        training_acceleration.set_fp8_arm(kwargs["model"], "bf16")
        kwargs["model"](torch.randint(0, 16, (1, 4)), active_expert="shared")
        return {}, {}

    with pytest.raises(RuntimeError, match="W5_TREATMENT_ARM_DISPATCHED_NO_FP8_REFUSED"):
        MODULE.run_update_w5(acceleration=training_acceleration, base_update=silent_update, arm="treatment", model=model)


def test_configure_refuses_aa_mode_and_split_heads():
    with pytest.raises(ValueError, match="W5_AA_MODE_REFUSED"):
        MODULE._configure_w5(root=ROOT, control_rebased_head="a" * 40, treatment_rebased_head="a" * 40, aa_mode=True)
    with pytest.raises(ValueError, match="W5_HEADS_MUST_MATCH_REFUSED"):
        MODULE._configure_w5(root=ROOT, control_rebased_head="a" * 40, treatment_rebased_head="b" * 40, aa_mode=False)
    saved = list(sys.argv)
    try:
        sys.argv = ["x", "--aa"]
        with pytest.raises(ValueError, match="W5_AA_MODE_REFUSED"):
            MODULE.main()
    finally:
        sys.argv = saved
