"""Daemon-dispatched CIA-3B step measurements; no checkpoint or qualification credit."""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import argparse
import atexit
import ctypes
from dataclasses import asdict, replace
import contextlib
import gc
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback


ROOT = Path(__file__).resolve().parents[5]
ENTRY = 'src/ember/infrastructure/tools/ember-restart-3b/cia_step_runner.py'
CONFIG = 'configs/ember-cia-3b.json'
DISK_ENTRY = 'src/ember/infrastructure/tools/ember-restart-3b/disk_budget_runner.py'
GIB = 1024 ** 3
POPULATION = 3_082_539_008
CLAIM = 'governed execution evidence; model qualification requires its separate acceptance gates'
JOB_NAMESPACE = 'EmberCIAMeasurement'
LIMITS = {
    'host_memory_bytes': 40 * GIB, 'total_gpu_bytes': 20 * GIB,
    'allocator_bytes': 18 * GIB, 'wall_seconds': 600,
    'min_c_free_bytes': 150 * GIB, 'min_b_free_bytes': 250 * GIB,
    'min_free_commit_bytes': 42 * GIB, 'max_c_write_gib': 0.125, 'max_b_write_gib': 2.0,
}
CACHE_DIRS = {'TEMP': 'tmp', 'TMP': 'tmp', 'TORCH_HOME': 'torch', 'TRITON_CACHE_DIR': 'triton',
              'CUDA_CACHE_PATH': 'cuda', 'HF_HOME': 'hf', 'XDG_CACHE_HOME': 'xdg-cache'}
SOURCES = (
    ENTRY, DISK_ENTRY,
    'src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py',
    'src/ember/governance/scripts/ember_dispatch_token.py',
    'src/ember/governance/scripts/owned_process.py',
    'src/ember/governance/scripts/cia_conformance_resources.py',
    'src/ember/governance/scripts/gpu_lock_guard.py',
    'src/ember/model/ember_v0_decoder.py', 'src/ember/model/ember_v0_contract.py',
    'src/ember/model/ember_v0_inventory.py', 'src/ember/model/ember_v0_residency.py',
    'src/ember/model/ember_v0_routing.py',
    # Universal, not mode-conditional: the decoder imports it at module scope, so it is executed
    # bytes under every mode and a measurement that omitted it would under-report its own source set.
    'src/ember/model/ember_v0_document_reduction.py',
)
DATA_KEYS = {'receipt_path', 'receipt_sha256', 'tokenizer_path', 'tokenizer_sha256',
             'shards_root', 'shard_ledger_path', 'shard_ledger_sha256', 'cursor'}
INPUT_FIELDS = ('token_ids', 'target_ids', 'positions', 'document_starts')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def checked_sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('explicit expected sha256 is required')
    return value


def positive_int(value, name, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f'{name} is outside its fixed positive bound')
    return value


def geometry_counts(geometry, *, trajectory=False, hour=False, measurement=False):
    if (type(trajectory) is not bool or type(hour) is not bool or type(measurement) is not bool
            or trajectory + hour + measurement > 1):
        raise ValueError('one explicit boolean extended geometry selection required')
    if set(geometry) != {'sequence_length', 'documents_per_step', 'warm_steps', 'measured_steps'}:
        raise ValueError('geometry fields differ')
    sequence = positive_int(geometry['sequence_length'], 'sequence length', 1024)
    documents = positive_int(geometry['documents_per_step'], 'documents per step', MICRO_DOCUMENTS * MAX_MICRO_STEPS)
    warm = geometry['warm_steps']
    if type(warm) is not int or not 0 <= warm <= 2:
        raise ValueError('warm count is outside its fixed bound')
    measured = positive_int(geometry['measured_steps'], 'measured steps',
                            131072 if hour else MEASUREMENT_UPDATES if measurement else 63 if trajectory else 8)
    if trajectory and (sequence, documents, warm, measured) != (1024, 4, 1, 63):
        raise ValueError('trajectory requires exactly 64 complete 4x1024 updates with one warm exemplar')
    if measurement and ((sequence, warm, measured) != (1024, 1, MEASUREMENT_UPDATES)
                        or documents % MICRO_DOCUMENTS or documents // MICRO_DOCUMENTS not in ACCUMULATION_DEPTHS):
        raise ValueError('long measurement requires exactly 1024 complete updates of 4xN documents of 1024 positions '
                         '(N in %s micro-steps) with one warm exemplar' % (ACCUMULATION_DEPTHS,))
    if not measurement and documents > MICRO_DOCUMENTS:
        raise ValueError('only the long measurement accumulates micro-steps; every other geometry is one 4x1024 step')
    if hour and ((sequence, documents, warm) != (1024, 4, 1) or measured < 2):
        raise ValueError('extended worker requires 4x1024 geometry, one warm exemplar and at least two measured updates')
    return sequence, documents, warm, measured


ROW_FSYNC_EVERY = 64  # rows are flushed every update; fsync'd in batches (see patch note)


def _pack_digest(packs):
    body = [{name: pack[name] for name in INPUT_FIELDS + (('images',) if 'images' in pack else ())}
            for pack in packs]
    return hashlib.sha256(canonical(body)).hexdigest()


_DRAWN_DIGESTS = {}
# The look-ahead holds at most one pack in flight, so a handful of entries covers every consumer that pops. The bound
# is what keeps a consumer that never pops (the governed hour) from retaining every pack it ever drew: 4,096 position
# lists per update, a host MemoryError near update 28.8k, and a full collection scanning all of them.
_DRAWN_DIGESTS_CAP = 8
_DRAWN_DIGESTS_LOCK = threading.Lock()


def _remember_drawn(pack, digest):
    with _DRAWN_DIGESTS_LOCK:
        _DRAWN_DIGESTS[id(pack)] = (pack, digest)
        while len(_DRAWN_DIGESTS) > _DRAWN_DIGESTS_CAP:
            _DRAWN_DIGESTS.pop(next(iter(_DRAWN_DIGESTS)))


def _row_digest(pack):
    """The row's pack digest: the producer's, when it digested this very object, else computed here."""
    entry = _DRAWN_DIGESTS.pop(id(pack), None)
    if entry is not None and entry[0] is pack:
        return entry[1]
    return _pack_digest([pack])


def open_input_stream(data):
    """Verify the existing receipt and ledger and detach the admitted shard list."""
    if not isinstance(data, dict) or set(data) not in (DATA_KEYS, DATA_KEYS | {'image_text'}):
        raise ValueError('data plan fields differ')
    semantic_path = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py'
    spec = importlib.util.spec_from_file_location('cia_measurement_semantic_stream', semantic_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    ManifestBoundTokenStream = module.ManifestBoundTokenStream
    receipt = Path(data['receipt_path']).resolve(strict=True)
    tokenizer = Path(data['tokenizer_path']).resolve(strict=True)
    if file_sha256(receipt) != checked_sha(data['receipt_sha256']):
        raise ValueError('receipt sha256 differs')
    if file_sha256(tokenizer) != checked_sha(data['tokenizer_sha256']):
        raise ValueError('tokenizer sha256 differs')
    explicit_ledger = Path(data['shard_ledger_path']).resolve(strict=True) if data['shard_ledger_path'] else None
    stream = ManifestBoundTokenStream.from_receipt(
        receipt_path=receipt, shards_root=Path(data['shards_root']), tokenizer_path=tokenizer,
        shard_ledger=explicit_ledger)
    if stream.receipt_sha256 != data['receipt_sha256'] or stream.tokenizer_sha256 != data['tokenizer_sha256']:
        raise ValueError('stream changed while opening bound inputs')
    ledger = stream.shard_ledger_path
    if ledger is not None:
        expected = checked_sha(data['shard_ledger_sha256'])
        stream.bind_shard_ledger(expected_sha256=expected)
        if file_sha256(ledger) != expected:
            raise ValueError('ledger changed while binding')
    elif data['shard_ledger_sha256'] is not None or data['shard_ledger_path'] is not None:
        raise ValueError('ledger declaration has no corresponding file')
    # The existing stream may refresh at shard boundaries. A detached verified
    # list, with no ledger path, makes every later read bounded by this plan.
    stream = replace(stream, shards=[dict(item) for item in stream.shards], shard_ledger_path=None)
    return stream, receipt, tokenizer, ledger


IMAGE_TEXT_KEYS = {'manifest_path', 'manifest_sha256', 'seed'}


def load_image_text_module():
    name = 'cia_measurement_image_text_stream'
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, ROOT / 'src/ember/infrastructure/tools/ember-restart-3b/image_text_stream.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


def open_image_text(data, tokenizer, sequence):
    """Mixture amendment A1: None for a text-only plan, else the frozen image-text document source."""
    binding = data.get('image_text')
    if binding is None:
        return None
    if type(binding) is not dict or set(binding) != IMAGE_TEXT_KEYS or type(binding['seed']) is not int:
        raise ValueError('image-text binding fields differ')
    from tokenizers import Tokenizer
    frozen = Tokenizer.from_file(str(tokenizer))
    def encode(text):
        return list(frozen.encode(text, add_special_tokens=False).ids)
    return load_image_text_module().ImageTextStream(binding['manifest_path'], checked_sha(binding['manifest_sha256']),
                                                    encode, seed=binding['seed'], sequence=sequence)


def text_documents(image_text, documents):
    return documents - (1 if image_text is not None else 0)


def fill_pack(pack, stream, cursor, image_text, *, sequence, documents, image_index=None):
    """Text documents from the stream, then (A1) one image-text document at the given global image position.

    image_index defaults to the pack's local index (a non-chained run); a chained hour passes its global position."""
    for _ in range(text_documents(image_text, documents)):
        episode, after = stream.next_episode(**cursor, sequence_length=sequence)
        pack['document_starts'].append(len(pack['token_ids']))
        pack['token_ids'].extend(episode['token_ids'])
        pack['target_ids'].extend(episode['target_ids'])
        pack['positions'].extend([[position, 0, 0] for position in range(sequence)])
        cursor = {key: after[key] for key in ('shard_index', 'token_offset')}
    if image_text is not None:
        load_image_text_module().append_document(
            pack, image_text.document(pack['index'] if image_index is None else image_index))
    return cursor


def prepare_inputs(data, geometry, *, trajectory=False):
    """Open the real stream and freeze the whole short plan before model allocation."""
    stream, receipt, tokenizer, ledger = open_input_stream(data)
    sequence, documents, warm, measured = geometry_counts(geometry, trajectory=trajectory)
    cursor = dict(data['cursor'])
    if set(cursor) != {'shard_index', 'token_offset'}:
        raise ValueError('cursor fields differ')
    image_text = open_image_text(data, tokenizer, sequence)
    planned_positions = (warm + measured) * documents * sequence
    span = stream.check_cursor_span(**cursor, tokens=(warm + measured) * text_documents(image_text, documents) * sequence)
    packs = []
    for index in range(warm + measured):
        pack = {'token_ids': [], 'target_ids': [], 'positions': [], 'document_starts': [],
                'index': index, 'phase': 'warm' if index < warm else 'measured'}
        cursor = fill_pack(pack, stream, cursor, image_text, sequence=sequence, documents=documents)
        packs.append(pack)
    if file_sha256(receipt) != data['receipt_sha256'] or file_sha256(tokenizer) != data['tokenizer_sha256']:
        raise ValueError('receipt or tokenizer changed during input preparation')
    if ledger is not None and file_sha256(ledger) != data['shard_ledger_sha256']:
        raise ValueError('ledger changed during input preparation')
    binding = {'cursor_start': dict(data['cursor']), 'cursor_end': cursor, 'span': span,
               'planned_positions': planned_positions, 'input_sha256': _pack_digest(packs),
               'shard_ledger_path': str(ledger) if ledger is not None else None,
               'shard_ledger_sha256': data['shard_ledger_sha256']}
    prepared = {'packs': packs, 'binding': binding, 'geometry': dict(geometry)}
    if trajectory:
        prepared['trajectory'] = True
    return prepared


def verify_prepared_inputs(prepared):
    sequence, documents, warm, measured = geometry_counts(prepared['geometry'], trajectory=prepared.get('trajectory', False))
    packs = prepared['packs']
    if len(packs) != warm + measured or _pack_digest(packs) != prepared['binding']['input_sha256']:
        raise ValueError('prepared input bytes or plan length changed')
    for index, pack in enumerate(packs):
        if (pack['index'] != index or pack['phase'] != ('warm' if index < warm else 'measured')
                or len(pack['token_ids']) != sequence * documents
                or len(pack['target_ids']) != sequence * documents
                or pack['document_starts'] != [step * sequence for step in range(documents)]):
            raise ValueError('prepared pack geometry or phase changed')


MEASUREMENT_INPUT_GRAMMAR = 'measurement-receipt-cursor-span-v1'


class MeasurementPacks:
    """Generate only the next complete pack from the verified detached shard list. The 1,025-pack plan is never
    resident, and each emitted pack carries the cursor it consumed so every row accounts for its own input."""
    def __init__(self, stream, cursor, *, maximum_steps, sequence, documents, warm, image_text=None):
        self.stream, self.image_text = stream, image_text
        self.cursor = dict(cursor)
        self.maximum_steps, self.sequence, self.documents, self.warm = maximum_steps, sequence, documents, warm
        self.index = 0

    def next_pack(self):
        if self.index >= self.maximum_steps:
            raise ValueError('declared measurement input capacity exhausted')
        before = dict(self.cursor)
        pack = {'token_ids': [], 'target_ids': [], 'positions': [], 'document_starts': [],
                'index': self.index, 'phase': 'warm' if self.index < self.warm else 'measured'}
        self.cursor = fill_pack(pack, self.stream, self.cursor, self.image_text,
                                sequence=self.sequence, documents=self.documents)
        pack['cursor_before'], pack['cursor_after'] = before, dict(self.cursor)
        self.index += 1
        return pack


class LookaheadPacks:
    """One-pack look-ahead over a pack source (MeasurementPacks or cia_hour.HourPacks); see the A1 route record.

    Reports the CONSUMED position through .cursor/.index, so the continuation reference and every published cursor
    are unchanged. Assigning .cursor or .index drops the buffered pack and writes through to the inner source."""
    def __init__(self, inner):
        from concurrent.futures import ThreadPoolExecutor
        self._inner = inner
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ember-pack-ahead')
        self._future = None
        self._at_submit = None
        self._submit()

    def _submit(self):
        if self._inner.index >= self._inner.maximum_steps:
            self._future, self._at_submit = None, None
            return
        self._at_submit = (dict(self._inner.cursor), self._inner.index)
        self._future = self._pool.submit(self._draw)

    def _draw(self):
        # The row digest is taken here, off the training thread; _row_digest uses it only for this same object.
        pack = self._inner.next_pack()
        _remember_drawn(pack, _pack_digest([pack]))
        return pack

    def _drop(self):
        if self._future is not None:
            try:
                self._future.result()
            except Exception:
                pass
            self._inner.cursor, self._inner.index = self._at_submit
            self._future, self._at_submit = None, None

    def next_pack(self):
        if self._future is None:
            pack = self._inner.next_pack()
        else:
            future, self._future, self._at_submit = self._future, None, None
            pack = future.result()
        self._submit()
        return pack

    def __getattr__(self, name):
        # Every read the look-ahead does not redefine is the inner source's (image_text, stream, geometry):
        # the hour reads .image_text for its experiment binding and the wrapper had no such attribute.
        if name.startswith('_'):
            raise AttributeError(name)
        return getattr(self._inner, name)

    @property
    def maximum_steps(self):
        return self._inner.maximum_steps

    @property
    def cursor(self):
        return dict(self._at_submit[0]) if self._future is not None else self._inner.cursor

    @cursor.setter
    def cursor(self, value):
        self._drop()
        self._inner.cursor = value

    @property
    def index(self):
        return self._at_submit[1] if self._future is not None else self._inner.index

    @index.setter
    def index(self, value):
        self._drop()
        self._inner.index = value


def pack_lookahead(packs):
    if os.environ.get('EMBER_PACK_LOOKAHEAD') != '1':
        return packs
    # The lookahead thread and the step thread share the interpreter lock; a shorter switch interval bounds how long the step
    # thread can wait for it behind the pack worker. Host scheduling only: no tensor, route or RNG state changes.
    if os.environ.get('EMBER_SWITCH_INTERVAL_S'):
        sys.setswitchinterval(float(os.environ['EMBER_SWITCH_INTERVAL_S']))
    if os.environ.get('EMBER_HOST_PRIORITY') == '1' and sys.platform == 'win32':
        # The step thread launches every captured segment; when it waits for the CPU behind the image read/decode pool the
        # device idles inside the step. HIGH process class and HIGHEST priority for the calling (step) thread, both
        # grantable without elevation. Host scheduling only: no tensor, route or RNG state changes.
        import ctypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetCurrentThread.restype = ctypes.c_void_p
        kernel32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel32.SetThreadPriority.argtypes = (ctypes.c_void_p, ctypes.c_int)
        if not kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x00000080):
            raise OSError(ctypes.get_last_error(), 'SetPriorityClass(HIGH) refused')
        if not kernel32.SetThreadPriority(kernel32.GetCurrentThread(), 2):
            raise OSError(ctypes.get_last_error(), 'SetThreadPriority(HIGHEST) refused')
    return LookaheadPacks(packs)


def prepare_measurement_inputs(data, geometry):
    """Bind the 1,024-update plan by receipt, tokenizer, ledger, cursor and span without materializing it. The input
    digest is the digest of that declaration under a named grammar, never a digest of pack bytes the plan does not
    hold; the executed bytes are accounted per row (pack digest, cursor before and after)."""
    stream, receipt, tokenizer, ledger = open_input_stream(data)
    sequence, documents, warm, measured = geometry_counts(geometry, measurement=True)
    cursor = dict(data['cursor'])
    if set(cursor) != {'shard_index', 'token_offset'}:
        raise ValueError('cursor fields differ')
    image_text = open_image_text(data, tokenizer, sequence)
    planned_positions = (warm + measured) * documents * sequence
    span = stream.check_cursor_span(**cursor, tokens=(warm + measured) * text_documents(image_text, documents) * sequence)
    declaration = {'receipt_sha256': data['receipt_sha256'], 'tokenizer_sha256': data['tokenizer_sha256'],
                   'shard_ledger_sha256': data['shard_ledger_sha256'], 'cursor_start': cursor,
                   'geometry': dict(geometry), 'span': span, 'planned_positions': planned_positions}
    if image_text is not None:
        declaration['image_text'] = dict(data['image_text'], grammar=load_image_text_module().GRAMMAR)
    binding = dict(declaration, input_sha256=hashlib.sha256(canonical(declaration)).hexdigest(),
                   input_digest_grammar=MEASUREMENT_INPUT_GRAMMAR,
                   shard_ledger_path=str(ledger) if ledger is not None else None)
    packs = MeasurementPacks(stream, cursor, maximum_steps=warm + measured, sequence=sequence, documents=documents,
                             warm=warm, image_text=image_text)
    first = packs.next_pack()
    packs = pack_lookahead(packs)
    bound = [(receipt, data['receipt_sha256']), (tokenizer, data['tokenizer_sha256'])]
    if ledger is not None:
        bound.append((ledger, data['shard_ledger_sha256']))
    for path, expected in bound:
        if file_sha256(path) != expected:
            raise ValueError('measurement inputs changed during preparation')
    return {'binding': binding, 'geometry': dict(geometry), 'first': first, 'packs': packs, 'measurement': True}


def measurement_packs(prepared):
    yield prepared['first']
    packs = prepared['packs']
    while packs.index < packs.maximum_steps:
        yield packs.next_pack()


def verify_measurement_pack(pack, index, *, sequence, documents, warm, measured):
    if (index >= warm + measured or pack['index'] != index or pack['phase'] != ('warm' if index < warm else 'measured')
            or len(pack['token_ids']) != sequence * documents or len(pack['target_ids']) != sequence * documents
            or len(pack['positions']) != sequence * documents
            or pack['document_starts'] != [step * sequence for step in range(documents)]):
        raise ValueError('measurement pack geometry or phase changed')


def measurement_summary(rates):
    """Rank statistics of the measured updates' positions per second: nearest-rank lower percentile (rank
    ceil(p*n), no interpolation), stated with the estimator so any consumer can recompute it from rows.jsonl."""
    if not rates or any(type(value) is not float or not math.isfinite(value) or value <= 0 for value in rates):
        raise ValueError('measurement summary needs finite positive measured rates')
    ordered = sorted(rates)
    def rank(p):
        return ordered[max(0, math.ceil(p * len(ordered)) - 1)]
    return {'schema': 'cia-measurement-summary-v1', 'measured_updates': len(ordered), 'estimator': 'nearest-rank-lower',
            'positions_per_second': {'min': ordered[0], 'p10': rank(0.10), 'p50': rank(0.50), 'p90': rank(0.90),
                                     'max': ordered[-1], 'mean': sum(ordered) / len(ordered)}}


def validate_prediction(prediction, *, expected_identity, positions_per_step):
    if (not isinstance(prediction, dict) or set(prediction) != {
            'schema', 'identity', 'expected_step_seconds', 'expected_positions_per_second', 'basis'}
            or prediction['schema'] != 'ember-cia-step-prediction-v1'):
        raise ValueError('prediction fields or schema differ')
    if not isinstance(prediction['basis'], str) or not prediction['basis'].strip():
        raise ValueError('prediction requires an explicit basis')
    if canonical(prediction['identity']) != canonical(expected_identity):
        raise ValueError('prediction identity differs from opened inputs and execution')
    if canonical(expected_identity.get('resources')) != canonical(resource_limits(expected_identity)):
        raise ValueError('prediction resource envelope differs')
    wall, rate = prediction['expected_step_seconds'], prediction['expected_positions_per_second']
    if any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0 for value in (wall, rate)):
        raise ValueError('prediction timing and rate must be finite positive numbers')
    positive_int(positions_per_step, 'counted step positions', 4096 * MAX_MICRO_STEPS)
    if not math.isclose(rate * wall, positions_per_step, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError('prediction arithmetic differs from counted positions')
    trajectory, hour = trajectory_mode(expected_identity), hour_mode(expected_identity)
    _, _, warm, measured = geometry_counts(expected_identity['geometry'], trajectory=trajectory, hour=hour,
                                           measurement=measurement_mode(expected_identity))
    planned = expected_identity['hour']['minimum_measured_steps'] if hour else measured
    executed_steps = 1 if 'continuation' in expected_identity else warm + planned
    if executed_steps * wall >= resource_limits(expected_identity)['wall_seconds']:
        raise ValueError('predicted steps do not fit the fixed wall bound')


def hidden_kwargs():
    if os.name != 'nt':
        return {'shell': False}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return {'creationflags': subprocess.CREATE_NO_WINDOW, 'startupinfo': startup, 'shell': False}


def run_readonly(command, *, timeout=20):
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout, **hidden_kwargs())


def process_census():
    result = run_readonly(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-Command',
        "$ErrorActionPreference='Stop'; @(Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine,ExecutablePath,PageFileUsage,CreationDate) | ConvertTo-Json -Compress"])
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or not rows:
        raise ValueError('process census is missing')
    return rows


def windows_command_args(command):
    from ctypes import wintypes
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    count = ctypes.c_int()
    values = shell.CommandLineToArgvW(command, ctypes.byref(count))
    if not values:
        raise ValueError('cannot parse actual process argv')
    try:
        return [values[index] for index in range(count.value)]
    finally:
        kernel.LocalFree(values)


def resource_census():
    result = run_readonly(['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader,nounits'], timeout=5)
    values = [value.strip() for value in result.stdout.splitlines() if value.strip()]
    if any(not value.isdecimal() for value in values):
        raise ValueError('GPU process identity is unreadable')
    gpu_pids = {int(value) for value in values}
    rows = process_census()
    by_pid = {row['ProcessId']: row for row in rows}
    current, ancestors = os.getpid(), set()
    while current in by_pid and current not in ancestors:
        ancestors.add(current)
        current = by_pid[current]['ParentProcessId']
    training_entries = {'cia_step_runner.py', 'cia_conformance_launch.py', 'train.py', 'pretrain.py',
                        'certified_train_launch.py', 'timeshare_pretrain.py', 'train_multimodal_v0.py'}
    for row in rows:
        if row['ProcessId'] in ancestors or str(row['Name']).lower() not in {'python.exe', 'pythonw.exe', 'py.exe'}:
            continue
        if row.get('PageFileUsage') is None or not row.get('CommandLine'):
            raise ValueError('cannot classify model process resources')
        argv = windows_command_args(row['CommandLine'])
        if (row['ProcessId'] in gpu_pids or int(row['PageFileUsage']) >= 1024 ** 2
                or any(Path(arg).name.lower() in training_entries for arg in argv[1:])):
            raise ValueError(f'unowned model resource process requires coordination: {row["ProcessId"]}')
    return rows


def headroom():
    if os.name != 'nt':
        raise ValueError('measurement resource envelope requires Windows')
    class Performance(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong)] + [(name, ctypes.c_size_t) for name in (
            'CommitTotal', 'CommitLimit', 'CommitPeak', 'PhysicalTotal', 'PhysicalAvailable',
            'SystemCache', 'KernelTotal', 'KernelPaged', 'KernelNonpaged', 'PageSize')] + [
            ('HandleCount', ctypes.c_ulong), ('ProcessCount', ctypes.c_ulong), ('ThreadCount', ctypes.c_ulong)]
    info = Performance()
    info.cb = ctypes.sizeof(info)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
        raise ValueError('cannot read system commit headroom')
    free = (info.CommitLimit - info.CommitTotal) * info.PageSize
    disks = {drive: shutil.disk_usage(drive + ':/').free for drive in ('C', 'B')}
    if (free < LIMITS['min_free_commit_bytes'] or disks['C'] < LIMITS['min_c_free_bytes']
            or disks['B'] < LIMITS['min_b_free_bytes']):
        raise ValueError('measurement operating reserve is unavailable')
    return {'free_commit_bytes': free, 'free_disk_bytes': disks}


def daemon_identity():
    from ember.governance.scripts import ember_dispatch_token as dispatch
    binary = dispatch._canonical_ember_lab_binary(ROOT)
    source = dispatch._canonical_ember_lab_source_sha256(ROOT)
    if binary is None or source is None:
        raise ValueError('canonical daemon identity is missing')
    return {'path': str(binary.resolve(strict=True)), 'binary_sha256': file_sha256(binary), 'source_sha256': source}


def load_prediction(path, digest):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != checked_sha(digest):
        raise ValueError('prediction bytes differ from authenticated dispatch')
    if len(raw) > 512 * 1024:
        raise ValueError('prediction exceeds bounded metadata size')
    return json.loads(raw), raw


EXECUTION_MODES = ('resident-segmented-capture', 'resident-dynamic-capture')
# Sources a mode binds IN ADDITION to SOURCES: the G1 segmented-capture module for every capture mode, the dynamic
# grouped-kernel module only for the dynamic treatment. A mode whose module is absent at the measured head refuses.
MODE_SOURCES = {
    'resident-segmented-capture': ('src/ember/model/ember_v0_capture.py',),
    'resident-dynamic-capture': ('src/ember/model/ember_v0_capture.py', 'src/ember/model/ember_v0_grouped_capture.py'),
}


def execution_mode(identity):
    """The optional identity field selecting the resident step's execution regime; absent means the eager resident
    step. The value set is fixed so an unknown mode refuses before any file read instead of silently running eager."""
    mode = identity.get('execution_mode')
    if mode is not None and mode not in EXECUTION_MODES:
        raise ValueError('execution mode is outside its fixed set')
    return mode


def local_routing_mode(identity):
    """Bind an explicit capture route without changing the existing batched default."""
    mode = execution_mode(identity)
    selected = identity.get('local_routing_mode', 'per-chunk' if mode is None else 'batched')
    if type(selected) is not str or selected not in ('batched', 'per-chunk'):
        raise ValueError('local routing mode is outside its fixed set')
    if mode is None and selected != 'per-chunk':
        raise ValueError('eager execution uses per-chunk local routing')
    return selected


_loss_widen_counts = {'fused_widen': 0, 'materialised_widen': 0}


def loss_widen_counts():
    return dict(_loss_widen_counts)


def _fused_logit_widen():
    """Fold the fp32 widening of the logits INTO the log-softmax instead of materialising it.

    `cross_entropy(logits.float(), targets)` upcasts the whole [positions, vocabulary] logit
    tensor to fp32 first -- at this geometry a 4096x32768 fp32 copy, measured at 1,813.1 us
    per step over two launches in the fusibility audit -- and only then reduces it. Passing
    `dtype=torch.float32` to `log_softmax` performs the identical widening per element as the
    reduction reads it, so the copy never exists.

    BIT-EXACT BY CONSTRUCTION, not merely close: bf16 -> fp32 is an exact widening (every
    bf16 value is representable in fp32), so the softmax arithmetic sees the same values in
    the same order either way. `cross_entropy` is defined as `nll_loss(log_softmax(x))` and
    both carry reduction='mean' over the same denominator.

    Counted at the call site rather than read back from the environment: a frozen manifest
    variable records that the flag reached the worker, and only a count records that the
    branch which ran is the branch that was asked for.
    """
    on = os.environ.get('EMBER_FUSED_LOGIT_WIDEN') == '1'
    _loss_widen_counts['fused_widen' if on else 'materialised_widen'] += 1
    return on


def _native_loss(logits, targets):
    import torch
    if _fused_logit_widen():
        return torch.nn.functional.nll_loss(
            torch.nn.functional.log_softmax(logits, dim=-1, dtype=torch.float32),
            targets, reduction='mean')
    return torch.nn.functional.cross_entropy(logits.float(), targets, reduction='mean')


def _merge_counter_receipt(variable, counts):
    # Two processes run THIS FILE per dispatch and both carry the frozen environment:
    # the controller (--daemon-run --live --hidden-helper) re-execs itself as the worker
    # (--worker <binding>) and verifies the ancestry, then outlives it. The controller
    # never calls measure_step, so its counts are zero, and on 2026-09-22 it exited 1.2 s
    # behind its child and overwrote a real count with those zeros -- twice, on two
    # governed 1,024-update runs, each time reporting an executing member INERT.
    # Taking the per-key MAXIMUM makes exit order irrelevant: whichever process did the
    # work contributes its counts, and one that did none cannot erase them. The custody
    # is fresh per run, so no stale count can be carried in from an earlier measurement.
    path = os.environ.get(variable)
    if not path:
        return
    merged = dict(counts)
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            prior = json.load(handle)
        if type(prior) is dict:
            for key, value in prior.items():
                if type(value) is int and value > merged.get(key, 0):
                    merged[key] = value
    except (OSError, ValueError):
        pass
    try:
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(merged, handle)
    except OSError:
        pass


def _write_loss_widen_receipt():
    _merge_counter_receipt('EMBER_LOSS_WIDEN_RECEIPT', _loss_widen_counts)


atexit.register(_write_loss_widen_receipt)


def training_head(identity):
    selected = identity.get('training_head', 'native')
    if type(selected) is not str or selected not in ('native', 'cce-document-v1'):
        raise ValueError('training head is outside its fixed set')
    if selected != 'native' and execution_mode(identity) is None:
        raise ValueError('streamed training head requires explicit resident capture')
    return selected


def experiment_fields(identity):
    binding = identity.get('experiment_plan')
    if binding is None:
        return {}
    return dict(plan_sha256=binding['sha256'], candidate_function_id=binding['candidate_function_id'])


def step_experiment_fields(capture, binding):
    captured = getattr(getattr(capture, 'loss_fn', None), 'experiment_binding', {})
    supplied = {} if binding is None else binding
    if type(supplied) is not dict or (supplied and set(supplied) != {'plan_sha256', 'candidate_function_id'}):
        raise ValueError('Explicit step function and plan binding required')
    if captured and supplied and captured != supplied:
        raise ValueError('Step plan differs from the captured loss declaration')
    return dict(supplied or captured)


def validate_experiment_plan(identity):
    binding = identity.get('experiment_plan')
    if binding is None:
        if training_head(identity) != 'native':
            raise ValueError('Selected training function requires its frozen experiment plan')
        return None
    if type(binding) is not dict or set(binding) != {'path', 'sha256', 'candidate_function_id'}:
        raise ValueError('Explicit experiment plan path, hash and function identity required')
    raw = Path(binding['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != checked_sha(binding['sha256']):
        raise ValueError('Frozen experiment plan bytes differ')
    plan = json.loads(raw)
    if type(plan) is not dict or not isinstance(binding['candidate_function_id'], str) or not binding['candidate_function_id']:
        raise ValueError('Experiment plan must name a training function')
    if plan.get('candidate_function_id') != binding['candidate_function_id']:
        raise ValueError('Experiment plan function differs')
    validate_experiment_sources(identity, plan)
    for key in ('source_commit', 'optimizer', 'support', 'seed', 'data'):
        if key not in plan or plan[key] != identity[key]:
            raise ValueError('Experiment plan differs from execution: ' + key)
    for key in ('documents_per_step', 'sequence_length'):
        if plan.get('geometry', {}).get(key) != identity['geometry'][key]:
            raise ValueError('Experiment plan geometry differs: ' + key)
    selected = dict(training_head=training_head(identity), execution_mode=execution_mode(identity),
                    local_routing_mode=local_routing_mode(identity), **attention_selection(identity))
    for key, value in selected.items():
        if plan.get('selectors', {}).get(key) != value:
            raise ValueError('Experiment plan selector differs: ' + key)
    return plan


def capture_loss_kwargs(model, identity, lengths):
    import torch
    if training_head(identity) == 'native':
        return dict(loss_fn=_native_loss)
    from ember.model.ember_v0_streamed_loss import document_streamed_loss
    os.environ['CCE_AUTOTUNE'] = '0'
    lengths = tuple(lengths)
    def loss(hidden, targets, selections=None, denominator=None):
        return document_streamed_loss(hidden, model._weight('embedding.weight'), targets, lengths,
                                      sum(lengths) if denominator is None else denominator, selections=selections)
    loss.experiment_binding = experiment_fields(identity)
    return dict(head_output='hidden', loss_fn=loss)


def streamed_sources(identity):
    if training_head(identity) == 'native':
        return ()
    manifest = 'src/ember/model/streamed_loss_vendor.json'
    binding = json.loads((ROOT / manifest).read_bytes())
    for relative, digest in binding['files'].items():
        if not relative.startswith('src/cut_cross_entropy/') or '..' in Path(relative).parts:
            raise ValueError('Streamed implementation source outside its package')
        if file_sha256(ROOT / relative) != checked_sha(digest):
            raise ValueError('Streamed implementation bytes differ: ' + relative)
    return ('src/ember/model/ember_v0_streamed_loss.py', manifest, *sorted(binding['files']))


TRAJECTORY_SOURCES = ('src/ember/infrastructure/tools/ember-restart-3b/cia_trajectory.py',)
CHECKPOINT_SOURCES = tuple('src/ember/infrastructure/tools/ember-restart-3b/' + name for name in
    ('cia_hour.py', 'checkpoint_artifacts.py', 'parameter_counter.py'))
HOUR_SOURCES = ('src/ember/governance/scripts/catalog_train_stream.py',) + tuple(
    'src/ember/infrastructure/tools/ember-restart-3b/' + name for name in
    ('cia_hour_energy.py', 'boundary_energy_collector.py'))


def allowed_experiment_sources(identity):
    """One selected training function's allowed source closure across every run stage."""
    return frozenset(SOURCES + MODE_SOURCES.get(execution_mode(identity), ()) +
                     TRAJECTORY_SOURCES + CHECKPOINT_SOURCES + HOUR_SOURCES + streamed_sources(identity))


def validate_experiment_sources(identity, plan):
    declared, executed = plan.get('source_sha256'), identity.get('source_sha256')
    if type(declared) is not dict or type(executed) is not dict:
        raise ValueError('Experiment source bindings must be explicit maps')
    if set(executed) != set(required_sources(identity)):
        raise ValueError('Execution source set differs from its selected stage')
    if not set(executed) <= set(declared) <= allowed_experiment_sources(identity):
        raise ValueError('Experiment source closure is missing required or contains unbound files')
    root = ROOT.resolve(strict=True)
    for relative, expected in declared.items():
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError('Experiment source resolved outside the source checkout')
        if file_sha256(path) != checked_sha(expected):
            raise ValueError('Frozen experiment source bytes differ: ' + relative)
    if any(declared[name] != value for name, value in executed.items()):
        raise ValueError('Execution source digest differs from its frozen experiment')


def required_sources(identity):
    """Exact source set of one stage; the frozen experiment may bind its full stage union."""
    additional = TRAJECTORY_SOURCES if trajectory_mode(identity) else ()
    if hour_mode(identity) or trajectory_checkpoint_emission(identity):
        additional += CHECKPOINT_SOURCES
    if hour_mode(identity):
        additional += HOUR_SOURCES
    return SOURCES + MODE_SOURCES.get(execution_mode(identity), ()) + additional + streamed_sources(identity)


def trajectory_mode(identity):
    if 'trajectory' not in identity:
        return False
    arms = {'R1': None, 'R2': None, 'R3': None, 'Tsegmented': 'resident-segmented-capture',
            'Tdynamic': 'resident-dynamic-capture', 'Tfused': 'resident-dynamic-capture'}
    value = identity['trajectory']
    keys = {'schema', 'arm', 'comparison_id'}
    if isinstance(value, dict) and 'checkpoint_emission' in value:
        if value['checkpoint_emission'] is not True:
            raise ValueError('trajectory checkpoint emission must be explicitly true')
        keys = keys | {'checkpoint_emission'}
    if isinstance(value, dict) and value.get('arm') == 'R3':
        keys = keys | {'document_permutation'}
    if (not isinstance(value, dict) or set(value) != keys
            or value['schema'] != 'reference-noise-floor-64-v1' or value['arm'] not in arms
            or not isinstance(value['comparison_id'], str) or not re.fullmatch('[0-9a-f]{32}', value['comparison_id'])
            or execution_mode(identity) != arms[value['arm']]):
        raise ValueError('trajectory requires a bound comparison and matching 64-update arm')
    if value['arm'] == 'R3':
        validate_document_permutation(value['document_permutation'])
    return True


def trajectory_checkpoint_emission(identity):
    if 'checkpoint_emission' in identity:
        raise ValueError('checkpoint emission belongs only to the trajectory declaration')
    return trajectory_mode(identity) and identity['trajectory'].get('checkpoint_emission') is True


def validate_document_permutation(value):
    """R3: one pinned permutation of the four documents per update; identity everywhere is refused."""
    if (type(value) is not list or len(value) != 64
            or any(type(row) is not list or len(row) != 4 or any(type(item) is not int for item in row)
                   or sorted(row) != [0, 1, 2, 3] for row in value)
            or all(row == [0, 1, 2, 3] for row in value)):
        raise ValueError('R3 requires a pinned non-identity document permutation for each of the 64 updates')
    return value


MEASUREMENT_UPDATES = 1024
# Gradient accumulation (#1945). The forward context is 4 documents of 1,024 positions -- routing buffers, captured
# segments and the attention geometry are all bound to it -- so positions per OPTIMIZER step grow by running N such
# micro-steps into the same gradients and applying ONE update. The pack is still one contiguous cursor span of 4N
# documents, so the data plan, cursor chain and applied-position accounting are unchanged in kind; only the number of
# positions each update applies changes, and that IS the learning contract, declared by the geometry itself.
# #1945 wide micro-step: EMBER_MICRO_DOCUMENTS documents per captured micro-step (default 4).
MICRO_DOCUMENTS = int(os.environ.get('EMBER_MICRO_DOCUMENTS', '4'))
MAX_MICRO_STEPS = 16
ACCUMULATION_DEPTHS = (1, 2, 4, 8, 16)
MEASUREMENT_SCHEMA = 'governed-1024-v1'
MEASUREMENT_WALL_SECONDS = 3000
# Long-measurement arms: the declared execution regime of each; only the fused arm declares the fused optimizer.
MEASUREMENT_ARMS = {'eager': None, 'segmented': 'resident-segmented-capture',
                    'dynamic': 'resident-dynamic-capture', 'fused': 'resident-dynamic-capture'}


def measurement_mode(identity):
    """The explicit 1,024-update measurement identity. Distinct from the 64-update trajectory comparison (numerical
    evidence) and the governed hour (checkpoint-bound qualification): it produces the warmed step-time distribution
    over 1,024 complete updates and nothing else, so it is admitted only with its own declared block and arm."""
    if 'measurement' not in identity:
        return False
    value = identity['measurement']
    if ('trajectory' in identity or 'hour' in identity or not isinstance(value, dict)
            or set(value) != {'schema', 'arm'} or value['schema'] != MEASUREMENT_SCHEMA
            or value['arm'] not in MEASUREMENT_ARMS or execution_mode(identity) != MEASUREMENT_ARMS[value['arm']]):
        raise ValueError('explicit fixed long-measurement identity with a matching arm required')
    return True


def expected_optimizer(identity):
    """The one fixed optimizer definition an identity may carry. fused=True is a declared treatment: admitted for the
    trajectory Tfused arm, the hour treatment arm and the long-measurement fused arm, never by request alone."""
    expected = {'name': 'AdamW', 'foreach': False, 'lr': 0.001, 'betas': [0.9, 0.999],
                'eps': 1e-8, 'weight_decay': 0.01, 'membership': 'complete_parameter_inventory'}
    if ((trajectory_mode(identity) and identity['trajectory']['arm'] == 'Tfused')
            or (hour_mode(identity) and identity['hour']['arm'] == 'treatment')
            or (measurement_mode(identity) and identity['measurement']['arm'] == 'fused')):
        expected['fused'] = True
    return expected


def optimizer_kwargs(definition):
    """Constructor arguments from a validated definition. The fused flag is forwarded exactly when declared, so the
    executed optimizer is the one the identity names; an identity-only admission would measure ordinary AdamW."""
    kwargs = {'lr': definition['lr'], 'betas': tuple(definition['betas']), 'eps': definition['eps'],
              'weight_decay': definition['weight_decay'], 'foreach': False}
    if definition.get('fused') is True:
        kwargs['fused'] = True
    return kwargs


def attention_selection(identity):
    """Normalize defaults; admit attention changes only for an explicit fused resident treatment."""
    backend = identity.get('attention_backend', 'unforced')
    recompute = identity.get('attention_recompute', 'none')
    if (('attention_backend' in identity and backend != 'math')
            or ('attention_recompute' in identity and recompute != 'non_reentrant_checkpoint')
            or ((backend == 'math') != (recompute == 'non_reentrant_checkpoint'))):
        raise ValueError('attention selection must explicitly bind MATH and non-reentrant recomputation')
    if backend == 'math':
        if (execution_mode(identity) != 'resident-dynamic-capture'
                or type(identity.get('optimizer')) is not dict or identity['optimizer'].get('fused') is not True
                or expected_optimizer(identity).get('fused') is not True):
            raise ValueError('attention selection requires the declared fused resident treatment')
    return dict(attention_backend=backend, attention_recompute=recompute)


@contextlib.contextmanager
def attention_context(identity):
    """Keep the selected arithmetic through exemplars, backward capture and replay, then restore it."""
    if attention_selection(identity)['attention_backend'] == 'unforced':
        yield
        return
    import torch
    from torch.nn.attention import SDPBackend, sdpa_kernel
    reduction = torch.backends.cuda.fp16_bf16_reduction_math_sdp_allowed()
    try:
        torch.backends.cuda.allow_fp16_bf16_reduction_math_sdp(False)
        with sdpa_kernel(SDPBackend.MATH):
            yield
    finally:
        torch.backends.cuda.allow_fp16_bf16_reduction_math_sdp(reduction)


def decoder_kwargs(identity):
    """Omit the constructor option for the unchanged default execution path."""
    return ({'attention_recompute': True}
            if attention_selection(identity)['attention_recompute'] == 'non_reentrant_checkpoint' else {})


# Issue #2119 successor: 256 s measured startup + 3600 s governed hour + 1800 s provisional tail bound. The 4500 s wall cut the
# post-hour tail (counter, quarantine, worker-terminal, hour-result, pointer CAS) of the first chained hour.
HOUR_WALL_SECONDS = 5656
# Issue #2119 only: one optional declared wall for a governed-hour-v1 identity, HOUR_WALL_SECONDS < value <= this cap. Absent means
# HOUR_WALL_SECONDS. It lives in the identity, so prediction, plan, worker and supervisor all read the same value through
# resource_limits; there is no supervisor-side override and no mode alias.
HOUR_WALL_SECONDS_CAP = 7200


# Issue #2119 layer policy: the hour identity declares the layer template the child trains under, {mode: full} or three keep sets.
# Full CLEARS the three EMBER_SKIP_KEEP* selectors in the child env; keep SETS them from the identity; the decoder's own receipt path
# is always set to a custody file. The worker refuses before training when its env or the decoder's resolved sets differ.
LAYER_KEYS = ('attention_keep', 'ffn_keep', 'expert_keep')
LAYER_SELECTOR_ENV = ('EMBER_SKIP_KEEP', 'EMBER_SKIP_KEEP_FFN', 'EMBER_SKIP_KEEP_EXPERT')
LAYER_RECEIPT_ENV = 'EMBER_LAYER_TEMPLATE_RECEIPT'
LAYER_RECEIPT_NAME = 'layer-template-counts.json'
LAYER_RESOLVED_NAME = 'layer-policy-resolved.json'
ALL_LAYERS = tuple(range(24))


def _layer_sets(value):
    if value == {'mode': 'full'}:
        return {key: ALL_LAYERS for key in LAYER_KEYS}
    if type(value) is not dict or set(value) != set(LAYER_KEYS):
        raise ValueError('layer template is neither {mode: full} nor the three keep fields')
    sets = {}
    for key in LAYER_KEYS:
        raw = value[key]
        layers = [int(part) for part in raw.split(',')] if isinstance(raw, str) else [int(item) for item in raw]
        if not layers or any(item < 0 or item > 23 for item in layers):
            raise ValueError(f'{key} has no layers or a layer outside 0..23')
        sets[key] = tuple(sorted(set(layers)))
    return sets


def canonical_layer_template(value):
    """{mode: full} when all three sets are 0..23, else the keep-set dict of sorted comma strings (same rule as the NLL adapter)."""
    sets = _layer_sets(value)
    if all(sets[key] == ALL_LAYERS for key in LAYER_KEYS):
        return {'mode': 'full'}
    return {key: ','.join(str(item) for item in sets[key]) for key in LAYER_KEYS}


def declared_layer_template(identity):
    hour = identity.get('hour') if isinstance(identity, dict) else None
    return hour.get('layer_template') if isinstance(hour, dict) else None


def layer_child_env(identity, custody, base_env=None):
    """The explicit per-child environment: selectors from the identity (never ambient) and the decoder receipt path in custody."""
    declared = declared_layer_template(identity)
    if declared is None:
        raise ValueError('governed-hour-v1 launch requires hour.layer_template')
    env = dict(os.environ if base_env is None else base_env)
    for name in LAYER_SELECTOR_ENV:
        env.pop(name, None)
    if declared != {'mode': 'full'}:
        env.update(zip(LAYER_SELECTOR_ENV, (declared[key] for key in LAYER_KEYS)))
    env[LAYER_RECEIPT_ENV] = str(Path(custody) / LAYER_RECEIPT_NAME)
    return env


def check_layer_env(identity, env=None):
    """Before the decoder is imported: the worker's own selector env equals the declaration (full = all three unset)."""
    declared = declared_layer_template(identity)
    if declared is None:
        return
    env = os.environ if env is None else env
    seen = {name: env.get(name) for name in LAYER_SELECTOR_ENV}
    want = ({name: None for name in LAYER_SELECTOR_ENV} if declared == {'mode': 'full'}
            else dict(zip(LAYER_SELECTOR_ENV, (declared[key] for key in LAYER_KEYS))))
    if seen != want:
        raise ValueError(f'worker layer selectors {seen} differ from the declared layer_template {declared}')
    if not env.get(LAYER_RECEIPT_ENV):
        raise ValueError('worker layer-template receipt path is not set')


def check_resolved_layers(identity, resolved):
    """After the decoder import: its resolved sets equal the canonical declaration. Returns the failure list (empty = equal)."""
    declared = declared_layer_template(identity)
    if declared is None:
        return []
    want = _layer_sets(declared)
    failures = []
    for key in LAYER_KEYS:
        got = tuple(sorted(resolved.get(key, ())))
        if got != want[key]:
            failures.append(f'{key}: resolved {got} != declared {want[key]}; differing layers {sorted(set(got) ^ set(want[key]))}')
    return failures


def resource_limits(identity):
    limits = dict(LIMITS)
    if hour_mode(identity):
        limits.update(wall_seconds=identity['hour'].get('wall_seconds', HOUR_WALL_SECONDS), max_b_write_gib=24)
        if identity['hour']['schema'] == 'learning-comparison-v1':
            # Two checkpoints plus four full parameter snapshots; the full-compute control arm runs 16,384 updates.
            limits.update(wall_seconds=10800, max_b_write_gib=80)
        if 'continuation' in identity:
            limits.update(wall_seconds=900, max_b_write_gib=1)
    elif trajectory_mode(identity):
        if trajectory_checkpoint_emission(identity):
            limits.update(wall_seconds=1800, max_b_write_gib=32)
        else:
            limits['max_b_write_gib'] = 8
    elif measurement_mode(identity):
        limits['wall_seconds'] = MEASUREMENT_WALL_SECONDS
    return limits


def hour_mode(identity):
    if 'hour' not in identity:
        if 'continuation' in identity:
            raise ValueError('continuation requires a bound governed hour')
        return False
    value = identity['hour']
    fixed = {'schema', 'arm', 'minimum_wall_seconds', 'minimum_measured_steps'}
    if isinstance(value, dict) and 'wall_seconds' in value:
        wall = value['wall_seconds']
        if (value.get('schema') != 'governed-hour-v1' or type(wall) is not int
                or not HOUR_WALL_SECONDS < wall <= HOUR_WALL_SECONDS_CAP):
            raise ValueError(f'hour wall_seconds is governed-hour-v1 only, an int in ({HOUR_WALL_SECONDS}, {HOUR_WALL_SECONDS_CAP}]; '
                             'omit it for the default')
        fixed = fixed | {'wall_seconds'}
    if isinstance(value, dict) and 'layer_template' in value:
        if value.get('schema') != 'governed-hour-v1':
            raise ValueError('hour layer_template is governed-hour-v1 only')
        try:
            canonical = canonical_layer_template(value['layer_template'])
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError(f'hour layer_template is invalid: {error}')
        if value['layer_template'] != canonical:
            raise ValueError('hour layer_template must be written in canonical form')
        fixed = fixed | {'layer_template'}
    if ('trajectory' in identity or 'measurement' in identity or not isinstance(value, dict)
            or set(value) != fixed
            or value['schema'] not in ('governed-hour-v1', 'checkpoint-probe-v1', 'learning-comparison-v1')
            or value['arm'] not in ('control', 'treatment')
            or type(value['minimum_wall_seconds']) is not int
            or type(value['minimum_measured_steps']) is not int
            or (value['minimum_wall_seconds'], value['minimum_measured_steps']) !=
               {'governed-hour-v1': (3600, 1024), 'checkpoint-probe-v1': (0, 2),
                'learning-comparison-v1': (0, 16383)}[value['schema']]):
        raise ValueError('explicit fixed governed-hour identity required')
    if 'continuation' in identity and value['schema'] != 'governed-hour-v1':
        raise ValueError('continuation requires the completed governed hour')
    return True


def validate_trajectory_resources(identity):
    if trajectory_mode(identity):
        emission = trajectory_checkpoint_emission(identity)
        maximum = (32 if emission else 8) * GIB
        walls = identity['dispatch_resources'].get('disk_write_walls')
        if (not isinstance(walls, list) or len(walls) != 1 or not isinstance(walls[0], dict)
                or walls[0].get('volume_root') != 'B:/'
                or walls[0].get('maximum_write_bytes') != maximum):
            raise ValueError('trajectory requires its matching 32 GiB checkpoint disk wall' if emission else
                             'trajectory requires its matching eight GiB native disk wall')


def load_trajectory_module():
    path = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b/cia_trajectory.py'
    spec = importlib.util.spec_from_file_location('cia_measurement_trajectory', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def load_hour_module():
    path = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b/cia_hour.py'
    spec = importlib.util.spec_from_file_location('cia_governed_hour', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def load_ledger_module():
    path = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b/training_continuity_ledger.py'
    spec = importlib.util.spec_from_file_location('cia_training_continuity_ledger', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def load_eligibility_module():
    path = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b/retention_eligibility.py'
    spec = importlib.util.spec_from_file_location('cia_retention_eligibility', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def load_purpose_module():
    path = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b/certified_train_launch.py'
    spec = importlib.util.spec_from_file_location('cia_training_job_purpose', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def validate_training_job_purpose(identity, *, hour):
    """Issue #2119: the real CIA dispatch path (this file) never passed through
    certified_train_launch.py's validate_certified_request, so a run here declared no
    training_job_purpose and required none of its bindings -- the exact gap the issue names.
    This calls the SAME shared predicate certified_train_launch.py enforces on the governed-
    vertical path (imported, never duplicated), so retained-training credit and required
    bindings never diverge between the two dispatch routes.

    has_resume/has_data_segment are read from fields this identity already carries and already
    verifies elsewhere in this function: checkpoint_probe/continuation reopen a real prior
    admitted checkpoint (validate_checkpoint_probe, below); an arm's chained parent_checkpoint is
    reopened by run_hour in cia_hour.py, which re-verifies the manifest digest against the
    published receipt and restores every object before an hour trains from it -- this reads only
    the key's PRESENCE, and prepare_execution's own shape check (above, before this call) has
    already accepted its {root, manifest_sha256} shape, so no second admission check is
    introduced here either; production_mixture is the admitted next data segment for an hour
    (validate_identity, below).
    """
    purpose_module = load_purpose_module()
    has_resume = (bool(identity.get('checkpoint_probe')) or 'continuation' in identity
                  or 'parent_checkpoint' in identity)
    has_data_segment = bool(hour) and bool(identity.get('production_mixture'))
    return purpose_module._validate_training_job_purpose(
        identity, has_resume=has_resume, has_data_segment=has_data_segment)


def validate_scored_pair_binding(identity):
    """review 63986 R2 / ruling 64046: the scored-pair frozen-binding entry (population, mixture, run, source, promotion target) is pinned in a
    RETENTION_ELIGIBLE_EXPERIMENT identity, and so in the prediction digest, before launch; `scored_pair_entry.finalize_scored_pair` refuses any
    entry whose bytes do not hash to it. Any other purpose carries no such field."""
    if identity.get('training_job_purpose') == 'RETENTION_ELIGIBLE_EXPERIMENT':
        if not load_eligibility_module()._is_sha256(identity.get('scored_pair_binding_sha256')):
            raise ValueError('a RETENTION_ELIGIBLE_EXPERIMENT identity freezes the scored-pair entry digest (scored_pair_binding_sha256)')
    elif 'scored_pair_binding_sha256' in identity:
        raise ValueError('scored_pair_binding_sha256 belongs to a RETENTION_ELIGIBLE_EXPERIMENT identity only')


def prepare_execution(prediction):
    identity = prediction.get('identity')
    keys = {'run_id', 'source_commit', 'source_sha256', 'config_sha256', 'data', 'seed',
            'support', 'optimizer', 'geometry', 'batch_documents', 'resources', 'input_binding', 'gpu_uuid',
            'dispatch_resources', 'training_job_purpose'}
    if not isinstance(identity, dict) or not keys <= set(identity) <= keys | {'execution_mode', 'trajectory', 'hour', 'production_mixture', 'checkpoint_probe', 'measurement', 'local_routing_mode', 'continuation', 'attention_backend', 'attention_recompute', 'training_head', 'experiment_plan', 'parent_checkpoint', 'training_experiment_protocol', 'training_experiment_continuation_rule', 'scored_pair_binding_sha256', 'training_diagnostic_question', 'training_diagnostic_non_advancement_reason', 'training_diagnostic_return_condition', 'training_diagnostic_readiness_blocker'}:
        raise ValueError('measurement identity fields differ')
    if 'parent_checkpoint' in identity and ('hour' not in identity or not isinstance(identity['parent_checkpoint'], dict)
            or set(identity['parent_checkpoint']) != {'root', 'manifest_sha256'}):
        raise ValueError('a chained parent checkpoint binds a governed hour by root and manifest digest')
    execution_mode(identity)
    trajectory, hour, measurement = trajectory_mode(identity), hour_mode(identity), measurement_mode(identity)
    local_routing_mode(identity)
    attention_selection(identity)
    training_head(identity)
    validate_experiment_plan(identity)
    if ('production_mixture' in identity) != hour:
        raise ValueError('production mixture requires the explicit hour identity')
    if 'checkpoint_probe' in identity and not hour:
        raise ValueError('checkpoint probe reference requires the explicit hour identity')
    validate_training_job_purpose(identity, hour=hour)
    if identity.get('training_job_purpose') == 'RETENTION_ELIGIBLE_EXPERIMENT':
        # Issue #2119 rows 5/14: the eligibility rule is frozen in the identity (and so in the prediction digest) before launch.
        load_eligibility_module().validate_identity_rule(identity)
    validate_scored_pair_binding(identity)
    validate_trajectory_resources(identity)
    if hour:
        load_hour_module().validate_checkpoint_probe(sys.modules[__name__], identity)
        mixture_validation = load_hour_module().validate_identity(runner=sys.modules[__name__], identity=identity)
    sequence, documents, _, _ = geometry_counts(identity['geometry'], trajectory=trajectory, hour=hour,
                                                measurement=measurement)
    validate_prediction(prediction, expected_identity=identity, positions_per_step=sequence * documents)
    outer = identity['dispatch_resources']
    if (not isinstance(outer, dict) or outer.get('profile') != 'cia_measurement'
            or outer.get('maximum_job_memory_bytes') != LIMITS['host_memory_bytes']
            or outer.get('window_contract') != 'headless_no_windows'):
        raise ValueError('authenticated outer resource projection differs')
    if not re.fullmatch('[0-9a-f]{32}', identity['run_id']):
        raise ValueError('run identity must be 32 lowercase hex characters')
    if type(identity['seed']) is not int or not 0 <= identity['seed'] < 2 ** 63:
        raise ValueError('seed is outside its integer bound')
    if type(identity['batch_documents']) is not bool:
        raise ValueError('batch_documents must be an explicit boolean')
    if not isinstance(identity['gpu_uuid'], str) or not re.fullmatch('GPU-[0-9a-fA-F-]+', identity['gpu_uuid']):
        raise ValueError('exact GPU UUID is required')
    wall = outer.get('vram_wall')
    contract = wall.get('contract') if isinstance(wall, dict) else None
    if (not isinstance(wall, dict) or wall.get('applicability') != 'required'
            or not isinstance(contract, dict) or contract.get('device_uuid') != identity['gpu_uuid']):
        raise ValueError('measurement GPU UUID differs from the required VRAM contract')
    if set(identity['source_sha256']) != set(required_sources(identity)):
        raise ValueError('complete measurement source binding is required')
    for relative, digest in identity['source_sha256'].items():
        if not (ROOT / relative).is_file():
            raise ValueError(f'execution mode needs a source absent at this head: {relative}')
        if file_sha256(ROOT / relative) != checked_sha(digest):
            raise ValueError(f'bound source changed: {relative}')
    head = run_readonly(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']).stdout.strip()
    if head != identity['source_commit']:
        raise ValueError('source commit differs from prediction')
    config_path = ROOT / CONFIG
    if file_sha256(config_path) != checked_sha(identity['config_sha256']):
        raise ValueError('config bytes differ from prediction')
    config = json.loads(config_path.read_bytes())
    if (config.get('authority', {}).get('total_parameters') != POPULATION
            or config.get('model', {}).get('total_unique_parameters') != POPULATION):
        raise ValueError('complete canonical CIA-3B population is required')
    support = identity['support']
    if not isinstance(support, dict) or set(support) != {'locus', 'experts'}:
        raise ValueError('update support fields differ')
    if support['locus'] != 'core+expert-set' or not isinstance(support['experts'], list):
        raise ValueError('explicit core and expert-set measurement support required')
    experts = support['experts']
    if (not 1 <= len(experts) <= 4
            or any(type(value) is not int or not 0 <= value < 25 for value in experts)
            or experts != sorted(set(experts))):
        raise ValueError('measurement expert support is outside its fixed bound')
    if canonical(identity['optimizer']) != canonical(expected_optimizer(identity)):
        raise ValueError('fixed optimizer definition differs')
    prepared = (load_hour_module().prepare_inputs(sys.modules[__name__], identity['data'], identity['geometry'],
                    image_start=load_hour_module().chained_image_start(sys.modules[__name__], identity))
                if hour else prepare_measurement_inputs(identity['data'], identity['geometry'])
                if measurement else prepare_inputs(identity['data'], identity['geometry'], trajectory=trajectory))
    if hour:
        prepared['mixture_validation'] = mixture_validation
        if 'continuation' in identity:
            prepared['continuation'] = load_hour_module().validate_continuation(sys.modules[__name__], identity)
    actual = dict(identity, input_binding=prepared['binding'], resources=resource_limits(identity))
    sequence, documents, _, _ = geometry_counts(identity['geometry'], trajectory=trajectory, hour=hour,
                                                measurement=measurement)
    validate_prediction(prediction, expected_identity=actual, positions_per_step=sequence * documents)
    if not (hour or measurement):
        verify_prepared_inputs(prepared)
    return config, prepared


def _cache_values(cache):
    return {name: getattr(cache, name) for name in ('lease_count', 'miss_count', 'eviction_count',
                                                  'transfer_bytes', 'transfer_seconds')}


ROUTES_DIGEST_GRAMMARS = ('legacy-rows-v1', 'device-buffers-v1')
_ROUTING_BUFFERS = {}
_NEXT_STEP = None  # measure_step's staging of update index+1 (EMBER_STAGE_NEXT_STEP); consumed only for the same pack


def _with_successor(packs):
    """(pack, the pack after it or None): one pack of lookahead, drawn between steps, outside every wall."""
    iterator = iter(packs)
    end = object()
    current = next(iterator, end)
    while current is not end:
        following = next(iterator, end)
        yield current, (None if following is end else following)
        current = following


class RoutingStatisticsBuffers:
    """Fixed device buffers for one static document geometry (issue 1945 device routing statistics).

    The resident decoder reports each step's routing through a collector callback: one 'global' call
    (priors FP32 [E,25], ranked and candidates int64 [E,2] over the E=sum(ceil(len/1024)) epochs) and one
    'local' call per sparse layer (winners int64 [C], logits FP32 [C,2], gates FP32 [C], valid bool over the
    C=sum(ceil(len/256)) chunks). The collector copies every payload into ONE preallocated device byte
    buffer with copy_ and never reads it on the host, so the step keeps zero route-induced host reads;
    the receipt digest, the legacy route rows and the per-step statistics all come from ONE device-to-host
    copy of that buffer taken after the step's own final synchronization. Grammar 'device-buffers-v1'.
    """
    LAYERS = tuple(range(1, 24, 2))
    GRAMMAR = 'device-buffers-v1'

    def __init__(self, lengths, *, device):
        import torch
        if (type(lengths) is not tuple or not lengths or any(type(n) is not int or n <= 0 for n in lengths)
                or sum(lengths) > 1024 * MICRO_DOCUMENTS):
            raise ValueError('complete positive document geometry within context required')
        self.lengths = lengths
        chunks, offset, epochs = [], 0, 0
        for document, length in enumerate(lengths):
            for start in range(0, length, 1024):
                chunks.extend((document, offset, segment, min(256, length - segment), epochs)
                              for segment in range(start, min(start + 1024, length), 256))
                epochs += 1
            offset += length
        self.chunks, self.epochs, self.chunk_count = tuple(chunks), epochs, len(chunks)
        E, C, L = epochs, len(chunks), len(self.LAYERS)
        # int64 sections first (8-byte alignment at offset 0), then float32, then bool; every section padded to 8.
        # 'reports' counts the step's device-side reports (index 0 = global, 1..12 = the sparse layers): zeroed at
        # begin_step, incremented in place by the collector, validated from the boundary snapshot, so completion
        # does not depend on Python executing (a captured replay writes the buffer without running the collector).
        sections = (('reports', torch.int64, (1 + L,)),
                    ('ranked', torch.int64, (E, 2)), ('candidates', torch.int64, (E, 2)), ('winners', torch.int64, (L, C)),
                    ('priors', torch.float32, (E, 25)), ('logits', torch.float32, (L, C, 2)), ('gates', torch.float32, (L, C)),
                    ('valid', torch.bool, (L,)))
        self.layout, cursor = [], 0
        for name, dtype, shape in sections:
            size = torch.tensor([], dtype=dtype).element_size()
            count = 1
            for n in shape:
                count *= n
            nbytes = -(-count * size // 8) * 8
            self.layout.append((name, str(dtype).replace('torch.', ''), tuple(shape), cursor, nbytes))
            cursor += nbytes
        self.nbytes = cursor
        self.device = torch.device(device)
        self.raw = torch.zeros(cursor, dtype=torch.uint8, device=self.device)
        self.views = {}
        for name, dtype, shape in sections:
            start, nbytes = next((row[3], row[4]) for row in self.layout if row[0] == name)
            count = 1
            for n in shape:
                count *= n
            self.views[name] = self.raw[start:start + nbytes].view(dtype)[:count].view(*shape)
        self.header = canonical({'grammar': self.GRAMMAR, 'lengths': list(lengths), 'epochs': E, 'chunks': C,
                                 'layers': list(self.LAYERS), 'layout': self.layout, 'byteorder': sys.byteorder})
        self.route_host_reads = 0
        self._global_calls, self._local_layers = 0, []
        self.capturing = False  # True only inside SegmentedStep.capture(): synthetic repeats of one step's reports

    def begin_step(self):
        self._global_calls, self._local_layers = 0, []
        self.views['valid'].fill_(False)
        self.views['reports'].zero_()

    def _receive(self, name, tensor, index=None):
        import torch
        target = self.views[name] if index is None else self.views[name][index]
        if not isinstance(tensor, torch.Tensor) or tuple(tensor.shape) != tuple(target.shape):
            raise ValueError(f'routing statistic {name} must be a tensor of shape {tuple(target.shape)}')
        if tensor.device != self.device:
            raise ValueError(f'routing statistic {name} must live on {self.device}')
        if tensor.dtype != target.dtype:
            raise ValueError(f'routing statistic {name} must be {target.dtype}, got {tensor.dtype}')
        target.copy_(tensor.detach(), non_blocking=True)

    def collector(self, kind, payload):
        if type(payload) is not dict:
            raise ValueError('routing collector payload must be a dict')
        if kind == 'global':
            geometry = payload['geometry']
            if tuple(getattr(geometry, 'lengths', ())) != self.lengths or tuple(getattr(geometry, 'chunks', ())) != self.chunks:
                raise ValueError('routing geometry differs from the bound statistics buffers')
            if self._global_calls and not self.capturing:
                raise ValueError('duplicate global routing report within one step')
            self._global_calls += 1
            for name in ('priors', 'ranked', 'candidates'):
                self._receive(name, payload[name])
            self.views['reports'][0] += 1
            return
        if kind == 'local':
            layer = payload['layer']
            if type(layer) is not int or layer not in self.LAYERS:
                raise ValueError('local routing report requires an odd sparse layer in 1..23')
            if layer in self._local_layers and not self.capturing:
                raise ValueError(f'duplicate local routing report for layer {layer}')
            self._local_layers.append(layer)
            index = layer // 2
            for name in ('winners', 'logits', 'gates'):
                self._receive(name, payload[name], index)
            self._receive('valid', payload['valid'].reshape(()), index)
            self.views['reports'][1 + index] += 1
            return
        raise ValueError(f'unknown routing report kind {kind!r}')

    def complete(self, snapshot=None):
        """Validate completion from the DEVICE report counts (one global, one per sparse layer), never from Python."""
        counts = self._decode(self.snapshot() if snapshot is None else snapshot)['reports'].tolist()
        if counts != [1] * (1 + len(self.LAYERS)):
            raise RuntimeError(f'incomplete routing statistics for the step: device report counts {counts}')

    def snapshot(self):
        """ONE device-to-host copy of the whole buffer (the step's final synchronization has drained the stream);
        refuses unless the device report counts show exactly one global and one report per sparse layer."""
        raw = bytes(self.raw.cpu().numpy().tobytes())
        self.complete(raw)
        return raw

    def digest(self, snapshot):
        return hashlib.sha256(self.header + b'\0' + snapshot).hexdigest()

    def _decode(self, snapshot):
        import numpy
        out = {}
        for name, dtype, shape, start, nbytes in self.layout:
            count = 1
            for n in shape:
                count *= n
            out[name] = numpy.frombuffer(snapshot, dtype=dtype, count=count, offset=start).reshape(shape)
        return out

    def routes(self, snapshot):
        """Legacy route rows (document, layer, start, ranked pair, winner) in the resident trace's materialize() order."""
        fields = self._decode(snapshot)
        ranked, winners = fields['ranked'].tolist(), fields['winners'].tolist()
        rows = [(document, 2 * depth + 1, start, tuple(ranked[epoch]), winners[depth][index])
                for depth in range(len(self.LAYERS))
                for index, (document, offset, start, size, epoch) in enumerate(self.chunks)]
        return tuple(sorted(rows, key=lambda row: row[:3]))

    def unrouted(self, snapshot):
        """Per sparse layer, the global expert identities that won no chunk this step (zero routed rows), as
        {layer: (expert, ...)}; layers where every expert won at least one chunk are absent. Invalid winners (< 0) are
        not routes. Membership is per layer: an expert used in another layer is still unrouted here."""
        fields = self._decode(snapshot)
        out = {}
        for depth, layer in enumerate(self.LAYERS):
            used = {int(winner) for winner in fields['winners'][depth].tolist() if winner >= 0}
            zero = tuple(expert for expert in range(25) if expert not in used)
            if zero:
                out[layer] = zero
        return out

    def statistics(self, snapshot):
        import numpy
        fields = self._decode(snapshot)
        return {'grammar': self.GRAMMAR, 'epochs': self.epochs, 'chunks': self.chunk_count,
                'winner_histogram': [numpy.bincount(row.clip(min=0), minlength=25).tolist() for row in fields['winners']],
                'mean_gate': [float(x) for x in fields['gates'].mean(axis=1)],
                'valid': [bool(x) for x in fields['valid']],
                'ranked_pairs': fields['ranked'].tolist()}


EXPERT_OWNER = re.compile(r'^experts\.(\d+)\.layers\.(\d+)\.')


def expert_owner_index(inventory):
    """{(layer, expert): [Parameter, ...]} over the expert-layer owners of the complete inventory that can carry a
    gradient (requires_grad); parsed from the equation-inventory names experts.<expert>.layers.<layer>.<...>."""
    index = {}
    for name, parameter in inventory.items():
        match = EXPERT_OWNER.match(name)
        if match and parameter.requires_grad:
            index.setdefault((int(match.group(2)), int(match.group(1))), []).append(parameter)
    return index


def template_untrained_parameters(inventory):
    """Parameters the decoder's fixed layer template never runs this step: attention (and its norm) outside
    _ATTENTION_KEEP, shared FFN (and its norm) outside _FFN_KEEP, and the expert norm and every expert's weights at a
    sparse layer outside _EXPERT_KEEP. The captured path materialises and zeroes grads IN PLACE for every registered
    owner, so without release fused AdamW steps them with zero gradient: no moment change, but decoupled weight decay
    shrinks weights the template never trains, and the kernel walks their elements. Releasing their grads to None
    before optimizer.step gives them reference skip semantics (the release_unrouted_expert_grads rule applied to
    template sites). With no template in force every set is the full range and this returns an empty list."""
    from ember.model import ember_v0_decoder as decoder
    layers = range(24)
    attention = {layer for layer in layers if layer not in decoder._ATTENTION_KEEP}
    ffn = {layer for layer in layers if layer not in decoder._FFN_KEEP}
    expert = {layer for layer in layers if layer % 2 == 1 and layer not in decoder._EXPERT_KEEP}
    released = []
    for name, parameter in inventory.items():
        match = re.match(r'(?:experts\.\d+\.)?layers\.(\d+)\.(attention|shared|expert_norm|down|up|gate)', name)
        if match is None:
            continue
        layer, site = int(match.group(1)), match.group(2)
        if name.startswith('experts.'):
            hit = layer in expert
        elif site == 'attention':
            hit = layer in attention
        elif site == 'shared':
            hit = layer in ffn
        elif site == 'expert_norm':
            hit = layer in expert
        else:
            hit = False
        if hit:
            released.append(parameter)
    if (attention or ffn or expert) and not released:
        raise ValueError('layer template is in force but no untrained parameter name matched')
    return released


def deferred_verdict_enabled():
    return os.environ.get('EMBER_DEFERRED_VERDICT') == '1'


def gated_optimizer_step(optimizer, expert_owners, buffers, refused):
    """Fused AdamW over the parameters that carry a gradient, with found_inf on the device: the dense set gated by
    `refused`, every expert owner by refused | unrouted (its expert won no chunk of its layer in this step's winners).
    Per tensor this is the same kernel with the same arguments optimizer.step() launches; the partition changes only
    which tensors share a launch. Returns (keys, skip): the gated expert owners and their device found_inf values."""
    import torch
    from torch.optim.adam import adam
    cache = getattr(optimizer, '_ember_gate_cache', None)
    if cache is None:
        owner_of = {id(parameter): key for key, parameters in expert_owners.items() for parameter in parameters}
        cache = optimizer._ember_gate_cache = {'owner_of': owner_of, 'index': {}}
    owner_of = cache['owner_of']
    members = []
    for group in optimizer.param_groups:
        if group.get('fused') is not True or group.get('amsgrad') or group.get('maximize'):
            raise ValueError('the deferred verdict gates fused AdamW only')
        split = {}
        for parameter in group['params']:
            if parameter.grad is not None:
                split.setdefault(owner_of.get(id(parameter)), []).append(parameter)
        members.append((group, split))
    keys = tuple(sorted({key for _, split in members for key in split if key is not None}))
    index = cache['index'].get(keys)
    if index is None:
        rows = torch.tensor([layer // 2 for layer, _ in keys], dtype=torch.long).to(buffers.device)
        experts = torch.tensor([expert for _, expert in keys], dtype=torch.long).to(buffers.device)
        index = cache['index'][keys] = (rows, experts, {key: k for k, key in enumerate(keys)})
    rows, experts, position = index
    dense = refused.to(torch.float32)
    skip = None
    if keys:
        hits = (buffers.views['winners'].index_select(0, rows) == experts[:, None]).any(1)
        skip = (refused | ~hits).to(torch.float32)
    with torch.no_grad():
        for group, split in members:
            beta1, beta2 = group['betas']
            for key, parameters in split.items():
                sub = dict(group)
                sub['params'] = parameters
                params, grads, exp_avgs, exp_avg_sqs, max_exp_avg_sqs, steps = [], [], [], [], [], []
                has_complex = optimizer._init_group(sub, params, grads, exp_avgs, exp_avg_sqs, max_exp_avg_sqs, steps)
                adam(params, grads, exp_avgs, exp_avg_sqs, max_exp_avg_sqs, steps, amsgrad=False,
                     has_complex=has_complex, beta1=beta1, beta2=beta2, lr=group['lr'],
                     weight_decay=group['weight_decay'], eps=group['eps'], maximize=False, foreach=group['foreach'],
                     capturable=group['capturable'], differentiable=group['differentiable'], fused=True,
                     grad_scale=None, found_inf=(dense if key is None else skip[position[key]]),
                     decoupled_weight_decay=group['decoupled_weight_decay'])
    return keys, skip


def segment_optimizer_enabled():
    return os.environ.get('EMBER_SEGMENT_OPTIMIZER') == '1'


class SegmentOptimizer:
    """Gated fused AdamW per captured segment on a side stream, launched from post-accumulate-grad hooks as the
    backward completes each segment. Per tensor the kernel and its arguments equal gated_optimizer_step's; only the
    launch partition, the stream and the launch time change. Armed per update by arm() (before backward), closed by
    finish() (after backward), which steps whatever did not complete early and joins the side stream."""

    def __init__(self, optimizer, expert_owners, capture, device):
        import torch
        for group in optimizer.param_groups:
            if group.get('fused') is not True or group.get('amsgrad') or group.get('maximize'):
                raise ValueError('the segment optimizer gates fused AdamW only')
        self.optimizer, self.device = optimizer, device
        self.side = torch.cuda.Stream(device=device)
        self.owner_of = {id(p): key for key, ps in expert_owners.items() for p in ps}
        self.keys = tuple(sorted(expert_owners))
        self.position = {key: k for k, key in enumerate(self.keys)}
        self.group_index = {id(p): gi for gi, group in enumerate(optimizer.param_groups) for p in group['params']}
        untrained = {id(p) for p in getattr(optimizer, '_ember_template_untrained', ())}
        seen = {}
        for segment in capture.segments:
            for p in segment.params:
                seen.setdefault(id(p), []).append(segment.index)
        self.segment_of, self.members = {}, {}
        for segment in capture.segments:
            for p in segment.params:
                i = id(p)
                if (i in self.group_index and i not in untrained and p.requires_grad and len(seen[i]) == 1
                        and i not in self.segment_of):
                    self.segment_of[i] = segment.index
                    self.members.setdefault(segment.index, []).append(p)
        self.hooks = [p.register_post_accumulate_grad_hook(self._hook)
                      for ps in self.members.values() for p in ps]
        self.armed, self._index, self._gather, self.last_early = None, None, {}, None

    def arm(self, execution, buffers, loss):
        import torch
        if self.keys and self._index is None:
            self._index = (torch.tensor([layer // 2 for layer, _ in self.keys], dtype=torch.long).to(buffers.device),
                           torch.tensor([expert for _, expert in self.keys], dtype=torch.long).to(buffers.device))
        refused = ~(execution.input_valid.all() & execution.routing_valid
                    & (buffers.views['reports'] == 1).all() & torch.isfinite(loss.detach().float()))
        skip = None
        if self.keys:
            rows, experts = self._index
            hits = (buffers.views['winners'].index_select(0, rows) == experts[:, None]).any(1)
            skip = (refused | ~hits).to(torch.float32)
        self.armed = dict(refused=refused, dense=refused.to(torch.float32), skip=skip, stepped=set(), early=0,
                          twice=False, pending={index: {id(p) for p in ps} for index, ps in self.members.items()})
        return refused

    def _hook(self, parameter):
        armed = self.armed
        if armed is None:
            return
        i = id(parameter)
        if i in armed['stepped']:
            armed['twice'] = True
            return
        pending = armed['pending'][self.segment_of[i]]
        pending.discard(i)
        if not pending:
            members = [p for p in self.members[self.segment_of[i]] if p.grad is not None]
            if members:
                self._launch(members, armed)
                armed['early'] += 1

    def _launch(self, params, armed):
        import torch
        from torch.optim.adam import adam
        ready = torch.cuda.Event()
        ready.record(torch.cuda.current_stream(self.device))
        self.side.wait_event(ready)
        split = {}
        for p in params:
            split.setdefault((self.group_index[id(p)], self.owner_of.get(id(p))), []).append(p)
        with torch.cuda.stream(self.side), torch.no_grad():
            for (gi, key), members in split.items():
                group = self.optimizer.param_groups[gi]
                beta1, beta2 = group['betas']
                sub = dict(group)
                sub['params'] = members
                ps, grads, exp_avgs, exp_avg_sqs, max_exp_avg_sqs, steps = [], [], [], [], [], []
                has_complex = self.optimizer._init_group(sub, ps, grads, exp_avgs, exp_avg_sqs, max_exp_avg_sqs, steps)
                adam(ps, grads, exp_avgs, exp_avg_sqs, max_exp_avg_sqs, steps, amsgrad=False,
                     has_complex=has_complex, beta1=beta1, beta2=beta2, lr=group['lr'],
                     weight_decay=group['weight_decay'], eps=group['eps'], maximize=False, foreach=group['foreach'],
                     capturable=group['capturable'], differentiable=group['differentiable'], fused=True,
                     grad_scale=None, found_inf=(armed['dense'] if key is None else armed['skip'][self.position[key]]),
                     decoupled_weight_decay=group['decoupled_weight_decay'])
        armed['stepped'].update(id(p) for p in params)

    def finish(self, refused):
        """Step every parameter with a gradient that did not complete early, join the side stream, and return
        (stepped owner keys, their device skip values, device mismatch of the boundary verdict vs the armed one)."""
        import torch
        armed, self.armed = self.armed, None
        if armed is None:
            raise RuntimeError('segment optimizer finished an update it never armed')
        remaining = [p for group in self.optimizer.param_groups for p in group['params']
                     if p.grad is not None and id(p) not in armed['stepped']]
        if remaining:
            self._launch(remaining, armed)
        torch.cuda.current_stream(self.device).wait_stream(self.side)
        if armed['twice']:
            raise RuntimeError('a segment owner accumulated twice in one backward')
        keys = tuple(sorted({self.owner_of[i] for i in armed['stepped'] if i in self.owner_of}))
        skip = None
        if keys:
            gather = self._gather.get(keys)
            if gather is None:
                gather = self._gather[keys] = torch.tensor([self.position[k] for k in keys],
                                                           dtype=torch.long).to(self.device)
            skip = armed['skip'].index_select(0, gather)
        self.last_early = armed['early']
        return keys, skip, refused != armed['refused']


def _stage_next_early(next_pack, device, image_text, pack, two_ahead):
    """Update index+1's pinned inputs and image patches (non-blocking copies on the current stream)."""
    staged = (staged_inputs(next_pack, device),
              load_image_text_module().load_patches(next_pack, device, pinned=True)
              if next_pack.get('images') else (None, None),
              load_image_text_module().LAST_SOURCE if next_pack.get('images') else None)
    if image_text is not None and two_ahead:
        # index+1's decode began one update earlier, so the staging above did not wait on it;
        # index+2's begins now and is joined inside this update's wall.
        load_image_text_module().prefetch_index(image_text, pack.get('index', 0) + 2)
    return staged


def release_unrouted_expert_grads(expert_owners, unrouted):
    """Reference AdamW skip semantics at the pre-update boundary: an expert owner that routed no rows in its layer this
    step has NO gradient, so its grad is None before optimizer.step. (The grouped resident backward materialises zeros
    for every supported owner of the group; a zero gradient would apply weight decay, moment decay and a step count the
    reference paged path never applies.) Returns {layer: [expert, ...]} of the owners actually released."""
    released = {}
    for (layer, expert), parameters in sorted(expert_owners.items()):
        if expert not in unrouted.get(layer, ()):
            continue
        found = False
        for parameter in parameters:
            if parameter.grad is not None:
                parameter.grad = None
                found = True
        if found:
            released.setdefault(layer, []).append(expert)
    return released


def capture_prerequisites(identity):
    """Refuse the capture mode before any device allocation unless the identity declares what resident execution
    needs: exactly four ascending expert identities (the resident capacity), document-batched steps, and at least one
    warm step (the recorded exemplar). Returns the resident expert tuple."""
    experts = tuple(identity['support']['experts'])
    if len(experts) != 4 or experts != tuple(sorted(set(experts))):
        raise ValueError('segmented capture needs exactly four declared resident experts')
    if identity.get('batch_documents') is not True:
        raise ValueError('segmented capture needs document-batched steps')
    _, _, warm, _ = geometry_counts(identity['geometry'], trajectory=trajectory_mode(identity), hour=hour_mode(identity),
                                    measurement=measurement_mode(identity))
    if warm < 1:
        raise ValueError('segmented capture needs one warm step as the recorded exemplar')
    return experts


def prepare_model(model, identity, first_lengths, device, *, mode, optimizer_factory):
    """Activation order per execution mode; returns (inventory, optimizer).

    Legacy (mode None): activate the paged execution (capacity 2), then declare support, then build the optimizer over
    the device population — the official baseline order, unchanged. Capture mode: prerequisites first (no allocation
    on refusal), support and optimizer declared on the CPU population, resident activation with the four declared
    experts retaining that optimizer, geometry bound to the first pack so the segment factory sees it."""
    support = identity['support']
    if mode in MODE_SOURCES:
        experts = capture_prerequisites(identity)
        model.apply_update_support(support['locus'], experts=experts)
        inventory = model.parameter_inventory()
        optimizer = optimizer_factory(inventory)
        model.activate_cuda(device, resident_capacity=4, resident_experts=experts, optimizer=optimizer)
        model._cuda_execution.bind_geometry(tuple(first_lengths))
        return inventory, optimizer
    model.activate_cuda(device)
    inventory = model.parameter_inventory()
    model.apply_update_support(support['locus'], experts=tuple(support['experts']))
    return inventory, optimizer_factory(inventory)


def routing_buffers(lengths, device):
    """One buffer set per static geometry per device, allocated once (the collector then only copies)."""
    import torch
    key = (tuple(lengths), str(torch.device(device)))
    if key not in _ROUTING_BUFFERS:
        _ROUTING_BUFFERS[key] = RoutingStatisticsBuffers(tuple(lengths), device=device)
    return _ROUTING_BUFFERS[key]


def document_lengths(starts, total):
    starts = tuple(starts)
    return tuple(b - a for a, b in zip(starts, starts[1:] + (total,)))


def micro_packs(pack):
    """Split one update's pack into its 4-document micro-steps (a 4-document pack is its own single micro-step).
    Documents are whole and positions are per document, so each micro-step is exactly the forward geometry the
    capture was recorded under."""
    starts = tuple(pack['document_starts'])
    total = len(pack['token_ids'])
    if len(starts) <= MICRO_DOCUMENTS:
        return [pack]
    if pack.get('images'):
        raise ValueError('image-text packs are defined for one 4-document micro-step only')
    if len(starts) % MICRO_DOCUMENTS or starts[0] != 0:
        raise ValueError('pack documents are not a whole number of micro-steps')
    bounds = list(starts) + [total]
    out = []
    for first in range(0, len(starts), MICRO_DOCUMENTS):
        lo, hi = bounds[first], bounds[first + MICRO_DOCUMENTS]
        out.append({'token_ids': pack['token_ids'][lo:hi], 'target_ids': pack['target_ids'][lo:hi],
                    'positions': pack['positions'][lo:hi],
                    'document_starts': [s - lo for s in starts[first:first + MICRO_DOCUMENTS]]})
    if sum(len(m['token_ids']) for m in out) != total:
        raise ValueError('micro-steps do not cover the pack')
    return out


def _take_route_snapshot(buffers, routes, verify_routes, micro_snapshots, unrouted):
    """Per-micro-step boundary copy: each micro-step's report set is validated on its own, and an expert owner is
    unrouted for the UPDATE only if it routed no rows in ANY micro-step. Returns the updated unrouted map."""
    snapshot = buffers.snapshot()
    if verify_routes and buffers.routes(snapshot) != tuple(routes.materialize()):
        raise ValueError('device routing buffers differ from the model trace')
    micro_snapshots.append(snapshot)
    these = {layer: set(experts) for layer, experts in buffers.unrouted(snapshot).items()}
    return these if unrouted is None else {
        layer: unrouted[layer] & these[layer] for layer in unrouted if layer in these}


IGNORE_TARGET = -100


def answer_weight():
    """EMBER_ANSWER_WEIGHT: each answer-letter target counts this many times in the loss (unset: 1)."""
    raw = os.environ.get('EMBER_ANSWER_WEIGHT', '')
    if not raw:
        return 1
    weight = int(raw)
    if weight < 2:
        raise ValueError('EMBER_ANSWER_WEIGHT must be an integer >= 2 when set')
    return weight


def _weighted_rows(rows, answer_rows, weight):
    """rows plus (weight - 1) repeats of every answer row inside them, repeats appended in row order."""
    if weight == 1 or not answer_rows:
        return rows
    inside = [row for row in answer_rows if row in set(rows)]
    return list(rows) + [row for row in inside for _ in range(weight - 1)]


def loss_selection(micro, device):
    """None when every target is loss-bearing (text-only: the prior function); else per-document row selections."""
    import torch
    targets = micro['target_ids']
    if IGNORE_TARGET not in targets:
        return None
    starts = list(micro['document_starts']) + [len(targets)]
    selections, count = [], 0
    for lo, hi in zip(starts, starts[1:]):
        rows = [row for row in range(lo, hi) if targets[row] != IGNORE_TARGET]
        if not rows:
            raise ValueError('a document carries no loss-bearing target')
        rows = _weighted_rows(rows, micro.get('answer_rows', ()), answer_weight())
        count += len(rows)
        selections.append(None if len(rows) == hi - lo and rows == list(range(lo, hi)) else
                          (torch.tensor(rows, dtype=torch.long).to(device, non_blocking=True), len(rows)))
    return {'selections': tuple(selections), 'denominator': count}


def staged_inputs(micro, device):
    """tokens, targets, positions and loss_selection(micro, device), through ONE pinned host array and ONE copy.

    Same values and dtypes as the three torch.tensor(list, device=...) calls plus loss_selection: the selection rows
    are the indices whose target is not IGNORE_TARGET within each document, in order, and a fully loss-bearing
    document keeps None exactly as loss_selection does."""
    import numpy
    import torch
    targets_host = numpy.asarray(micro['target_ids'], dtype=numpy.int64)
    n = targets_host.shape[0]
    # positions are [n] on text-only packs and [n, 3] (position, x, y) on image-text packs: flattened here,
    # restored to their own shape on the device slice.
    positions_host = numpy.asarray(micro['positions'], dtype=numpy.int64)
    end = 2 * n + positions_host.size
    parts = [numpy.asarray(micro['token_ids'], dtype=numpy.int64), targets_host, positions_host.reshape(-1)]
    spans, weight, answers = None, answer_weight(), micro.get('answer_rows', ())
    if (targets_host == IGNORE_TARGET).any():
        starts = list(micro['document_starts']) + [n]
        spans, offset = [], end
        for lo, hi in zip(starts, starts[1:]):
            rows = lo + numpy.flatnonzero(targets_host[lo:hi] != IGNORE_TARGET)
            if rows.shape[0] == 0:
                raise ValueError('a document carries no loss-bearing target')
            if weight > 1 and answers:
                rows = numpy.asarray(_weighted_rows(rows.tolist(), answers, weight), dtype=numpy.int64)
            if rows.shape[0] == hi - lo:
                spans.append(None)
            else:
                spans.append((offset, rows.shape[0]))
                parts.append(rows.astype(numpy.int64))
                offset += rows.shape[0]
    host = torch.from_numpy(numpy.concatenate(parts))
    if device.type == 'cuda':
        host = host.pin_memory()
    staged = host.to(device, non_blocking=True)
    selection = None
    if spans is not None:
        selection = {'selections': tuple(None if span is None else (staged[span[0]:span[0] + span[1]], span[1])
                                         for span in spans),
                     'denominator': sum(length for *_, length in (s for s in spans if s is not None)) +
                                    sum(hi - lo for (lo, hi), s in zip(zip(starts, starts[1:]), spans)
                                        if s is None)}
    return staged[:n], staged[n:2 * n], staged[2 * n:end].view(positions_host.shape), selection


def exposure_fields(pack, wall):
    """A1 counting: loss-bearing decoder targets, image patches, images and non-loss positions, never converted.
    positions_per_second is loss-bearing decoder targets per second (identical to decoder positions/s on text packs)."""
    targets = pack['target_ids']
    loss_bearing = sum(1 for value in targets if value != IGNORE_TARGET)
    images = pack.get('images', ())
    return {'loss_bearing_positions': loss_bearing, 'non_loss_positions': len(targets) - loss_bearing,
            'image_patches': sum(span['count'] for span in images), 'images': len(images),
            'positions_per_second': loss_bearing / wall, 'decoder_positions_per_second': len(targets) / wall,
            'images_per_second': len(images) / wall,
            'rate_basis': 'loss-bearing-decoder-targets'}


def measure_step(model, optimizer, pack, *, device, batch_documents=False, run_id=None, verify_routes=False,
                 capture=None, record=False, expert_owners=None, route_observer=None, route_snapshot=None,
                 experiment_binding=None, image_text=None, next_pack=None,
                 prelaunch_next=False):
    """Return one row only after context exit, successful update and synchronization.

    next_pack with EMBER_STAGE_NEXT_STEP=1 (on the resident captured path, after the recording step): once this step's
    optimizer is launched, and before its wall closes, the host stages update index+1 while the device runs the
    update -- the in-place gradient clear, the pinned input copy, the image patches, and the begin_step
    structure/registration tuple of the staged owner. The next step consumes exactly that staging only when handed
    the SAME pack object; otherwise it recomputes. Every staged cost is paid inside this measured wall.

    image_text (the A1 stream) makes the step start decoding update index+1's images once its last backward is
    launched, and join them before its own wall closes: the decode is paid inside a measured wall, beside device work.

    On a resident-expert model the step reports its routes through RoutingStatisticsBuffers (zero host reads
    inside the forward/backward; ONE device-to-host copy at the pre-update boundary validates the report set and
    then serves the digest and the statistics). verify_routes additionally materializes the model's own trace and
    requires it to equal the rows decoded from the buffers (the reference path; never on the measured path).
    Both refusals fire before optimizer.step(), so a step whose device reports are incomplete cannot mutate the model.

    capture (a bound SegmentedStep from model.bind_segmented_capture) selects the segmented path: with record=True this
    step is the eager exemplar the graphs are recorded from (a real update, counted as warm work); afterwards the step
    runs through the captured segments. Owner grads are zeroed IN PLACE (static-accumulate) so the captured backward
    keeps its grad storage; the routing buffers are the collector's static state, so the pre-update boundary copy is
    unchanged.
    """
    import torch
    if device.type == 'cuda':
        if not isinstance(run_id, str) or not re.fullmatch('[0-9a-f]{32}', run_id):
            raise ValueError('CUDA step requires the bound owned run')
        from ember.governance.scripts import cia_conformance_resources as resources
        resources.require_owned_job(run_id, namespace=JOB_NAMESPACE, host_memory_bytes=LIMITS['host_memory_bytes'])
    if route_observer is not None and not callable(route_observer):
        raise ValueError('reference routing observer must be callable')
    if route_snapshot is not None and type(route_snapshot) is not dict:
        raise ValueError('trajectory routing snapshot requires a plain output dictionary')
    experiment = step_experiment_fields(capture, experiment_binding)
    synchronize = (lambda: torch.cuda.synchronize(device)) if device.type == 'cuda' else (lambda: None)
    global _NEXT_STEP
    # A forward pre-launched by the previous call (prelaunch_next) is queued behind that call's optimizer on the
    # same stream; draining here would idle the device while the host launches this step's backward.
    if not (_NEXT_STEP is not None and 'forward' in _NEXT_STEP):
        synchronize()
    if device.type == 'cuda':
        torch.cuda.reset_peak_memory_stats(device)
    before = _cache_values(model._cuda_execution.cache)
    micros = micro_packs(pack)
    depth = len(micros)
    if depth > 1 and (route_observer is not None or route_snapshot is not None or verify_routes):
        raise ValueError('reference routing observation is defined for one micro-step only')
    started = time.perf_counter()
    resident = bool(getattr(model, '_resident_experts', None))
    if (route_snapshot is not None and not resident) or (route_observer is not None and resident):
        raise ValueError('routing observation interface differs from the selected execution mode')
    if capture is not None:
        if not resident:
            raise ValueError('segmented capture requires the resident routing buffers')
        if capture.execution is not model._cuda_execution or getattr(model._cuda_execution, 'segmented', None) is not capture:
            raise ValueError('segmented capture is not bound to this model execution')
    ahead, _NEXT_STEP = _NEXT_STEP, None
    pre = ahead.get('forward') if ahead is not None else None
    if pre is not None and (ahead['pack'] is not pack or depth != 1 or capture is None or record):
        raise RuntimeError('a pre-launched forward was handed a different pack or path')
    if ahead is not None and (ahead['pack'] is not pack or depth != 1 or capture is None or record):
        ahead = None  # staged for a different pack or path: discarded, everything below recomputes
    if capture is not None:
        if ahead is None:
            capture.zero_grad(optimizer=optimizer)  # one in-place clear across optimizer and captured owners
    else:
        optimizer.zero_grad(set_to_none=True)
    if depth > 1 and expert_owners is not None:
        # An owner released to None last update would receive its first micro-step gradient by AccumulateGrad
        # STEALING the incoming tensor -- on the captured path that tensor aliases the graph's static gradient
        # output, which the next micro-step's replay overwrites before adding it again. Materialised zeros force
        # every micro-step onto the in-place += path, so the sum is the sum.
        for parameters in expert_owners.values():
            for parameter in parameters:
                if parameter.requires_grad and parameter.grad is None:
                    parameter.grad = torch.zeros_like(parameter)
    staged = time.perf_counter()
    events = (pre['events'] if pre is not None else
              [torch.cuda.Event(enable_timing=True) for _ in range(3 * depth + 1)] if device.type == 'cuda' else None)
    forward_seconds = backward_seconds = 0.0
    losses = []
    micro_snapshots = []
    unrouted = None
    routes = None
    deferred_buffers = None
    stage_next = (next_pack is not None and not record and capture is not None and resident and depth == 1
                  and os.environ.get('EMBER_STAGE_NEXT_STEP') == '1' and len(micro_packs(next_pack)) == 1)
    staged_early = None

    def _prepare(micro, staged_ahead):
        # Inputs, embedding and routing-buffer reset for one micro-step (same calls, same order as before).
        if staged_ahead is not None:
            (tokens, targets, positions, selection), (image_rows, image_patches) = (staged_ahead['inputs'],
                                                                                    staged_ahead['patches'])
            patches_source = staged_ahead['patches_source']
        else:
            tokens, targets, positions, selection = staged_inputs(micro, device)
            image_rows, image_patches = (load_image_text_module().load_patches(micro, device)
                                         if micro.get('images') else (None, None))
            patches_source = load_image_text_module().LAST_SOURCE if micro.get('images') else None
        starts = tuple(micro['document_starts'])
        embedded = model.embed_text(tokens)
        if image_rows is not None:
            # Placeholder rows are REPLACED (out of place), so image.weight is trained through these rows and
            # the placeholder token's embedding receives no gradient from them.
            embedded = embedded.index_put((image_rows,), model.embed_image(image_patches))
        buffers = routing_buffers(document_lengths(starts, len(micro['token_ids'])), device) if resident else None
        if buffers is not None:
            buffers.begin_step()
        return dict(targets=targets, positions=positions, selection=selection, starts=starts, embedded=embedded,
                    buffers=buffers, patches_source=patches_source)

    def _launch(prep, micro_index, events):
        # Forward and loss for one micro-step; returns what the backward and the row need.
        targets, positions, selection = prep['targets'], prep['positions'], prep['selection']
        starts, embedded, buffers = prep['starts'], prep['embedded'], prep['buffers']
        micro_started = time.perf_counter()
        if events is not None:
            events[3 * micro_index].record()
        if buffers is not None:
            logits, routes = model(embedded, positions, document_starts=starts,
                                   return_routes=True, batch_documents=batch_documents,
                                   return_device_routes=True, device_route_collector=buffers.collector,
                                   **({'training_hidden': True} if capture is not None and getattr(capture, '_cia_head_output', 'logits') == 'hidden' else {}))
        else:
            logits, routes = model(embedded, positions, document_starts=starts,
                                   return_routes=True, batch_documents=batch_documents,
                                   **({'route_observer': route_observer} if route_observer is not None else {}))
        streamed = capture is not None and getattr(capture, '_cia_head_output', 'logits') == 'hidden'
        if streamed and selection is not None:
            loss = capture.loss(logits, targets.clamp(min=0), **selection)
        else:
            loss = (capture.loss(logits, targets) if capture is not None else
                    _native_loss(logits, targets))
        if events is not None:
            events[3 * micro_index + 1].record()
        return logits, routes, loss, micro_started, time.perf_counter()

    deferred = deferred_verdict_enabled()
    if deferred and (depth != 1 or verify_routes or route_observer is not None or route_snapshot is not None
                     or expert_owners is None or capture is None or device.type != 'cuda'):
        raise ValueError('the deferred verdict is defined for one captured resident micro-step on CUDA only')
    if deferred:
        model._cuda_execution.defer_verdict = True
    segment_optimizer = None
    if segment_optimizer_enabled():
        if not deferred:
            raise ValueError('the segment optimizer requires the deferred verdict')
        if capture.captured and not record:
            segment_optimizer = getattr(optimizer, '_ember_segment_optimizer', None)
            if segment_optimizer is None:
                segment_optimizer = optimizer._ember_segment_optimizer = SegmentOptimizer(
                    optimizer, expert_owners, capture, device)
    step_stack = pre['stack'] if pre is not None else contextlib.ExitStack()
    if pre is None:
        step_stack.enter_context(model.candidate_step())
    with step_stack:
        for micro_index, micro in enumerate(micros):
            prep = pre['prepared'] if pre is not None else _prepare(micro, ahead)
            buffers, patches_source = prep['buffers'], prep['patches_source']
            recording = (capture.record() if (capture is not None and record and micro_index == 0)
                         else contextlib.nullcontext())
            with recording:
                logits, routes, loss, micro_started, micro_forwarded = (
                    pre['launched'] if pre is not None else _launch(prep, micro_index, events))
                if segment_optimizer is not None:
                    # The verdict and the unrouted gate are final once the forward is enqueued, so each segment's
                    # owners are stepped (gated) on the side stream as the backward finishes that segment.
                    segment_optimizer.arm(model._cuda_execution, buffers, loss)
                loss.backward()
                if events is not None:
                    events[3 * micro_index + 2].record()
                micro_backwarded = time.perf_counter()
                two_ahead = stage_next and os.environ.get('EMBER_DECODE_TWO_AHEAD') == '1'
                stage_after_optimizer = stage_next and os.environ.get('EMBER_STAGE_AFTER_OPTIMIZER') == '1'
                if image_text is not None and micro_index == len(micros) - 1 and not two_ahead:
                    load_image_text_module().prefetch_index(image_text, pack.get('index', 0) + 1)
                if stage_next and micro_index == len(micros) - 1:
                    # Update index+1's inputs, staged at the last backward launch: the device still has this
                    # backward queued, and end_step below synchronizes, so staging after candidate_step exits
                    # ran on an idle device. Pure host-to-device work, ordered before optimizer.step.
                    if not stage_after_optimizer:
                        staged_early = _stage_next_early(next_pack, device, image_text, pack, two_ahead)
            forward_seconds += micro_forwarded - micro_started
            backward_seconds += micro_backwarded - micro_forwarded
            losses.append(loss.detach())
            deferred_buffers = None
            if buffers is not None:
                if micro_index == len(micros) - 1 and not verify_routes:
                    # The last micro-step's copy blocks until backward drains; taken after candidate_step exits, the
                    # end_step host checks overlap backward instead of following it. Still before optimizer.step.
                    deferred_buffers = buffers
                else:
                    unrouted = _take_route_snapshot(buffers, routes, verify_routes, micro_snapshots, unrouted)
            if capture is not None and record:
                del logits, loss, routes
                routes = None
    forwarded = staged + forward_seconds
    backwarded = forwarded + backward_seconds
    exited = time.perf_counter()
    if deferred:
        # No host read before the optimizer: one device refusal, pinned copies of the routing buffer and the loss.
        if deferred_buffers is None:
            raise ValueError('the deferred verdict requires the routing statistics buffers')
        execution = model._cuda_execution
        loss_device = losses[0].float()
        refused = ~(execution.input_valid.all() & execution.routing_valid
                    & (deferred_buffers.views['reports'] == 1).all() & torch.isfinite(loss_device))
        raw_host = torch.empty(deferred_buffers.nbytes, dtype=torch.uint8, pin_memory=True)
        raw_host.copy_(deferred_buffers.raw, non_blocking=True)
        loss_host = torch.empty((), dtype=torch.float32, pin_memory=True)
        loss_host.copy_(loss_device, non_blocking=True)
        loss_value = snapshot = None
    else:
        if deferred_buffers is not None:
            unrouted = _take_route_snapshot(deferred_buffers, None, False, micro_snapshots, unrouted)
        loss_value = float(sum(float(value) for value in losses) / depth)
        if not math.isfinite(loss_value):
            raise ValueError('nonfinite step loss')
        snapshot = micro_snapshots[-1] if micro_snapshots else None
    released = None
    routing_boundary_started = time.perf_counter()
    if not deferred and unrouted is not None and expert_owners is not None:
        # Reference skip semantics over the whole update: unrouted expert owners carry no gradient into it.
        released = release_unrouted_expert_grads(expert_owners, {layer: tuple(sorted(experts))
                                                                 for layer, experts in unrouted.items() if experts})
    routing_digest_seconds = time.perf_counter() - routing_boundary_started
    if depth > 1:
        # Each micro-step loss is a mean over its own positions; the update applies the mean over all of them.
        grads = [parameter.grad for group in optimizer.param_groups for parameter in group['params']
                 if parameter.grad is not None]
        if grads:
            torch._foreach_mul_(grads, 1.0 / depth)
    template_untrained = getattr(optimizer, '_ember_template_untrained', ())
    for parameter in template_untrained:
        parameter.grad = None
    if deferred:
        segment_mismatch_host = None
        if segment_optimizer is not None:
            gated_keys, gated_skip, segment_mismatch = segment_optimizer.finish(refused)
            segment_mismatch_host = torch.empty((), dtype=torch.bool, pin_memory=True)
            segment_mismatch_host.copy_(segment_mismatch, non_blocking=True)
        else:
            gated_keys, gated_skip = gated_optimizer_step(optimizer, expert_owners, deferred_buffers, refused)
        skip_host = None
        if gated_skip is not None:
            skip_host = torch.empty(gated_skip.shape, dtype=torch.float32, pin_memory=True)
            skip_host.copy_(gated_skip, non_blocking=True)
        refused_host = torch.empty((), dtype=torch.bool, pin_memory=True)
        refused_host.copy_(refused, non_blocking=True)
    else:
        optimizer.step()
    if events is not None:
        events[-1].record()
    if stage_next and staged_early is None:
        # EMBER_STAGE_AFTER_OPTIMIZER: staged behind this update's optimizer, ahead of the prelaunched forward.
        staged_early = _stage_next_early(next_pack, device, image_text, pack,
                                         os.environ.get('EMBER_DECODE_TWO_AHEAD') == '1')
    if os.environ.get('EMBER_STAGE_OWNER_IDENTITY') == '1':
        stage = getattr(model._cuda_execution, 'stage_next_identity', None)
        if stage is not None:
            model._cuda_execution.stage_validation = stage_next
            stage()
    if stage_next:
        # Update index+1, staged on the host while the device runs this update (all ordered after optimizer.step on
        # the same stream): the in-place clear it would open with, its pinned inputs, and its image patches.
        capture.zero_grad(optimizer=optimizer)
        next_inputs, next_patches, next_source = staged_early
        _NEXT_STEP = {'pack': next_pack, 'inputs': next_inputs, 'patches': next_patches,
                      'patches_source': next_source}
        if prelaunch_next:
            # Update index+1's candidate step opens here (this update's step exited above and its routing
            # snapshot is already on the host) and its forward is enqueued behind this update's optimizer, so
            # the device is not drained between updates. The forward writes no parameter or gradient; its
            # backward, end_step checks and optimizer run in the next call, which must be handed this pack.
            next_events = [torch.cuda.Event(enable_timing=True) for _ in range(4)]
            next_stack = contextlib.ExitStack()
            next_stack.enter_context(model.candidate_step())
            try:
                next_prep = _prepare(micro_packs(next_pack)[0], _NEXT_STEP)
                next_launched = _launch(next_prep, 0, next_events)
            except BaseException:
                next_stack.__exit__(*sys.exc_info())
                raise
            _NEXT_STEP['forward'] = dict(stack=next_stack, prepared=next_prep, launched=next_launched,
                                         events=next_events)
    if _NEXT_STEP is not None and 'forward' in _NEXT_STEP:
        events[-1].synchronize()  # this update's optimizer has completed; the next forward stays queued
    else:
        synchronize()
    if deferred:
        try:
            # The verdict end_step and the boundary snapshot used to give before the optimizer, given now from the
            # pinned copies. Any refusal here found the kernels gated (found_inf 1.0): nothing was mutated.
            model._cuda_execution.settle_deferred()
            snapshot = bytes(raw_host.numpy().tobytes())
            deferred_buffers.complete(snapshot)
            loss_value = float(loss_host)
            if not math.isfinite(loss_value):
                raise ValueError('nonfinite step loss')
            if bool(refused_host):
                raise RuntimeError('device refusal set with every host predicate passing')
            if segment_mismatch_host is not None and bool(segment_mismatch_host):
                raise RuntimeError('the pre-backward verdict differs from the boundary verdict')
            micro_snapshots.append(snapshot)
            unrouted_host = deferred_buffers.unrouted(snapshot)
            gated_unrouted = [key for key in gated_keys if key[1] in unrouted_host.get(key[0], ())]
            if skip_host is not None and [key for key, value in zip(gated_keys, skip_host.tolist())
                                          if value == 1.0] != gated_unrouted:
                raise RuntimeError('device unrouted masks differ from the boundary snapshot')
            released = {}
            for layer, expert in gated_unrouted:
                released.setdefault(layer, []).append(expert)
        except BaseException:
            forward = (_NEXT_STEP or {}).get('forward')
            if forward is not None:
                _NEXT_STEP = None
                forward['stack'].__exit__(*sys.exc_info())
            raise
    if image_text is not None:
        load_image_text_module().join_prefetch()
    finished = time.perf_counter()
    after = _cache_values(model._cuda_execution.cache)
    wall = finished - started
    if buffers is not None and depth == 1:
        routes_sha256, grammar = buffers.digest(snapshot), buffers.GRAMMAR
        routing_statistics, route_host_reads = buffers.statistics(snapshot), buffers.route_host_reads
    elif buffers is not None:
        routes_sha256 = hashlib.sha256(''.join(buffers.digest(s) for s in micro_snapshots).encode()).hexdigest()
        grammar = buffers.GRAMMAR + '+accumulated-v1'
        routing_statistics = [buffers.statistics(s) for s in micro_snapshots]
        route_host_reads = buffers.route_host_reads
    else:
        routes_sha256, grammar, routing_statistics, route_host_reads = (
            hashlib.sha256(canonical(routes)).hexdigest(), ROUTES_DIGEST_GRAMMARS[0], None, None)
    if not math.isfinite(wall) or wall <= 0:
        raise ValueError('complete step wall observation is invalid')
    allocator = ({'allocated_bytes': torch.cuda.memory_allocated(device),
                  'reserved_bytes': torch.cuda.memory_reserved(device),
                  'peak_allocated_bytes': torch.cuda.max_memory_allocated(device),
                  'peak_reserved_bytes': torch.cuda.max_memory_reserved(device)} if device.type == 'cuda' else None)
    if route_snapshot is not None:
        route_snapshot.update(buffers=buffers, snapshot=snapshot)
    return {'index': pack.get('index', 0), 'phase': pack['phase'], 'batch_documents': batch_documents,
            'training_head': ('cce-document-v1' if capture is not None and getattr(capture, '_cia_head_output', 'logits') == 'hidden' else 'native'),
            **experiment,
            'applied_positions': len(pack['token_ids']), 'wall_seconds': wall,
            **exposure_fields(pack, wall),
            'staging_seconds': staged - started, 'forward_seconds': forwarded - staged,
            'backward_seconds': backwarded - forwarded, 'context_exit_seconds': exited - backwarded,
            'optimizer_and_sync_seconds': finished - exited, 'loss': loss_value,
            **({'image_patches_source': patches_source} if pack.get('images') else {}),
            'staged_by_previous_step': ahead is not None, 'staged_next_step': stage_next,
            'accumulation_micro_steps': depth,
            'template_untrained_released': len(template_untrained),
            'cuda_phase_seconds': ({'forward': sum(events[3 * m].elapsed_time(events[3 * m + 1])
                                                   for m in range(depth)) / 1000,
                                   'backward': sum(events[3 * m + 1].elapsed_time(events[3 * m + 2])
                                                   for m in range(depth)) / 1000,
                                   'context_exit_and_optimizer': events[3 * depth - 1].elapsed_time(events[-1]) / 1000}
                                  if events is not None else None),
            'routes_sha256': routes_sha256, 'routes_digest_grammar': grammar,
            'routing_digest_seconds': routing_digest_seconds, 'routing_statistics': routing_statistics,
            'route_host_reads': route_host_reads,
            'unrouted_expert_grads_released': ({str(layer): experts for layer, experts in released.items()}
                                               if released is not None else None),
            'expert_leases': after['lease_count'] - before['lease_count'],
            'expert_bundle_fetches': after['miss_count'] - before['miss_count'],
            'expert_evictions': after['eviction_count'] - before['eviction_count'],
            'host_to_device_bytes': after['transfer_bytes'] - before['transfer_bytes'],
            'cache': {key: after[key] - before[key] for key in before}, 'allocator': allocator,
            'captured': bool(capture is not None and capture.captured), 'claim': CLAIM}


def load_disk_module():
    spec = importlib.util.spec_from_file_location('cia_measurement_disk_runner', ROOT / DISK_ENTRY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _python_command(helper, hidden, *args):
    return ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(helper),
            '--', '-B', str(hidden), *map(str, args)]


def _write_new(path, value):
    with Path(path).open('xb') as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


# Order of the real calls (cia_hour.run_hour emits hour_result then pointer_cas; the worker writes worker-terminal.json and stamps
# worker_terminal only after run_hour returns; the parent stamps segment_complete after OwnedProcessRunner returns with cleanup verified).
TAIL_PHASES = ('segment_launch', 'child_publish_start', 'quarantine', 'counter', 'hour_result', 'pointer_cas', 'worker_terminal', 'segment_complete')
TAIL_STAMP_RETRIES = 40
TAIL_STAMP_RETRY_SECONDS = 0.05


def _write_failed_terminal(custody, payload):
    """Record status=failed unless a terminal record already exists. A terminal written earlier (status=completed) is immutable evidence:
    the failure path must not die on it (H33 FileExistsError masked the original PermissionError) and must not overwrite it."""
    path = Path(custody) / 'worker-terminal.json'
    if path.exists():
        return False
    _write_new(path, payload)
    return True


def tail_stamp(custody, phase):
    """Append one (phase, monotonic_s, wall_utc) row to custody/tail-stamps.jsonl, fsynced, so a killed tail still names its last phase."""
    if phase not in TAIL_PHASES:
        raise ValueError('unknown tail phase: ' + str(phase))
    row = {'phase': phase, 'monotonic_s': time.perf_counter(), 'wall_utc': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()) + ('%.3f' % (time.time() % 1))[1:] + 'Z'}
    # H33 (2026-10-07): a reader that opened this file without write sharing (a sampler's ReadAllLines, a scanner) makes the append-open
    # raise PermissionError for the length of its read; the stamp is retried for a bounded 2 s, so a transient reader never fails an hour.
    for attempt in range(TAIL_STAMP_RETRIES):
        try:
            with Path(custody).joinpath('tail-stamps.jsonl').open('ab') as stream:
                stream.write(canonical(row) + b'\n')
                stream.flush()
                os.fsync(stream.fileno())
            return
        except PermissionError:
            if attempt == TAIL_STAMP_RETRIES - 1:
                raise
            time.sleep(TAIL_STAMP_RETRY_SECONDS)


class GcPauseMeter:
    """Attribute host pauses to CPython cyclic-GC collections: a gc.callbacks hook records every collection's
    generation, duration and start instant; drain() hands back the collections since the previous drain, so the
    loop can file them against the step they interrupted (custody/gc-events.jsonl). Diagnostic only: it changes no
    collection policy and touches no row field.

    Receipt behind it (governed hour 256270a2, 2026-09-12): 5.1% of measured rows carried a +139 ms host pause inside
    the forward wall at strictly step-periodic gaps with every CUDA phase unchanged; the 1,024-update run 9fd531b6
    carried the same pauses at gaps of 29-30 steps."""

    def __init__(self):
        self._open = None
        self.events = []
        self.total = 0

    def __call__(self, phase, info):
        now = time.perf_counter()
        if phase == 'start':
            self._open = (info.get('generation'), now)
        elif phase == 'stop' and self._open is not None:
            generation, began = self._open
            self._open = None
            self.total += 1
            self.events.append({'generation': generation, 'seconds': now - began, 'collected': info.get('collected'),
                                'uncollectable': info.get('uncollectable'), 'at': began})

    def install(self):
        if self not in gc.callbacks:
            gc.callbacks.append(self)
        return self

    def remove(self):
        if self in gc.callbacks:
            gc.callbacks.remove(self)

    # Ownership is scoped: entering installs, leaving (normally or by exception) removes exactly this callback.
    def __enter__(self):
        return self.install()

    def __exit__(self, *exc):
        self.remove()
        return False

    def drain(self):
        events, self.events = self.events, []
        return events

    def bind(self, **identity):
        """run_id / prediction_sha256 stamped on every sidecar row so the file is bound to its run, not a neighbour."""
        self.identity = dict(identity)
        return self

    def file(self, index, phase, *, call_started, call_finished):
        """One sidecar row per governed step: the step call's own start/end instants, the collections that BEGAN
        inside that window (the only ones admissible as pauses of this step), and every other collection since the
        previous row (setup, capture, the explicit collect+freeze, between-step bookkeeping) filed as outside-step.
        Attribution is a question the rows answer by overlap; nothing here presumes a collection caused a pause."""
        inside, outside = [], []
        for event in self.drain():
            (inside if call_started <= event['at'] <= call_finished else outside).append(event)
        return dict(getattr(self, 'identity', {}), index=index, phase=phase, call_started=call_started,
                    call_finished=call_finished, in_step=inside, outside_step=outside)


def bounded_collect(step):
    """The bound on a disabled collector, run every 64 steps. Generation 0 alone leaks: cycles still referenced
    by the in-flight (staged or pre-launched) update at a pass are promoted, become garbage a step later, and a
    disabled collector never examines them again. Two #1945 hours grew from ~33 to ~108 ms per update and died
    at ~28,700 updates on host commit (WinError 1455). Generation 1 each pass reclaims them one pass later; a
    full pass every 4,096 steps bounds anything that outlives two passes."""
    return gc.collect(2 if step % 4096 == 4095 else 1)


def freeze_resident_object_graph(**identity):
    """Move every object alive now -- the resident model, optimizer state, capture graphs, routing buffers -- into
    CPython's permanent generation after one full collection, so every later generation-2 collection traverses only
    the objects allocated since. Host-side only: no tensor, route, optimizer or RNG state is read or written, and the
    collector stays enabled. Called exactly once, immediately before the first measured step (after the last declared
    warm update, whatever warm_steps in 0..2 declares), outside every timed interval."""
    collected = gc.collect()
    gc.freeze()
    if os.environ.get('EMBER_GC_GEN0'):
        gc.set_threshold(int(os.environ['EMBER_GC_GEN0']), *gc.get_threshold()[1:])
    return dict(identity, schema='gc-freeze-v1', collected=collected, frozen=gc.get_freeze_count(),
                threshold=list(gc.get_threshold()), enabled=gc.isenabled(),
                switch_interval_seconds=sys.getswitchinterval())


def verify_worker(binding, binding_path):
    from ember.governance.scripts import cia_conformance_resources as resources
    launch = binding['launch']
    run_id = binding_path.parent.name.removeprefix('measurement-')
    resources.require_owned_job(run_id, namespace=JOB_NAMESPACE, host_memory_bytes=LIMITS['host_memory_bytes'])
    prediction, _ = load_prediction(binding_path.parent / 'prediction.json', launch['prediction_sha256'])
    if (binding.get('claim') != CLAIM or launch['run_id'] != run_id
            or canonical(launch['limits']) != canonical(resource_limits(prediction['identity']))
            or launch['worker_argv'] != sys.argv
            or sys.argv != [str(ROOT / ENTRY), '--worker', str(binding_path)]):
        raise ValueError('worker command, identity or resource envelope differs')
    custody = binding_path.parent.resolve(strict=True)
    if custody.drive.upper() != 'B:' or str(custody) != launch['custody']:
        raise ValueError('measurement custody differs')
    rows = process_census()
    by_pid = {row['ProcessId']: row for row in rows}
    owner = by_pid.get(launch['owner_pid'])
    if owner is None:
        raise ValueError('measurement controller is not alive')
    args = windows_command_args(owner.get('CommandLine') or '')
    expected = [str(Path(sys.executable).resolve(strict=True)), '-B', str(ROOT / ENTRY),
                '--daemon-run', '--live', '--custody', launch['parent_custody'],
                '--hidden-helper', launch['hidden_helper'], '--prediction', launch['prediction_path'],
                '--prediction-sha256', launch['prediction_sha256']]
    if (not args or args[1:] != expected[1:] or not owner.get('ExecutablePath')
            or not os.path.samefile(args[0], sys.executable)
            or not os.path.samefile(owner['ExecutablePath'], sys.executable)):
        raise ValueError('measurement controller executable or argv differs')
    daemon = daemon_identity()
    parent = by_pid.get(owner['ParentProcessId'])
    dispatch = launch['dispatch']
    if (parent is None or not parent.get('ExecutablePath') or daemon != binding['daemon']
            or not os.path.samefile(parent['ExecutablePath'], daemon['path'])
            or dispatch != {'job_id': run_id, 'daemon_pid': owner['ParentProcessId'],
                            'memory_cap': LIMITS['host_memory_bytes']}):
        raise ValueError('controller is not the bound canonical daemon child')
    current, visited = os.getpid(), set()
    while current != owner['ProcessId'] and current in by_pid and current not in visited:
        visited.add(current)
        current = by_pid[current]['ParentProcessId']
    if current != owner['ProcessId']:
        raise ValueError('worker is outside controller ancestry')
    helper = str((Path.home() / '.codex/headless-python.ps1').resolve(strict=True))
    if set(launch['helpers']) != {helper, launch['hidden_helper']}:
        raise ValueError('fixed hidden helper identities differ')
    for raw, digest in launch['helpers'].items():
        if file_sha256(raw) != checked_sha(digest):
            raise ValueError('hidden helper bytes changed')
    lock_path = Path(os.environ.get('EMBER_GPU_LOCK_PATH', '')).resolve(strict=True)
    if str(lock_path) != launch['gpu_lock']:
        raise ValueError('shared GPU lock path differs')
    lock = json.loads(lock_path.read_bytes())
    if lock.get('daemon_pid') != owner['ProcessId'] or lock.get('side') != 'windows' or lock.get('active_jobs') != 1:
        raise ValueError('controller does not own the shared GPU lock')
    cache = {name: str((custody / directory).resolve()) for name, directory in CACHE_DIRS.items()}
    if any(os.environ.get(name) != value for name, value in cache.items()):
        raise ValueError('measurement cache custody differs')
    assertion = custody / 'child-env-startup.json'
    if os.environ.get('EMBER_DISK_BUDGET_ENV_ASSERTION') != str(assertion):
        raise ValueError('disk assertion path differs')
    _, _, error = load_disk_module()._load_child_cache_assertion(
        assertion, cache, os.environ.get('EMBER_DISK_BUDGET_ENV_NONCE', ''))
    if error:
        raise ValueError(error)
    if os.environ.get('EMBER_GATE_AUTHORIZED') != '1':
        raise ValueError('explicit live gate condition missing')
    headroom()
    resource_census()
    resources.sample_device(launch['gpu_uuid'], total_gpu_bytes=LIMITS['total_gpu_bytes'])


def worker(binding_path):
    """Direct worker calls fail at actual job membership, before artifact reads."""
    global _NEXT_STEP
    from ember.governance.scripts import cia_conformance_resources as resources
    binding_path = Path(binding_path)
    if not binding_path.parent.name.startswith('measurement-'):
        raise ValueError('worker custody is not a measurement run')
    run_id = binding_path.parent.name.removeprefix('measurement-')
    resources.require_owned_job(run_id, namespace=JOB_NAMESPACE, host_memory_bytes=LIMITS['host_memory_bytes'])
    binding = json.loads(binding_path.read_bytes())
    verify_worker(binding, binding_path)
    custody = binding_path.parent
    applied_positions = 0
    attention_scope = contextlib.ExitStack()
    try:
        prediction, _ = load_prediction(custody / 'prediction.json', binding['launch']['prediction_sha256'])
        if prediction['identity']['run_id'] != run_id or prediction['identity']['gpu_uuid'] != binding['launch']['gpu_uuid']:
            raise ValueError('prediction differs from owned run or selected GPU')
        config, prepared = prepare_execution(prediction)
        check_layer_env(prediction['identity'])  # before ANY decoder import: the selectors the process holds equal the declaration
        attention_scope.enter_context(attention_context(prediction['identity']))
        import torch
        from ember.model.ember_v0_decoder import CIADecoder, bind_triton_c_compiler
        from ember.model.ember_v0_contract import validate_cia_architecture
        if declared_layer_template(prediction['identity']) is not None:
            import ember.model.ember_v0_decoder as resolved_decoder
            resolved = dict(attention_keep=sorted(resolved_decoder._ATTENTION_KEEP), ffn_keep=sorted(resolved_decoder._FFN_KEEP),
                            expert_keep=sorted(resolved_decoder._EXPERT_KEEP))
            mismatch = check_resolved_layers(prediction['identity'], resolved)
            _write_new(custody / LAYER_RESOLVED_NAME, dict(declared=declared_layer_template(prediction['identity']),
                resolved=resolved, mismatch=mismatch, claim=CLAIM))
            if mismatch:
                raise ValueError('decoder resolved layer sets differ from the declared layer_template: ' + '; '.join(mismatch))
        # The fused elementwise chains compile through inductor/Triton on first CUDA use; bind Triton's C compiler
        # here, once, before activation, so the binding never happens inside a timed step and its identity is recorded.
        c_compiler = bind_triton_c_compiler()
        validate_cia_architecture(config)
        if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
            raise ValueError('one explicitly bound CUDA device is required')
        selected = run_readonly(['nvidia-smi', '-i', '0', '--query-gpu=uuid', '--format=csv,noheader'], timeout=5).stdout.strip()
        if selected != prediction['identity']['gpu_uuid']:
            raise ValueError('CUDA index differs from bound device UUID')
        device = torch.device('cuda:0')
        total = torch.cuda.get_device_properties(device).total_memory
        torch.cuda.set_per_process_memory_fraction(LIMITS['allocator_bytes'] / total, device)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.manual_seed(prediction['identity']['seed'])
        if hour_mode(prediction['identity']):
            def applied(count):
                nonlocal applied_positions
                geometry = prediction['identity']['geometry']
                if type(count) is not int or count != geometry['sequence_length'] * geometry['documents_per_step']:
                    raise ValueError('hour applied count differs from bound geometry')
                applied_positions += count
            hour_module = load_hour_module()
            execute = hour_module.run_continuation if 'continuation' in prediction['identity'] else hour_module.run_hour
            execute(runner=sys.modules[__name__], config=config,
                prepared=prepared, prediction=prediction, binding=binding, custody=custody,
                device=device, compiler=c_compiler, applied=applied)
            _write_new(custody / 'worker-terminal.json', dict(status='completed',
                applied_positions=applied_positions, claim=CLAIM))
            try:
                tail_stamp(custody, 'worker_terminal')
            except OSError as error:   # evidence-only stamp after the completed terminal: the hour is not failed by it; the miss is named on stderr
                print('TAIL_STAMP_DEGRADED worker_terminal %s: %s' % (type(error).__name__, error), file=sys.stderr, flush=True)
            return 0
        if trajectory_mode(prediction['identity']):
            def applied(count):
                nonlocal applied_positions
                if type(count) is not int or count != 4096:
                    raise ValueError('trajectory applied count differs from bound geometry')
                applied_positions += count
            load_trajectory_module().run_trajectory_arm(runner=sys.modules[__name__], config=config,
                prepared=prepared, prediction=prediction, binding=binding, custody=custody,
                device=device, compiler=c_compiler, applied=applied)
            _write_new(custody / 'worker-terminal.json', dict(status='completed',
                applied_positions=applied_positions, claim=CLAIM))
            return 0
        model = CIADecoder(architecture_config=config, **decoder_kwargs(prediction['identity'])).materialize_cpu(seed=prediction['identity']['seed'])
        mode = execution_mode(prediction['identity'])
        definition = prediction['identity']['optimizer']
        measurement = measurement_mode(prediction['identity'])
        first = prepared['first'] if measurement else prepared['packs'][0]
        first_micro = micro_packs(first)[0]
        first_lengths = document_lengths(tuple(first_micro['document_starts']), len(first_micro['token_ids']))

        def optimizer_factory(inventory):
            if sum(parameter.numel() for parameter in inventory.values()) != POPULATION:
                raise ValueError('full CIA-3B population is missing')
            built = torch.optim.AdamW(list(inventory.values()), **optimizer_kwargs(definition))
            built._ember_template_untrained = template_untrained_parameters(inventory)
            return built

        inventory, optimizer = prepare_model(model, prediction['identity'], first_lengths, device, mode=mode,
                                             optimizer_factory=optimizer_factory)
        support = prediction['identity']['support']
        membership = [parameter for group in optimizer.param_groups for parameter in group['params']]
        if len(membership) != len(inventory) or {id(parameter) for parameter in membership} != {id(parameter) for parameter in inventory.values()}:
            raise ValueError('optimizer membership differs from complete population')
        supported = {name: parameter.numel() for name, parameter in inventory.items() if parameter.requires_grad}
        _write_new(custody / 'model.json', {'population': POPULATION, 'parameter_count': len(inventory),
            'trainable_parameters': sum(supported.values()), 'trainable_support': supported,
            'optimizer_membership': list(inventory), 'input_binding': prepared['binding'], 'c_compiler': c_compiler,
            'execution_mode': mode, 'resident_experts': (list(support['experts']) if mode is not None else None),
            'optimizer': dict(definition), 'measurement': prediction['identity'].get('measurement'),
            **attention_selection(prediction['identity']), 'claim': CLAIM})
        expert_owners = expert_owner_index(inventory)
        capture = None
        if mode in MODE_SOURCES:
            buffers = routing_buffers(first_lengths, device)
            # The dynamic treatment is an explicit option on the same factory (grouped kernels inside each segment,
            # expert owners in the segment surface); the published G1 default takes no such argument.
            dynamic = {'capture_experts': True} if mode == 'resident-dynamic-capture' else {}
            capture = model.bind_segmented_capture(
                local_routing_mode=local_routing_mode(prediction['identity']),
                collector=buffers.collector,
                **capture_loss_kwargs(model, prediction['identity'], first_lengths),
                static_state=(buffers.raw,), warmup_steps=2, **dynamic)
        counts = geometry_counts(prediction['identity']['geometry'], measurement=True) if measurement else None
        measured_rates = []
        frozen = False
        gc_identity = dict(run_id=run_id, prediction_sha256=binding['launch']['prediction_sha256'])
        with GcPauseMeter().bind(**gc_identity) as gc_meter, (custody / 'rows.jsonl').open('xb') as rows, \
                (custody / 'gc-events.jsonl').open('xb') as gc_rows:
            source_packs = measurement_packs(prepared) if measurement else prepared['packs']
            stage_next_step = measurement and capture is not None and os.environ.get('EMBER_STAGE_NEXT_STEP') == '1'
            for index, (pack, next_pack) in enumerate(_with_successor(source_packs) if stage_next_step
                                                      else ((pack, None) for pack in source_packs)):
                if measurement:
                    verify_measurement_pack(pack, index, sequence=counts[0], documents=counts[1], warm=counts[2],
                                            measured=counts[3])
                else:
                    verify_prepared_inputs(prepared)
                if pack['phase'] == 'measured' and not frozen:
                    # Warm-to-measured transition: after the last declared warm update (none when warm_steps is 0),
                    # before the first measured step's clock starts; eager and captured paths alike.
                    _write_new(custody / 'gc-freeze.json', freeze_resident_object_graph(**gc_identity))
                    frozen = True
                    if os.environ.get('EMBER_GC_DISABLE_MEASURED') == '1':
                        gc.disable()  # bounded below: bounded_collect every 64 rows
                # EMBER_PRELAUNCH_FORWARD: the next update's forward is enqueued behind this update's optimizer
                # (never on the recorded exemplar, index 0, whose capture follows the call); its pack is verified first.
                prelaunch = (measurement and stage_next_step and next_pack is not None and index >= 1
                             and os.environ.get('EMBER_PRELAUNCH_FORWARD') == '1')
                if prelaunch:
                    verify_measurement_pack(next_pack, index + 1, sequence=counts[0], documents=counts[1],
                                            warm=counts[2], measured=counts[3])
                call_started = time.perf_counter()
                row = measure_step(model, optimizer, pack, device=device,
                                   batch_documents=prediction['identity']['batch_documents'], run_id=run_id,
                                   capture=capture, record=(capture is not None and index == 0),
                                   expert_owners=expert_owners, experiment_binding=experiment_fields(prediction['identity']),
                                   image_text=getattr(prepared.get('packs'), 'image_text', None) if measurement else None,
                                   next_pack=next_pack, prelaunch_next=prelaunch)
                call_finished = time.perf_counter()
                # The applied update is persisted and counted BEFORE any synthetic capture work, so a capture refusal
                # after the successful warm update leaves a truthful applied count in the terminal record.
                row.update(run_id=run_id, prediction_sha256=binding['launch']['prediction_sha256'],
                           input_sha256=prepared['binding']['input_sha256'], update_completed_monotonic=call_finished)
                if measurement:
                    row.update(cursor_before=pack['cursor_before'], cursor_after=pack['cursor_after'],
                               pack_sha256=_row_digest(pack), measurement=prediction['identity']['measurement'])
                    if pack['phase'] == 'measured':
                        measured_rates.append(row['positions_per_second'])
                rows.write(canonical(row) + b'\n')
                rows.flush()
                if index == 0 or index % ROW_FSYNC_EVERY == ROW_FSYNC_EVERY - 1:
                    os.fsync(rows.fileno())
                # Collections since the previous row, classified in-step / outside-step by their start instant against
                # this step call's window; filed beside (never inside) the row.
                gc_rows.write(canonical(gc_meter.file(index, pack['phase'], call_started=call_started,
                                                      call_finished=call_finished)) + b'\n')
                gc_rows.flush()
                if frozen and not gc.isenabled() and index % 64 == 63:
                    bounded_collect(index)
                applied_positions += row['applied_positions']
                if capture is not None and index == 0:
                    capture.zero_grad(optimizer=optimizer)  # full retained membership, eager expert owners included
                    buffers.capturing = True
                    try:
                        capture.capture(optimizer=optimizer)  # state proof inside; refuses instead of measuring a drifted model
                    finally:
                        buffers.capturing = False
                    _write_new(custody / 'capture.json', dict(capture.receipt(), claim=CLAIM))
            if _NEXT_STEP is not None and 'forward' in _NEXT_STEP:
                raise RuntimeError('measurement ended with a pre-launched update still open')
            _NEXT_STEP = None
            # Collections after the last step (teardown side) are outside every step by construction.
            closing_instant = time.perf_counter()
            gc_rows.write(canonical(gc_meter.file(None, 'after-last-step', call_started=closing_instant,
                                                  call_finished=closing_instant)) + b'\n')
        if measurement:
            _write_new(custody / 'measurement-summary.json', dict(measurement_summary(measured_rates),
                measurement=prediction['identity']['measurement'], execution_mode=mode, optimizer=dict(definition),
                input_sha256=prepared['binding']['input_sha256'], applied_positions=applied_positions,
                gc_events_sha256=file_sha256(custody / 'gc-events.jsonl'),
                gc_freeze_sha256=file_sha256(custody / 'gc-freeze.json') if frozen else None, claim=CLAIM))
        _write_new(custody / 'worker-terminal.json', {'status': 'completed', 'applied_positions': applied_positions,
                                                    'claim': CLAIM})
        return 0
    except BaseException as error:
        _write_failed_terminal(custody, {'status': 'failed', 'error_type': type(error).__name__,
            'error': str(error), 'traceback': traceback.format_exc(), 'applied_positions': applied_positions,
            'claim': CLAIM})
        raise
    finally:
        attention_scope.close()


def record_retention_outcome(identity, *, succeeded, custody, parent, run_id, dispatch_started, run_complete_at=None):
    """Issue #2119 rows 5/14: record the experiment outcome in the continuity ledger. Launch success is only a prerequisite:
    eligibility is the adjudicator's verdict from the rule frozen in the identity and the arm results in this custody. It is
    False with no arm results, and False when the adjudicator escapes with any error (the refusal is written beside the
    custody); the ledger outcome is recorded either way, so a malformed arm record can never skip budget accounting."""
    ledger_module = load_ledger_module()
    try:
        eligible = load_eligibility_module().adjudicated_eligible_descendant(identity, run_succeeded=succeeded, custody=custody)
    except Exception as error:  # noqa: BLE001 - an escape from the adjudicator is a refusal, never a skipped outcome
        eligible = False
        try:
            (Path(custody) / 'eligibility-refusal.json').write_text(
                json.dumps({'refused': f'adjudicator raised {type(error).__name__}: {error}'}, sort_keys=True), encoding='utf-8')
        except OSError:
            pass
    ledger_module.record_retention_experiment_outcome(
        path=ledger_module.ledger_path(parent),
        lineage_sha=ledger_module.lineage_checkpoint_manifest_sha256(identity, receipts_root=ledger_module.ledger_root(parent)),
        run_id=run_id, eligible_descendant_published=eligible,
        # review 63986 R1: the occupancy is the run's own execution (dispatch_started to the run-complete instant the launch recorded), never the
        # time the finalizer happened to run; deferred scoring or review delay is not model execution. A caller with no recorded end
        # (the launch exception path, which records at the end of the run) falls back to now.
        elapsed_seconds=int((time.time() if run_complete_at is None else run_complete_at) - dispatch_started),
        finalization_delay_seconds=0 if run_complete_at is None else max(int(time.time() - run_complete_at), 0))
    return eligible


RUN_COMPLETE_FILENAME = 'run-complete.json'
OUTCOME_RECORDED_FILENAME = 'retention-outcome-recorded.json'


def finalize_retention_outcome(identity, *, custody, parent):
    """The ONLY writer of the retention outcome (ruling 63035), called by the scoring chain after both arms are scored and
    `arm_results_producer.produce_arm_results` wrote arm-results.json. Refuses (outcome stays ABSENT, so the next segment refuses on the
    missing outcome) when the run-complete marker is absent, when arm-results.json is absent (no producer ran), or when this custody's
    outcome was already recorded. Reads `succeeded`, `run_id` and `dispatch_started` from the launch's marker, never from the caller."""
    custody = Path(custody)
    try:
        marker = json.loads((custody / RUN_COMPLETE_FILENAME).read_bytes())
    except (OSError, ValueError) as error:
        raise RuntimeError(f'no run-complete marker in {custody}: {error}') from error
    _validate_run_complete_marker(marker, identity, custody)   # review 63367 P1-4: every field checked BEFORE any ledger mutation
    if not (custody / load_eligibility_module().ARM_RESULTS_FILENAME).is_file():
        raise RuntimeError('arm-results.json is absent: the producer has not run, so the retention outcome is NOT recorded')
    ledger_module = load_ledger_module()
    # review 63367 P1-3: serialize competing finalizers and make the outcome idempotent across the ledger/marker boundary. The OS lock covers
    # check-record-mark; the ledger itself records one outcome row per (lineage, run_id), so a retry after a failed marker write finds the
    # row already present and never charges the occupancy twice; the marker (exclusive create) is the last durable step.
    with ledger_module.exclusive_lock(custody / OUTCOME_RECORDED_FILENAME):
        if (custody / OUTCOME_RECORDED_FILENAME).exists():
            raise RuntimeError('the retention outcome for this custody was already recorded (one writer, one outcome)')
        eligible = record_retention_outcome(identity, succeeded=marker['succeeded'], custody=custody, parent=parent,
                                            run_id=marker['run_id'], dispatch_started=marker['dispatch_started'],
                                            run_complete_at=marker['run_complete_at'])
        _write_new(custody / OUTCOME_RECORDED_FILENAME, {'eligible_descendant_published': eligible, 'run_id': marker['run_id']})
    return eligible


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_run_complete_marker(marker, identity, custody):
    """Reject a malformed or foreign run-complete marker before eligibility or ledger accounting (review 63367 P1-4). `succeeded` must be an exact
    bool (a truthy string such as 'false' is refused), `run_id` the nonempty id this custody and this identity carry, `custody_name` this
    custody's directory name, and the timestamps finite and ordered (0 < dispatch_started <= run_complete_at)."""
    if not isinstance(marker, dict) or marker.get('status') != 'run_complete_not_yet_scored':
        raise RuntimeError('run-complete marker is malformed')
    if type(marker.get('succeeded')) is not bool:
        raise RuntimeError('run-complete marker: succeeded is not an exact bool')
    run_id = marker.get('run_id')
    if not isinstance(run_id, str) or not run_id:
        raise RuntimeError('run-complete marker: run_id is missing or empty')
    custody = Path(custody)
    if marker.get('custody_name') != custody.name or custody.name != 'measurement-' + run_id:
        raise RuntimeError('run-complete marker: custody or run_id does not match this custody directory')
    if isinstance(identity, dict) and identity.get('run_id') != run_id:
        raise RuntimeError('run-complete marker: run_id does not match the identity being finalized')
    started, completed = marker.get('dispatch_started'), marker.get('run_complete_at')
    if not (_finite_number(started) and _finite_number(completed) and 0 < started <= completed):
        raise RuntimeError('run-complete marker: timestamps are missing, non-finite or not ordered')


def launch_succeeded(result, supervisor_failure, custody):
    """A launch succeeded only if the owned process status is 'completed' with returncode 0, verified cleanup and no supervisor
    failure, AND the worker wrote a worker-terminal.json whose status is 'completed'. The first chained hour was killed by its wall
    with status 'terminated', returncode 0, cleanup verified and no supervisor failure, so the returncode alone read as success."""
    if not (result.status == 'completed' and result.returncode == 0 and result.cleanup_verified and not supervisor_failure):
        return False
    try:
        terminal = json.loads((Path(custody) / 'worker-terminal.json').read_bytes())
    except (OSError, ValueError):
        return False
    return isinstance(terminal, dict) and terminal.get('status') == 'completed'


def launch(args, dispatch):
    from ember.governance.scripts import cia_conformance_resources as resources, gpu_lock_guard
    from ember.governance.scripts.owned_process import OwnedProcessRunner
    if not args.live or os.environ.get('EMBER_GATE_AUTHORIZED') != '1':
        raise ValueError('explicit live conditions are missing')
    prediction, prediction_bytes = load_prediction(args.prediction, args.prediction_sha256)
    run_id = prediction['identity']['run_id']
    if not isinstance(run_id, str) or not re.fullmatch('[0-9a-f]{32}', run_id):
        raise ValueError('run identity must be 32 lowercase hex characters')
    if dispatch['job_id'] != run_id:
        raise ValueError('prediction run identity differs from authenticated dispatch')
    parent = args.custody.resolve(strict=True)
    if parent.drive.upper() != 'B:' or not parent.is_dir():
        raise ValueError('daemon custody must be an existing B directory')
    custody = parent / ('measurement-' + run_id)
    custody.mkdir()  # Exclusive creation is the one-use run-custody boundary.
    tail_stamp(custody, 'segment_launch')  # typed wall start of the governed segment (#2119 accounting)
    helper = (Path.home() / '.codex/headless-python.ps1').resolve(strict=True)
    hidden = args.hidden_helper.resolve(strict=True)
    preflight = headroom()
    census = resource_census()
    _, prepared = prepare_execution(prediction)
    identity = prediction['identity']
    child_env = None
    if hour_mode(identity) and identity['hour']['schema'] == 'governed-hour-v1':
        child_env = layer_child_env(identity, custody)  # refuses a governed hour whose identity declares no layer_template
    launch_lineage_sha = None
    if identity.get('training_job_purpose') in ('DIAGNOSTIC', 'RETENTION_ELIGIBLE_EXPERIMENT'):
        # Issue #2119 row 3b: the lineage key is read ONCE, before any spawn, from the live pointer (refusing when there is none), and reused
        # by the reservation and by the launch-exception outcome row, so a refusal can never mask the original error after the run started.
        launch_lineage_sha = load_ledger_module().lineage_checkpoint_manifest_sha256(
            identity, receipts_root=load_ledger_module().ledger_root(parent))
    if identity.get('training_job_purpose') == 'DIAGNOSTIC':
        # Issue #2119 section 3: reserve the declared budget BEFORE any GPU spawn. The budget is
        # the same wall_seconds limit OwnedProcessRunner already enforces below -- no second,
        # independently-declared budget field is introduced for this.
        ledger_module = load_ledger_module()
        ledger_module.reserve_diagnostic_dispatch(
            path=ledger_module.ledger_path(parent),
            lineage_sha=launch_lineage_sha,
            run_id=run_id, budget_seconds=resource_limits(identity)['wall_seconds'],
            diagnostic_question=identity['training_diagnostic_question'],
            non_advancement_reason=identity['training_diagnostic_non_advancement_reason'],
            return_condition=identity['training_diagnostic_return_condition'],
            readiness_blocker=identity.get('training_diagnostic_readiness_blocker'))
    gpu_uuid = prediction['identity']['gpu_uuid']
    # #1945: this one-shot preflight call had zero tolerance for a slow/failing nvidia-smi.
    # sample_device_at_launch() retries only here; the watcher's own tolerance is unchanged.
    resources.sample_device_at_launch(gpu_uuid, total_gpu_bytes=LIMITS['total_gpu_bytes'])
    with (custody / 'prediction.json').open('xb') as stream:
        stream.write(prediction_bytes)
    _write_new(custody / 'preflight.json', {'headroom': preflight, 'processes': census,
                                          'input_binding': prepared['binding'], 'claim': CLAIM})
    worker_argv = [str(ROOT / ENTRY), '--worker', str(custody / 'launch.json')]
    binding = {'daemon': daemon_identity(), 'claim': CLAIM, 'launch': {
        'run_id': run_id, 'owner_pid': os.getpid(), 'parent_custody': str(parent), 'custody': str(custody),
        'hidden_helper': str(hidden), 'helpers': {str(path): file_sha256(path) for path in (helper, hidden)},
        'prediction_path': str(args.prediction), 'prediction_sha256': args.prediction_sha256,
        'gpu_uuid': gpu_uuid, 'gpu_lock': str(Path(gpu_lock_guard._require_lock_path()).resolve()),
        'limits': resource_limits(prediction['identity']), 'worker_argv': worker_argv, 'dispatch': dispatch,
        **({'layer_policy': {'declared': declared_layer_template(identity),
                             'selectors': {name: child_env.get(name) for name in LAYER_SELECTOR_ENV},
                             'receipt_path': child_env[LAYER_RECEIPT_ENV]}} if child_env is not None else {})}}
    _write_new(custody / 'launch.json', binding)
    command = _python_command(helper, hidden, ROOT / DISK_ENTRY,
        '--max-c-write-gib', str(LIMITS['max_c_write_gib']), '--max-b-write-gib', str(resource_limits(prediction['identity'])['max_b_write_gib']),
        '--receipt', custody / 'disk.json', '--write-root', f'custody={custody}',
        '--', *_python_command(helper, hidden, *worker_argv))
    jobs = []
    def factory():
        job = resources.ResourceJob(run_id, gpu_uuid, namespace=JOB_NAMESPACE,
                                    host_memory_bytes=LIMITS['host_memory_bytes'], total_gpu_bytes=LIMITS['total_gpu_bytes'])
        jobs.append(job)
        return job
    dispatch_started = time.time()
    try:
        with gpu_lock_guard.acquire(script=ENTRY):
            headroom()
            resource_census()
            result = OwnedProcessRunner(windows_job_factory=factory).run(command,
                timeout_s=resource_limits(prediction['identity'])['wall_seconds'], cwd=ROOT, env=child_env)
    except BaseException as error:
        _write_new(custody / 'owned-failure.json', {'status': 'exception', 'error_type': type(error).__name__,
            'error': str(error), 'cleanup_verified': False, 'claim': CLAIM,
            'device_samples': jobs[0].samples if jobs else [],
            'supervisor_failure': jobs[0].failure if jobs else None})
        if identity.get('training_job_purpose') == 'RETENTION_ELIGIBLE_EXPERIMENT':
            # Issue #2119 section 3: an experiment that never reached a terminal receipt
            # published no eligible descendant by construction.
            ledger_module = load_ledger_module()
            ledger_module.record_retention_experiment_outcome(
                path=ledger_module.ledger_path(parent),
                lineage_sha=launch_lineage_sha,
                run_id=run_id, eligible_descendant_published=False,
                elapsed_seconds=int(time.time() - dispatch_started))
        raise
    (custody / 'stdout.log').write_text(result.stdout, encoding='utf-8')
    (custody / 'stderr.log').write_text(result.stderr, encoding='utf-8')
    receipt = asdict(result)
    receipt.pop('stdout')
    receipt.pop('stderr')
    receipt.update(prediction_sha256=args.prediction_sha256, claim=CLAIM,
                   device_samples=jobs[0].samples, supervisor_failure=jobs[0].failure)
    _write_new(custody / 'owned.json', receipt)
    if result.cleanup_verified:
        tail_stamp(custody, 'segment_complete')  # typed parent-side end of the governed segment, after cleanup (charged against the hour allowance, not timeout_s)
    succeeded = launch_succeeded(result, jobs[0].failure, custody)
    if identity.get('training_job_purpose') == 'RETENTION_ELIGIBLE_EXPERIMENT':
        # ruling 63035: the retention outcome has exactly ONE writer, the scoring chain (finalize_retention_outcome), after the arm
        # producer has written arm-results.json. Nothing is scored yet here, so launch only marks the run complete-and-unscored.
        _write_new(custody / RUN_COMPLETE_FILENAME, {'status': 'run_complete_not_yet_scored', 'succeeded': succeeded,
                                                     'run_id': run_id, 'custody_name': custody.name, 'dispatch_started': dispatch_started,
                                                     'run_complete_at': time.time(), 'claim': CLAIM})
    return 0 if succeeded else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 2 and argv[0] == '--worker':
        return worker(Path(argv[1]))
    # First controller operation: authenticate and consume the real daemon token.
    # Preserve only non-secret dispatch identity; consumption removes token env.
    from ember.governance.scripts.ember_dispatch_token import consume_dispatch
    dispatch = {'job_id': os.environ.get('EMBER_LAB_DISPATCH_JOB_ID'),
                'daemon_pid': os.environ.get('EMBER_LAB_DISPATCH_DAEMON_PID')}
    cap = consume_dispatch(ROOT)
    if type(cap) is not int or cap != LIMITS['host_memory_bytes']:
        raise ValueError('authenticated daemon host cap differs from measurement envelope')
    dispatch.update(daemon_pid=int(dispatch['daemon_pid']), memory_cap=cap)
    parser = argparse.ArgumentParser()
    parser.add_argument('--daemon-run', action='store_true', required=True)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--custody', type=Path, required=True)
    parser.add_argument('--hidden-helper', type=Path, required=True)
    parser.add_argument('--prediction', type=Path, required=True)
    parser.add_argument('--prediction-sha256', required=True)
    args = parser.parse_args(argv)
    expected = ['--daemon-run', '--live', '--custody', str(args.custody), '--hidden-helper', str(args.hidden_helper),
                '--prediction', str(args.prediction), '--prediction-sha256', args.prediction_sha256]
    if argv != expected:
        raise ValueError('controller argv differs from fixed measurement dispatch')
    return launch(args, dispatch)


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT / 'src'))
    sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
    sys.exit(main())
