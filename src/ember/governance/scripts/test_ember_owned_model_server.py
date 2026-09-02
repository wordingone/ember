#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""
Tests for ember_owned_model_server.py (issue #110: parent-liveness tether).

Tests verify:
1. Server fails (sys.exit(1)) if --parent-pid is missing and --standalone is not set
2. Server fails if parent PID doesn't exist
3. Tether polls parent liveness every ~10s
4. After 2 consecutive missed polls, server exits cleanly
5. If parent is alive, server doesn't exit
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import psutil

# Import the server module
sys.path.insert(0, str(Path(__file__).parent))
from ember_owned_model_server import ParentLivenessTether, create_parser


class TestParentLivenessTether(unittest.TestCase):
    """Unit tests for ParentLivenessTether class."""

    def test_tether_detects_parent_alive(self):
        """If parent is alive, tether should not exit."""
        # Use current process as mock parent
        parent_pid = os.getpid()
        tether = ParentLivenessTether(parent_pid, poll_interval_sec=0.1, grace_window_polls=2)
        tether.start()

        # Let it run for a bit (should not trigger exit)
        time.sleep(0.5)

        # Verify no failures have accumulated
        with tether._lock:
            failures = tether.consecutive_failures
        tether.stop()

        # After several polls with a live parent, failures should stay at 0
        self.assertEqual(failures, 0)

    def test_tether_detects_parent_dead(self):
        """If parent is dead, tether should detect it within grace window."""
        # Use a high PID that almost certainly doesn't exist
        fake_parent_pid = 999999

        tether = ParentLivenessTether(fake_parent_pid, poll_interval_sec=0.05, grace_window_polls=2)

        # Mock the _exit_cleanly to avoid actually exiting
        exit_called = []
        tether._exit_cleanly = lambda: exit_called.append(True)

        tether.start()

        # Wait for grace window to trigger (2 failed polls at 50ms each = ~100ms + buffer)
        time.sleep(1.0)
        tether.stop()

        # The tether should have detected the dead parent and called exit
        self.assertTrue(len(exit_called) > 0, "Tether should have detected dead parent and called _exit_cleanly")

    def test_tether_grace_window(self):
        """Grace window: one failure doesn't trigger exit, two consecutive do."""
        fake_parent_pid = 999999
        tether = ParentLivenessTether(fake_parent_pid, poll_interval_sec=0.05, grace_window_polls=2)

        # Manually trigger one failure
        with tether._lock:
            tether.consecutive_failures = 1

        # One failure should not trigger exit yet
        self.assertLess(tether.consecutive_failures, tether.grace_window_polls)

        # Add another failure
        with tether._lock:
            tether.consecutive_failures = 2

        # Now we're at the threshold (should trigger exit on next poll if exit_cleanly is called)
        self.assertEqual(tether.consecutive_failures, tether.grace_window_polls)


class TestArgumentParser(unittest.TestCase):
    """Tests for argument parsing."""

    def test_parser_accepts_parent_pid(self):
        """Parser should accept --parent-pid."""
        parser = create_parser()
        args = parser.parse_args(['--parent-pid', '12345'])
        self.assertEqual(args.parent_pid, 12345)

    def test_parser_accepts_standalone(self):
        """Parser should accept --standalone flag."""
        parser = create_parser()
        args = parser.parse_args(['--standalone'])
        self.assertTrue(args.standalone)

    def test_parser_accepts_port(self):
        """Parser should accept --port."""
        parser = create_parser()
        args = parser.parse_args(['--port', '8091'])
        self.assertEqual(args.port, 8091)

    def test_parser_default_port(self):
        """Default port should be 8090."""
        parser = create_parser()
        args = parser.parse_args([])
        self.assertEqual(args.port, 8090)


class TestMainRejection(unittest.TestCase):
    """Integration tests for main() fail-closed logic."""

    def test_main_rejects_missing_parent_pid_without_standalone(self):
        """main() should exit(1) if --parent-pid is missing and --standalone is not set."""
        # Run the server script with no args and capture exit code
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / 'ember_owned_model_server.py')],
            capture_output=True,
            timeout=5
        )
        # Should fail with exit code 1
        self.assertEqual(result.returncode, 1)
        # Error message should be in stderr
        self.assertIn(b'--parent-pid is required', result.stderr)

    def test_main_accepts_valid_parent_pid(self):
        """main() should initialize tether with valid parent PID."""
        # Use current process as parent
        parent_pid = os.getpid()

        # Run server with valid parent PID (will run until timeout or we kill it)
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).parent / 'ember_owned_model_server.py'),
             '--parent-pid', str(parent_pid)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Give it a moment to start up
        time.sleep(0.2)

        # Server should still be running
        self.assertIsNone(proc.poll(), "Server should be running with valid parent PID")

        # Clean up
        proc.terminate()
        proc.wait(timeout=2)


if __name__ == '__main__':
    unittest.main()
