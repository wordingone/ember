"""Named resource enforcement using OwnedProcessRunner; numerical defaults retained."""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import ctypes
import os
import re
import subprocess
import threading
import time

from ember.governance.scripts import owned_process

GIB = 1024 ** 3
HOST_MEMORY_BYTES = 20 * GIB
TOTAL_GPU_BYTES = 20 * GIB
ALLOCATOR_BYTES = 16 * GIB
WALL_SECONDS = 600
MIN_FREE_COMMIT = 42 * GIB


def parse_device_sample(text, expected_uuid, *, total_gpu_bytes=TOTAL_GPU_BYTES):
    if type(total_gpu_bytes) is not int or total_gpu_bytes <= 0:
        raise ValueError('total device ceiling must be a positive integer')
    rows = [row.strip() for row in text.splitlines() if row.strip()]
    if len(rows) != 1:
        raise ValueError('expected exactly one selected GPU sample')
    fields = [field.strip() for field in rows[0].split(',')]
    if len(fields) != 3 or fields[0] != expected_uuid:
        raise ValueError('GPU identity changed or sample malformed')
    if not all(re.fullmatch(r'[0-9]+', field) for field in fields[1:]):
        raise ValueError('GPU memory sample is not an exact nonnegative integer')
    total, used = (int(field) * 1024 ** 2 for field in fields[1:])
    if used > total or total <= total_gpu_bytes:
        raise ValueError('GPU total or used memory invalid')
    if used >= total_gpu_bytes:
        raise ValueError('total-device memory envelope exceeded')
    return {'uuid': fields[0], 'total_bytes': total, 'used_bytes': used}


def sample_device(uuid, *, total_gpu_bytes=TOTAL_GPU_BYTES):
    if not re.fullmatch(r'GPU-[0-9a-fA-F-]+', uuid):
        raise ValueError('an exact GPU UUID is required')
    flags = {}
    if os.name == 'nt':
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        flags = {'creationflags': subprocess.CREATE_NO_WINDOW, 'startupinfo': startup}
    result = subprocess.run(['nvidia-smi', '-i', uuid, '--query-gpu=uuid,memory.total,memory.used',
                             '--format=csv,noheader,nounits'], check=True, capture_output=True,
                            text=True, timeout=3, shell=False, **flags)
    return parse_device_sample(result.stdout, uuid, total_gpu_bytes=total_gpu_bytes)


def job_name(run_id, *, namespace='EmberCIAConformance'):
    if not re.fullmatch('[0-9a-f]{32}', run_id):
        raise ValueError('run identity must be 32 lowercase hex characters')
    if not re.fullmatch('[A-Za-z][A-Za-z0-9]{1,63}', namespace):
        raise ValueError('resource job namespace is malformed')
    return 'Local\\' + namespace + '-' + run_id


def require_owned_job(run_id, *, namespace='EmberCIAConformance', host_memory_bytes=HOST_MEMORY_BYTES):
    """Read back the actual containing job; an environment flag is insufficient."""
    if os.name != 'nt':
        raise ValueError('this numerical resource envelope requires Windows')
    if type(host_memory_bytes) is not int or host_memory_bytes <= 0:
        raise ValueError('host memory ceiling must be a positive integer')
    from ctypes import wintypes
    kernel = owned_process._kernel32
    kernel.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenJobObjectW.restype = wintypes.HANDLE
    kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel.IsProcessInJob.restype = wintypes.BOOL
    kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                wintypes.DWORD, ctypes.c_void_p]
    kernel.QueryInformationJobObject.restype = wintypes.BOOL
    handle = kernel.OpenJobObjectW(4, False, job_name(run_id, namespace=namespace))
    if not handle:
        raise ValueError('owned numerical job is missing')
    try:
        member = wintypes.BOOL()
        if not kernel.IsProcessInJob(wintypes.HANDLE(-1), handle, ctypes.byref(member)) or not member.value:
            raise ValueError('consumer is not in the bound owned job')
        info = owned_process._JobExtendedLimitInformation()
        if not kernel.QueryInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info), None):
            raise ValueError('cannot query owned numerical job')
        required = owned_process._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | 0x200
        if info.JobMemoryLimit != host_memory_bytes or info.BasicLimitInformation.LimitFlags & required != required:
            raise ValueError('owned job resource limits differ from the bound envelope')
    finally:
        kernel.CloseHandle(handle)


class ResourceJob(owned_process._WindowsJob if os.name == 'nt' else object):
    """Extend the existing cohort owner; never terminate an unrelated process."""
    def __init__(self, run_id, gpu_uuid, *, namespace='EmberCIAConformance',
                 host_memory_bytes=HOST_MEMORY_BYTES, total_gpu_bytes=TOTAL_GPU_BYTES):
        if os.name != 'nt':
            raise ValueError('Windows numerical resource envelope required')
        if type(host_memory_bytes) is not int or host_memory_bytes <= 0:
            raise ValueError('host memory ceiling must be a positive integer')
        if type(total_gpu_bytes) is not int or total_gpu_bytes <= 0:
            raise ValueError('total device ceiling must be a positive integer')
        self.total_gpu_bytes = total_gpu_bytes
        from ctypes import wintypes
        kernel = owned_process._kernel32
        ctypes.set_last_error(0)
        self._handle = kernel.CreateJobObjectW(None, job_name(run_id, namespace=namespace))
        if not self._handle or ctypes.get_last_error() == 183:
            if self._handle:
                kernel.CloseHandle(self._handle)
            self._handle = None
            raise ValueError('numerical job identity missing or already exists')
        self.samples = []
        self.failure = None
        self.peak_job_memory = None
        self.gpu_uuid = gpu_uuid
        self._stop = threading.Event()
        self._handle_lock = threading.RLock()
        self._containment_error = None
        self._watcher = None
        info = owned_process._JobExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = owned_process._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | 0x200
        info.JobMemoryLimit = host_memory_bytes
        if not kernel.SetInformationJobObject(self._handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.close()
            raise ValueError('cannot enforce numerical job memory ceiling')
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateJobObject.restype = wintypes.BOOL

    def _observe(self):
        sample = sample_device(self.gpu_uuid, total_gpu_bytes=self.total_gpu_bytes)
        sample['monotonic_seconds'] = time.monotonic()
        self.samples.append(sample)

    def assign_and_resume(self, process):
        self._observe()
        # A supervisor cannot terminate an empty job and then allow a resume.
        with self._handle_lock:
            super().assign_and_resume(process)
            self._watcher = threading.Thread(target=self._watch, daemon=True)
            self._watcher.start()

    def _watch(self):
        while not self._stop.wait(1):
            try:
                self._observe()
            except Exception as error:
                with self._handle_lock:
                    if self._stop.is_set():
                        return
                    self.failure = str(error)
                    if self._handle and not owned_process._kernel32.TerminateJobObject(self._handle, 125):
                        self._containment_error = 'TerminateJobObject failed during GPU supervision'
                        # Closing the sole owning handle is the existing kill-on-close fallback.
                        try:
                            super().close()
                        except Exception as cleanup_error:
                            self._containment_error += ': ' + str(cleanup_error)
                return

    def close(self):
        self._stop.set()
        if self._watcher is not None:
            self._watcher.join(timeout=5)
            if self._watcher.is_alive():
                self.failure = self.failure or 'GPU supervisor failed to terminate'
                self._containment_error = self.failure
        # The watcher only accesses the job while holding this same lock.
        with self._handle_lock:
            super().close()
        if self._containment_error:
            raise owned_process.ProcessContainmentError(self._containment_error)


class ConformanceJob(ResourceJob):
    """The existing fixed numerical resource contract, with unchanged defaults."""

    def __init__(self, run_id, gpu_uuid):
        super().__init__(run_id, gpu_uuid)
