# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Hidden, owned child interpreters for the #2119 process tests.

Every child is started through the existing owned_process.OwnedProcessRunner (Windows: job object,
CREATE_NO_WINDOW and a hidden STARTUPINFO, shell=False, captured streams; POSIX: its own process group plus the
controller-death guard), never through a bare subprocess call, so no test child can open a console window and no
child outlives its test: the runner kills the whole tree on a timeout and on every exit path.

run_group() adds the concurrency the race tests need on top of that runner: one owned child per thread, a file
barrier released only after EVERY child has acknowledged readiness (fail-closed within READY_TIMEOUT_S), and an
abort file so a child waiting at the barrier exits instead of running when the group has already failed.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import NamedTuple, Sequence

ROOT = Path(__file__).resolve().parents[2]
_GOVERNANCE_SCRIPTS = ROOT / 'src' / 'ember' / 'governance' / 'scripts'
if str(_GOVERNANCE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_GOVERNANCE_SCRIPTS))

import owned_process  # noqa: E402

READY_TIMEOUT_S = 30.0

# Child-side half of the barrier; paste into a child script. A child that never sees `go` (the group failed, or
# the controller is gone) exits 9 after wait_s instead of waiting forever.
BARRIER_CHILD_PRELUDE = '''
import time as _barrier_time
from pathlib import Path as _BarrierPath
def barrier_ready_and_wait(barrier_dir, name, start_delay=0.0, wait_s=60.0):
    _barrier_time.sleep(start_delay)
    barrier = _BarrierPath(barrier_dir)
    (barrier / ('ready-' + name)).write_text('1')
    deadline = _barrier_time.monotonic() + wait_s
    while not (barrier / 'go').exists():
        if (barrier / 'abort').exists() or _barrier_time.monotonic() > deadline:
            raise SystemExit(9)
        _barrier_time.sleep(0.005)
'''


class BarrierFailure(AssertionError):
    """A child died or never acknowledged readiness; nothing was released."""


class GroupOutcome(NamedTuple):
    results: dict          # name -> owned_process.OwnedProcessResult (status, returncode, pid, stdout, stderr)
    ready_before_go: list  # names whose ready file the controller had seen when it released the barrier


HEADLESS_PYTHON_WRAPPER = os.environ.get('EMBER_HEADLESS_PYTHON_WRAPPER') or os.path.join(os.path.expanduser('~'), '.codex', 'headless-python.ps1')


def python_argv(*args) -> list:
    """Windows: every non-Ember interpreter starts through the mandatory headless wrapper (powershell -File
    headless-python.ps1 -- <args>), which itself starts the interpreter with no window; the owned runner's job object
    still covers the whole descendant tree. POSIX: the interpreter directly."""
    tail = ['-B', *[str(part) for part in args]]
    if os.name == 'nt':
        return ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-File', HEADLESS_PYTHON_WRAPPER, '--', *tail]
    return [sys.executable, *tail]


def run_one(argv: Sequence[str], *, timeout_s: float, env=None) -> 'owned_process.OwnedProcessResult':
    """One owned, hidden child to completion. status == 'terminated' means the timeout fired and the tree was killed."""
    if os.name == 'nt':
        # the wrapper starts CODEX_PYTHON (default a fixed install); pin it to the interpreter running these tests
        env = dict(os.environ if env is None else env)
        env.setdefault('CODEX_PYTHON', sys.executable)
    return owned_process.OwnedProcessRunner().run(list(argv), timeout_s=timeout_s, env=env)


def pid_alive(pid: int) -> bool:
    """True while the process still exists (used to prove an owned child is gone, not merely reported dead)."""
    if os.name == 'nt':
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))) and code.value == 259
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def run_group(jobs: Sequence[tuple], *, barrier_dir, timeout_s: float, env=None,
              ready_timeout_s: float = READY_TIMEOUT_S) -> GroupOutcome:
    """Run every (name, argv) as an owned child; release them together only once all have written ready-<name>.

    Fail-closed: a child that finishes before acknowledging, or a missing acknowledgement after ready_timeout_s,
    writes the abort file, waits for every owned child to finish, and raises BarrierFailure. Whatever happens, every
    thread is joined (and so every owned child is gone) before this returns or raises."""
    barrier = Path(barrier_dir)
    names = [name for name, _ in jobs]
    results: dict = {}
    errors: dict = {}

    def target(name, argv):
        try:
            results[name] = run_one(argv, timeout_s=timeout_s, env=env)
        except BaseException as exc:  # noqa: BLE001 - recorded, re-raised by the controller after the join
            errors[name] = exc

    threads = [threading.Thread(target=target, args=(name, argv), name=f'owned-child-{name}', daemon=True)
               for name, argv in jobs]
    failure = None
    ready_before_go: list = []
    try:
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + ready_timeout_s
        while True:
            ready_before_go = sorted(name for name in names if (barrier / f'ready-{name}').exists())
            if len(ready_before_go) == len(names):
                break
            early = {name: results[name] for name in names if name in results}
            if errors or early or time.monotonic() > deadline:
                detail = {name: (r.returncode, r.stderr[-400:]) for name, r in early.items()}
                raise BarrierFailure(f'children not all ready before release: ready={ready_before_go} finished={detail} errors={errors}')
            time.sleep(0.01)
        (barrier / 'go').write_text('1')
    except BaseException as exc:  # noqa: BLE001 - abort the group first, re-raise after every child is reaped
        failure = exc
        (barrier / 'abort').write_text('1')
    for thread in threads:
        thread.join(timeout_s + 30.0)
    still_running = [thread.name for thread in threads if thread.is_alive()]
    if failure is not None:
        raise failure
    if still_running:
        raise AssertionError(f'owned child threads did not finish: {still_running}')
    if errors:
        raise AssertionError(f'owned child launch failed: {errors}')
    return GroupOutcome(results, ready_before_go)
