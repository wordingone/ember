"""test_ember_resident_training_gate_econ.py -- TDD suite for gh #128 (resident
gate loop-econ wiring). Exercises the real DT-6 field extraction + invoked
check_econ_gate conjunct in ember_resident_training_gate.py against the three
ACs in docs/dt6-loop-economics-gate-amendment.md:

  AC1: PASS verdict missing a required field -> REJECT (named field(s))
  AC2: all three fields + exceeds_band:true, signal > band -> ACCEPT
  AC3: fields present but signal_per_gpu_hour <= equal_wallclock_band ->
       REJECT-as-within-floor (power statement, not PASS)

Hermetic fixtures only (tempfile.TemporaryDirectory via
ember_resident_training_gate.build_fixture_repo /
build_valid_candidate_manifest) -- no live receipts touched, no network,
no paid API surface.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ember_resident_training_gate as gate  # noqa: E402


def _write_candidate(root: Path, repo: Path, candidate_path: Path, dt6_fields: dict | None) -> dict:
    candidate = gate.build_valid_candidate_manifest(root, repo, dt6_fields=dt6_fields)
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    return candidate


# ---------------------------------------------------------------------------
# (a) complete DT-6 fields + passing econ -> PASS
# ---------------------------------------------------------------------------

def test_complete_dt6_fields_and_passing_econ_yields_pass():
    with tempfile.TemporaryDirectory(prefix="econ-gate-pass-") as td:
        root = Path(td)
        repo, index, full_parity = gate.build_fixture_repo(root)
        candidate_path = root / "candidate.json"
        _write_candidate(
            root, repo, candidate_path,
            dt6_fields={"signal_per_gpu_hour": 1.2, "equal_wallclock_band": 0.5, "exceeds_band": True},
        )

        receipt = gate.build_gate_receipt(repo, index, None, candidate_path, [], full_parity)

        assert receipt["resident_training_gate_status"] == "PASS"
        assert receipt["component_status"]["loop_econ_gate"] == "PASS"
        verdict = receipt["loop_economics_gate_verdict"]
        assert verdict["decision"] == "ACCEPT"
        assert verdict["ac"] == "AC2"


# ---------------------------------------------------------------------------
# (b) missing field -> BLOCKED, naming the missing field (never pending-pass)
# ---------------------------------------------------------------------------

def test_missing_dt6_field_blocks_and_names_it():
    with tempfile.TemporaryDirectory(prefix="econ-gate-missing-") as td:
        root = Path(td)
        repo, index, full_parity = gate.build_fixture_repo(root)
        candidate_path = root / "candidate.json"
        # equal_wallclock_band omitted entirely
        _write_candidate(
            root, repo, candidate_path,
            dt6_fields={"signal_per_gpu_hour": 1.2, "exceeds_band": True},
        )

        receipt = gate.build_gate_receipt(repo, index, None, candidate_path, [], full_parity)

        assert receipt["resident_training_gate_status"] == "BLOCKED"
        assert receipt["component_status"]["loop_econ_gate"] == "BLOCKED"
        verdict = receipt["loop_economics_gate_verdict"]
        assert verdict["decision"] == "REJECT"
        assert verdict["ac"] == "AC1"
        assert "equal_wallclock_band" in verdict["reason"]
        assert verdict["decision"] != "PENDING"
        assert "loop_econ_gate_not_accept" in receipt["invalid_codes"]


def test_missing_all_dt6_fields_blocks_and_names_all_three():
    with tempfile.TemporaryDirectory(prefix="econ-gate-missing-all-") as td:
        root = Path(td)
        repo, index, full_parity = gate.build_fixture_repo(root)
        candidate_path = root / "candidate.json"
        _write_candidate(root, repo, candidate_path, dt6_fields=None)

        receipt = gate.build_gate_receipt(repo, index, None, candidate_path, [], full_parity)

        assert receipt["resident_training_gate_status"] == "BLOCKED"
        verdict = receipt["loop_economics_gate_verdict"]
        assert verdict["decision"] == "REJECT"
        assert verdict["ac"] == "AC1"
        for field in ("signal_per_gpu_hour", "equal_wallclock_band", "exceeds_band"):
            assert field in verdict["reason"]


# ---------------------------------------------------------------------------
# (c) failing econ values -> BLOCKED as within-floor (power statement, not PASS)
# ---------------------------------------------------------------------------

def test_failing_econ_values_blocks_as_within_floor():
    with tempfile.TemporaryDirectory(prefix="econ-gate-fail-") as td:
        root = Path(td)
        repo, index, full_parity = gate.build_fixture_repo(root)
        candidate_path = root / "candidate.json"
        # signal_per_gpu_hour <= equal_wallclock_band -> AC3
        _write_candidate(
            root, repo, candidate_path,
            dt6_fields={"signal_per_gpu_hour": 0.4, "equal_wallclock_band": 0.5, "exceeds_band": True},
        )

        receipt = gate.build_gate_receipt(repo, index, None, candidate_path, [], full_parity)

        assert receipt["resident_training_gate_status"] == "BLOCKED"
        verdict = receipt["loop_economics_gate_verdict"]
        assert verdict["decision"] == "REJECT"
        assert verdict["ac"] == "AC3"
        assert "within-floor" in verdict["reason"]


def test_exceeds_band_false_blocks_even_with_signal_above_band():
    with tempfile.TemporaryDirectory(prefix="econ-gate-exceeds-false-") as td:
        root = Path(td)
        repo, index, full_parity = gate.build_fixture_repo(root)
        candidate_path = root / "candidate.json"
        _write_candidate(
            root, repo, candidate_path,
            dt6_fields={"signal_per_gpu_hour": 1.2, "equal_wallclock_band": 0.5, "exceeds_band": False},
        )

        receipt = gate.build_gate_receipt(repo, index, None, candidate_path, [], full_parity)

        assert receipt["resident_training_gate_status"] == "BLOCKED"
        assert receipt["loop_economics_gate_verdict"]["decision"] == "REJECT"


# ---------------------------------------------------------------------------
# (d) import smoke -- every import resolves at HEAD, CI-runnable form
# ---------------------------------------------------------------------------

def test_import_smoke_resolves_at_head():
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    proc = subprocess.run(
        [sys.executable, "-c", "import ember_resident_training_gate; import loop_econ_gate"],
        cwd=scripts_dir,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"


# ---------------------------------------------------------------------------
# (e) theater-regression -- check_econ_gate must actually be CALLED, not just
# imported. This is the exact defect the 067ac17-era wiring shipped: a
# try-block wrapping a dict literal, never invoking the checker.
# ---------------------------------------------------------------------------

def test_check_econ_gate_is_actually_invoked_on_a_pass():
    with tempfile.TemporaryDirectory(prefix="econ-gate-theater-pass-") as td:
        root = Path(td)
        repo, index, full_parity = gate.build_fixture_repo(root)
        candidate_path = root / "candidate.json"
        _write_candidate(
            root, repo, candidate_path,
            dt6_fields={"signal_per_gpu_hour": 1.2, "equal_wallclock_band": 0.5, "exceeds_band": True},
        )

        with mock.patch.object(gate, "check_econ_gate", wraps=gate.check_econ_gate) as spy:
            receipt = gate.build_gate_receipt(repo, index, None, candidate_path, [], full_parity)

        assert spy.call_count >= 1, (
            "check_econ_gate imported but never invoked -- the exact theater "
            "this test guards against (067ac17-era wiring)"
        )
        assert receipt["resident_training_gate_status"] == "PASS"


def test_check_econ_gate_is_invoked_even_when_no_candidate_manifest():
    """A PASS with the econ leg unevaluated must be impossible by
    construction -- so check_econ_gate must fire even on the earliest-exit
    BLOCKED path (no candidate manifest at all), not only inside a
    conditional PASS branch."""
    with tempfile.TemporaryDirectory(prefix="econ-gate-theater-noman-") as td:
        root = Path(td)
        repo, index, full_parity = gate.build_fixture_repo(root)

        with mock.patch.object(gate, "check_econ_gate", wraps=gate.check_econ_gate) as spy:
            receipt = gate.build_gate_receipt(repo, index, None, None, [], full_parity)

        assert spy.call_count >= 1
        assert receipt["resident_training_gate_status"] == "BLOCKED"
        assert receipt["loop_economics_gate_verdict"]["decision"] != "PENDING"


def test_econ_gate_call_receives_the_extracted_fields():
    """Regression guard for a subtler theater form: check_econ_gate called
    with a dict that never actually carries the extracted receipt fields
    (e.g. an empty stub) would still show call_count >= 1 above. Assert the
    call argument itself carries the real values."""
    with tempfile.TemporaryDirectory(prefix="econ-gate-args-") as td:
        root = Path(td)
        repo, index, full_parity = gate.build_fixture_repo(root)
        candidate_path = root / "candidate.json"
        _write_candidate(
            root, repo, candidate_path,
            dt6_fields={"signal_per_gpu_hour": 1.2, "equal_wallclock_band": 0.5, "exceeds_band": True},
        )

        with mock.patch.object(gate, "check_econ_gate", wraps=gate.check_econ_gate) as spy:
            gate.build_gate_receipt(repo, index, None, candidate_path, [], full_parity)

        assert spy.call_count >= 1
        called_with = spy.call_args[0][0]
        assert called_with["signal_per_gpu_hour"] == 1.2
        assert called_with["equal_wallclock_band"] == 0.5
        assert called_with["exceeds_band"] is True
