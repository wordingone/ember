"""Declared pause, post-update parameter dumps and their offline comparator (issue #2115 pair protocol).

A governed hour may declare a pause after its hour result is durable. The worker records what is on disk,
waits, and an operator may end it by a PID-cohort kill with intent and outcome receipts. Only that
declared case is admitted as a continuation source by `validate_terminated_source`; every other
non-clean hour is refused exactly as before. Claim boundary: this widens "completed" for the declared
case only. It credits no training, qualifies nothing and changes no frozen criterion.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

PAUSE_KIND = 'ember-cia-declared-pause-v1'
POSITIONS = ('after-hour-result', 'after-witness')
MAX_PAUSE_SECONDS = 3600
DUMP_KIND = 'ember-cia-parameter-dump-v1'
DUMP_SCOPE = 'optimizer-state-owners'
# Dumps hold only the parameters that carry optimizer state: about 72.6 M elements under the layer template.
DUMP_EXTRA_B_WRITE_GIB = 2
ENTERED = 'pause-entered.json'
EXITED = 'pause-exited.json'
TERMINATION = 'pause-termination.json'
ENTERED_SCHEMA = 'ember-cia-pause-entered-v1'
EXITED_SCHEMA = 'ember-cia-pause-exited-v1'
TERMINATION_SCHEMA = 'ember-cia-pause-termination-v1'
DUMP_LIVE = 'continuation-parameters-live.pt'
DUMP_REPRODUCED = 'continuation-parameters-reproduced.pt'
BOUND_ALWAYS = ('hour-result.json', 'prediction.json', 'rows.jsonl', 'terminal-witness.json',
                'continuation-reference.json', 'continuation-hour.json', 'continuation-next-pack.json',
                'trained-child/checkpoint-manifest.json')
BOUND_IF_PRESENT = ('model.json', 'gc-events.jsonl', 'gc-freeze.json')


def pause_declaration(identity):
    """The validated declaration, or None when the identity declares no pause."""
    if 'declared_pause' not in identity:
        return None
    value = identity['declared_pause']
    if (not isinstance(value, dict) or set(value) != {'kind', 'position', 'seconds'}
            or value['kind'] != PAUSE_KIND or value['position'] not in POSITIONS
            or type(value['seconds']) is not int or not 0 < value['seconds'] <= MAX_PAUSE_SECONDS):
        raise ValueError('declared_pause is {kind, position, seconds} with an int in (0, %d]' % MAX_PAUSE_SECONDS)
    hour = identity.get('hour')
    if (not isinstance(hour, dict) or hour.get('schema') != 'governed-hour-v1'
            or any(key in identity for key in ('continuation', 'verify_tail', 'checkpoint_probe', 'measurement', 'trajectory'))):
        raise ValueError('declared_pause belongs to a governed-hour-v1 identity only')
    return value


def dump_declared(identity):
    if 'parameter_dump' not in identity:
        return False
    value = identity['parameter_dump']
    if (not isinstance(value, dict) or set(value) != {'kind', 'scope'}
            or value['kind'] != DUMP_KIND or value['scope'] != DUMP_SCOPE):
        raise ValueError('parameter_dump is {kind, scope} with the pinned values')
    hour = identity.get('hour')
    if (not isinstance(hour, dict) or hour.get('schema') != 'governed-hour-v1' or 'verify_tail' in identity
            or any(key in identity for key in ('checkpoint_probe', 'measurement', 'trajectory'))):
        raise ValueError('parameter_dump belongs to a governed hour or its continuation only')
    return True


def extra_wall_seconds(identity):
    declaration = pause_declaration(identity)
    return 0 if declaration is None else declaration['seconds']


def extra_b_write_gib(identity):
    return DUMP_EXTRA_B_WRITE_GIB if dump_declared(identity) else 0


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _write_new(path, value):
    with Path(path).open('xb') as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())
        stream.flush()
        os.fsync(stream.fileno())


def dump_updated_parameters(path, optimizer, inventory):
    """Write the parameters that carry optimizer state, dtype and bytes exactly as they are, once."""
    import torch
    names = sorted(name for name, parameter in inventory.items() if optimizer.state.get(parameter))
    if not names:
        raise ValueError('parameter dump found no optimizer-state owners')
    tensors = {name: inventory[name].detach().to('cpu').contiguous() for name in names}
    path = Path(path)
    if path.exists():
        raise ValueError('parameter dump already exists: ' + path.name)
    temporary = path.with_name(path.name + '.partial')
    torch.save(tensors, temporary)
    with temporary.open('r+b') as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    return dict(path=path.name, sha256=_sha256(path), tensors=len(names),
                elements=sum(tensor.numel() for tensor in tensors.values()),
                dtypes=sorted({str(tensor.dtype) for tensor in tensors.values()}))


def enter_pause(custody, identity, *, position, physical_positions, sleep=time.sleep, clock=time.time, pid=None):
    """Record what is durable, hold the declared seconds in one-second steps, then record the exit."""
    declaration = pause_declaration(identity)
    if declaration is None or declaration['position'] != position:
        return 0.0
    custody = Path(custody)
    names = [name for name in BOUND_ALWAYS if (custody / name).is_file()]
    names += [name for name in BOUND_IF_PRESENT if (custody / name).is_file()]
    names += [name for name in (DUMP_LIVE,) if dump_declared(identity) and (custody / name).is_file()]
    entered_at = clock()
    _write_new(custody / ENTERED, dict(schema=ENTERED_SCHEMA, run_id=identity['run_id'], pid=os.getpid() if pid is None else pid,
        position=position, seconds=declaration['seconds'], entered_unix=entered_at,
        physical_positions=physical_positions, files={name: _sha256(custody / name) for name in names},
        claim='Durable state at a declared pause; no qualification and no credit'))
    held = 0
    while held < declaration['seconds']:
        sleep(1)
        held += 1
    exited_at = clock()
    _write_new(custody / EXITED, dict(schema=EXITED_SCHEMA, run_id=identity['run_id'], exited_unix=exited_at,
        entered_unix=entered_at, held_seconds=held))
    return exited_at - entered_at


def _bound(root, name, files):
    if name not in files:
        raise ValueError('declared pause marker does not bind ' + name)
    path = Path(root) / name
    if not path.is_file() or _sha256(path) != files[name]:
        raise ValueError('declared pause bound file differs: ' + name)


def validate_terminated_source(runner, root, prior, hour, result_sha256):
    """The one outcome class `terminated_in_declared_pause`; returns the worker's physical position tally.

    Admissible only when the prior identity carried the pinned declaration, the marker bound every durable
    file by digest before the signal, no exit was recorded, and a cohort kill with intent then outcome
    receipts landed inside the declared window. Anything else raises."""
    root = Path(root)
    declaration = pause_declaration(prior)
    if declaration is None:
        raise ValueError('declared pause: the source hour declared no pause')
    if not (root / ENTERED).is_file():
        raise ValueError('declared pause: the source hour never entered its pause')
    if (root / EXITED).exists():
        raise ValueError('declared pause: the pause exited; this is not a termination')
    if (root / 'worker-terminal.json').exists():
        raise ValueError('declared pause: the worker wrote its own terminal')
    entered = json.loads((root / ENTERED).read_bytes())
    if (entered.get('schema') != ENTERED_SCHEMA or entered.get('run_id') != prior['run_id']
            or entered.get('position') != declaration['position'] or entered.get('seconds') != declaration['seconds']
            or type(entered.get('pid')) is not int or type(entered.get('physical_positions')) is not int
            or not isinstance(entered.get('files'), dict)):
        raise ValueError('declared pause: entered marker differs from the declaration')
    if declaration['position'] != 'after-hour-result':
        raise ValueError('declared pause: a continuation needs the hour result durable before the signal')
    required = set(BOUND_ALWAYS)
    if dump_declared(prior):
        required.add(DUMP_LIVE)
    for name in sorted(required):
        _bound(root, name, entered['files'])
    if entered['files']['hour-result.json'] != result_sha256:
        raise ValueError('declared pause: the marker binds a different hour result')
    for name in entered['files']:
        _bound(root, name, entered['files'])
    termination = json.loads((root / TERMINATION).read_bytes()) if (root / TERMINATION).is_file() else None
    if termination is None or termination.get('schema') != TERMINATION_SCHEMA or termination.get('run_id') != prior['run_id']:
        raise ValueError('declared pause: no cohort termination receipt')
    intent, outcome = termination.get('intent'), termination.get('outcome')
    if (not isinstance(intent, dict) or not isinstance(outcome, dict)
            or intent.get('root_pid') != entered['pid'] or entered['pid'] not in intent.get('cohort', ())
            or not entered['entered_unix'] <= intent.get('written_unix', -1) < entered['entered_unix'] + declaration['seconds']
            or outcome.get('intent_sha256') != hashlib.sha256(json.dumps(intent, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            or outcome.get('written_unix', -1) < intent['written_unix'] or outcome.get('all_gone') is not True
            or outcome.get('remaining') != []):
        raise ValueError('declared pause: termination intent and outcome receipts differ from the marker')
    return entered['physical_positions']


def process_cohort(root_pid, table):
    """Root pid plus every descendant, from a {pid: parent_pid} table."""
    if root_pid not in table:
        raise ValueError('declared pause: root pid is not alive')
    cohort, frontier = {root_pid}, [root_pid]
    while frontier:
        current = frontier.pop()
        for pid, parent in table.items():
            if parent == current and pid not in cohort:
                cohort.add(pid)
                frontier.append(pid)
    return sorted(cohort)


def _process_table():
    text = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-Command',
        "Get-CimInstance Win32_Process | ForEach-Object { '{0} {1}' -f $_.ProcessId,$_.ParentProcessId }"],
        capture_output=True, text=True, timeout=60, check=True).stdout
    return {int(a): int(b) for a, b in (line.split() for line in text.splitlines() if line.strip())}


def _kill(pid):
    subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True, timeout=60)


def terminate_in_pause(custody, *, table=None, kill=_kill, clock=time.time):
    """Kill the paused worker's PID cohort. Intent receipt first, outcome receipt after; PID-only, never a name match."""
    custody = Path(custody)
    if (custody / EXITED).exists() or (custody / TERMINATION).exists() or (custody / 'worker-terminal.json').exists():
        raise ValueError('declared pause: not terminable (exited, already terminated, or terminal written)')
    entered = json.loads((custody / ENTERED).read_bytes())
    now = clock()
    if not entered['entered_unix'] <= now < entered['entered_unix'] + entered['seconds']:
        raise ValueError('declared pause: outside the declared window')
    live = _process_table() if table is None else table
    cohort = process_cohort(entered['pid'], live)
    intent = dict(root_pid=entered['pid'], cohort=cohort, written_unix=now,
                  action='kill the paused worker cohort by PID only; hour result is already durable')
    path = custody / TERMINATION
    head = dict(schema=TERMINATION_SCHEMA, run_id=entered['run_id'], intent=intent)
    _write_new(path, head)   # intent lands before any signal
    for pid in sorted(cohort, reverse=True):
        kill(pid)
    after = _process_table() if table is None else {pid: parent for pid, parent in table.items() if pid not in cohort}
    remaining = sorted(pid for pid in cohort if pid in after)
    outcome = dict(intent_sha256=hashlib.sha256(json.dumps(intent, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                   written_unix=clock(), all_gone=not remaining, remaining=remaining)
    final = dict(head, outcome=outcome)
    temporary = path.with_name(path.name + '.final')
    _write_new(temporary, final)
    os.replace(temporary, path)
    return final


def compare_dumps(first, second):
    """Bitwise comparison of two parameter dumps. No tolerance exists here: any difference refuses."""
    import torch
    a = torch.load(first, map_location='cpu', weights_only=True)
    b = torch.load(second, map_location='cpu', weights_only=True)
    report = dict(first=str(first), second=str(second), first_sha256=_sha256(first), second_sha256=_sha256(second),
                  names_only_in_first=sorted(set(a) - set(b)), names_only_in_second=sorted(set(b) - set(a)), differing=[], compared=0)
    for name in sorted(set(a) & set(b)):
        report['compared'] += 1
        x, y = a[name], b[name]
        if x.dtype != y.dtype or x.shape != y.shape:
            report['differing'].append(dict(name=name, reason='dtype or shape', first=[str(x.dtype), list(x.shape)],
                                            second=[str(y.dtype), list(y.shape)]))
            continue
        if torch.equal(x.contiguous().view(-1).view(torch.uint8), y.contiguous().view(-1).view(torch.uint8)):
            continue
        xf, yf = x.double(), y.double()
        delta = (xf - yf)
        report['differing'].append(dict(name=name, dtype=str(x.dtype), max_abs_diff=float(delta.abs().max()),
            relative_l2=float(delta.norm() / (xf.norm() + 1e-300)), elements=int(x.numel()), elements_differing=int((x != y).sum())))
    report['bitwise_equal'] = not (report['names_only_in_first'] or report['names_only_in_second'] or report['differing'])
    report['verdict'] = 'BITWISE_EQUAL' if report['bitwise_equal'] else 'REFUSE_DIFFERS'
    return report


def main(argv):
    if len(argv) == 4 and argv[1] == 'compare':
        report = compare_dumps(argv[2], argv[3])
        print(json.dumps(report, indent=1, sort_keys=True))
        return 0 if report['bitwise_equal'] else 1
    if len(argv) == 3 and argv[1] == 'terminate':
        print(json.dumps(terminate_in_pause(argv[2]), indent=1, sort_keys=True))
        return 0
    print('usage: declared_pause.py compare FIRST.pt SECOND.pt | terminate CUSTODY', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
