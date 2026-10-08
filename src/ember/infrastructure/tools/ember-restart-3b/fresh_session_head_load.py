"""Issue #2119 row 9: a fresh session loads the selected head from durable state, and the receipt proves it was a fresh process.

    fresh_session_head_load.py --receipts-root RECEIPTS_ROOT --out fresh-session-load-receipt.json [--head-dir DIR] [--controls]

The parent spawns a CHILD python process (`--child`, a new interpreter that shares no memory with the parent or with any earlier session) which:
  1. reads the selected-continuation-head pointer from disk (no caller-supplied head);
  2. checks the hour result the pointer names hashes to the pointer's `hour_result_sha256` and that its child is the pointer's lineage head;
  3. resolves the head directory (default: `trained-child` beside the hour result; `--head-dir` overrides) and requires its checkpoint-manifest.json
     bytes to hash to the pointer's lineage head;
  4. runs the SAME admission the next hour's launch runs on its parent: `parameter_counter._cia_parent_snapshot(head, expected_digest=pointer head)`;
  5. with `--controls`, runs it again with a wrong digest, which must refuse (the load is not vacuous).
The parent records its own pid and the child's pid (they must differ), the child's start time and python executable, and writes the receipt atomically.
It confirms nothing: The coordinator's confirmation of the load is a ruling on this receipt.

Exit codes: 0 loaded (and, with --controls, the wrong-digest control refused), 3 refused before admission, 4 admission refused or the control did not refuse.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECEIPT_SCHEMA = 'ember-fresh-session-head-load-v1'
CHILD_MARKER = 'FRESH_SESSION_CHILD_RESULT '


class LoadRefusal(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_head(receipts_root: Path, *, head_dir: Path | None = None, controls: bool = False, admit=None) -> dict:
    """Everything the child does. `admit(head_dir, expected_digest, max_restore_payload_bytes)` is the admission; the default is the launch's own."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import selected_continuation_head as sch
    pointer_file = sch.pointer_path(Path(receipts_root))
    if not pointer_file.is_file():
        raise LoadRefusal(f'no selected-continuation-head pointer at {pointer_file}')
    pointer = sch.load_selected_continuation_head(pointer_file)
    head = pointer['lineage_checkpoint_manifest_sha256']
    hour_result = Path(pointer['hour_result_path'])
    if not hour_result.is_file():
        raise LoadRefusal(f'the pointer names an hour result that is not a file: {hour_result}')
    if _sha256(hour_result) != pointer['hour_result_sha256']:
        raise LoadRefusal('the hour result bytes do not hash to the pointer hour_result_sha256')
    if json.loads(hour_result.read_text(encoding='utf-8')).get('child_manifest_sha256') != head:
        raise LoadRefusal('the hour result child differs from the pointer lineage head')
    directory = Path(head_dir) if head_dir is not None else hour_result.parent / 'trained-child'
    manifest = directory / 'checkpoint-manifest.json'
    if not manifest.is_file():
        raise LoadRefusal(f'the head directory has no checkpoint-manifest.json: {directory}')
    if _sha256(manifest) != head:
        raise LoadRefusal('the head directory manifest bytes do not hash to the pointer lineage head')
    cap = json.loads(manifest.read_text(encoding='utf-8'))['max_restore_payload_bytes']
    if admit is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location('parameter_counter', HERE / 'parameter_counter.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules['parameter_counter'] = module
        spec.loader.exec_module(module)

        def admit(path, expected, cap_bytes):
            parent, _ = module._cia_parent_snapshot(str(path), max_restore_payload_bytes=cap_bytes, expected_digest=expected)
            return {'global_step': parent['data_cursor']['global_step'], 'genesis_kind': parent['genesis_provenance']['kind']}

    def attempt(expected):
        started = time.monotonic()
        try:
            return dict(admit(directory, expected, cap), outcome='ADMITTED', seconds=round(time.monotonic() - started, 1))
        except Exception as error:  # noqa: BLE001 - the receipt records the exact refusal class and text
            return {'outcome': 'REFUSED', 'error_class': type(error).__name__, 'error': str(error)[:300], 'seconds': round(time.monotonic() - started, 1)}

    result = {'pointer_sha256': _sha256(pointer_file), 'lineage_head': head, 'hour_result_sha256': pointer['hour_result_sha256'],
              'admission': attempt(head)}
    if controls:
        result['control_wrong_digest'] = attempt('0' * 64)
    return result


def run_fresh(child_command: list[str]) -> dict:
    """Spawn the child interpreter and return its result with process facts. A child that shares the parent's pid refuses."""
    started = time.time()
    done = subprocess.run(child_command, capture_output=True, text=True, timeout=3600)
    lines = [line for line in done.stdout.splitlines() if line.startswith(CHILD_MARKER)]
    if done.returncode not in (0, 3, 4) or not lines:
        raise LoadRefusal(f'the child produced no result (exit {done.returncode}): {done.stderr.strip()[-300:]}')
    child = json.loads(lines[-1][len(CHILD_MARKER):])
    if child.get('pid') == os.getpid():
        raise LoadRefusal('the child ran in the parent process, so it is not a fresh session')
    child['parent_pid'] = os.getpid()
    child['spawned_at_epoch'] = started
    child['child_exit'] = done.returncode
    return child


def child_main(argv) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--receipts-root', required=True, type=Path)
    parser.add_argument('--head-dir', type=Path)
    parser.add_argument('--controls', action='store_true')
    args = parser.parse_args(argv)
    facts = {'pid': os.getpid(), 'python': sys.executable, 'child_started_epoch': time.time()}
    try:
        facts['result'] = load_head(args.receipts_root, head_dir=args.head_dir, controls=args.controls)
    except (LoadRefusal, OSError, ValueError, KeyError) as error:
        facts['refused'] = f'{type(error).__name__}: {error}'
        print(CHILD_MARKER + json.dumps(facts, sort_keys=True, default=str))
        return 3
    ok = facts['result']['admission']['outcome'] == 'ADMITTED' and (
        not args.controls or facts['result']['control_wrong_digest']['outcome'] == 'REFUSED')
    print(CHILD_MARKER + json.dumps(facts, sort_keys=True, default=str))
    return 0 if ok else 4


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == '--child':
        return child_main(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--receipts-root', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--head-dir', type=Path)
    parser.add_argument('--controls', action='store_true')
    args = parser.parse_args(argv)
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--child', '--receipts-root', str(args.receipts_root)]
    if args.head_dir is not None:
        command += ['--head-dir', str(args.head_dir)]
    if args.controls:
        command.append('--controls')
    try:
        child = run_fresh(command)
    except LoadRefusal as error:
        print(json.dumps({'status': 'REFUSED', 'error': str(error)}, sort_keys=True))
        return 3
    receipt = {'schema': RECEIPT_SCHEMA, 'ts': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'controls_requested': args.controls, 'child': child}
    temporary = args.out.with_name(args.out.name + '.tmp')
    temporary.write_text(json.dumps(receipt, indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    os.replace(temporary, args.out)
    print(json.dumps({'status': 'WRITTEN', 'out': str(args.out).replace('\\', '/'), 'child_exit': child['child_exit']}, sort_keys=True))
    return child['child_exit']


if __name__ == '__main__':
    sys.exit(main())
