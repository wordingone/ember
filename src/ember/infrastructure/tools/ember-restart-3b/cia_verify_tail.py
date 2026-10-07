"""Verify-only tail entry for a governed hour whose restore verification did not complete (issue #2119, lead order 66882).

    python -B cia_verify_tail.py --custody <the lost hour's custody directory>

The hour published its child and wrote `terminal-witness.json` before the verification ran (cia_hour.write_terminal_witness). This entry rebuilds the
hour's complete model and optimizer exactly as the hour built them, then runs `cia_hour.verify_tail`: the same restore verification, against the
persisted witness. It trains nothing, publishes nothing, writes no hour result and moves no head; the hour's disposition is the release authority's.

It is a GPU leg: it refuses unless the governed window marker exists (open it with gpu_window.sh open --hypothesis) and unless exactly one CUDA device
is bound to the UUID the hour's prediction declared. Execution authority is the worker boundary (`authorize`): membership in the measurement run's owned
numerical job, the explicit live gate, and a shared GPU lock held by this process's ancestor daemon with exactly one active job; a direct invocation
refuses at the first of those, before any artifact is read. The running file must also be the bytes the prediction pins (the entry is in HOUR_SOURCES).
No daemon dispatch path for a tail job exists yet, so until one does this entry refuses everywhere (fail closed).
Every refusal prints `REFUSE rc2: <why>` and exits 2, before any model is built; a check or restore failure after that prints `FAIL rc3: ...` and exits 3.
Not exercised under a real window by its test file: the refusal paths and the hand-off to `verify_tail` are tested on CPU; the GPU build is not.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

WINDOW_MARKER_ENV = 'EMBER_GPU_WINDOW_MARKER'    # the governed window's marker path, set by the window opener (same variable promote_with_pending_v1 reads)
BINDING_NAME = 'launch.json'
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


def authorize(custody: Path, *, runner, resources=None, environ=None, pid=None) -> None:
    """The worker boundary, before any artifact is read (cia_step_runner.worker / verify_worker). A marker plus old files are not execution
    authority: the process must be a member of the owned numerical job of this measurement run, launched under the explicit live gate, and the
    shared GPU lock must belong to a daemon that is this process's ancestor with exactly one active job. The lost hour's own controller and
    dispatch argv are NOT re-checked (that controller has exited); a tail job is dispatched by the daemon under its own job and lock.
    A direct invocation fails at the first check."""
    environ = os.environ if environ is None else environ
    custody = Path(custody)
    if not custody.name.startswith('measurement-'):
        raise Refused('worker custody is not a measurement run')
    run_id = custody.name.removeprefix('measurement-')
    if resources is None:
        from ember.governance.scripts import cia_conformance_resources as resources
    try:
        resources.require_owned_job(run_id, namespace=runner.JOB_NAMESPACE, host_memory_bytes=runner.LIMITS['host_memory_bytes'])
    except ValueError as error:
        raise Refused(f'not an owned daemon-dispatched job: {error}') from error
    if environ.get('EMBER_GATE_AUTHORIZED') != '1':
        raise Refused('explicit live gate condition missing')
    try:
        lock_path = Path(environ.get('EMBER_GPU_LOCK_PATH', '')).resolve(strict=True)
        lock = json.loads(lock_path.read_bytes())
    except (OSError, ValueError) as error:
        raise Refused(f'shared GPU lock is absent or unreadable: {type(error).__name__}') from error
    if not isinstance(lock, dict) or lock.get('side') != 'windows' or lock.get('active_jobs') != 1:
        raise Refused('shared GPU lock does not show exactly one active windows job')
    by_pid = {row['ProcessId']: row for row in runner.process_census()}
    current, visited = os.getpid() if pid is None else pid, set()
    while current != lock.get('daemon_pid') and current in by_pid and current not in visited:
        visited.add(current)
        current = by_pid[current]['ParentProcessId']
    if current != lock.get('daemon_pid'):
        raise Refused('the shared GPU lock daemon is not an ancestor of this process')


def pinned_entry_matches(identity: dict, runner) -> None:
    relative = ENTRY_RELATIVE
    pinned = identity.get('source_sha256', {}).get(relative)
    if pinned is None or runner.file_sha256(Path(__file__).resolve()) != runner.checked_sha(pinned):
        raise Refused('this entry point is not the source bound by the prediction')


def preflight(custody: Path, *, window_marker: Path) -> dict:
    """Everything that can be checked without importing torch or touching a GPU. Returns the launch binding."""
    require_window(window_marker)
    custody = Path(custody)
    if not custody.is_dir():
        raise Refused(f'custody {custody} is not a directory')
    import cia_hour
    if (custody / 'hour-result.json').exists():
        raise Refused('the hour already has an hour-result; there is nothing to resume')
    if (custody / cia_hour.VERIFY_TAIL_RESULT).exists():
        raise Refused('a verify tail result already exists for this hour')
    if not (custody / cia_hour.TERMINAL_WITNESS).is_file():
        raise Refused('no terminal witness: this hour never reached the restore verification, so there is nothing to verify')
    try:
        cia_hour.read_terminal_witness(None, custody)
    except ValueError as error:
        raise Refused(f'terminal witness is malformed: {error}') from error
    if not (custody / 'trained-child').is_dir():
        raise Refused('no published trained-child under the custody')
    try:
        binding = json.loads((custody / BINDING_NAME).read_bytes())
        launch = binding['launch']
        fields = (launch['prediction_sha256'], launch['run_id'], launch['gpu_uuid'])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise Refused(f'{BINDING_NAME} is absent or unreadable: {type(error).__name__}') from error
    if not all(isinstance(value, str) and value for value in fields) or re.fullmatch('[0-9a-f]{64}', fields[0]) is None:
        raise Refused(f'{BINDING_NAME} launch must carry a hex prediction_sha256 and non-empty run_id and gpu_uuid')
    if not (custody / 'prediction.json').is_file():
        raise Refused('prediction.json is absent')
    return binding


def run(custody: Path, *, window_marker: Path | None = None) -> dict:
    custody = Path(custody)
    window_marker = window_marker_from_environment() if window_marker is None else window_marker
    require_window(window_marker)
    import cia_step_runner as runner
    import cia_hour
    authorize(custody, runner=runner)
    binding = preflight(custody, window_marker=window_marker)
    prediction, _ = runner.load_prediction(custody / 'prediction.json', binding['launch']['prediction_sha256'])
    identity = prediction['identity']
    pinned_entry_matches(identity, runner)
    if identity['run_id'] != binding['launch']['run_id'] or identity['gpu_uuid'] != binding['launch']['gpu_uuid']:
        raise Refused('prediction differs from the launch binding')
    if not runner.hour_mode(identity):
        raise Refused('the prediction is not a governed hour')
    config, prepared = runner.prepare_execution(prediction)
    runner.check_layer_env(identity)
    import contextlib
    with contextlib.ExitStack() as scope:
        scope.enter_context(runner.attention_context(identity))
        import torch
        from ember.model.ember_v0_decoder import bind_triton_c_compiler
        from ember.model.ember_v0_contract import validate_cia_architecture
        c_compiler = bind_triton_c_compiler()
        validate_cia_architecture(config)
        if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
            raise Refused('one explicitly bound CUDA device is required')
        selected = runner.run_readonly(['nvidia-smi', '-i', '0', '--query-gpu=uuid', '--format=csv,noheader'], timeout=5).stdout.strip()
        if selected != identity['gpu_uuid']:
            raise Refused('CUDA index differs from the hour\'s bound device UUID')
        device = torch.device('cuda:0')
        total = torch.cuda.get_device_properties(device).total_memory
        torch.cuda.set_per_process_memory_fraction(runner.LIMITS['allocator_bytes'] / total, device)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.manual_seed(identity['seed'])
        return cia_hour.run_verify_tail(runner=runner, config=config, prepared=prepared, prediction=prediction, binding=binding,
                                        custody=custody, device=device, compiler=c_compiler, applied=lambda count: None)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != '--custody':
        print('usage: cia_verify_tail.py --custody <lost hour custody directory>')
        return 2
    try:
        result = run(Path(args[1]))
    except Refused as error:
        print(f'REFUSE rc2: {error}')
        return 2
    except (ValueError, OSError) as error:     # past the boundary: an input or restore check failed; nothing was published or moved
        print(f'FAIL rc3: {type(error).__name__}: {error}')
        return 3
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
    sys.exit(main())
