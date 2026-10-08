"""Verify-only tail for a governed hour whose restore verification did not complete (issue #2119, lead orders 66882, 67346).

The hour published its child and wrote `terminal-witness.json` before the verification ran (cia_hour.write_terminal_witness). A tail is its OWN
dispatched job: a fresh `tail_run_id`, its own custody `measurement-<tail_run_id>`, run by `cia_step_runner.py --worker`. The lost hour's custody is a
READ-ONLY input named in the tail prediction (`identity['verify_tail']`: lost custody, lost run id, witness digest, published-child manifest digest),
so a witness or child changed after the prediction froze is refused. The tail rebuilds the hour's complete model and optimizer exactly as the hour
built them (`cia_hour.build_hour_model`), then runs `cia_hour.verify_tail`: the same restore verification, against the persisted witness. It trains
nothing, publishes nothing, writes no hour result, moves no head and writes nothing into the lost custody; `verify-tail-result.json` lands in the
tail's own custody after that job's worker-terminal (`cia_hour.write_verify_tail_result`) and the release authority reads it by digest from there.

Execution authority is the runner's own worker boundary (`cia_step_runner.verify_worker`, unchanged): membership in the tail's owned numerical job,
the controller's argv and ancestry, the canonical daemon, the shared GPU lock and the explicit live gate. This module adds only what is specific to a
tail and is called by the worker before the model is built: the governed GPU window must be open (`preflight`), the prediction and launch must name
the owned tail run and device, and the lost custody must still match its frozen digests. The entry is pinned by a tail prediction alone (TAIL_SOURCES).
There is no command-line entry: `main` refuses, so a direct invocation cannot build or verify anything. No daemon dispatch of a tail has run yet;
the GPU build and the restore against the witness are not exercised by this file's tests (CPU only).
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import os
import sys
from pathlib import Path

WINDOW_MARKER_ENV = 'EMBER_GPU_WINDOW_MARKER'    # the governed window's marker path, set by the window opener (same variable promote_with_pending_v1 reads)
ENTRY_RELATIVE = 'src/ember/infrastructure/tools/ember-restart-3b/cia_verify_tail.py'


class Refused(ValueError):
    pass


def window_marker_from_environment(environ=None) -> Path:
    value = (os.environ if environ is None else environ).get(WINDOW_MARKER_ENV)
    if not value:
        raise Refused(f'{WINDOW_MARKER_ENV} is not set: no governed GPU window is bound to this process')
    return Path(value)


def require_window(window_marker: Path) -> None:
    if not window_marker.exists():
        raise Refused('no governed GPU window is open (gpu_window.sh open --hypothesis); the tail is a GPU leg')


def check_run_identity(custody: Path, binding: dict, identity: dict) -> None:
    """The owned job id (the TAIL custody basename), the launch binding and the prediction must all name one run and one device, and that run is
    never the lost hour's."""
    run_id = Path(custody).name.removeprefix('measurement-')
    if identity['run_id'] != run_id or binding['launch']['run_id'] != run_id:
        raise Refused('prediction or launch binding names another run than the owned tail custody')
    if identity['gpu_uuid'] != binding['launch']['gpu_uuid']:
        raise Refused('prediction differs from the launch binding')
    if identity['verify_tail']['lost_run_id'] == run_id:
        raise Refused('the tail run id is the lost hour run id')


def pin_lost_custody(identity: dict, *, hour_module) -> tuple:
    """Everything about the lost custody that can be checked without importing torch or touching a GPU, against the digests frozen in the tail
    prediction. Read-only. Returns (witness, witness sha256 of the one read)."""
    pin = identity['verify_tail']
    lost = Path(pin['lost_custody'])
    if not lost.is_dir():
        raise Refused(f'lost custody {lost} is not a directory')
    if lost.name != 'measurement-' + pin['lost_run_id']:
        raise Refused('lost custody is not the measurement directory of the lost run id')
    if (lost / 'hour-result.json').exists():
        raise Refused('the hour already has an hour-result; there is nothing to resume')
    if not (lost / hour_module.TERMINAL_WITNESS).is_file():
        raise Refused('no terminal witness: this hour never reached the restore verification, so there is nothing to verify')
    try:
        witness, digest = hour_module.read_terminal_witness(None, lost)
    except ValueError as error:
        raise Refused(f'terminal witness is malformed: {error}') from error
    if digest != pin['witness_sha256']:
        raise Refused('terminal witness bytes differ from the digest frozen in the tail prediction')
    if witness['child_manifest_sha256'] != pin['child_manifest_sha256']:
        raise Refused('terminal witness describes another child than the one frozen in the tail prediction')
    if not (lost / 'trained-child').is_dir():
        raise Refused('no published trained-child under the lost custody')
    return witness, digest


def preflight(custody: Path, binding: dict, identity: dict, *, hour_module, window_marker: Path | None = None) -> tuple:
    """Called by cia_step_runner.worker after verify_worker and before any model is built."""
    require_window(window_marker_from_environment() if window_marker is None else window_marker)
    check_run_identity(custody, binding, identity)
    return pin_lost_custody(identity, hour_module=hour_module)


def main(argv: list[str] | None = None) -> int:
    print('REFUSE rc2: the verify tail has no command line; it runs only as a daemon-dispatched tail job (cia_step_runner.py --worker)')
    return 2


if __name__ == '__main__':
    sys.exit(main())
