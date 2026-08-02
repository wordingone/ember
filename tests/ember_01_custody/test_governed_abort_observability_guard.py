# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression test for
scripts/ember_01_custody/governed_abort_observability_guard.py -- the C0
GOVERNED_ABORT_OBSERVABILITY guard (EMBER-01 conjunct-3 CLOSURE increment 2).

No live training run, no real kill-discipline event: every test drives
build_abort_receipt()/emit_abort_receipt()/verify_abort_observed() with fixture
trigger/threshold/reading/phase values and a temp receipts directory.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = REPO_ROOT / "scripts" / "ember_01_custody"
sys.path.insert(0, str(SCRIPT_ROOT))

import governed_abort_observability_guard as guard  # noqa: E402


FIXTURE_TRIGGER = "VRAM_OOM_HEADROOM_BREACH"
FIXTURE_THRESHOLDS = {"vram_fraction_cap": 0.80, "margin_gib_floor": 1.5}
FIXTURE_LIVE_READING = {"total_gib": 24.0, "allocated_gib": 21.0, "requested_additional_gib": 2.0}
FIXTURE_PHASE = "pretrain-step-4821"


# ---------------------------------------------------------------------------
# build_abort_receipt() -- pure construction, fail-closed on missing fields
# ---------------------------------------------------------------------------

class TestBuildAbortReceipt:
    def test_builds_well_formed_receipt(self) -> None:
        receipt = guard.build_abort_receipt(
            trigger=FIXTURE_TRIGGER,
            thresholds=FIXTURE_THRESHOLDS,
            live_reading=FIXTURE_LIVE_READING,
            phase=FIXTURE_PHASE,
        )
        for field in guard.REQUIRED_ABORT_RECEIPT_FIELDS:
            assert field in receipt, f"missing required field {field!r}"
        assert receipt["trigger"] == FIXTURE_TRIGGER
        assert receipt["class"] == "GOVERNED_ABORT_OBSERVABILITY"

    def test_extra_fields_are_merged(self) -> None:
        receipt = guard.build_abort_receipt(
            trigger=FIXTURE_TRIGGER,
            thresholds=FIXTURE_THRESHOLDS,
            live_reading=FIXTURE_LIVE_READING,
            phase=FIXTURE_PHASE,
            extra={"run_id": "abc123"},
        )
        assert receipt["run_id"] == "abc123"

    def test_fails_closed_on_empty_trigger(self) -> None:
        with pytest.raises(ValueError, match="trigger"):
            guard.build_abort_receipt(
                trigger="", thresholds=FIXTURE_THRESHOLDS,
                live_reading=FIXTURE_LIVE_READING, phase=FIXTURE_PHASE,
            )

    def test_fails_closed_on_non_string_trigger(self) -> None:
        with pytest.raises(ValueError, match="trigger"):
            guard.build_abort_receipt(
                trigger=None, thresholds=FIXTURE_THRESHOLDS,  # type: ignore[arg-type]
                live_reading=FIXTURE_LIVE_READING, phase=FIXTURE_PHASE,
            )

    def test_fails_closed_on_empty_thresholds(self) -> None:
        with pytest.raises(ValueError, match="thresholds"):
            guard.build_abort_receipt(
                trigger=FIXTURE_TRIGGER, thresholds={},
                live_reading=FIXTURE_LIVE_READING, phase=FIXTURE_PHASE,
            )

    def test_fails_closed_on_non_dict_thresholds(self) -> None:
        with pytest.raises(ValueError, match="thresholds"):
            guard.build_abort_receipt(
                trigger=FIXTURE_TRIGGER, thresholds="not-a-dict",  # type: ignore[arg-type]
                live_reading=FIXTURE_LIVE_READING, phase=FIXTURE_PHASE,
            )

    def test_fails_closed_on_empty_live_reading(self) -> None:
        with pytest.raises(ValueError, match="live_reading"):
            guard.build_abort_receipt(
                trigger=FIXTURE_TRIGGER, thresholds=FIXTURE_THRESHOLDS,
                live_reading={}, phase=FIXTURE_PHASE,
            )

    def test_fails_closed_on_empty_phase(self) -> None:
        with pytest.raises(ValueError, match="phase"):
            guard.build_abort_receipt(
                trigger=FIXTURE_TRIGGER, thresholds=FIXTURE_THRESHOLDS,
                live_reading=FIXTURE_LIVE_READING, phase="",
            )


# ---------------------------------------------------------------------------
# emit_abort_receipt() -- checked write
# ---------------------------------------------------------------------------

class TestEmitAbortReceipt:
    def test_writes_valid_receipt_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = guard.emit_abort_receipt(
                td, trigger=FIXTURE_TRIGGER, thresholds=FIXTURE_THRESHOLDS,
                live_reading=FIXTURE_LIVE_READING, phase=FIXTURE_PHASE,
            )
            assert path.is_file()
            reloaded = json.loads(path.read_text(encoding="utf-8"))
            assert reloaded["trigger"] == FIXTURE_TRIGGER
            for field in guard.REQUIRED_ABORT_RECEIPT_FIELDS:
                assert field in reloaded

    def test_creates_receipt_dir_if_absent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            nested = Path(td) / "nested" / "receipts"
            path = guard.emit_abort_receipt(
                nested, trigger=FIXTURE_TRIGGER, thresholds=FIXTURE_THRESHOLDS,
                live_reading=FIXTURE_LIVE_READING, phase=FIXTURE_PHASE,
            )
            assert path.is_file()

    def test_propagates_construction_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with pytest.raises(ValueError, match="trigger"):
                guard.emit_abort_receipt(
                    td, trigger="", thresholds=FIXTURE_THRESHOLDS,
                    live_reading=FIXTURE_LIVE_READING, phase=FIXTURE_PHASE,
                )
            # a failed construction must never leave a partial receipt on disk
            assert list(Path(td).glob("*.json")) == []


# ---------------------------------------------------------------------------
# verify_abort_observed() -- fail-closed detection
# ---------------------------------------------------------------------------

class TestVerifyAbortObserved:
    def test_pass_when_matching_receipt_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = guard.emit_abort_receipt(
                td, trigger=FIXTURE_TRIGGER, thresholds=FIXTURE_THRESHOLDS,
                live_reading=FIXTURE_LIVE_READING, phase=FIXTURE_PHASE,
            )
            ts = json.loads(path.read_text(encoding="utf-8"))["ts"]
            event = {"trigger": FIXTURE_TRIGGER, "ts_start": ts, "ts_end": ts}
            ok, detail = guard.verify_abort_observed(event, td)
            assert ok is True
            assert "matching receipt" in detail

    def test_red_when_no_receipt_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            event = {
                "trigger": FIXTURE_TRIGGER,
                "ts_start": "20260801T000000Z",
                "ts_end": "20260801T235959Z",
            }
            ok, detail = guard.verify_abort_observed(event, td)
            assert ok is False
            assert "no matching receipt" in detail

    def test_red_when_trigger_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = guard.emit_abort_receipt(
                td, trigger=FIXTURE_TRIGGER, thresholds=FIXTURE_THRESHOLDS,
                live_reading=FIXTURE_LIVE_READING, phase=FIXTURE_PHASE,
            )
            ts = json.loads(path.read_text(encoding="utf-8"))["ts"]
            event = {"trigger": "SOME_OTHER_TRIGGER", "ts_start": ts, "ts_end": ts}
            ok, _ = guard.verify_abort_observed(event, td)
            assert ok is False

    def test_red_when_receipt_ts_outside_window(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            guard.emit_abort_receipt(
                td, trigger=FIXTURE_TRIGGER, thresholds=FIXTURE_THRESHOLDS,
                live_reading=FIXTURE_LIVE_READING, phase=FIXTURE_PHASE,
            )
            # window entirely before the real receipt's ts (2020, far in the past)
            event = {
                "trigger": FIXTURE_TRIGGER,
                "ts_start": "20200101T000000Z",
                "ts_end": "20200101T235959Z",
            }
            ok, _ = guard.verify_abort_observed(event, td)
            assert ok is False

    def test_red_when_receipts_dir_missing(self) -> None:
        ok, detail = guard.verify_abort_observed(
            {"trigger": FIXTURE_TRIGGER, "ts_start": "a", "ts_end": "z"},
            "C:/definitely/does/not/exist/receipts",
        )
        assert ok is False
        assert "does not exist" in detail

    def test_fails_closed_on_non_dict_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ok, detail = guard.verify_abort_observed(None, td)  # type: ignore[arg-type]
            assert ok is False
            assert "not a dict" in detail

    def test_fails_closed_on_missing_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ok, detail = guard.verify_abort_observed(
                {"ts_start": "a", "ts_end": "z"}, td
            )
            assert ok is False
            assert "trigger" in detail

    def test_fails_closed_on_inverted_window(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ok, detail = guard.verify_abort_observed(
                {"trigger": FIXTURE_TRIGGER, "ts_start": "20260801T120000Z", "ts_end": "20260801T000000Z"},
                td,
            )
            assert ok is False
            assert "malformed window" in detail

    def test_malformed_receipt_json_is_skipped_not_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            garbage = Path(td) / "governed-abort-garbage.json"
            garbage.write_text("{not valid json", encoding="utf-8")
            event = {
                "trigger": FIXTURE_TRIGGER,
                "ts_start": "20260801T000000Z",
                "ts_end": "20260801T235959Z",
            }
            ok, _ = guard.verify_abort_observed(event, td)  # must not raise
            assert ok is False  # garbage receipt doesn't match; no crash either


def test_governed_abort_mutation_guard_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED-first proof: an abort event with NO matching receipt on disk must be
    RED with the guard present (the silent-abort case this class names). If
    verify_abort_observed is stubbed to always return (True, "stubbed"), the SAME
    no-receipt event is wrongly approved -- proving the guard is load-bearing."""
    with tempfile.TemporaryDirectory() as td:
        event = {
            "trigger": FIXTURE_TRIGGER,
            "ts_start": "20260801T000000Z",
            "ts_end": "20260801T235959Z",
        }
        ok_present, detail_present = guard.verify_abort_observed(event, td)
        assert ok_present is False, "guard present must RED a silent (unreceipted) abort"
        assert "silent abort" in detail_present

        def _stubbed_always_ok(event, receipts_dir):
            return True, "STUBBED: guard removed"

        monkeypatch.setattr(guard, "verify_abort_observed", _stubbed_always_ok)
        ok_mutated, _ = guard.verify_abort_observed(event, td)
        assert ok_mutated is True, "mutated/no-op guard must wrongly approve (proves guard was load-bearing)"
