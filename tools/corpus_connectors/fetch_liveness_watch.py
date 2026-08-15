#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""fetch_liveness_watch.py -- mtime staleness + terminal-state watch for an
unattended connector fetch.

    fetch_liveness_watch.py --log FILE --dest DIR [--pid N]
                            [--stale-seconds N] [--poll-seconds N]

Emits one line per state CHANGE on stdout (nothing while healthy) so it can be
attached to a notification stream without producing a firehose. Exits 0 on
clean completion, 1 on any terminal failure or unexplained death.

Why this exists: an arXiv fetch died on an unretried HTTP 429 and sat
undiscovered for hours because nothing was watching -- the only evidence was a
single 57-byte log line, and the silence looked identical to healthy progress.
Nothing here can prevent a death; the point is that a death stops being silent.

Backoff-awareness (the reason this isn't a bare `find -newermt` one-liner):
a legitimate flow-control backoff can hold the fetch quiet for up to
BACKOFF_MAX_SLEEP_SECONDS, which is far longer than any staleness threshold
useful for catching a real death. A watch that can't tell those apart forces a
choice between false alarms during every legitimate backoff and a threshold too
coarse to catch anything -- and an alarm nobody can satisfy trains everyone to
ignore alarms. So this reads the `next_attempt_at=` stamp the connector logs on
every retry: quiet time that is ACCOUNTED FOR by a pending retry is healthy,
quiet time that isn't is stale.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

NEXT_ATTEMPT_RE = re.compile(r"next_attempt_at=(\S+)")
TERMINAL_TOKENS = ("TERMINAL ", "FLOW-CONTROL-EXHAUSTED")
DONE_TOKEN = "DONE receipt committed"

# Grace beyond a declared next_attempt_at before calling it stale: the retry
# still has to make the request and receive a response after waking.
RETRY_GRACE_SECONDS = 180.0


def emit(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).isoformat()} {msg}", flush=True)


def newest_mtime(dest: Path) -> float:
    """Newest mtime among dest's immediate children, not dest's own.

    A directory's mtime updates on create/unlink of an entry but not on writes
    INTO an existing child, so watching the directory alone can read as stale
    while a large download is actively streaming into a file inside it."""
    newest = 0.0
    try:
        newest = dest.stat().st_mtime
    except OSError:
        return 0.0
    try:
        for child in dest.iterdir():
            try:
                newest = max(newest, child.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        pass
    return newest


def pending_retry_deadline(log_path: Path) -> Optional[datetime]:
    """Wall-clock time the most recent logged retry says it will wake at, or
    None if the log's last flow-control stamp is already in the past."""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    stamps = NEXT_ATTEMPT_RE.findall(text)
    if not stamps:
        return None
    try:
        when = datetime.fromisoformat(stamps[-1])
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when + timedelta(seconds=RETRY_GRACE_SECONDS)


def log_contains(log_path: Path, tokens) -> Optional[str]:
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(text.splitlines()):
        for tok in tokens:
            if tok in line:
                return line
    return None


def pid_alive(pid: Optional[int]) -> bool:
    if pid is None:
        return True  # not tracking a pid; liveness comes from mtime alone
    if sys.platform == "win32":
        import subprocess

        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=30,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return True  # can't tell -> don't cry wolf
        return str(pid) in out
    try:
        import os

        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def watch(log_path: Path, dest: Path, pid: Optional[int], stale_seconds: float, poll_seconds: float) -> int:
    emit(
        f"WATCH-START log={log_path} dest={dest} pid={pid} "
        f"stale_seconds={stale_seconds} poll_seconds={poll_seconds} "
        f"retry_grace_seconds={RETRY_GRACE_SECONDS}"
    )
    stale_announced = False
    while True:
        terminal = log_contains(log_path, TERMINAL_TOKENS)
        if terminal:
            emit(f"ALERT TERMINAL detected -- {terminal}")
            return 1
        if log_contains(log_path, (DONE_TOKEN,)):
            emit("DONE fetch completed cleanly, receipt committed")
            return 0

        if not pid_alive(pid):
            # Give the log a beat to land its final line, then decide.
            time.sleep(2)
            if log_contains(log_path, (DONE_TOKEN,)):
                emit("DONE fetch completed cleanly, receipt committed")
                return 0
            last_terminal = log_contains(log_path, TERMINAL_TOKENS)
            emit(
                f"ALERT DIED process pid={pid} is gone with no completion line -- "
                f"last terminal line: {last_terminal or '(none -- killed or crashed silently)'}"
            )
            return 1

        # Progress is EITHER a new/updated output file OR a new log line: a
        # large paper-list spends its whole metadata phase writing log lines
        # and no files at all, so watching dest alone would call a healthy
        # 27-minute metadata walk a stall.
        try:
            log_mtime = log_path.stat().st_mtime
        except OSError:
            log_mtime = 0.0
        age = time.time() - max(newest_mtime(dest), log_mtime)
        if age > stale_seconds:
            deadline = pending_retry_deadline(log_path)
            now = datetime.now(timezone.utc)
            if deadline is not None and now < deadline:
                if not stale_announced:
                    emit(
                        f"BACKOFF quiet {age:.0f}s but accounted for by a pending retry "
                        f"(waking by {deadline.isoformat()}) -- not stale"
                    )
                    stale_announced = True
            else:
                emit(
                    f"ALERT STALE no output in {age:.0f}s (threshold {stale_seconds:.0f}s) "
                    f"and no pending retry accounts for it -- fetch may be wedged"
                )
                stale_announced = True
        elif stale_announced:
            emit(f"RECOVERED output resumed (age {age:.0f}s)")
            stale_announced = False

        time.sleep(poll_seconds)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--log", type=Path, required=True, help="connector --log-file path to watch")
    p.add_argument("--dest", type=Path, required=True, help="output dir whose mtime indicates progress")
    p.add_argument("--pid", type=int, default=None, help="fetch process id, to detect death directly")
    p.add_argument(
        "--stale-seconds", type=float, default=300.0,
        help="quiet time before alarming, when no pending retry accounts for it (default 300)",
    )
    p.add_argument("--poll-seconds", type=float, default=30.0, help="poll interval (default 30)")
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    return watch(args.log, args.dest, args.pid, args.stale_seconds, args.poll_seconds)


if __name__ == "__main__":
    sys.exit(main())
