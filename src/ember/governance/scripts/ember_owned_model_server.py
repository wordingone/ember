#!/usr/bin/env python3
"""
Ember-owned model server with parent-liveness tether (issue #110).

The server polls parent process liveness every ~10s and exits cleanly when the
parent is gone (grace window: two consecutive missed polls). This prevents the
server from becoming an orphaned resource-holding process when the CLI crashes.

--parent-pid is REQUIRED for owned mode (fail-closed). Running without it
requires an explicit --standalone flag with its own teardown documented.
"""

import argparse
import json
import json
import os
import psutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path


class ParentLivenessTether:
    """Manages parent process liveness monitoring for owned-mode servers."""

    def __init__(self, parent_pid, poll_interval_sec=10, grace_window_polls=2):
        self.parent_pid = parent_pid
        self.poll_interval_sec = poll_interval_sec
        self.grace_window_polls = grace_window_polls
        self.consecutive_failures = 0
        self.running = False
        self._lock = threading.Lock()

    def start(self):
        """Start the background tether thread. Returns immediately."""
        self.running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=False)
        self.thread.start()

    def stop(self):
        """Stop the background tether thread."""
        with self._lock:
            self.running = False
        self.thread.join(timeout=5)

    def _poll_loop(self):
        """Background thread: poll parent liveness every poll_interval_sec."""
        while self.running:
            try:
                parent = psutil.Process(self.parent_pid)
                # Check if process still exists and is running
                if parent.is_running():
                    with self._lock:
                        self.consecutive_failures = 0
                else:
                    with self._lock:
                        self.consecutive_failures += 1
            except (psutil.NoSuchProcess, OSError):
                with self._lock:
                    self.consecutive_failures += 1
            except Exception as e:
                print(f"[tether] poll error: {e}", file=sys.stderr)
                with self._lock:
                    self.consecutive_failures += 1

            with self._lock:
                if self.consecutive_failures >= self.grace_window_polls:
                    print(f"[tether] parent PID {self.parent_pid} not responding after {self.consecutive_failures} polls", file=sys.stderr)
                    self._exit_cleanly()

            time.sleep(self.poll_interval_sec)

    def _exit_cleanly(self):
        """Log exit and terminate the server."""
        log_msg = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "event": "parent-liveness-exit",
            "parent_pid": self.parent_pid,
            "consecutive_failures": self.consecutive_failures
        }
        print(json.dumps(log_msg), file=sys.stderr)
        print(f"[tether] exiting due to parent loss", file=sys.stderr)
        os._exit(0)


def create_parser():
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        description="Ember-owned model server with parent-liveness tether"
    )
    parser.add_argument(
        "--parent-pid",
        type=int,
        help="Parent CLI process PID (required for owned mode, fail-closed)"
    )
    parser.add_argument(
        "--standalone",
        action="store_true",
        help="Run in standalone mode without parent tether (no auto-exit)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8090,
        help="Port to serve on (default: 8090)"
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        help="Directory for server logs"
    )
    return parser


def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # Fail-closed: --parent-pid is REQUIRED unless --standalone is explicit
    if not args.parent_pid and not args.standalone:
        print(
            "[owned-server] ERROR: --parent-pid is required for owned mode. "
            "Either supply --parent-pid or use --standalone (with documented teardown).",
            file=sys.stderr
        )
        sys.exit(1)

    # Initialize tether if owned mode
    tether = None
    if args.parent_pid:
        tether = ParentLivenessTether(args.parent_pid)
        try:
            parent = psutil.Process(args.parent_pid)
            if not parent.is_running():
                print(
                    f"[owned-server] ERROR: parent PID {args.parent_pid} is not running",
                    file=sys.stderr
                )
                sys.exit(1)
        except (psutil.NoSuchProcess, psutil.ProcessLookupError):
            print(
                f"[owned-server] ERROR: parent PID {args.parent_pid} does not exist",
                file=sys.stderr
            )
            sys.exit(1)

        tether.start()
        print(f"[owned-server] parent-liveness tether started (parent PID: {args.parent_pid})", file=sys.stderr)

    try:
        # Placeholder: mock server loop
        print(f"[owned-server] starting on port {args.port}", file=sys.stderr)

        # Simulate a simple server loop (in real impl, would run actual model server)
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("[owned-server] interrupted", file=sys.stderr)
    finally:
        if tether:
            tether.stop()
            print("[owned-server] tether stopped", file=sys.stderr)


if __name__ == "__main__":
    main()
