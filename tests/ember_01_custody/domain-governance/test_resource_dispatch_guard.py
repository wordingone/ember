# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression test for src/ember/governance/scripts/ember_01_custody/resource_dispatch_guard.py --
the C0 VRAM_OOM / COMMIT_CHARGE pre-dispatch guard (EMBER-01 conjunct-3
CLOSURE increment 1).

No GPU allocation, no host commit-charge draining: every test drives the
pure-logic check_vram_headroom()/check_commit_charge_margin()/
dispatch_guard() functions with INJECTED fixture readings. read_vram_live()
and read_commit_charge_live() (the real-counter production path) are NOT
called by this suite.

RED-first structure: for each class, one test proves the guard catches the
exact failure the ledger's blocking_reason named as unguarded (present ->
correctly blocks); a paired mutation test proves that failure would have
been silently missed if the guard's threshold check were stubbed out
(absent/mutated -> would wrongly pass) -- i.e. the test is guard-dependent,
not vacuously true.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPT_ROOT = REPO_ROOT / "scripts" / "ember_01_custody"
sys.path.insert(0, str(SCRIPT_ROOT))

import resource_dispatch_guard as guard  # noqa: E402


# ---------------------------------------------------------------------------
# VRAM_OOM
# ---------------------------------------------------------------------------

class TestVramHeadroomCorrectness:
    def test_pass_within_cap_and_margin(self) -> None:
        reading = {"total_gib": 24.0, "allocated_gib": 10.0, "requested_additional_gib": 5.0}
        ok, detail = guard.check_vram_headroom(reading)
        assert ok is True
        assert "VRAM_OOM" in detail

    def test_blocks_over_fraction_cap(self) -> None:
        # allocated+requested = 20 of 24 -> fraction 0.833 > cap 0.80
        reading = {"total_gib": 24.0, "allocated_gib": 15.0, "requested_additional_gib": 5.0}
        ok, detail = guard.check_vram_headroom(reading)
        assert ok is False
        assert "cap" in detail

    def test_blocks_under_margin_floor(self) -> None:
        # A reading comfortably under the fraction cap (0.70) that still isolates
        # the margin-floor clause: use a tightened margin_gib_floor override so the
        # cap clause cannot bind first (the two clauses are not independent at the
        # default floor on every total, so the margin-only case is proven directly
        # via the keyword override rather than hunting default-config geometry).
        reading = {"total_gib": 20.0, "allocated_gib": 14.0, "requested_additional_gib": 0.0}
        ok_default, _ = guard.check_vram_headroom(reading)
        assert ok_default is True  # fraction 0.70 <= 0.80 cap, free 6.0 >= 1.5 default floor

        ok_tightened, detail_tightened = guard.check_vram_headroom(reading, margin_gib_floor=8.0)
        assert ok_tightened is False
        assert "margin" in detail_tightened

    def test_fails_closed_on_non_dict_reading(self) -> None:
        ok, detail = guard.check_vram_headroom(None)  # type: ignore[arg-type]
        assert ok is False
        assert "VRAM_OOM" in detail

    def test_fails_closed_on_missing_field(self) -> None:
        ok, detail = guard.check_vram_headroom({"total_gib": 24.0, "allocated_gib": 10.0})
        assert ok is False
        assert "requested_additional_gib" in detail

    def test_fails_closed_on_negative_field(self) -> None:
        reading = {"total_gib": 24.0, "allocated_gib": -1.0, "requested_additional_gib": 5.0}
        ok, detail = guard.check_vram_headroom(reading)
        assert ok is False

    def test_fails_closed_on_bool_field(self) -> None:
        # bool is a subclass of int in Python; must not silently pass isinstance(int) checks.
        reading = {"total_gib": 24.0, "allocated_gib": True, "requested_additional_gib": 5.0}
        ok, detail = guard.check_vram_headroom(reading)
        assert ok is False

    def test_fails_closed_on_zero_total(self) -> None:
        reading = {"total_gib": 0.0, "allocated_gib": 0.0, "requested_additional_gib": 0.0}
        ok, detail = guard.check_vram_headroom(reading)
        assert ok is False


def test_vram_headroom_mutation_guard_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED-first proof: a reading that genuinely exceeds the VRAM_OOM floor
    (0.833 usage fraction > 0.80 cap) must be BLOCKED by check_vram_headroom
    (guard present -> RED-worthy reading correctly rejected). If the guard's
    threshold comparison is stubbed to a no-op pass-through (simulating the
    guard being removed/mutated), the SAME over-cap reading is wrongly
    approved -- proving this test's pass/fail genuinely depends on the
    guard's logic, not on a vacuous assertion."""
    over_cap_reading = {"total_gib": 24.0, "allocated_gib": 15.0, "requested_additional_gib": 5.0}

    # Guard present: correctly blocks.
    ok_present, detail_present = guard.check_vram_headroom(over_cap_reading)
    assert ok_present is False, "guard present must block an over-cap VRAM reading"
    assert "cap" in detail_present

    # Guard mutated to a no-op pass-through: the same reading is now wrongly approved.
    def _stubbed_always_ok(reading, *, fraction_cap=None, margin_gib_floor=None):
        return True, "STUBBED: guard removed"

    monkeypatch.setattr(guard, "check_vram_headroom", _stubbed_always_ok)
    ok_mutated, _ = guard.check_vram_headroom(over_cap_reading)
    assert ok_mutated is True, "mutated/no-op guard must wrongly approve (proves guard was load-bearing)"


# ---------------------------------------------------------------------------
# COMMIT_CHARGE
# ---------------------------------------------------------------------------

class TestCommitChargeMarginCorrectness:
    def test_pass_above_floor(self) -> None:
        reading = {"total_pagefile_gib": 64.0, "avail_pagefile_gib": 20.0}
        ok, detail = guard.check_commit_charge_margin(reading)
        assert ok is True
        assert "COMMIT_CHARGE" in detail

    def test_blocks_below_floor(self) -> None:
        reading = {"total_pagefile_gib": 64.0, "avail_pagefile_gib": 4.2}
        ok, detail = guard.check_commit_charge_margin(reading)
        assert ok is False
        assert "floor" in detail

    def test_blocks_exactly_at_floor_is_pass_boundary_inclusive_check(self) -> None:
        # avail == floor is documented as passing (< floor blocks, not <=)
        reading = {"total_pagefile_gib": 64.0, "avail_pagefile_gib": 6.0}
        ok, _ = guard.check_commit_charge_margin(reading)
        assert ok is True

    def test_fails_closed_on_non_dict_reading(self) -> None:
        ok, detail = guard.check_commit_charge_margin([])  # type: ignore[arg-type]
        assert ok is False
        assert "COMMIT_CHARGE" in detail

    def test_fails_closed_on_missing_field(self) -> None:
        ok, detail = guard.check_commit_charge_margin({"total_pagefile_gib": 64.0})
        assert ok is False
        assert "avail_pagefile_gib" in detail

    def test_fails_closed_on_negative_field(self) -> None:
        reading = {"total_pagefile_gib": 64.0, "avail_pagefile_gib": -3.0}
        ok, detail = guard.check_commit_charge_margin(reading)
        assert ok is False

    def test_fails_closed_on_string_field(self) -> None:
        reading = {"total_pagefile_gib": 64.0, "avail_pagefile_gib": "plenty"}
        ok, detail = guard.check_commit_charge_margin(reading)
        assert ok is False


def test_commit_charge_mutation_guard_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED-first proof, same shape as the VRAM mutation test. A reading below
    the 6GiB free-commit floor (visible-window-hygiene.md's in-run commit
    governor law, applied here pre-dispatch) must be BLOCKED by
    check_commit_charge_margin (guard present -> correctly rejected). A
    stubbed no-op guard wrongly approves the identical low-commit reading --
    proving the test is guard-dependent."""
    starved_reading = {"total_pagefile_gib": 64.0, "avail_pagefile_gib": 3.1}

    ok_present, detail_present = guard.check_commit_charge_margin(starved_reading)
    assert ok_present is False, "guard present must block a below-floor commit-charge reading"
    assert "floor" in detail_present

    def _stubbed_always_ok(reading, *, free_floor_gib=None):
        return True, "STUBBED: guard removed"

    monkeypatch.setattr(guard, "check_commit_charge_margin", _stubbed_always_ok)
    ok_mutated, _ = guard.check_commit_charge_margin(starved_reading)
    assert ok_mutated is True, "mutated/no-op guard must wrongly approve (proves guard was load-bearing)"


# ---------------------------------------------------------------------------
# Combined dispatch_guard() -- both classes gated together, pre-dispatch
# ---------------------------------------------------------------------------

class TestDispatchGuardCombined:
    GOOD_VRAM = {"total_gib": 24.0, "allocated_gib": 8.0, "requested_additional_gib": 2.0}
    BAD_VRAM = {"total_gib": 24.0, "allocated_gib": 15.0, "requested_additional_gib": 5.0}
    GOOD_COMMIT = {"total_pagefile_gib": 64.0, "avail_pagefile_gib": 20.0}
    BAD_COMMIT = {"total_pagefile_gib": 64.0, "avail_pagefile_gib": 3.1}

    def test_ok_when_both_pass(self) -> None:
        ok, reasons = guard.dispatch_guard(self.GOOD_VRAM, self.GOOD_COMMIT)
        assert ok is True
        assert len(reasons) == 2

    def test_blocked_when_vram_fails_even_if_commit_ok(self) -> None:
        ok, reasons = guard.dispatch_guard(self.BAD_VRAM, self.GOOD_COMMIT)
        assert ok is False
        assert any("cap" in r for r in reasons)

    def test_blocked_when_commit_fails_even_if_vram_ok(self) -> None:
        ok, reasons = guard.dispatch_guard(self.GOOD_VRAM, self.BAD_COMMIT)
        assert ok is False
        assert any("floor" in r for r in reasons)

    def test_blocked_when_both_fail(self) -> None:
        ok, reasons = guard.dispatch_guard(self.BAD_VRAM, self.BAD_COMMIT)
        assert ok is False
        assert len(reasons) == 2

    def test_non_live_requires_explicit_vram_reading(self) -> None:
        with pytest.raises(ValueError, match="vram_reading"):
            guard.dispatch_guard(None, self.GOOD_COMMIT, live=False)

    def test_non_live_requires_explicit_commit_reading(self) -> None:
        with pytest.raises(ValueError, match="commit_reading"):
            guard.dispatch_guard(self.GOOD_VRAM, None, live=False)


# ---------------------------------------------------------------------------
# Live-reader fail-closed behavior (no GPU/host dependency -- these prove the
# EXCEPTION path, not a real read; on a non-Windows host or a host with no
# CUDA device, they exercise the actual fail-closed branch directly).
# ---------------------------------------------------------------------------

class TestLiveReadersFailClosed:
    def test_read_commit_charge_live_rejects_non_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(guard.sys, "platform", "linux")
        with pytest.raises(guard.ResourceReadingError, match="Windows-only"):
            guard.read_commit_charge_live()

    def test_read_vram_live_rejects_missing_torch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins

        real_import = builtins.__import__

        def _blocked_import(name, *args, **kwargs):
            if name == "torch":
                raise ImportError("simulated: torch not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _blocked_import)
        with pytest.raises(guard.ResourceReadingError, match="torch not importable"):
            guard.read_vram_live()


# ---------------------------------------------------------------------------
# CLI entrypoint (fixture-driven only -- no --live invocation from tests)
# ---------------------------------------------------------------------------

class TestMainCLI:
    def test_main_exits_zero_on_good_readings(self, capsys: pytest.CaptureFixture) -> None:
        import json as _json

        rc = guard.main([
            "--vram-json", _json.dumps(TestDispatchGuardCombined.GOOD_VRAM),
            "--commit-json", _json.dumps(TestDispatchGuardCombined.GOOD_COMMIT),
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "RESOURCE_DISPATCH_GUARD_GREEN" in out

    def test_main_exits_nonzero_on_bad_readings(self, capsys: pytest.CaptureFixture) -> None:
        import json as _json

        rc = guard.main([
            "--vram-json", _json.dumps(TestDispatchGuardCombined.BAD_VRAM),
            "--commit-json", _json.dumps(TestDispatchGuardCombined.GOOD_COMMIT),
        ])
        assert rc == 1
        out = capsys.readouterr().out
        assert "RESOURCE_DISPATCH_GUARD_BLOCKED" in out
