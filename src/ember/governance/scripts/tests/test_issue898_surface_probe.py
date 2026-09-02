# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
MODULE_PATH = ROOT / "runtime" / "ember-lab" / "issue898_surface_probe.py"
SPEC = importlib.util.spec_from_file_location("issue898_surface_probe", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def test_dispatch_token_is_consumed_before_probe_mode_is_parsed(monkeypatch):
    consumed = []
    monkeypatch.setattr(probe, "consume_dispatch", lambda root: consumed.append(root) or 256)

    with pytest.raises(SystemExit):
        probe.main(["not-a-mode", "--attempt-bytes", "257"])

    assert consumed == [ROOT]


def test_commit_probe_attempts_above_cage_cap_and_reports_os_refusal():
    attempted = []

    result = probe.run_commit_probe(
        attempt_bytes=257,
        maximum_job_memory_bytes=256,
        allocate=lambda size: attempted.append(size) or (False, 1455),
        hold=lambda: (_ for _ in ()).throw(AssertionError("refused allocation must not hold")),
    )

    assert attempted == [257]
    assert result == {"result": "OS_ALLOCATION_REFUSED", "attempt_bytes": 257, "win32_error": 1455}


def test_commit_probe_refuses_a_non_crossing_configuration_without_calling_allocator():
    with pytest.raises(ValueError, match="must cross"):
        probe.run_commit_probe(
            attempt_bytes=256,
            maximum_job_memory_bytes=256,
            allocate=lambda _size: (_ for _ in ()).throw(AssertionError("must not allocate")),
            hold=lambda: None,
        )


def test_disk_probe_really_writes_past_each_named_budget(tmp_path):
    roots = [tmp_path / "b", tmp_path / "c"]
    for root in roots:
        root.mkdir()
    held = []

    result = probe.run_disk_probe(
        write_roots=roots,
        maximum_write_bytes=15,
        attempt_bytes_per_root=16,
        hold=lambda: held.append(True),
    )

    assert result["result"] == "WRITE_PAST_BUDGET_ATTEMPTED"
    assert result["bytes_per_root"] == 16
    assert [Path(row["path"]).read_bytes() for row in result["writes"]] == [b"x" * 16, b"x" * 16]
    assert held == [True]


class _Cuda:
    def __init__(self):
        self.fractions = []

    def set_per_process_memory_fraction(self, fraction, device=0):
        self.fractions.append((fraction, device))

    def synchronize(self):
        raise AssertionError("an allocator refusal must occur before synchronize")

    def mem_get_info(self, device=0):
        return (1024, 2048)


class _Torch:
    uint8 = object()

    def __init__(self):
        self.cuda = _Cuda()
        self.attempted = []

    def empty(self, size, *, dtype, device):
        self.attempted.append((size, dtype, device))
        raise RuntimeError("CUDA out of memory")


def test_vram_fraction_probe_treats_allocator_oom_as_inconclusive():
    torch = _Torch()
    result = probe.run_vram_fraction_probe(
        attempt_bytes=513,
        maximum_process_vram_bytes=512,
        daemon_process_fraction_millionths=250_000,
        minimum_device_margin_bytes=256,
        torch_module=torch,
    )

    assert torch.cuda.fractions == []
    assert torch.attempted == [(513, torch.uint8, "cuda")]
    assert result["result"] == "INCONCLUSIVE_CUDA_OOM"
    assert result["attempt_bytes"] == 513


def test_vram_fraction_probe_holds_a_successful_crossing_for_the_daemon_ladder():
    held = []

    class CrossingTorch(_Torch):
        def __init__(self):
            super().__init__()
            self.cuda.synchronize = lambda: None

        def empty(self, size, *, dtype, device):
            self.attempted.append((size, dtype, device))
            return object()

    torch = CrossingTorch()
    result = probe.run_vram_fraction_probe(
        attempt_bytes=1200,
        maximum_process_vram_bytes=1024,
        daemon_process_fraction_millionths=41_666,
        minimum_device_margin_bytes=256,
        torch_module=torch,
        hold=lambda: held.append(True),
    )

    assert torch.cuda.fractions == []
    assert torch.attempted == [(1200, torch.uint8, "cuda")]
    assert held == [True]
    assert result["result"] == "CROSSING_SURVIVED_UNEXPECTEDLY"


def test_vram_floor_probe_allocates_and_holds_for_the_daemon_ladder():
    held = []

    class HoldingTorch(_Torch):
        def __init__(self):
            super().__init__()
            self.cuda.synchronize = lambda: None

        def empty(self, size, *, dtype, device):
            self.attempted.append((size, dtype, device))
            return object()

    torch = HoldingTorch()
    result = probe.run_vram_floor_probe(
        allocation_bytes=256,
        minimum_free_vram_bytes=800,
        torch_module=torch,
        hold=lambda: held.append(True),
    )

    assert torch.cuda.fractions == []
    assert torch.attempted == [(256, torch.uint8, "cuda")]
    assert held == [True]
    assert result["result"] == "VRAM_FLOOR_CROSSING_HELD_FOR_SENTINEL"


def test_vram_floor_probe_refuses_when_fresh_free_read_would_not_cross_floor():
    torch = _Torch()
    result = probe.run_vram_floor_probe(
        allocation_bytes=128,
        minimum_free_vram_bytes=800,
        torch_module=torch,
        hold=lambda: (_ for _ in ()).throw(AssertionError("must not hold")),
    )

    assert torch.attempted == []
    assert result == {
        "result": "INCONCLUSIVE_FLOOR_NOT_CROSSED",
        "observed_free_bytes": 1024,
        "minimum_free_vram_bytes": 800,
        "allocation_bytes": 128,
    }


def test_vram_fraction_probe_refuses_when_device_margin_is_not_available():
    torch = _Torch()
    result = probe.run_vram_fraction_probe(
        attempt_bytes=1900,
        maximum_process_vram_bytes=1024,
        daemon_process_fraction_millionths=41_666,
        minimum_device_margin_bytes=256,
        torch_module=torch,
        hold=lambda: (_ for _ in ()).throw(AssertionError("must not hold")),
    )

    assert torch.attempted == []
    assert result == {
        "result": "INCONCLUSIVE_DEVICE_MARGIN",
        "attempt_bytes": 1900,
        "minimum_device_margin_bytes": 256,
        "observed_free_bytes": 1024,
        "observed_total_bytes": 2048,
    }
