# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Regressions for the job-memory ceiling probe's private-commit reading.

These live apart from the certified-launch orchestration suite because they are the
only tests that exercise _current_private_commit_bytes itself. Every ceiling-probe
test in that suite injects private_commit_probe, so a green suite there never
invoked this function, and it failed on every call: GetCurrentProcess and
GetProcessMemoryInfo were called through ctypes.windll with no restype and no
argtypes, so the x64 pseudo-handle (HANDLE)-1 was marshalled as 32 bits.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "tools" / "ember-restart-3b" / "certified_train_launch.py"


def load_module():
    spec = importlib.util.spec_from_file_location("certified_train_launch", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrivateCommitProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    @unittest.skipUnless(os.name == "nt", "Windows process counters are required")
    def test_private_commit_probe_returns_plausible_nonzero_usage(self) -> None:
        self.assertGreater(self.module._current_private_commit_bytes(), 1024 * 1024)

    @unittest.skipUnless(os.name == "nt", "Windows process counters are required")
    def test_private_commit_probe_reports_a_real_win32_failure(self) -> None:
        class FakeFunction:
            def __init__(self, callback):
                self.callback = callback
                self.restype = None
                self.argtypes = None

            def __call__(self, *args):
                return self.callback(*args)

        get_current_process = FakeFunction(lambda: -1)

        def fail_get_process_memory_info(*_args):
            self.module.ctypes.set_last_error(5)
            return 0

        get_process_memory_info = FakeFunction(fail_get_process_memory_info)
        kernel32 = SimpleNamespace(GetCurrentProcess=get_current_process)
        psapi = SimpleNamespace(GetProcessMemoryInfo=get_process_memory_info)
        with mock.patch.object(
            self.module.ctypes, "WinDLL", side_effect=[kernel32, psapi]
        ):
            with self.assertRaises(OSError) as raised:
                self.module._current_private_commit_bytes()
        self.assertEqual(raised.exception.winerror, 5)
        self.assertNotEqual(raised.exception.errno, 0)
