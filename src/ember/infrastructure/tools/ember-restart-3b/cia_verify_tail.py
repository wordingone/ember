"""Verify-only tail entry for a governed hour whose restore verification did not complete (issue #2119, lead order 66882).

    python -B cia_verify_tail.py --custody <the lost hour's custody directory>

The hour published its child and wrote `terminal-witness.json` before the verification ran (cia_hour.write_terminal_witness). This entry rebuilds the
hour's complete model and optimizer exactly as the hour built them, then runs `cia_hour.verify_tail`: the same restore verification, against the
persisted witness. It trains nothing, publishes nothing, writes no hour result and moves no head; the hour's disposition is the release authority's.

It is a GPU leg: it refuses unless the governed window marker exists (open it with gpu_window.sh open --hypothesis) and unless exactly one CUDA device
is bound to the UUID the hour's prediction declared. Every refusal prints `REFUSE rc2: <why>` and exits 2, before any model is built.
Not exercised under a real window by its test file: the refusal paths and the hand-off to `verify_tail` are tested on CPU; the GPU build is not.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import sys
from pathlib import Path

WINDOW_MARKER = Path('B:/M/avir/leo/state/gpu-window-open')
BINDING_NAME = 'launch.json'


class Refused(ValueError):
    pass


def preflight(custody: Path, *, window_marker: Path = WINDOW_MARKER) -> dict:
    """Everything that can be checked without importing torch or touching a GPU. Returns the launch binding."""
    if not window_marker.exists():
        raise Refused('no governed GPU window is open (gpu_window.sh open --hypothesis); the tail is a GPU leg')
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
    if not (custody / 'trained-child').is_dir():
        raise Refused('no published trained-child under the custody')
    try:
        binding = json.loads((custody / BINDING_NAME).read_bytes())
        digest = binding['launch']['prediction_sha256']
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise Refused(f'{BINDING_NAME} is absent or unreadable: {type(error).__name__}') from error
    if not (custody / 'prediction.json').is_file():
        raise Refused('prediction.json is absent')
    return binding


def run(custody: Path, *, window_marker: Path = WINDOW_MARKER) -> dict:
    custody = Path(custody)
    binding = preflight(custody, window_marker=window_marker)
    import cia_step_runner as runner
    import cia_hour
    prediction, _ = runner.load_prediction(custody / 'prediction.json', binding['launch']['prediction_sha256'])
    identity = prediction['identity']
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
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
    sys.exit(main())
