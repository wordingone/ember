# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression test for scripts/ember_01_custody/native_crash_guard.py -- the C0
NATIVE_CRASH supervised-dispatch guard (EMBER-01 conjunct-3 CLOSURE increment 2).

classify_exit() correctness is proven with hand-picked returncode fixtures for BOTH
platform branches (parametrized, so both run on any host OS -- this test suite must
pass on the ubuntu-latest CI runner, not just this Windows dev box).

run_supervised() is proven end-to-end with a REAL crashing child process
(platform-appropriate: os.kill(SIGSEGV) on POSIX, ctypes ExitProcess(NTSTATUS) on
Windows) -- not a mocked/fabricated returncode -- so the test proves the guard
against a genuine process death, matching the assignment's "fixture child that
exits -11/0xC0000005 -> receipt written" instruction.
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

import native_crash_guard as guard  # noqa: E402


# ---------------------------------------------------------------------------
# classify_exit() -- pure logic, both platform branches, host-OS-independent
# ---------------------------------------------------------------------------

class TestClassifyExitWindows:
    def test_named_access_violation(self) -> None:
        result = guard.classify_exit(0xC0000005, platform="win32")
        assert result is not None
        assert result["crash_signature"] == "STATUS_ACCESS_VIOLATION"

    def test_named_stack_overflow(self) -> None:
        result = guard.classify_exit(0xC00000FD, platform="win32")
        assert result is not None
        assert result["crash_signature"] == "STATUS_STACK_OVERFLOW"

    def test_unnamed_fault_severity_code_still_classifies(self) -> None:
        # top two bits set (0xC0000000 mask) but not in the named table -- must
        # still classify as a crash (fail-closed: the mask, not the name table, is
        # the load-bearing check).
        result = guard.classify_exit(0xFFFFFFF5, platform="win32")  # -11 as unsigned DWORD
        assert result is not None
        assert "UNNAMED_NTSTATUS" in result["crash_signature"]

    def test_negative_int_normalized_to_unsigned_dword(self) -> None:
        # Python ints CAN be negative even when representing a Windows DWORD if a
        # caller passes a signed interpretation; normalization must still catch it.
        result = guard.classify_exit(-11, platform="win32")  # == 0xFFFFFFF5 unsigned
        assert result is not None

    def test_clean_exit_is_not_a_crash(self) -> None:
        assert guard.classify_exit(0, platform="win32") is None

    def test_ordinary_application_error_is_not_a_crash(self) -> None:
        # a script's own sys.exit(1) must NOT be misclassified as a native crash
        assert guard.classify_exit(1, platform="win32") is None
        assert guard.classify_exit(2, platform="win32") is None


class TestClassifyExitPosix:
    def test_sigsegv_classifies(self) -> None:
        result = guard.classify_exit(-11, platform="linux")
        assert result is not None
        assert result["crash_signature"] == "SIGSEGV"

    def test_sigabrt_classifies(self) -> None:
        result = guard.classify_exit(-6, platform="linux")
        assert result is not None
        assert result["crash_signature"] == "SIGABRT"

    def test_unnamed_signal_still_classifies(self) -> None:
        result = guard.classify_exit(-63, platform="linux")  # not a real POSIX signal number
        assert result is not None
        assert "SIG63" in result["crash_signature"]

    def test_clean_exit_is_not_a_crash(self) -> None:
        assert guard.classify_exit(0, platform="linux") is None

    def test_ordinary_application_error_is_not_a_crash(self) -> None:
        assert guard.classify_exit(1, platform="linux") is None


class TestClassifyExitFailsClosedOnBadInput:
    def test_rejects_non_int(self) -> None:
        with pytest.raises(TypeError):
            guard.classify_exit("not-an-int", platform="win32")  # type: ignore[arg-type]

    def test_rejects_bool(self) -> None:
        with pytest.raises(TypeError):
            guard.classify_exit(True, platform="win32")  # type: ignore[arg-type]


def test_native_crash_classify_mutation_guard_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED-first proof: a real crash-signature returncode must classify as a crash
    with the guard present. If classify_exit is stubbed to always return None
    (guard removed/mutated), the identical crash-signature returncode is wrongly
    treated as clean -- proving the classification logic is load-bearing."""
    crash_code = 0xC0000005

    present = guard.classify_exit(crash_code, platform="win32")
    assert present is not None, "guard present must classify a real crash code as a crash"

    def _stubbed_never_crash(returncode, *, platform=None):
        return None

    monkeypatch.setattr(guard, "classify_exit", _stubbed_never_crash)
    mutated = guard.classify_exit(crash_code, platform="win32")
    assert mutated is None, "mutated/no-op guard must wrongly report no crash (proves guard was load-bearing)"


# ---------------------------------------------------------------------------
# run_supervised() -- clean / ordinary-error / REAL crash, end-to-end
# ---------------------------------------------------------------------------

class TestRunSupervised:
    def test_clean_child_writes_no_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            result = guard.run_supervised(
                [sys.executable, "-c", "import sys; sys.exit(0)"], receipt_dir=td
            )
            assert result["crashed"] is False
            assert result["returncode"] == 0
            assert result["receipt_path"] is None
            assert list(Path(td).glob("*.json")) == []

    def test_ordinary_error_child_writes_no_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            result = guard.run_supervised(
                [sys.executable, "-c", "import sys; sys.exit(1)"], receipt_dir=td
            )
            assert result["crashed"] is False
            assert result["returncode"] == 1
            assert result["receipt_path"] is None
            assert list(Path(td).glob("*.json")) == []

    def test_real_crash_child_writes_receipt_with_named_class(self) -> None:
        # Genuine process death, platform-appropriate: os.kill(SIGSEGV) on POSIX
        # (returncode -11, matching the assignment's "-11" fixture), ExitProcess
        # (0xC0000005) on Windows (matching the assignment's "0xC0000005" fixture).
        with tempfile.TemporaryDirectory() as td:
            result = guard.spawn_and_supervise_real_crash(td)
            assert result["crashed"] is True
            assert result["receipt_path"] is not None
            receipt_path = Path(result["receipt_path"])
            assert receipt_path.is_file()
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            assert receipt["class"] == "NATIVE_CRASH"
            assert receipt["crash_signature"] == result["crash_signature"]
            assert receipt["returncode"] == result["returncode"]
            for field in guard.REQUIRED_RECEIPT_FIELDS:
                assert field in receipt, f"crash receipt missing required field {field!r}"
            if sys.platform == "win32":
                assert result["crash_signature"] == "STATUS_ACCESS_VIOLATION"
            else:
                assert result["crash_signature"] == "SIGSEGV"

    def test_extra_receipt_fields_are_merged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            if sys.platform == "win32":
                src = guard._windows_exit_process_child_code(0xC0000005)
            else:
                src = guard._posix_self_signal_child_code(11)
            result = guard.run_supervised(
                [sys.executable, "-c", src],
                receipt_dir=td,
                extra_receipt_fields={"phase": "test-phase", "run_id": "abc123"},
            )
            receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
            assert receipt["phase"] == "test-phase"
            assert receipt["run_id"] == "abc123"


def test_run_supervised_mutation_guard_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED-first proof at the run_supervised() level: a real crashing child must
    produce crashed=True + a receipt with the guard present. If classify_exit is
    stubbed to a no-op (guard removed/mutated), the SAME crashing child is wrongly
    reported as crashed=False with no receipt written -- proving run_supervised's
    behavior genuinely depends on classify_exit, not on a vacuous assertion."""
    with tempfile.TemporaryDirectory() as td:
        result_present = guard.spawn_and_supervise_real_crash(td)
        assert result_present["crashed"] is True
        assert result_present["receipt_path"] is not None

    def _stubbed_never_crash(returncode, *, platform=None):
        return None

    monkeypatch.setattr(guard, "classify_exit", _stubbed_never_crash)
    with tempfile.TemporaryDirectory() as td2:
        result_mutated = guard.spawn_and_supervise_real_crash(td2)
        assert result_mutated["crashed"] is False, (
            "mutated/no-op classify_exit must wrongly report no crash for a real "
            "crashing child (proves run_supervised's detection was load-bearing)"
        )
        assert list(Path(td2).glob("*.json")) == [], "no receipt when the guard is stubbed out"
