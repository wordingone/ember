# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import importlib.util
from pathlib import Path

import pytest


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
MODULE_PATH = ROOT / "runtime" / "ember-lab" / "issue898_resource_projection.py"
SPEC = importlib.util.spec_from_file_location("issue898_resource_projection", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
projection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(projection)


def test_launch_packet_authority_resolves_the_populated_layout():
    canonical = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "launch_packet.py"
    legacy = ROOT / "tools" / "ember-restart-3b" / "launch_packet.py"
    expected = canonical if canonical.is_file() else legacy
    assert projection._LAUNCH_PACKET == expected
    assert projection._LAUNCH_PACKET.is_file()


def test_exact_projection_uses_active_gradient_and_optimizer_terms():
    result = projection.exact_resource_projection(ROOT / "configs" / "ember-restart-3b.json")

    assert result["total_parameters"] == 3_839_161_856
    assert result["active_parameters"] < result["total_parameters"]
    assert result["parameter_bytes_all"] == result["total_parameters"] * 2
    assert result["gradient_bytes_active"] == result["active_parameters"] * 2
    assert result["optimizer_state_bytes_active"] == result["active_parameters"] * 2
    assert result["mechanism_peak_bytes"] == (
        result["parameter_bytes_all"]
        + result["gradient_bytes_active"]
        + result["optimizer_state_bytes_active"]
        + result["activation_reserve_bytes"]
        + result["runtime_reserve_bytes"]
    )
    assert result["checkpoint_publication_host_commit_reserve_bytes"] == 8 * projection.GIB


def test_exact_projection_refuses_rounded_authority_drift(monkeypatch):
    real = projection._AUTHORITY.preflight_resource

    def drifted(cfg, root):
        result = real(cfg, root)
        result["breakdown_gib"]["optimizer_active"] += 0.0001
        return result

    monkeypatch.setattr(projection._AUTHORITY, "preflight_resource", drifted)
    with pytest.raises(ValueError, match="drifted from preflight_resource"):
        projection.exact_resource_projection(ROOT / "configs" / "ember-restart-3b.json")
