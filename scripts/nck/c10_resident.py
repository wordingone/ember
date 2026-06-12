"""NC-K C10 resident entry-point — closes #340.

Wires all four event sources (MailSource, FileWatchSource, JobReceiptSource,
ScheduleSource) against the NCKEventLoop and runs forever.

Usage:
    python scripts/nck/c10_resident.py [--config <path>]

Default config: config/nck-c10.json (relative to repo root).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_THIS)
_REPO = os.path.dirname(_SCRIPTS)

for _p in (_THIS, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nck.event_loop import (
    FileWatchSource,
    JobReceiptSource,
    MailSource,
    NCKEventLoop,
    ScheduleSource,
)

_DEFAULT_CONFIG = os.path.join(_REPO, "config", "nck-c10.json")

_BUILTIN_DEFAULTS: dict = {
    "governor": {
        "vram_fraction": 0.7,
        "margin_gib_floor": 1.0,
        "pace_s_per_step": 0.05,
    },
    "goal_file": os.path.join(_REPO, "GOAL.md"),
    "heartbeat_file": os.path.join(_REPO, "state", "nck-heartbeat.txt"),
    "journal_path": os.path.join(_REPO, "state", "nck-journal.jsonl"),
    "gate_notes_dir": os.path.join(_REPO, "state", "nck-gate-notes"),
    "event_receipts_dir": os.path.join(_REPO, "state", "nck-event-receipts"),
    "poll_interval_s": 2.0,
    # Mail source
    "mail_signal_path": os.path.join(_REPO, "..", "avir", "infra", "mailbox", "signals", "ember"),
    "mail_db_path": os.path.join(_REPO, "..", "avir", "mailbox", "mailbox.db"),
    "mail_identity": "ember",
    # File watch source
    "file_watch_dir": os.path.join(_REPO, "state", "watched"),
    "file_watch_suffix": ".json",
    # Job receipt source
    "job_receipts_dir": os.path.join(_REPO, "receipts"),
    # Schedule source
    "schedule_path": os.path.join(_REPO, "config", "nck-schedule.json"),
    # RSS cap (MiB, 0=disabled)
    "rss_cap_mib": 512,
    # Kill-switch sentinel
    "kill_flag": os.path.join(_REPO, "state", "nck-kill"),
}


def _load_config(config_path: str) -> dict:
    cfg = dict(_BUILTIN_DEFAULTS)
    if os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            overrides = json.load(f)
        cfg.update(overrides)
    return cfg


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="NC-K C10 resident event loop")
    ap.add_argument("--config", default=_DEFAULT_CONFIG, help="path to nck-c10.json")
    args = ap.parse_args(argv)

    config = _load_config(args.config)

    loop = NCKEventLoop(config)

    # Mail source
    loop.add_source(MailSource(
        signal_path=config["mail_signal_path"],
        db_path=config["mail_db_path"],
        identity=config["mail_identity"],
    ))

    # File watch source
    os.makedirs(config["file_watch_dir"], exist_ok=True)
    loop.add_source(FileWatchSource(
        watch_dir=config["file_watch_dir"],
        glob_suffix=config.get("file_watch_suffix", ""),
    ))

    # Job receipt source
    os.makedirs(config["job_receipts_dir"], exist_ok=True)
    loop.add_source(JobReceiptSource(
        receipts_dir=config["job_receipts_dir"],
    ))

    # Schedule source (optional: create empty schedule if absent)
    schedule_path = config["schedule_path"]
    if not os.path.isfile(schedule_path):
        os.makedirs(os.path.dirname(schedule_path), exist_ok=True)
        with open(schedule_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump([], f)
    loop.add_source(ScheduleSource(schedule_path=schedule_path))

    loop.run()  # perpetual (max_ticks=0)


if __name__ == "__main__":
    main()
