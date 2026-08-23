# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# issue: #898 packet-2 A VRAM wall

from __future__ import annotations

import os
import sys
import uuid
from types import SimpleNamespace
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import governor  # noqa: E402


def _contract() -> dict[str, str]:
    return {
        "EMBER_LAB_DISPATCH_VRAM_PROVIDER": "nvidia_smi_nvml",
        "EMBER_LAB_DISPATCH_VRAM_DEVICE_UUID": "GPU-00000000-1111-2222-3333-444444444444",
        "EMBER_LAB_DISPATCH_VRAM_FRACTION_MILLIONTHS": "500000",
        "EMBER_LAB_DISPATCH_MAXIMUM_PROCESS_VRAM_BYTES": str(12 * 1024**3),
        "EMBER_LAB_DISPATCH_MINIMUM_FREE_VRAM_BYTES": str(2 * 1024**3),
    }


def test_daemon_contract_overrides_ambient_fraction_and_margin(monkeypatch):
    monkeypatch.setattr(os, "environ", {
        **_contract(),
        "EMBER_VRAM_FRACTION": "0.99",
        "EMBER_VRAM_MARGIN_GB": "0.01",
        "EMBER_THROTTLE_S": "0.3",
    })
    contract = governor.daemon_vram_contract()
    assert contract["fraction"] == 0.5
    assert contract["maximum_process_vram_bytes"] == 12 * 1024**3
    assert "not_total_vram_guarantee" in contract["claim_boundary"]
    fraction, margin_gb, throttle = governor.env_limits()
    assert fraction == 0.5
    assert margin_gb == pytest.approx(2 * 1024**3 / 1e9)
    assert throttle == 0.3


def test_partial_or_noncanonical_daemon_contract_fails_closed(monkeypatch):
    partial = _contract()
    partial.pop("EMBER_LAB_DISPATCH_VRAM_DEVICE_UUID")
    monkeypatch.setattr(os, "environ", partial)
    with pytest.raises(RuntimeError, match="incomplete daemon contract"):
        governor.daemon_vram_contract()

    malformed = _contract()
    malformed["EMBER_LAB_DISPATCH_VRAM_FRACTION_MILLIONTHS"] = "0500000"
    monkeypatch.setattr(os, "environ", malformed)
    with pytest.raises(RuntimeError, match="not canonical positive"):
        governor.daemon_vram_contract()


class _FakeCuda:
    def __init__(self, uuids):
        self._uuids = uuids
        self.cap_calls = []
        self.info_calls = []

    def device_count(self):
        return len(self._uuids)

    def get_device_properties(self, index):
        return SimpleNamespace(uuid=self._uuids[index])

    def set_per_process_memory_fraction(self, fraction, device=None):
        self.cap_calls.append((fraction, device))

    def mem_get_info(self, device=None):
        self.info_calls.append(device)
        return (8 * 1024**3, 24 * 1024**3)


def test_preflight_caps_and_measures_the_contracted_uuid_not_default(monkeypatch):
    monkeypatch.setattr(os, "environ", _contract())
    cuda = _FakeCuda([
        "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        uuid.UUID(_contract()["EMBER_LAB_DISPATCH_VRAM_DEVICE_UUID"][4:]),
    ])
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=cuda))

    receipt = governor.preflight()

    assert cuda.cap_calls == [(0.5, 1)]
    assert cuda.info_calls == [1]
    assert receipt["daemon_vram_wall"]["torch_device_ordinal"] == 1


def test_preflight_refuses_when_contracted_uuid_is_not_visible(monkeypatch):
    monkeypatch.setattr(os, "environ", _contract())
    cuda = _FakeCuda(["GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"])
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=cuda))

    with pytest.raises(RuntimeError, match="contracted device UUID"):
        governor.preflight()
    assert cuda.cap_calls == []
    assert cuda.info_calls == []


def test_preflight_refuses_malformed_visible_uuid_without_fallback(monkeypatch):
    monkeypatch.setattr(os, "environ", _contract())
    cuda = _FakeCuda(["not-a-device-uuid"])
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=cuda))

    with pytest.raises(RuntimeError, match="malformed CUDA device UUID"):
        governor.preflight()
    assert cuda.cap_calls == []
    assert cuda.info_calls == []
