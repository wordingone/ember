"""Daemon-dispatched fixed CIA numerical run body; no standalone authority."""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import argparse
import ctypes
from dataclasses import asdict
import importlib.util
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'src'))

from ember.governance.scripts import cia_conformance as subject
from ember.governance.scripts import cia_conformance_resources as resources
from ember.governance.scripts import gpu_lock_guard
from ember.governance.scripts.owned_process import OwnedProcessRunner

RELATIVE_ENTRY = 'src/ember/governance/scripts/cia_conformance_launch.py'
DISK_ENTRY = 'src/ember/infrastructure/tools/ember-restart-3b/disk_budget_runner.py'
CACHE_DIRS = {'TEMP': 'tmp', 'TMP': 'tmp', 'TORCH_HOME': 'torch',
              'TRITON_CACHE_DIR': 'triton', 'CUDA_CACHE_PATH': 'cuda',
              'HF_HOME': 'hf', 'XDG_CACHE_HOME': 'xdg-cache'}


def headroom():
    class Performance(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong)] + [(name, ctypes.c_size_t) for name in (
            'CommitTotal', 'CommitLimit', 'CommitPeak', 'PhysicalTotal', 'PhysicalAvailable',
            'SystemCache', 'KernelTotal', 'KernelPaged', 'KernelNonpaged', 'PageSize')] + [
            ('HandleCount', ctypes.c_ulong), ('ProcessCount', ctypes.c_ulong), ('ThreadCount', ctypes.c_ulong)]
    if os.name != 'nt':
        raise ValueError('Windows resource envelope required')
    info = Performance()
    info.cb = ctypes.sizeof(info)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
        raise ValueError('cannot read system commit headroom')
    free = (info.CommitLimit - info.CommitTotal) * info.PageSize
    if free < resources.MIN_FREE_COMMIT:
        raise ValueError('less than 42 GiB free system commit')
    disks = {drive: shutil.disk_usage(drive + ':/').free for drive in ('C', 'B')}
    if disks['C'] < 150 * resources.GIB or disks['B'] < 250 * resources.GIB:
        raise ValueError('operating disk reserve is unavailable')
    return {'free_commit_bytes': free, 'free_disk_bytes': disks}


def process_census():
    command = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-Command',
               "$ErrorActionPreference='Stop'; @(Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine,ExecutablePath,PageFileUsage,CreationDate) | ConvertTo-Json -Compress"]
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=20,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or not rows:
        raise ValueError('process census missing')
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
        raise ValueError('cannot parse process command line')
    try:
        args = [values[index] for index in range(count.value)]
    finally:
        kernel.LocalFree(values)
    return args


def training_command(command):
    args = windows_command_args(command)
    entries = {'train.py', 'pretrain.py', 'certified_train_launch.py',
               'ember_resident_training_candidate.py', 'train_multimodal_v0.py',
               'train_delta_rule_dt1.py', 'timeshare_pretrain.py', 'igrpo_trainer.py'}
    return any(Path(arg).name.lower() in entries or arg == 'ember.training.pretrain' for arg in args[1:])


def reject_resource_conflicts(rows, owner_pid, gpu_pids=()):
    by_pid = {row['ProcessId']: row for row in rows}
    ancestors = set()
    current = owner_pid
    while current in by_pid and current not in ancestors:
        ancestors.add(current)
        current = by_pid[current]['ParentProcessId']
    conflicts = []
    for row in rows:
        pid = row['ProcessId']
        if pid in ancestors:
            continue
        if str(row['Name']).lower() not in ('python.exe', 'pythonw.exe', 'py.exe'):
            continue
        commit_kib = row.get('PageFileUsage')
        command = row.get('CommandLine')
        if commit_kib is None or command is None:
            raise ValueError(f'cannot classify Python resource ownership: {pid}')
        training = training_command(command)
        # WDDM lists desktop graphics applications as C+G with no per-process
        # memory attribution. Device-list membership alone is not a trainer.
        # For Python it corroborates a potential model process; native desktop
        # allocation remains included in the total-device supervisor's ceiling.
        if pid in gpu_pids or int(commit_kib) >= 1024 ** 2 or training:
            conflicts.append(pid)
    if conflicts:
        raise ValueError(f'unowned resource-consuming cohort requires coordination: {conflicts}')


def current_resource_census():
    result = subprocess.run(['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader,nounits'],
                            check=True, capture_output=True, text=True, timeout=5,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    values = [value.strip() for value in result.stdout.splitlines() if value.strip()]
    if any(not value.isdecimal() for value in values):
        raise ValueError('cannot classify current GPU compute processes')
    # Query live process identities after the device census. Exited PIDs are not retained.
    rows = process_census()
    reject_resource_conflicts(rows, os.getpid(), {int(value) for value in values})
    for row in rows:
        row['wddm_device_listed'] = str(row['ProcessId']) in values
    return rows


def python_command(helper, hidden, *args):
    return ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-File',
            str(helper), '--', '-B', str(hidden), *map(str, args)]


def load_disk_module(root):
    spec = importlib.util.spec_from_file_location('cia_bound_disk_runner', root / DISK_ENTRY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verify_controller_identity(root, binding, owner, rows):
    from ember.governance.scripts.ember_dispatch_token import _canonical_ember_lab_binary
    launch = binding['launch']
    helpers = list(launch['helpers'])
    fixed_helper = (Path.home() / '.codex/headless-python.ps1').resolve(strict=True)
    hidden = [raw for raw in helpers if Path(raw).resolve(strict=True) != fixed_helper]
    if len(helpers) != 2 or len(hidden) != 1:
        raise ValueError('fixed controller helper identities differ')
    args = windows_command_args(owner.get('CommandLine') or '')
    expected = [str(Path(sys.executable).resolve(strict=True)), '-B',
                str(root / RELATIVE_ENTRY), '--daemon-run', '--custody',
                str(Path(launch['custody']).parent), '--hidden-helper', hidden[0]]
    if (not args or args[1:] != expected[1:]
            or not os.path.samefile(args[0], sys.executable)
            or Path(owner.get('ExecutablePath') or '').resolve(strict=True) != Path(sys.executable).resolve(strict=True)):
        raise ValueError('controller exact executable or argv differs')
    parents = [row for row in rows if row['ProcessId'] == owner['ParentProcessId']]
    canonical = _canonical_ember_lab_binary(root)
    if len(parents) != 1 or canonical is None:
        raise ValueError('canonical daemon parent missing')
    actual = Path(parents[0].get('ExecutablePath') or '').resolve(strict=True)
    if actual != canonical.resolve(strict=True) or subject.daemon_identity(root) != binding['daemon']:
        raise ValueError('controller parent is not the bound canonical daemon')


def verify_envelope(root, binding):
    launch = binding['launch']
    expected_keys = {'run_id', 'owner_pid', 'gpu_uuid', 'gpu_lock', 'custody', 'helpers',
                     'host_memory_bytes', 'allocator_bytes', 'total_gpu_bytes', 'wall_seconds',
                     'max_c_write_gib', 'max_b_write_gib', 'worker_argv', 'daemon_dispatch'}
    if set(launch) != expected_keys:
        raise ValueError('numerical launch binding fields differ')
    limits = {'host_memory_bytes': resources.HOST_MEMORY_BYTES,
              'allocator_bytes': resources.ALLOCATOR_BYTES,
              'total_gpu_bytes': resources.TOTAL_GPU_BYTES, 'wall_seconds': resources.WALL_SECONDS,
              'max_c_write_gib': 0.125, 'max_b_write_gib': 2.0}
    if any(type(launch[key]) is not type(value) or launch[key] != value for key, value in limits.items()):
        raise ValueError('numerical resource envelope differs')
    resources.require_owned_job(launch['run_id'])
    custody = Path(launch['custody']).resolve(strict=True)
    if custody.drive.upper() != 'B:':
        raise ValueError('numerical custody must be on B')
    if sys.argv != [str(root / subject.ENTRY)]:
        raise ValueError('fixed numerical test argv differs')
    if launch['worker_argv'] != [str(root / RELATIVE_ENTRY), '--worker', str(custody / 'subject.json')]:
        raise ValueError('worker command differs')
    if os.environ.get('EMBER_CIA_GPU_MAX_BYTES') != str(resources.ALLOCATOR_BYTES):
        raise ValueError('allocator envelope differs')
    lock_path = Path(os.environ.get('EMBER_GPU_LOCK_PATH', '')).resolve(strict=True)
    if str(lock_path) != launch['gpu_lock']:
        raise ValueError('shared GPU lease path differs')
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    if (lock.get('daemon_pid') != launch['owner_pid'] or lock.get('side') != 'windows'
            or lock.get('active_jobs') != 1):
        raise ValueError('numerical controller does not own GPU lease')
    rows = process_census()
    owners = [row for row in rows if row['ProcessId'] == launch['owner_pid']]
    if len(owners) != 1 or str(root / RELATIVE_ENTRY) not in (owners[0]['CommandLine'] or ''):
        raise ValueError('fixed numerical controller is not alive')
    dispatch = launch['daemon_dispatch']
    if (set(dispatch) != {'job_id', 'daemon_pid', 'memory_cap'}
            or not isinstance(dispatch['job_id'], str) or not dispatch['job_id']
            or type(dispatch['daemon_pid']) is not int or type(dispatch['memory_cap']) is not int
            or dispatch['memory_cap'] != resources.HOST_MEMORY_BYTES
            or owners[0]['ParentProcessId'] != dispatch['daemon_pid']):
        raise ValueError('numerical controller is not the bound daemon child')
    verify_controller_identity(root, binding, owners[0], rows)
    by_pid = {row['ProcessId']: row for row in rows}
    current, visited = os.getpid(), set()
    while current != launch['owner_pid'] and current in by_pid and current not in visited:
        visited.add(current)
        current = by_pid[current]['ParentProcessId']
    if current != launch['owner_pid']:
        raise ValueError('consumer is outside controller ancestry')
    for raw, digest in launch['helpers'].items():
        if subject.file_sha256(raw) != digest:
            raise ValueError('hidden launch helper changed')
    bindings = {name: str((custody / subdir).resolve()) for name, subdir in CACHE_DIRS.items()}
    if any(os.environ.get(name) != path for name, path in bindings.items()):
        raise ValueError('disk cache environment differs')
    assertion = custody / 'child-env-startup.json'
    if os.environ.get('EMBER_DISK_BUDGET_ENV_ASSERTION') != str(assertion):
        raise ValueError('disk startup assertion path differs')
    disk = load_disk_module(root)
    _, _, error = disk._load_child_cache_assertion(assertion, bindings,
                                                  os.environ.get('EMBER_DISK_BUDGET_ENV_NONCE', ''))
    if error:
        raise ValueError(error)
    headroom()
    current_resource_census()
    resources.sample_device(launch['gpu_uuid'])


def worker(path):
    binding = json.loads(path.read_text(encoding='utf-8'))
    if binding['launch']['worker_argv'] != sys.argv:
        raise ValueError('worker argv differs from bound fixed invocation')
    os.environ['EMBER_CIA_SUBJECT_BINDING'] = str(path)
    os.environ['EMBER_CIA_CUDA_CONFORMANCE'] = '1'
    os.environ['EMBER_CIA_GPU_MAX_BYTES'] = str(resources.ALLOCATOR_BYTES)
    sys.argv = [str(ROOT / subject.ENTRY), '--live']
    runpy.run_path(str(ROOT / subject.ENTRY), run_name='__main__')


def launch(custody, hidden, dispatch):
    if os.environ.get('EMBER_GATE_AUTHORIZED') != '1':
        raise ValueError('explicit live gate authorization missing')
    custody = custody.resolve(strict=True)
    if custody.drive.upper() != 'B:' or not custody.is_dir():
        raise ValueError('requires the existing daemon B custody root')
    custody = custody / 'numerical'
    if custody.exists():
        raise ValueError('numerical child custody already exists; refusing reuse')
    helper = Path.home() / '.codex/headless-python.ps1'
    hidden = hidden.resolve(strict=True)
    custody.mkdir(parents=True)
    preflight = headroom()
    rows = current_resource_census()
    (custody / 'preflight.json').write_bytes(subject.canonical({'headroom': preflight, 'processes': rows}))
    binding = subject.build_subject_binding(ROOT)
    run_id = uuid.uuid4().hex
    query = subprocess.run(['nvidia-smi', '--query-gpu=uuid', '--format=csv,noheader'], check=True,
                           capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
    gpu_uuid = query.stdout.strip()
    resources.sample_device(gpu_uuid)
    worker_argv = [str(ROOT / RELATIVE_ENTRY), '--worker', str(custody / 'subject.json')]
    binding['launch'] = {'run_id': run_id, 'owner_pid': os.getpid(), 'gpu_uuid': gpu_uuid,
                         'gpu_lock': str(Path(gpu_lock_guard._require_lock_path()).resolve()),
                         'custody': str(custody), 'helpers': {str(path): subject.file_sha256(path) for path in (helper, hidden)},
                         'host_memory_bytes': resources.HOST_MEMORY_BYTES,
                         'allocator_bytes': resources.ALLOCATOR_BYTES, 'total_gpu_bytes': resources.TOTAL_GPU_BYTES,
                         'wall_seconds': resources.WALL_SECONDS, 'max_c_write_gib': 0.125,
                         'max_b_write_gib': 2.0, 'worker_argv': worker_argv,
                         'daemon_dispatch': dispatch}
    (custody / 'subject.json').write_bytes(subject.canonical(binding))
    command = python_command(helper, hidden, ROOT / DISK_ENTRY,
                             '--max-c-write-gib', '0.125', '--max-b-write-gib', '2',
                             '--receipt', custody / 'disk.json', '--write-root', f'custody={custody}',
                             '--', *python_command(helper, hidden, *worker_argv))
    jobs = []
    def factory():
        job = resources.ConformanceJob(run_id, gpu_uuid)
        jobs.append(job)
        return job
    try:
        with gpu_lock_guard.acquire(script=RELATIVE_ENTRY):
            headroom()
            current_resource_census()
            result = OwnedProcessRunner(windows_job_factory=factory).run(
                command, timeout_s=resources.WALL_SECONDS, cwd=ROOT)
    except BaseException as error:
        failure = {'status': 'exception', 'error_type': type(error).__name__, 'error': str(error),
                   'cleanup_verified': False,
                   'subject_sha256': subject.file_sha256(custody / 'subject.json'),
                   'device_samples': jobs[0].samples if jobs else [],
                   'supervisor_failure': jobs[0].failure if jobs else None,
                   'claim': 'failed execution; no qualification or training credit'}
        (custody / 'owned-failure.json').write_bytes(subject.canonical(failure))
        raise
    (custody / 'stdout.log').write_text(result.stdout, encoding='utf-8')
    (custody / 'stderr.log').write_text(result.stderr, encoding='utf-8')
    receipt = asdict(result)
    receipt.pop('stdout'); receipt.pop('stderr')
    receipt.update(subject_sha256=subject.file_sha256(custody / 'subject.json'),
                   device_samples=jobs[0].samples, supervisor_failure=jobs[0].failure,
                   claim='fixed numerical correctness only; zero qualification or training credit')
    (custody / 'owned.json').write_bytes(subject.canonical(receipt))
    print(json.dumps(receipt))
    return 0 if result.returncode == 0 and result.cleanup_verified and not jobs[0].failure else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--custody', type=Path)
    parser.add_argument('--hidden-helper', type=Path)
    parser.add_argument('--daemon-run', action='store_true')
    args = parser.parse_args()
    if args.worker and not (args.daemon_run or args.custody or args.hidden_helper):
        worker(args.worker)
        return 0
    if args.daemon_run and args.custody and args.hidden_helper and not args.worker:
        expected = [str(ROOT / RELATIVE_ENTRY), '--daemon-run', '--custody', str(args.custody),
                    '--hidden-helper', str(args.hidden_helper)]
        if sys.argv != expected:
            raise ValueError('daemon run-body argv differs from fixed profile')
        from ember.governance.scripts.ember_dispatch_token import consume_dispatch
        # Never retain or publish the single-use token itself.
        dispatch = {'job_id': os.environ.get('EMBER_LAB_DISPATCH_JOB_ID'),
                    'daemon_pid': os.environ.get('EMBER_LAB_DISPATCH_DAEMON_PID')}
        cap = consume_dispatch(ROOT)
        if type(cap) is not int or cap != resources.HOST_MEMORY_BYTES:
            raise ValueError('authenticated daemon memory cap differs from fixed run')
        dispatch.update(daemon_pid=int(dispatch['daemon_pid']), memory_cap=cap)
        return launch(args.custody, args.hidden_helper, dispatch)
    parser.error('use exactly --daemon-run --custody PATH --hidden-helper PATH through the daemon, or the bound --worker PATH')


if __name__ == '__main__':
    sys.exit(main())
