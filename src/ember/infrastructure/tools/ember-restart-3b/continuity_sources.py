"""Issue #2119 row 7 (status producer side): the three live sources the continuity status reads, each with an explicit UNKNOWN when its source is missing.

Ruling 71869 (2026-10-08): the status shows (1) the last valid measurement with its time and receipt, (2) the GPU owner and purpose from the window marker, or "free",
(3) occupancy and postponement -- whether an hour is postponed and why. A missing or unreadable source reads UNKNOWN with the reason, never blank and never a
value carried over from another source. Every function reads files only (no process census, no GPU query, no python of its own beyond the caller's) and
returns plain dicts for `training_continuity_status.training_continuity_status`.

  gpu_owner(marker, census)                marker line 2 when the marker exists; else the process census; 'free' only when BOTH show nothing; UNKNOWN if the census fails
                                           (ruling 71916: not marker-only)
  gpu_owner_from_marker(marker)            the marker half: present -> held (owner, purpose from the label line); absent -> None; unreadable -> UNKNOWN
  last_measurement_from_receipt(path, head) a scorer receipt for exactly `head` -> measured (time, receipt name, sha256); anything else -> UNKNOWN + reason
  postponement_from_hold(path)             a hold record -> postponed True with its reason and since; absent source -> postponed 'UNKNOWN'

Marker format (the governed window script): line 1 the UTC open time, line 2 `<owner>: <reason>`.
Hold record: JSON object {"schema": "ember-training-hold-v1", "since": UTC stamp, "reason": text, "source": text} (source = the operator message or ruling it comes from).
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

SCORE_SCHEMA = 'ember-2119-child-episode-nll-v1'
HOLD_SCHEMA = 'ember-training-hold-v1'
UNKNOWN = 'UNKNOWN'
_STAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')
# command-line markers of a process that holds the GPU for training; a scorer or probe holds the GPU only inside a governed window, which writes the marker
TRAINER_MARKERS = ('cia_hour.py', 'cia_step_runner.py', 'certified_train_launch.py', 'cia_verify_tail.py')


def unknown(reason: str) -> dict[str, Any]:
    return {'status': UNKNOWN, 'reason': reason}


def gpu_owner_from_marker(marker: Path | None) -> dict[str, Any] | None:
    """Held (the marker's owner and purpose), None when there is no marker file, UNKNOWN for a marker that cannot be read or has no owner line."""
    if marker is None:
        return unknown('no window marker path was given')
    marker = Path(marker)
    if not marker.exists():
        return None
    try:
        lines = [line.strip() for line in marker.read_text(encoding='utf-8').splitlines() if line.strip()]
    except OSError as error:
        return unknown(f'the window marker is unreadable ({type(error).__name__})')
    if len(lines) < 2:
        return unknown('the window marker has no owner line')
    owner, _, purpose = lines[1].partition(':')
    if not owner.strip():
        return unknown('the window marker owner line is empty')
    return {'status': 'held', 'owner': owner.strip(), 'run_id': None, 'training_job_purpose': purpose.strip() or None}


def process_census() -> list[dict[str, Any]]:
    """Python processes whose command line names a training entry point (TRAINER_MARKERS). Raises on any failure to enumerate: the caller reports UNKNOWN."""
    command = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | "
               "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress")
    flags = 0x08000000 if os.name == 'nt' else 0
    done = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, text=True,
                          timeout=60, creationflags=flags)
    if done.returncode != 0:
        raise RuntimeError(f'the process census exited {done.returncode}')
    text = done.stdout.strip()
    rows = [] if not text else json.loads(text)
    if isinstance(rows, dict):
        rows = [rows]
    found = []
    for row in rows:
        line = row.get('CommandLine') or ''
        for marker in TRAINER_MARKERS:
            if marker in line:
                found.append({'pid': row.get('ProcessId'), 'entry_point': marker})
                break
    return found


def gpu_owner(marker: Path | None, census: Callable[[], list[dict[str, Any]]] = process_census) -> dict[str, Any]:
    """The marker's answer when the marker exists, else the census; 'free' only when both show nothing (ruling 71916)."""
    from_marker = gpu_owner_from_marker(marker)
    if from_marker is not None:
        return from_marker
    try:
        holders = census()
    except Exception as error:  # noqa: BLE001 - any failure to enumerate is UNKNOWN, never free
        return unknown(f'the process census failed ({type(error).__name__}); no marker is present')
    if not holders:
        return {'status': 'free'}
    first = holders[0]
    return {'status': 'held', 'owner': 'process census', 'run_id': None,
            'training_job_purpose': f"{first['entry_point']} (pid {first['pid']}), no window marker"}


def last_measurement_from_receipt(receipt: Path | None, head_manifest_sha256: str) -> dict[str, Any]:
    """The newest valid measurement for exactly this head. A receipt for another checkpoint is UNKNOWN, never carried forward as this head's."""
    if receipt is None:
        return unknown('no measurement receipt was named')
    receipt = Path(receipt)
    try:
        raw = receipt.read_bytes()
        body = json.loads(raw)
    except (OSError, ValueError) as error:
        return unknown(f'the measurement receipt is unreadable ({type(error).__name__})')
    bindings = body.get('bindings') if isinstance(body, dict) else None
    if not isinstance(bindings, dict) or body.get('schema') != SCORE_SCHEMA:
        return unknown(f'the measurement receipt is not a {SCORE_SCHEMA} receipt')
    if bindings.get('checkpoint_manifest_sha256') != head_manifest_sha256:
        return unknown('the newest measurement receipt scores a different checkpoint than the selected head')
    finished = body.get('finished_utc')
    if not isinstance(finished, str) or _STAMP.fullmatch(finished) is None:
        return unknown('the measurement receipt carries no UTC finish time')
    return {'status': 'measured', 'measurement': {
        'measured_at': finished, 'receipt': receipt.name, 'receipt_sha256': hashlib.sha256(raw).hexdigest(),
        'label': str(body.get('label', '')), 'episode_plan_sha256': bindings.get('episode_plan_sha256')}}


def postponement_from_hold(hold: Path | None) -> dict[str, Any]:
    """Whether an hour is postponed and why. A source that is absent says UNKNOWN; it never says 'not postponed' by silence."""
    if hold is None:
        return {'postponed': UNKNOWN, 'postponement_reason': 'no hold record was named'}
    hold = Path(hold)
    if not hold.exists():
        return {'postponed': UNKNOWN, 'postponement_reason': 'the hold record does not exist'}
    try:
        body = json.loads(hold.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        return {'postponed': UNKNOWN, 'postponement_reason': f'the hold record is unreadable ({type(error).__name__})'}
    if (not isinstance(body, dict) or body.get('schema') != HOLD_SCHEMA or not isinstance(body.get('reason'), str) or not body['reason'].strip()
            or not isinstance(body.get('since'), str) or _STAMP.fullmatch(body['since']) is None
            or not isinstance(body.get('source'), str) or not body['source'].strip()):
        return {'postponed': UNKNOWN, 'postponement_reason': f'the hold record is not a closed {HOLD_SCHEMA} record'}
    return {'postponed': True, 'postponement_reason': f"{body['reason'].strip()} (since {body['since']}; source {body['source'].strip()})"}
