# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The post-train counter pass inside a REAL capped Windows Job Object (#2119; the H50 hour lost its restore verify to this).

H50 published its child and then died in the continuation's restore verify: `_cia_counter_component` read the whole 5.3 GiB
optimizer-state.pt into one bytes object while the worker already held ~34.5 GiB inside a 40 GiB job memory limit. This is that
situation scaled down and run for real, no mock: a child process is put in a job object that carries
JOB_OBJECT_LIMIT_JOB_MEMORY (cap 1.6 GiB), holds 0.6 GiB of resident ballast, and reads a 1.18 GiB v3-shaped optimizer component through
the real `_cia_counter_component` and the real `_cia_counter_optimizer_facts` (so the fp32 master / moment helpers run too). One tensor
is the real maximum (the embedding, 32768 x 1024 fp32 = 128 MiB), so the per-tensor bound is tested unscaled.

Windows only: a job object memory limit is a Windows kernel object. ci-pr runs this file as a step of its windows-latest `launcher`
job; the ubuntu issue2119 wiring job accepts no skip and reads its file list from the wiring manifest, so this file is NOT in that
manifest. Standard library only (no torch).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cia_component_fixture as fixture  # noqa: E402

MIB, GIB = 1024 ** 2, 1024 ** 3
CAP = int(1.6 * GIB) // 4096 * 4096  # a whole number of pages: the kernel rounds the limit down to one. scaled from the 40 GiB job limit of the H50 hour
BALLAST = int(0.6 * GIB)         # scaled from the ~34.5 GiB resident set of the H50 hour
MARGIN = 256 * MIB               # the fixed code must stay at least this far under the cap
ROOMY = 6 * GIB                  # the control: the same read with room to spare must succeed on the OLD code too

CHILD = r'''
import json, sys
tool, root, relative, record, inventory, groups, ballast, result = sys.argv[1:9]
sys.path.insert(0, tool)
import parameter_counter as counter
from pathlib import Path
sys.stdin.readline()          # held until the parent has put this process into the job
blob = None
if int(ballast):
    blob = bytearray(int(ballast))
    for offset in range(0, len(blob), 4096):
        blob[offset] = 1      # touched: resident, not merely reserved
try:
    with counter._cia_counter_component(Path(root), relative, json.loads(record)) as (archive, payload):
        inv = {name: tuple(shape) for name, shape in json.loads(inventory).items()}
        optimizer, extra = counter._cia_counter_optimizer_facts(archive, payload, inv, json.loads(groups), True)
    Path(result).write_text(json.dumps([optimizer, extra], sort_keys=True), encoding='utf-8')
except MemoryError:
    print('MEMORY_ERROR', flush=True)
    sys.exit(7)
'''


if sys.platform == 'win32':
    from ctypes import wintypes
    import ctypes
    from ember.governance.scripts import owned_process

    _K = owned_process._kernel32
    _K.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    _K.QueryInformationJobObject.restype = wintypes.BOOL
    _JOB_MEMORY = 0x200

    class CappedJob:
        """A job object with a real JOB_OBJECT_LIMIT_JOB_MEMORY; reads PeakJobMemoryUsed back from the kernel."""

        def __init__(self, cap):
            self.handle = _K.CreateJobObjectW(None, None)
            if not self.handle:
                raise OSError(ctypes.get_last_error(), 'CreateJobObjectW')
            info = owned_process._JobExtendedLimitInformation()
            info.BasicLimitInformation.LimitFlags = owned_process._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | _JOB_MEMORY
            info.JobMemoryLimit = cap
            if not _K.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise OSError(ctypes.get_last_error(), 'SetInformationJobObject')

        def assign(self, process):
            if not _K.AssignProcessToJobObject(self.handle, wintypes.HANDLE(process._handle)):
                raise OSError(ctypes.get_last_error(), 'AssignProcessToJobObject')

        def kernel_limits(self):
            info = owned_process._JobExtendedLimitInformation()
            if not _K.QueryInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info), None):
                raise OSError(ctypes.get_last_error(), 'QueryInformationJobObject')
            return info.JobMemoryLimit, info.PeakJobMemoryUsed, info.BasicLimitInformation.LimitFlags

        def close(self):
            if self.handle:
                _K.CloseHandle(self.handle)
                self.handle = None


@unittest.skipUnless(sys.platform == 'win32', 'a Job Object memory limit is a Windows kernel object (ci-pr runs this in its windows-latest launcher job)')
class PostTrainCounterUnderJobCap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        # the embedding at its real maximum (128 MiB per fp32 tensor) plus 23 expert-sized owners: ~1.18 GiB in all
        owners = [('embedding.weight', (32768, 1024), False)]
        owners += [('experts.%d.layers.0.up.weight' % index, (3072, 1024), index % 2 == 0) for index in range(23)]
        cls.built = fixture.build_component(cls.root / 'optimizer-state.pt', owners)
        cls.expected = [cls.built['expected'][0], cls.built['expected'][1]]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_child(self, cap, ballast):
        result = self.root / ('result-%d-%d.json' % (cap, ballast))
        if result.exists():
            result.unlink()
        job = CappedJob(cap)
        self.addCleanup(job.close)
        child = subprocess.Popen(
            [sys.executable, '-B', '-c', CHILD, str(TOOL), str(self.root), 'optimizer-state.pt', json.dumps(self.built['record']),
             json.dumps({k: list(v) for k, v in self.built['inventory'].items()}), json.dumps(self.built['groups']), str(ballast), str(result)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        job.assign(child)
        out, err = child.communicate(b'go\n', timeout=900)
        limit, peak, flags = job.kernel_limits()
        self.assertEqual(limit, cap, 'the kernel must report the limit that was set')
        self.assertTrue(flags & _JOB_MEMORY, 'JOB_OBJECT_LIMIT_JOB_MEMORY must be in force')
        print('JOB_MEMORY cap=%d ballast=%d peak_job_memory_used=%d (%.3f GiB) rc=%d' % (cap, ballast, peak, peak / GIB, child.returncode),
              file=sys.stderr, flush=True)
        return child.returncode, out.decode(errors='replace') + err.decode(errors='replace')[-1500:], peak, result

    def test_the_fixture_is_a_real_over_one_gib_component(self):
        self.assertGreater(self.built['record']['bytes'], int(1.1 * GIB))
        self.assertLess(self.built['record']['bytes'] + BALLAST, 2 * GIB)
        self.assertGreater(self.built['record']['bytes'] + BALLAST, CAP, 'a whole-file read plus the ballast must exceed the cap')

    def test_control_the_same_read_with_room_to_spare_is_correct(self):
        # Proves a red below is memory and not the fixture: roomy cap, no ballast, exact expected digests on any counter version.
        code, text, peak, result = self.run_child(ROOMY, 0)
        self.assertEqual(code, 0, text)
        self.assertEqual(json.loads(result.read_text(encoding='utf-8')), json.loads(json.dumps(self.expected, sort_keys=True)))

    def test_capped_job_counter_pass_fits_with_the_resident_ballast(self):
        code, text, peak, result = self.run_child(CAP, BALLAST)
        self.assertEqual(code, 0, 'the counter pass died inside the capped job (H50 class): ' + text)
        self.assertEqual(json.loads(result.read_text(encoding='utf-8')), json.loads(json.dumps(self.expected, sort_keys=True)))
        self.assertLess(peak, CAP - MARGIN, 'peak job memory %d is not at least %d under the cap %d' % (peak, MARGIN, CAP))


if __name__ == '__main__':
    unittest.main()
