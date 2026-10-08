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
import math
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

SCORE_SCHEMA = 'ember-2119-child-episode-nll-v1'
HOLD_SCHEMA = 'ember-training-hold-v1'
UNKNOWN = 'UNKNOWN'
# the scorer states no tolerance; its mean is float64 total / targets, so a relative 1e-6 only absorbs float summation order, not a wrong number
SCORE_REL_TOL = 1e-6
_STAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')
# command-line markers of a process that holds the GPU for training; a scorer or probe holds the GPU only inside a governed window, which writes the marker
TRAINER_MARKERS = ('cia_hour.py', 'cia_step_runner.py', 'certified_train_launch.py', 'cia_verify_tail.py')


def unknown(reason: str) -> dict[str, Any]:
    return {'status': UNKNOWN, 'reason': reason}


def scores_problem(body: Any) -> str | None:
    """Why a score receipt carries no scores (None = it does). A header with the right schema, label and bindings but no measured episodes is not a measurement."""
    arms = body.get('arms') if isinstance(body, dict) else None
    fresh = arms.get('fresh') if isinstance(arms, dict) else None
    if not isinstance(fresh, dict):
        return 'the receipt has no arms.fresh section'
    episodes, mean, per_episode = fresh.get('episodes'), fresh.get('mean_nll'), fresh.get('per_episode')
    if isinstance(episodes, bool) or not isinstance(episodes, int) or episodes < 1:
        return 'arms.fresh.episodes is not a positive integer'
    if isinstance(mean, bool) or not isinstance(mean, (int, float)) or not math.isfinite(mean):
        return 'arms.fresh.mean_nll is not a finite number'
    if not isinstance(per_episode, list) or len(per_episode) != episodes:
        return 'arms.fresh.per_episode does not hold one row per episode'
    # scorer v12 writes one row per episode {shard_index, token_offset, loss_sum, targets} and the arm totals total_nll / targets / mean_nll
    # (= total_nll / targets); a row with no scored values is not a measurement, so every row and the aggregate are checked
    loss_total, target_total = 0.0, 0
    for index, row in enumerate(per_episode):
        if not isinstance(row, dict):
            return f'arms.fresh.per_episode[{index}] is not a row object'
        loss, targets = row.get('loss_sum'), row.get('targets')
        if isinstance(loss, bool) or not isinstance(loss, (int, float)) or not math.isfinite(loss) or loss < 0:
            return f'arms.fresh.per_episode[{index}].loss_sum is not a finite non-negative number'
        if isinstance(targets, bool) or not isinstance(targets, int) or targets < 1:
            return f'arms.fresh.per_episode[{index}].targets is not an integer of at least 1'
        loss_total += float(loss)
        target_total += targets
    total, arm_targets = fresh.get('total_nll'), fresh.get('targets')
    if isinstance(total, bool) or not isinstance(total, (int, float)) or not math.isfinite(total) or not math.isclose(total, loss_total, rel_tol=SCORE_REL_TOL):
        return 'arms.fresh.total_nll does not equal the sum of the row loss_sum values'
    if isinstance(arm_targets, bool) or not isinstance(arm_targets, int) or arm_targets != target_total:
        return 'arms.fresh.targets does not equal the sum of the row targets'
    if not math.isclose(mean, loss_total / target_total, rel_tol=SCORE_REL_TOL):
        return 'arms.fresh.mean_nll does not equal the row loss_sum total over the row targets total'
    return None


def gpu_owner_from_marker(marker: Path | None) -> dict[str, Any] | None:
    """Held (the marker's owner and purpose), None when there is no marker file, UNKNOWN for a marker that cannot be read or has no owner line."""
    if marker is None:
        return unknown('no window marker path was given')
    marker = Path(marker)
    if not marker.exists():
        return None
    try:
        lines = [line.strip() for line in marker.read_text(encoding='utf-8').splitlines()]      # blank lines are kept: line 2 is LITERALLY line 2
    except OSError as error:
        return unknown(f'the window marker is unreadable ({type(error).__name__})')
    if len(lines) < 2 or not lines[1]:
        return unknown('the window marker has no owner line (line 2 is missing or blank)')
    owner, _, purpose = lines[1].partition(':')
    if not owner.strip():
        return unknown('the window marker owner line is empty')
    return {'status': 'held', 'owner': owner.strip(), 'run_id': None, 'training_job_purpose': purpose.strip() or None}


def process_census() -> list[dict[str, Any]]:
    """Python processes whose command line names a training entry point (TRAINER_MARKERS). Raises on any failure to enumerate: the caller reports UNKNOWN."""
    command = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | "
               "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress")
    hidden: dict[str, Any] = {'shell': False}
    if os.name == 'nt':
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        hidden.update(creationflags=subprocess.CREATE_NO_WINDOW, startupinfo=startup)      # no console window, same boundary as every other child
    done = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, text=True,
                          timeout=60, **hidden)
    if done.returncode != 0:
        raise RuntimeError(f'the process census exited {done.returncode}')
    text = done.stdout.strip()
    return trainers_in_rows([] if not text else json.loads(text))


def trainers_in_rows(rows: Any) -> list[dict[str, Any]]:
    """Trainer processes among Win32_Process rows. A python process whose command line cannot be read (null or empty) could be a trainer, so the whole
    census raises and the caller reports UNKNOWN: an unreadable command line is never read as 'not a trainer', never as 'free'."""
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise RuntimeError('the process census returned rows that are not a list')
    found, unreadable = [], []
    for row in rows:
        line = row.get('CommandLine') if isinstance(row, dict) else None
        if not isinstance(line, str) or not line.strip():
            unreadable.append(row.get('ProcessId') if isinstance(row, dict) else None)
            continue
        for marker in TRAINER_MARKERS:
            if marker in line:
                found.append({'pid': row.get('ProcessId'), 'entry_point': marker})
                break
    if unreadable and not found:
        raise RuntimeError(f'the process census could not read the command line of python pid(s) {unreadable}')
    return found


def gpu_owner(marker: Path | None, census: Callable[[], list[dict[str, Any]]] = process_census) -> dict[str, Any]:
    """The marker's answer when the marker exists, else the census; 'free' only when both show nothing (ruling 71916)."""
    from_marker = gpu_owner_from_marker(marker)
    if from_marker is not None:
        return from_marker
    try:
        holders = census()
    except Exception as error:  # noqa: BLE001 - any failure to enumerate is UNKNOWN, never free
        return unknown(f'the process census failed ({type(error).__name__}: {str(error)[:200]}); no marker is present')
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
    missing_scores = scores_problem(body)
    if missing_scores is not None:
        return unknown(f'the measurement receipt names this head but carries no scores ({missing_scores})')
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
