#!/usr/bin/env python3
"""TDD: gh issue #342 -- per-probe timeout override + elapsed-seconds
disclosure in ember_totality_spec.py's run_probe().

Incident this fixes: C-BASE (test_c_base.py, hashes a 2.38GB on-disk
checkpoint + runs a real GPU forward-pass verify) was observed flapping
UNEVALUABLE<->RED/GREEN across consecutive board runs purely on the shared
180s HARNESS TIMEOUT budget -- a harness-budget defect, not evidence about
the condition. This was undiagnosable from the receipt alone: a completed
PASS gave no signal that it barely fit inside the budget, and a timeout gave
no signal of how close it actually got.

Two regression tests:
  (1) a probe with a per-filename override in PROBE_TIMEOUT_OVERRIDES gets
      that timeout instead of the 180s default, AND the timeout message
      names the overridden value, not the default.
  (2) elapsed wall-clock seconds are disclosed in `reason` on BOTH a
      completed (GREEN) path and a timeout path -- never silent either way.
"""

import importlib.util
import os
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
TOTALITY_DIR = os.path.join(REPO_ROOT, "scripts", "ember_totality")


def _load_spec_module(unique_suffix):
    """Import a FRESH copy of ember_totality_spec.py under a unique module
    name so each test can safely monkeypatch its own copy's
    PROBE_TIMEOUT_OVERRIDES without leaking into other tests."""
    name = f"ember_totality_spec_{unique_suffix}"
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(TOTALITY_DIR, "ember_totality_spec.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_probe(tmpdir, filename, body):
    path = os.path.join(tmpdir, filename)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


def test_per_probe_timeout_override_is_honored_and_named_in_timeout_message():
    mod = _load_spec_module("timeout_override")
    tmpdir = tempfile.mkdtemp()

    # A probe that sleeps well past a deliberately tiny override, so the
    # test runs fast without waiting anywhere near the real 600s C-BASE value.
    slow_probe = _write_probe(tmpdir, "slow_probe.py", (
        "import time\n"
        "time.sleep(5)\n"
        "print('GREEN should never be reached')\n"
    ))
    mod.PROBE_TIMEOUT_OVERRIDES = {"slow_probe.py": 0.5}

    row = mod.run_probe(slow_probe, dict(os.environ))
    assert row["status"] == "UNEVALUABLE", row
    assert "HARNESS TIMEOUT" in row["reason"], row
    assert "0.5s" in row["reason"], row  # the OVERRIDDEN value, not the 180s default
    assert "180s" not in row["reason"], row
    print("[PASS] per-probe timeout override is honored and named in the timeout message")


def test_elapsed_seconds_disclosed_on_both_pass_and_timeout_paths():
    mod = _load_spec_module("elapsed_disclosure")
    tmpdir = tempfile.mkdtemp()

    fast_probe = _write_probe(tmpdir, "fast_probe.py", (
        "print('GREEN fast probe completed cleanly')\n"
    ))
    slow_probe = _write_probe(tmpdir, "slow_probe2.py", (
        "import time\n"
        "time.sleep(5)\n"
        "print('GREEN should never be reached')\n"
    ))
    mod.PROBE_TIMEOUT_OVERRIDES = {"slow_probe2.py": 0.5}

    fast_row = mod.run_probe(fast_probe, dict(os.environ))
    assert fast_row["status"] == "GREEN", fast_row
    assert "elapsed" in fast_row["reason"] and "s)" in fast_row["reason"], fast_row

    slow_row = mod.run_probe(slow_probe, dict(os.environ))
    assert slow_row["status"] == "UNEVALUABLE", slow_row
    assert "elapsed" in slow_row["reason"], slow_row
    print("[PASS] elapsed seconds are disclosed in reason text on both the PASS and the timeout path")


if __name__ == "__main__":
    test_per_probe_timeout_override_is_honored_and_named_in_timeout_message()
    test_elapsed_seconds_disclosed_on_both_pass_and_timeout_paths()
    print("\n[SUCCESS] All tests passed!")
