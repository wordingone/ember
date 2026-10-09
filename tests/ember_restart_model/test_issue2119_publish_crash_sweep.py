"""Issue #2119 row 6b: a writer that dies inside the publish leaves nothing behind once the next writer has run.

A real crash (the child interpreter exits inside the atomic replace, so its `finally` never runs) leaves the staged temp file and the lock file. The next
writer must sweep its own stale files -- matched by this module's own staging name pattern and a dead-pid check -- and leave only the pointer. The
sweeper must not touch a live writer's file or any name that is not its own. POINTER_MODULE overrides the module under test (the deliberate red runs the
pre-sweep module and sees the strays).

Every child interpreter is an owned, hidden process (owned_children). Sibling authorities are stubbed with data-only fixtures: no checkpoint, no model, no GPU.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from owned_children import python_argv, run_one  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
MODULE = Path(os.environ.get('POINTER_MODULE') or TOOLS / 'selected_continuation_head.py')
P0, WIN_A, WIN_B = '0' * 64, 'a' * 64, 'b' * 64
TOKEN = 'e' * 32

CHILD = r'''
import importlib.util, os, sys, types
from pathlib import Path
module_path, receipts, mode, digest, expected = sys.argv[1:6]
artifacts = types.ModuleType('checkpoint_artifacts')
artifacts.published_checkpoint_receipt = lambda root: {'checkpoint_manifest_sha256': digest}
durable = types.ModuleType('durable_io')
def replace(staged, target):
    if mode == 'crash':
        os._exit(9)                      # dies inside the publish: no finally, no unlock call, staged file on disk
    os.replace(staged, target)
durable.atomic_replace_durable = replace
sys.modules['checkpoint_artifacts'], sys.modules['durable_io'] = artifacts, durable
spec = importlib.util.spec_from_file_location('pointer_under_test', module_path)
pointer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pointer)
common = dict(repo_root=Path(module_path).parent, receipts_root=Path(receipts), published_checkpoint_root=Path('unused'),
              hour_result_path=Path('hour-result.json'), hour_result_sha256='f' * 64)
if expected == 'SEED':
    pointer.seed_selected_continuation_head(reason='fixture', **common)
else:
    pointer.advance_selected_continuation_head(expected_parent_checkpoint_manifest_sha256=expected, **common)
'''


def dead_pid() -> int:
    out = run_one(python_argv('-c', 'import os;print(os.getpid())'), timeout_s=120)      # an owned, hidden child through the headless wrapper on Windows
    assert out.returncode == 0, out.stderr
    return int(out.stdout.strip())


class CrashSweepTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.script = self.root / 'child.py'
        self.script.write_text(CHILD, encoding='utf-8')
        self.receipts = self.root / 'copy-of-receipts'
        self.receipts.mkdir()

    def run_child(self, mode, digest, expected, *, expect_rc=0):
        result = run_one(python_argv(self.script, MODULE, self.receipts, mode, digest, expected), timeout_s=120)
        self.assertEqual(result.returncode, expect_rc, f'{mode}: {result.stderr}')

    def listing(self):
        return sorted(path.name for path in self.receipts.iterdir())

    def settled_listing(self):
        """What the directory holds once no writer is running. Windows removes the idle lock file; POSIX keeps it by design (an unlink would race a waiting
        flock), so there the lock file is the one expected extra and anything else is a stray."""
        return ['selected-continuation-head.json'] + ([] if os.name == 'nt' else ['selected-continuation-head.json.lock'])

    def head(self):
        return json.loads((self.receipts / 'selected-continuation-head.json').read_text(encoding='utf-8'))['lineage_checkpoint_manifest_sha256']

    def test_crash_inside_publish_then_the_next_writer_leaves_only_the_pointer_DELIBERATE_RED(self):
        self.run_child('ok', P0, 'SEED')
        self.run_child('crash', WIN_A, P0, expect_rc=9)
        stray = self.listing()
        self.assertEqual(self.head(), P0)                                 # the crashed publish changed nothing
        self.assertTrue(any(name.endswith('.tmp') for name in stray), stray)   # the crash really left a staged file behind (the unswept shape)
        self.run_child('ok', WIN_B, P0)                                   # the next writer: not blocked, and it cleans up after the dead one
        self.assertEqual(self.head(), WIN_B)
        self.assertEqual(self.listing(), self.settled_listing())

    def test_a_clean_advance_also_leaves_only_the_pointer(self):
        self.run_child('ok', P0, 'SEED')
        self.run_child('ok', WIN_A, P0)
        self.assertEqual(self.listing(), self.settled_listing())

    def test_the_settled_listing_names_no_staged_temp_file_on_any_platform_DELIBERATE_RED(self):
        self.run_child('ok', P0, 'SEED')
        self.run_child('crash', WIN_A, P0, expect_rc=9)
        self.assertNotEqual(self.listing(), self.settled_listing())      # the unswept crash shape is not the settled one on Windows or POSIX
        self.assertTrue(any(name.endswith('.tmp') for name in self.listing()))


class SweepScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(TOOLS))
        import selected_continuation_head as pointer
        import pending_continuation
        cls.pointer, cls.pending = pointer, pending_continuation
        cls.dead = dead_pid()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def staged(self, base, pid):
        path = self.dir / f'.{base}.{pid}.{TOKEN}.tmp'
        path.write_bytes(b'x')
        return path.name

    def test_the_staged_base_names_cover_the_pending_record_writer(self):
        self.assertIn(self.pending.FILENAME, self.pointer.STAGED_BASE_NAMES)
        self.assertIn(self.pointer.POINTER_FILENAME, self.pointer.STAGED_BASE_NAMES)
        self.assertIn(self.pointer.CANDIDATE_FILENAME, self.pointer.STAGED_BASE_NAMES)

    def test_dead_writers_staged_files_are_removed_for_every_own_base_name(self):
        names = sorted(self.staged(base, self.dead) for base in self.pointer.STAGED_BASE_NAMES)
        self.assertEqual(self.pointer.sweep_stale_staging(self.dir), names)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_a_live_writers_file_and_this_process_are_never_swept_DELIBERATE_RED(self):
        mine = self.staged(self.pointer.POINTER_FILENAME, os.getpid())
        parent = self.staged(self.pointer.POINTER_FILENAME, os.getppid()) if os.getppid() != self.dead else None
        removed = self.pointer.sweep_stale_staging(self.dir)
        self.assertNotIn(mine, removed)                       # a sweep that ignored liveness would delete the file a concurrent writer is about to rename
        self.assertTrue((self.dir / mine).is_file())
        if parent is not None and self.pointer._pid_alive(os.getppid()):
            self.assertNotIn(parent, removed)

    def test_names_that_are_not_this_modules_own_are_left_alone(self):
        keep = [self.staged('some-other-file.json', self.dead), 'notes.tmp', f'.selected-continuation-head.json.notapid.{TOKEN}.tmp',
                f'.selected-continuation-head.json.{self.dead}.SHORT.tmp', 'selected-continuation-head.json']
        for name in keep:
            (self.dir / name).write_bytes(b'x')
        self.assertEqual(self.pointer.sweep_stale_staging(self.dir), [])
        self.assertEqual(sorted(path.name for path in self.dir.iterdir()), sorted(set(keep)))

    def windows_state(self, *, handle, last_error=0, exit_ok=True, exit_code=0):
        """_windows_pid_state against a fake kernel32: no Windows needed, so this runs on every platform."""
        class Code:
            def __init__(self):
                self.value = 0

        class Kernel:
            closed = []

            def OpenProcess(self, access, inherit, pid):
                return handle

            def GetExitCodeProcess(self, process, ref):
                ref.value = exit_code
                return exit_ok

            def CloseHandle(self, process):
                self.closed.append(process)
        return self.pointer._windows_pid_state(41, Kernel(), lambda: last_error, c_ulong=Code, byref=lambda code: code, c_void_p=lambda value: value)

    def test_windows_death_is_proven_only_by_no_such_pid_or_an_exit_code(self):
        self.assertEqual(self.windows_state(handle=0, last_error=87), 'dead')                  # OpenProcess: no such process
        self.assertEqual(self.windows_state(handle=5, exit_code=0), 'dead')                    # it exited
        self.assertEqual(self.windows_state(handle=5, exit_code=259), 'alive')                 # STILL_ACTIVE

    def test_an_uninspectable_writer_counts_as_alive_so_its_staged_file_is_kept_DELIBERATE_RED(self):
        self.assertEqual(self.windows_state(handle=0, last_error=5), 'unknown')                # access denied is not absence
        self.assertEqual(self.windows_state(handle=5, exit_ok=False), 'unknown')               # a failing exit-code query is not absence
        for state_args in (dict(handle=0, last_error=5), dict(handle=5, exit_ok=False)):
            self.assertNotEqual(self.windows_state(**state_args), 'dead')                      # only 'dead' lets the sweep delete

    def test_a_missing_directory_is_not_an_error(self):
        self.assertEqual(self.pointer.sweep_stale_staging(self.dir / 'absent'), [])


if __name__ == '__main__':
    unittest.main()
