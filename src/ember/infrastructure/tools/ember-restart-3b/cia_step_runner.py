"""Daemon-dispatched CIA-3B step measurements; no checkpoint or qualification credit."""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import argparse
import ctypes
from dataclasses import asdict, replace
import contextlib
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
import time
import traceback


ROOT = Path(__file__).resolve().parents[5]
ENTRY = 'src/ember/infrastructure/tools/ember-restart-3b/cia_step_runner.py'
CONFIG = 'configs/ember-cia-3b.json'
DISK_ENTRY = 'src/ember/infrastructure/tools/ember-restart-3b/disk_budget_runner.py'
GIB = 1024 ** 3
POPULATION = 3_082_539_008
CLAIM = 'measurement rows only; no checkpoint publication, learning or throughput qualification'
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


def geometry_counts(geometry, *, trajectory=False):
    if type(trajectory) is not bool:
        raise ValueError('explicit boolean trajectory geometry selection required')
    if set(geometry) != {'sequence_length', 'documents_per_step', 'warm_steps', 'measured_steps'}:
        raise ValueError('geometry fields differ')
    sequence = positive_int(geometry['sequence_length'], 'sequence length', 1024)
    documents = positive_int(geometry['documents_per_step'], 'documents per step', 4)
    warm = geometry['warm_steps']
    if type(warm) is not int or not 0 <= warm <= 2:
        raise ValueError('warm count is outside its fixed bound')
    measured = positive_int(geometry['measured_steps'], 'measured steps', 63 if trajectory else 8)
    if trajectory and (sequence, documents, warm, measured) != (1024, 4, 1, 63):
        raise ValueError('trajectory requires exactly 64 complete 4x1024 updates with one warm exemplar')
    return sequence, documents, warm, measured


def _pack_digest(packs):
    body = [{name: pack[name] for name in INPUT_FIELDS} for pack in packs]
    return hashlib.sha256(canonical(body)).hexdigest()


def prepare_inputs(data, geometry, *, trajectory=False):
    """Open the real stream and freeze the whole plan before model allocation."""
    if not isinstance(data, dict) or set(data) != DATA_KEYS:
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
    sequence, documents, warm, measured = geometry_counts(geometry, trajectory=trajectory)
    cursor = dict(data['cursor'])
    if set(cursor) != {'shard_index', 'token_offset'}:
        raise ValueError('cursor fields differ')
    planned_positions = (warm + measured) * documents * sequence
    span = stream.check_cursor_span(**cursor, tokens=planned_positions)
    packs = []
    for index in range(warm + measured):
        pack = {'token_ids': [], 'target_ids': [], 'positions': [], 'document_starts': [],
                'index': index, 'phase': 'warm' if index < warm else 'measured'}
        for _ in range(documents):
            episode, next_cursor = stream.next_episode(**cursor, sequence_length=sequence)
            pack['document_starts'].append(len(pack['token_ids']))
            pack['token_ids'].extend(episode['token_ids'])
            pack['target_ids'].extend(episode['target_ids'])
            pack['positions'].extend([[position, 0, 0] for position in range(sequence)])
            cursor = {key: next_cursor[key] for key in ('shard_index', 'token_offset')}
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
    positive_int(positions_per_step, 'counted step positions', 4096)
    if not math.isclose(rate * wall, positions_per_step, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError('prediction arithmetic differs from counted positions')
    trajectory = trajectory_mode(expected_identity)
    _, _, warm, measured = geometry_counts(expected_identity['geometry'], trajectory=trajectory)
    if (warm + measured) * wall >= LIMITS['wall_seconds']:
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


def required_sources(identity):
    """The complete measurement source binding for this identity: SOURCES plus the selected mode's modules."""
    additional = ('src/ember/infrastructure/tools/ember-restart-3b/cia_trajectory.py',) if trajectory_mode(identity) else ()
    return SOURCES + MODE_SOURCES.get(execution_mode(identity), ()) + additional


def trajectory_mode(identity):
    if 'trajectory' not in identity:
        return False
    arms = {'R1': None, 'R2': None, 'Tsegmented': 'resident-segmented-capture',
            'Tdynamic': 'resident-dynamic-capture', 'Tfused': 'resident-dynamic-capture'}
    value = identity['trajectory']
    if (not isinstance(value, dict) or set(value) != {'schema', 'arm', 'comparison_id'}
            or value['schema'] != 'reference-noise-floor-64-v1' or value['arm'] not in arms
            or not isinstance(value['comparison_id'], str) or not re.fullmatch('[0-9a-f]{32}', value['comparison_id'])
            or execution_mode(identity) != arms[value['arm']]):
        raise ValueError('trajectory requires a bound comparison and matching 64-update arm')
    return True


def resource_limits(identity):
    limits = dict(LIMITS)
    if trajectory_mode(identity):
        limits['max_b_write_gib'] = 8
    return limits


def validate_trajectory_resources(identity):
    if trajectory_mode(identity):
        walls = identity['dispatch_resources'].get('disk_write_walls')
        if (not isinstance(walls, list) or len(walls) != 1 or not isinstance(walls[0], dict)
                or walls[0].get('volume_root') != 'B:/'
                or walls[0].get('maximum_write_bytes') != 8 * GIB):
            raise ValueError('trajectory requires its matching eight GiB native disk wall')


def load_trajectory_module():
    path = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b/cia_trajectory.py'
    spec = importlib.util.spec_from_file_location('cia_measurement_trajectory', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def prepare_execution(prediction):
    identity = prediction.get('identity')
    keys = {'run_id', 'source_commit', 'source_sha256', 'config_sha256', 'data', 'seed',
            'support', 'optimizer', 'geometry', 'batch_documents', 'resources', 'input_binding', 'gpu_uuid',
            'dispatch_resources'}
    if not isinstance(identity, dict) or not keys <= set(identity) <= keys | {'execution_mode', 'trajectory'}:
        raise ValueError('measurement identity fields differ')
    execution_mode(identity)
    trajectory = trajectory_mode(identity)
    validate_trajectory_resources(identity)
    sequence, documents, _, _ = geometry_counts(identity['geometry'], trajectory=trajectory)
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
    optimizer = identity['optimizer']
    expected = {'name': 'AdamW', 'foreach': False, 'lr': 0.001, 'betas': [0.9, 0.999],
                'eps': 1e-8, 'weight_decay': 0.01, 'membership': 'complete_parameter_inventory'}
    if trajectory and identity['trajectory']['arm'] == 'Tfused':
        expected['fused'] = True
    if canonical(optimizer) != canonical(expected):
        raise ValueError('fixed optimizer definition differs')
    prepared = prepare_inputs(identity['data'], identity['geometry'], trajectory=trajectory)
    actual = dict(identity, input_binding=prepared['binding'], resources=resource_limits(identity))
    sequence, documents, _, _ = geometry_counts(identity['geometry'], trajectory=trajectory)
    validate_prediction(prediction, expected_identity=actual, positions_per_step=sequence * documents)
    verify_prepared_inputs(prepared)
    return config, prepared


def _cache_values(cache):
    return {name: getattr(cache, name) for name in ('lease_count', 'miss_count', 'eviction_count',
                                                  'transfer_bytes', 'transfer_seconds')}


ROUTES_DIGEST_GRAMMARS = ('legacy-rows-v1', 'device-buffers-v1')
_ROUTING_BUFFERS = {}


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
                or sum(lengths) > 4096):
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
    _, _, warm, _ = geometry_counts(identity['geometry'], trajectory=trajectory_mode(identity))
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


def measure_step(model, optimizer, pack, *, device, batch_documents=False, run_id=None, verify_routes=False,
                 capture=None, record=False, expert_owners=None, route_observer=None, route_snapshot=None):
    """Return one row only after context exit, successful update and synchronization.

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
    synchronize = (lambda: torch.cuda.synchronize(device)) if device.type == 'cuda' else (lambda: None)
    synchronize()
    if device.type == 'cuda':
        torch.cuda.reset_peak_memory_stats(device)
    before = _cache_values(model._cuda_execution.cache)
    started = time.perf_counter()
    tokens = torch.tensor(pack['token_ids'], dtype=torch.long, device=device)
    targets = torch.tensor(pack['target_ids'], dtype=torch.long, device=device)
    positions = torch.tensor(pack['positions'], dtype=torch.long, device=device)
    starts = tuple(pack['document_starts'])
    resident = bool(getattr(model, '_resident_experts', None))
    if (route_snapshot is not None and not resident) or (route_observer is not None and resident):
        raise ValueError('routing observation interface differs from the selected execution mode')
    buffers = routing_buffers(document_lengths(starts, len(pack['token_ids'])), device) if resident else None
    if buffers is not None:
        buffers.begin_step()
    if capture is not None:
        if buffers is None:
            raise ValueError('segmented capture requires the resident routing buffers')
        if capture.execution is not model._cuda_execution or getattr(model._cuda_execution, 'segmented', None) is not capture:
            raise ValueError('segmented capture is not bound to this model execution')
        optimizer.zero_grad(set_to_none=False)  # static-accumulate: the captured backward owns the grad storage
        capture.zero_grad()
    else:
        optimizer.zero_grad(set_to_none=True)
    staged = time.perf_counter()
    events = [torch.cuda.Event(enable_timing=True) for _ in range(4)] if device.type == 'cuda' else None
    recording = capture.record() if (capture is not None and record) else contextlib.nullcontext()
    with model.candidate_step(), recording:
        if events is not None:
            events[0].record()
        if buffers is not None:
            logits, routes = model(model.embed_text(tokens), positions, document_starts=starts,
                                   return_routes=True, batch_documents=batch_documents,
                                   return_device_routes=True, device_route_collector=buffers.collector)
        else:
            logits, routes = model(model.embed_text(tokens), positions, document_starts=starts,
                                   return_routes=True, batch_documents=batch_documents,
                                   **({'route_observer': route_observer} if route_observer is not None else {}))
        loss = torch.nn.functional.cross_entropy(logits.float(), targets, reduction='mean')
        if events is not None:
            events[1].record()
        forwarded = time.perf_counter()
        loss.backward()
        if events is not None:
            events[2].record()
        backwarded = time.perf_counter()
    exited = time.perf_counter()
    if not math.isfinite(float(loss.detach())):
        raise ValueError('nonfinite step loss')
    # Pre-update boundary: the ONE device-to-host copy of the routing buffers happens here, so an incomplete or
    # duplicated report set (a captured segment that skipped the collector) and a trace mismatch refuse BEFORE
    # optimizer.step() can mutate the model. The copy is step work and stays inside the wall; the digest and the
    # statistics are decoded from the retained snapshot after timing, without a second copy.
    snapshot = None
    released = None
    routing_boundary_started = time.perf_counter()
    if buffers is not None:
        snapshot = buffers.snapshot()
        if verify_routes and buffers.routes(snapshot) != tuple(routes.materialize()):
            raise ValueError('device routing buffers differ from the model trace')
        if expert_owners is not None:
            # Reference skip semantics: unrouted expert owners carry no gradient into the update (per layer, per expert,
            # from the same snapshot that validated the report set). Captured dense owners are not in this index.
            released = release_unrouted_expert_grads(expert_owners, buffers.unrouted(snapshot))
    routing_digest_seconds = time.perf_counter() - routing_boundary_started
    if capture is not None and record:
        # The exemplar step's autograd graph must not outlive the record: the harness captures on a side stream and a
        # live AccumulateGrad node bound to the default stream invalidates the capture (proven in the harness fixture).
        del routes
    optimizer.step()
    if events is not None:
        events[3].record()
    synchronize()
    finished = time.perf_counter()
    after = _cache_values(model._cuda_execution.cache)
    wall = finished - started
    if buffers is not None:
        routes_sha256, grammar = buffers.digest(snapshot), buffers.GRAMMAR
        routing_statistics, route_host_reads = buffers.statistics(snapshot), buffers.route_host_reads
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
            'applied_positions': len(pack['token_ids']), 'wall_seconds': wall,
            'positions_per_second': len(pack['token_ids']) / wall,
            'staging_seconds': staged - started, 'forward_seconds': forwarded - staged,
            'backward_seconds': backwarded - forwarded, 'context_exit_seconds': exited - backwarded,
            'optimizer_and_sync_seconds': finished - exited, 'loss': float(loss.detach()),
            'cuda_phase_seconds': ({'forward': events[0].elapsed_time(events[1]) / 1000,
                                   'backward': events[1].elapsed_time(events[2]) / 1000,
                                   'context_exit_and_optimizer': events[2].elapsed_time(events[3]) / 1000}
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
    try:
        prediction, _ = load_prediction(custody / 'prediction.json', binding['launch']['prediction_sha256'])
        if prediction['identity']['run_id'] != run_id or prediction['identity']['gpu_uuid'] != binding['launch']['gpu_uuid']:
            raise ValueError('prediction differs from owned run or selected GPU')
        config, prepared = prepare_execution(prediction)
        import torch
        from ember.model.ember_v0_decoder import CIADecoder, bind_triton_c_compiler
        from ember.model.ember_v0_contract import validate_cia_architecture
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
        model = CIADecoder(architecture_config=config).materialize_cpu(seed=prediction['identity']['seed'])
        mode = execution_mode(prediction['identity'])
        definition = prediction['identity']['optimizer']
        first = prepared['packs'][0]
        first_lengths = document_lengths(tuple(first['document_starts']), len(first['token_ids']))

        def optimizer_factory(inventory):
            if sum(parameter.numel() for parameter in inventory.values()) != POPULATION:
                raise ValueError('full CIA-3B population is missing')
            return torch.optim.AdamW(list(inventory.values()), lr=definition['lr'], betas=tuple(definition['betas']),
                                     eps=definition['eps'], weight_decay=definition['weight_decay'], foreach=False)

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
            'claim': CLAIM})
        expert_owners = expert_owner_index(inventory)
        capture = None
        if mode in MODE_SOURCES:
            buffers = routing_buffers(first_lengths, device)
            # The dynamic treatment is an explicit option on the same factory (grouped kernels inside each segment,
            # expert owners in the segment surface); the published G1 default takes no such argument.
            dynamic = {'capture_experts': True} if mode == 'resident-dynamic-capture' else {}
            capture = model.bind_segmented_capture(
                collector=buffers.collector,
                loss_fn=lambda logits, targets: torch.nn.functional.cross_entropy(logits.float(), targets, reduction='mean'),
                static_state=(buffers.raw,), warmup_steps=2, **dynamic)
        with (custody / 'rows.jsonl').open('xb') as rows:
            for index, pack in enumerate(prepared['packs']):
                verify_prepared_inputs(prepared)
                row = measure_step(model, optimizer, pack, device=device,
                                   batch_documents=prediction['identity']['batch_documents'], run_id=run_id,
                                   capture=capture, record=(capture is not None and index == 0),
                                   expert_owners=expert_owners)
                # The applied update is persisted and counted BEFORE any synthetic capture work, so a capture refusal
                # after the successful warm update leaves a truthful applied count in the terminal record.
                row.update(run_id=run_id, prediction_sha256=binding['launch']['prediction_sha256'],
                           input_sha256=prepared['binding']['input_sha256'])
                rows.write(canonical(row) + b'\n')
                rows.flush()
                os.fsync(rows.fileno())
                applied_positions += row['applied_positions']
                if capture is not None and index == 0:
                    optimizer.zero_grad(set_to_none=False)  # full retained membership, eager expert owners included
                    capture.zero_grad()
                    buffers.capturing = True
                    try:
                        capture.capture(optimizer=optimizer)  # state proof inside; refuses instead of measuring a drifted model
                    finally:
                        buffers.capturing = False
                    _write_new(custody / 'capture.json', dict(capture.receipt(), claim=CLAIM))
        _write_new(custody / 'worker-terminal.json', {'status': 'completed', 'applied_positions': applied_positions,
                                                    'claim': CLAIM})
        return 0
    except BaseException as error:
        _write_new(custody / 'worker-terminal.json', {'status': 'failed', 'error_type': type(error).__name__,
            'error': str(error), 'traceback': traceback.format_exc(), 'applied_positions': applied_positions,
            'claim': CLAIM})
        raise


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
    helper = (Path.home() / '.codex/headless-python.ps1').resolve(strict=True)
    hidden = args.hidden_helper.resolve(strict=True)
    preflight = headroom()
    census = resource_census()
    _, prepared = prepare_execution(prediction)
    gpu_uuid = prediction['identity']['gpu_uuid']
    resources.sample_device(gpu_uuid, total_gpu_bytes=LIMITS['total_gpu_bytes'])
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
        'limits': resource_limits(prediction['identity']), 'worker_argv': worker_argv, 'dispatch': dispatch}}
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
    try:
        with gpu_lock_guard.acquire(script=ENTRY):
            headroom()
            resource_census()
            result = OwnedProcessRunner(windows_job_factory=factory).run(command,
                timeout_s=LIMITS['wall_seconds'], cwd=ROOT)
    except BaseException as error:
        _write_new(custody / 'owned-failure.json', {'status': 'exception', 'error_type': type(error).__name__,
            'error': str(error), 'cleanup_verified': False, 'claim': CLAIM,
            'device_samples': jobs[0].samples if jobs else [],
            'supervisor_failure': jobs[0].failure if jobs else None})
        raise
    (custody / 'stdout.log').write_text(result.stdout, encoding='utf-8')
    (custody / 'stderr.log').write_text(result.stderr, encoding='utf-8')
    receipt = asdict(result)
    receipt.pop('stdout')
    receipt.pop('stderr')
    receipt.update(prediction_sha256=args.prediction_sha256, claim=CLAIM,
                   device_samples=jobs[0].samples, supervisor_failure=jobs[0].failure)
    _write_new(custody / 'owned.json', receipt)
    return 0 if result.returncode == 0 and result.cleanup_verified and not jobs[0].failure else 1


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
