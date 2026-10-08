"""Issue #2119 section 5: the durable, atomically-updated pointer to the checkpoint a fresh
CONTINUE_TRAINING dispatch resumes from.

checkpoint_artifacts and durable_io are reused wholesale (imported, never reimplemented):
re-derive the published checkpoint's digest from disk rather than trusting the caller
(checkpoint_artifacts.published_checkpoint_receipt), then a pre-write round-trip validation
followed by a single atomic small-file replace (durable_io.atomic_replace_durable). The
compare-and-swap step -- the caller's declared parent must equal the pointer's current value --
MIRRORS update_current_subject.py's own CAS pattern but is implemented independently here, as
this module's own StaleParentError: nothing is imported from update_current_subject.py, and
nothing from it is executed by this module (see _import_siblings' docstring for why).

This is deliberately NOT manifests/ember-current-subject-v1.json. That file is governance's
public model-birth / capability-credit record: gen_readme_status.load_current_subject pins its
authority to one literal EMBER-02A binding and pins disposition/capability_credit/
sufficient_pretraining_proven to fixed "not yet admitted" values forever. This tool's own
training_continuity_status.py says as much in its own module docstring -- "This is a different
concept from gen_readme_status.py's CURRENT_SUBJECT_FIELDS ... This module reports training
CONTINUITY status: selected checkpoint and parent". A run_hour publication is neither a model
birth nor a capability-credit claim; it needs its own pointer, scoped to this tool's own
operational lineage.

Not a ledger (this is a single mutable pointer, never an append-only log -- the append-only
diagnostic-allowance ledger already exists in training_continuity_ledger.py and is untouched by
this module) and not a new checkpoint byte format (this only ever names an existing
checkpoint-manifest.json by its digest).

Lives beside the diagnostic-allowance ledger, at the same host-wide receipts root
(training_continuity_ledger.ledger_root), so a fresh --custody parent or a relabeled dispatch
never resets which checkpoint is selected.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

SCHEMA = 'ember-selected-continuation-head-v1'
POINTER_FILENAME = 'selected-continuation-head.json'
# An hour's own publish writes ONLY this file (operator ruling, mail 53920, after H20 and H21 each moved the selected
# head before its frozen score): the selected head moves only through advance_selected_continuation_head,
# called by the operator-ruled promotion step, never from inside an hour.
CANDIDATE_SCHEMA = 'ember-candidate-continuation-head-v1'
CANDIDATE_FILENAME = 'candidate-continuation-head.json'
_CANDIDATE_FIELDS = {
    'schema', 'candidate_checkpoint_manifest_sha256', 'parent_checkpoint_manifest_sha256',
    'hour_result_path', 'hour_result_sha256', 'published_at',
}
# Matches update_current_subject.py's and training_continuity_ledger.py's own GENESIS_SENTINEL
# convention: no checkpoint has ever advanced this pointer.
GENESIS_SENTINEL = 'GENESIS'
_POINTER_FIELDS = {
    'schema', 'lineage_checkpoint_manifest_sha256', 'hour_result_path',
    'hour_result_sha256', 'published_at', 'seeded_reason',
}
LOCK_SUFFIX = '.lock'
LOCK_TIMEOUT_SECONDS = 60.0
# Files a writer of this directory stages and renames (_write_pointer_atomically here, write_pending_continuation in pending_continuation.py).
# 'next-segment.json' is pending_continuation.FILENAME; a test compares the two so they cannot drift.
STAGED_BASE_NAMES = (POINTER_FILENAME, CANDIDATE_FILENAME, 'next-segment.json')
_STAGED_NAME = re.compile(r'^\.(?P<base>.+)\.(?P<pid>[0-9]+)\.(?P<token>[0-9a-f]{32})\.tmp$')
_SELF_DIR = Path(__file__).resolve().parent


class StaleParentError(ValueError):
    """The caller's declared parent no longer matches the pointer's current value -- a newer
    continuation head has already been selected since this run's parent was resolved."""


def _import_siblings(repo_root: Path):
    """Import the two existing authorities this pointer reuses.

    checkpoint_artifacts and durable_io are same-directory siblings, imported as plain top-level
    modules after this directory is on sys.path -- the same convention update_current_subject.py
    and training_continuity_ledger.py already use for their own sibling imports.

    update_current_subject.py is DELIBERATELY NOT loaded here. An earlier revision of this
    function loaded it by path (spec_from_file_location + exec) and executed its module top
    level, but nothing from the resulting module was ever called -- StaleParentError below is
    this module's own, independent exception type, not a reuse of update_current_subject's. That
    made the load an unowned side effect (running governance's script top level on every hour
    publication for no reason) and made the module docstring's "imported, never reimplemented"
    claim false for the CAS mechanism, which this module implements itself. The compare-and-swap
    pattern below mirrors update_current_subject.update_current_subject's; it is not called from
    it.
    """
    repo_root = Path(repo_root)
    for extra in (str(_SELF_DIR), str(repo_root)):
        if extra not in sys.path:
            sys.path.insert(0, extra)
    import checkpoint_artifacts  # noqa: E402
    import durable_io  # noqa: E402
    return checkpoint_artifacts, durable_io


def pointer_path(receipts_root: Path) -> Path:
    return Path(receipts_root) / POINTER_FILENAME


_ERROR_INVALID_PARAMETER = 87    # OpenProcess for a pid that does not exist
_STILL_ACTIVE = 259


def _windows_pid_state(pid: int, kernel32: Any, last_error: Callable[[], int], c_ulong: Any = None, byref: Any = None, c_void_p: Any = None) -> str:
    """'dead' only when Windows PROVES the process is gone (no such pid, or an exit code other than STILL_ACTIVE); 'alive' when it is running;
    'unknown' when it cannot be inspected (access denied, a failing exit-code query). Only 'dead' lets the sweep delete a staged file."""
    import ctypes
    c_ulong, byref, c_void_p = c_ulong or ctypes.c_ulong, byref or ctypes.byref, c_void_p or ctypes.c_void_p
    handle = kernel32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return 'dead' if last_error() == _ERROR_INVALID_PARAMETER else 'unknown'
    try:
        code = c_ulong()
        if not kernel32.GetExitCodeProcess(c_void_p(handle), byref(code)):
            return 'unknown'
        return 'alive' if code.value == _STILL_ACTIVE else 'dead'
    finally:
        kernel32.CloseHandle(c_void_p(handle))


def _pid_alive(pid: int) -> bool:
    """False only when the writer is PROVEN gone; an uninspectable process counts as alive so its staged file is retained."""
    if pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        return _windows_pid_state(pid, kernel32, ctypes.get_last_error) != 'dead'
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def sweep_stale_staging(directory: Path) -> list[str]:
    """Remove the staged temp files a CRASHED writer of this directory left behind (issue #2119 row 6b).

    A writer that dies inside the publish never reaches its `finally`, so `.<base>.<pid>.<token>.tmp` stays. Only a file matching this module's own
    staging pattern, whose base is one of STAGED_BASE_NAMES and whose writer pid is no longer alive, is removed; a live writer's staged file, the
    sweeper's own pid, and any other name are left alone. Returns the names removed. Called under the pointer lock by every writer."""
    removed: list[str] = []
    try:
        names = os.listdir(directory)
    except OSError:
        return removed
    for name in names:
        match = _STAGED_NAME.match(name)
        if match is None or match.group('base') not in STAGED_BASE_NAMES:
            continue
        pid = int(match.group('pid'))
        if pid == os.getpid() or _pid_alive(pid):
            continue
        try:
            os.unlink(Path(directory) / name)
            removed.append(name)
        except OSError:
            pass
    return sorted(removed)


@contextlib.contextmanager
def _pointer_lock(target_path: Path, timeout: float = LOCK_TIMEOUT_SECONDS):
    """Hold an OS-level exclusive lock on a sibling lock file for the WHOLE read-compare-replace.

    atomic_replace_durable protects only the write; two writers that both read the same current
    value would each pass the compare and the second replace would overwrite the newer head. The
    lock serialises every advance and seed, so the compare re-reads under it. The OS releases the
    byte-range lock when its holder dies, so a leftover file with no holder never blocks (probed by
    attempting the lock, not by existence). Row 6b: under the lock every writer first sweeps the
    staged temp files a crashed writer left (sweep_stale_staging), and on Windows removes the idle
    lock file once released, so a crash during publish followed by the next writer leaves nothing
    but the pointer (and the pending record).
    """
    lock_path = target_path.parent / (target_path.name + LOCK_SUFFIX)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with open(lock_path, 'a+b') as handle:
        if os.name == 'nt':
            import msvcrt

            def acquire():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

            def release():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def acquire():
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            def release():
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        while True:
            try:
                acquire()
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f'could not lock {lock_path} within {timeout} s')
                time.sleep(0.02)
        try:
            sweep_stale_staging(target_path.parent)
            yield
        finally:
            release()
    if os.name == 'nt':
        # Nobody holds it now. Windows refuses to delete a file another process has open, so a writer that opened it a moment ago keeps it;
        # on POSIX an unlink would race a waiting flock, so there the persistent file stays.
        try:
            os.unlink(lock_path)
        except OSError:
            pass


def load_selected_continuation_head(path: Path) -> dict[str, Any]:
    """Read and closed-schema-validate the pointer. Every field is checked -- the caller's own
    claim about the file's contents is never trusted, matching gen_readme_status.load_current_
    subject's discipline for the sibling authority this reuses the pattern from."""
    return parse_selected_continuation_head(Path(path).read_bytes())


def parse_selected_continuation_head(raw: bytes) -> dict[str, Any]:
    """The same closed-schema validation over bytes the caller already read, so one load can bind every later read to ONE generation of the pointer."""
    payload = json.loads(raw.decode('utf-8'))
    if not isinstance(payload, dict) or set(payload) != _POINTER_FIELDS:
        raise ValueError('selected continuation head fields are not closed')
    if payload.get('schema') != SCHEMA:
        raise ValueError(f'selected continuation head schema must be {SCHEMA!r}')
    sha = payload.get('lineage_checkpoint_manifest_sha256')
    if not isinstance(sha, str) or len(sha) != 64:
        raise ValueError('selected continuation head manifest sha256 must be a sha256 hex string')
    if not isinstance(payload.get('hour_result_path'), str) or not payload['hour_result_path']:
        raise ValueError('selected continuation head hour_result_path must be non-empty')
    hour_sha = payload.get('hour_result_sha256')
    if not isinstance(hour_sha, str) or len(hour_sha) != 64:
        raise ValueError('selected continuation head hour_result_sha256 must be a sha256 hex string')
    if not isinstance(payload.get('published_at'), (int, float)) or isinstance(payload.get('published_at'), bool):
        raise ValueError('selected continuation head published_at must be numeric')
    # Empty for a pointer advanced by advance_selected_continuation_head after a verified
    # publication; non-empty only for a pointer written by seed_selected_continuation_head, so a
    # seeded head (a lineage continued from history that predates this pointer) is distinguishable
    # from one this module itself advanced.
    if not isinstance(payload.get('seeded_reason'), str):
        raise ValueError('selected continuation head seeded_reason must be a string')
    return payload


def current_head_sha256(receipts_root: Path) -> str:
    """The lineage key a fresh dispatch should treat as its parent, or GENESIS_SENTINEL when
    nothing has ever advanced this pointer."""
    path = pointer_path(receipts_root)
    if not path.is_file():
        return GENESIS_SENTINEL
    return load_selected_continuation_head(path)['lineage_checkpoint_manifest_sha256']


def advance_selected_continuation_head(
    *, repo_root: Path, receipts_root: Path, published_checkpoint_root: Path,
    hour_result_path: Path, hour_result_sha256: str,
    expected_parent_checkpoint_manifest_sha256: str, now: float | None = None,
) -> dict[str, Any]:
    """Atomically advance the pointer after VERIFIED PUBLICATION.

    Three mechanisms, in order, mirroring update_current_subject.update_current_subject's own
    (implemented independently here -- see _import_siblings' docstring):
    (1) the published checkpoint reopens and its digest re-derives from disk -- the caller's own
    belief about the digest is never trusted; (2) compare-and-swap -- the caller's declared
    parent must equal the pointer's current value or this raises StaleParentError before
    touching disk (a fork from an older head cannot overwrite a newer one); (3) the candidate is
    written to a temp file, round-trip validated through load_selected_continuation_head, and
    only then atomically replaced (durable_io.atomic_replace_durable) -- a candidate that would
    fail validation is refused pre-write and the target file is provably unchanged.

    Raises StaleParentError (mechanism 2) or ValueError (mechanism 3's validation) and leaves the
    pointer file untouched on any refusal.
    """
    repo_root = Path(repo_root)
    receipts_root = Path(receipts_root)
    checkpoint_artifacts, durable_io = _import_siblings(repo_root)

    # Mechanism 1: never trust the caller -- re-derive from the published checkpoint's own bytes.
    receipt = checkpoint_artifacts.published_checkpoint_receipt(Path(published_checkpoint_root))
    computed_sha256 = receipt['checkpoint_manifest_sha256']

    target_path = pointer_path(receipts_root)
    # Mechanism 2: the compare-and-swap read and the stale-parent refusal run, with the write,
    # under one lock so the digest compared is the digest replaced.
    with _pointer_lock(target_path):
        if target_path.is_file():
            current_sha256 = load_selected_continuation_head(target_path)['lineage_checkpoint_manifest_sha256']
        else:
            current_sha256 = GENESIS_SENTINEL
        if expected_parent_checkpoint_manifest_sha256 != current_sha256:
            raise StaleParentError(
                'stale parent: expected the selected continuation head to be '
                f'{expected_parent_checkpoint_manifest_sha256!r}, but it is {current_sha256!r} -- '
                'a newer continuation head has already been selected since this run\'s parent was '
                'resolved'
            )

        candidate = {
            'schema': SCHEMA,
            'lineage_checkpoint_manifest_sha256': computed_sha256,
            'hour_result_path': str(hour_result_path),
            'hour_result_sha256': hour_result_sha256,
            'published_at': time.time() if now is None else now,
            'seeded_reason': '',
        }
        _write_pointer_atomically(target_path, candidate, durable_io)
    return candidate


def candidate_path(receipts_root: Path) -> Path:
    return Path(receipts_root) / CANDIDATE_FILENAME


def load_candidate_continuation_head(path: Path) -> dict[str, Any]:
    """Closed-schema read of the candidate pointer; the selected-head loader never accepts it
    (different schema and field set), so a candidate can never be read as a selected head."""
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(payload, dict) or set(payload) != _CANDIDATE_FIELDS:
        raise ValueError('candidate continuation head fields are not closed')
    if payload.get('schema') != CANDIDATE_SCHEMA:
        raise ValueError(f'candidate continuation head schema must be {CANDIDATE_SCHEMA!r}')
    for key in ('candidate_checkpoint_manifest_sha256', 'hour_result_sha256'):
        if not isinstance(payload.get(key), str) or len(payload[key]) != 64:
            raise ValueError(f'candidate continuation head {key} must be a sha256 hex string')
    parent = payload.get('parent_checkpoint_manifest_sha256')
    if not isinstance(parent, str) or not (parent == GENESIS_SENTINEL or len(parent) == 64):
        raise ValueError('candidate continuation head parent must be a sha256 hex string or GENESIS')
    if not isinstance(payload.get('hour_result_path'), str) or not payload['hour_result_path']:
        raise ValueError('candidate continuation head hour_result_path must be non-empty')
    if not isinstance(payload.get('published_at'), (int, float)) or isinstance(payload.get('published_at'), bool):
        raise ValueError('candidate continuation head published_at must be numeric')
    return payload


def publish_candidate_continuation_head(
    *, repo_root: Path, receipts_root: Path, published_checkpoint_root: Path,
    hour_result_path: Path, hour_result_sha256: str,
    expected_parent_checkpoint_manifest_sha256: str, now: float | None = None,
) -> dict[str, Any]:
    """After VERIFIED PUBLICATION, record the hour's child as a CANDIDATE only. Never reads or
    writes selected-continuation-head.json: the selected head is moved solely by
    advance_selected_continuation_head under an operator ruling on the frozen score.

    Mechanism 1 (re-derive the digest from the published checkpoint's bytes) and mechanism 3
    (staged, round-trip-validated, atomic replace) are the same as the advance path. There is no
    compare-and-swap against the candidate file: a newer hour overwrites an older candidate, and
    the declared parent is recorded so the promotion step can CAS against the selected head."""
    repo_root = Path(repo_root)
    receipts_root = Path(receipts_root)
    checkpoint_artifacts, durable_io = _import_siblings(repo_root)
    receipt = checkpoint_artifacts.published_checkpoint_receipt(Path(published_checkpoint_root))
    candidate = {
        'schema': CANDIDATE_SCHEMA,
        'candidate_checkpoint_manifest_sha256': receipt['checkpoint_manifest_sha256'],
        'parent_checkpoint_manifest_sha256': expected_parent_checkpoint_manifest_sha256,
        'hour_result_path': str(hour_result_path),
        'hour_result_sha256': hour_result_sha256,
        'published_at': time.time() if now is None else now,
    }
    _write_pointer_atomically(candidate_path(receipts_root), candidate, durable_io, loader=load_candidate_continuation_head)
    return candidate


def seed_selected_continuation_head(
    *, repo_root: Path, receipts_root: Path, published_checkpoint_root: Path,
    hour_result_path: Path, hour_result_sha256: str, reason: str, now: float | None = None,
) -> dict[str, Any]:
    """Seed the pointer from an EXISTING, already-published checkpoint, when the pointer has
    never been written and the live lineage nonetheless already has trained history that predates
    this module (issue #2119 s5 REDO: the bootstrap must not silently restart a real lineage from
    genesis).

    Legal ONLY while the pointer is absent -- a compare-and-swap with expected=GENESIS_SENTINEL,
    exactly like advance_selected_continuation_head's own CAS but refusing the moment a pointer
    already exists, since seeding is a one-time act and every later advance goes through
    advance_selected_continuation_head instead. `reason` is REQUIRED non-empty and is recorded
    verbatim as the written pointer's seeded_reason, so a seeded head is distinguishable from one
    this module advanced after a verified publication (whose seeded_reason is always '').

    Reuses mechanism 1 (re-derive the digest from the published checkpoint's own bytes, never
    trust the caller) and mechanism 3 (staged, round-trip-validated, atomic replace) from
    advance_selected_continuation_head -- only the compare-and-swap expectation differs.

    Raises StaleParentError if a pointer already exists (seeding is refused, not a merge) or
    ValueError (empty reason, or mechanism 3's validation) and leaves the pointer file untouched
    on any refusal.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('seed reason must be a non-empty string')
    repo_root = Path(repo_root)
    receipts_root = Path(receipts_root)
    checkpoint_artifacts, durable_io = _import_siblings(repo_root)

    # Mechanism 1: never trust the caller -- re-derive from the published checkpoint's own bytes.
    receipt = checkpoint_artifacts.published_checkpoint_receipt(Path(published_checkpoint_root))
    computed_sha256 = receipt['checkpoint_manifest_sha256']

    target_path = pointer_path(receipts_root)
    # Compare-and-swap: seeding is legal only from GENESIS. A pointer that already exists (even
    # one this same function seeded a moment ago) refuses -- seeding never overwrites.
    with _pointer_lock(target_path):
        if target_path.is_file():
            raise StaleParentError(
                'cannot seed the selected continuation head: a pointer already exists at '
                f'{target_path} -- seeding is a one-time act for an absent pointer; use '
                'advance_selected_continuation_head for every subsequent publication'
            )

        candidate = {
            'schema': SCHEMA,
            'lineage_checkpoint_manifest_sha256': computed_sha256,
            'hour_result_path': str(hour_result_path),
            'hour_result_sha256': hour_result_sha256,
            'published_at': time.time() if now is None else now,
            'seeded_reason': reason,
        }
        _write_pointer_atomically(target_path, candidate, durable_io)
    return candidate


def _write_pointer_atomically(target_path: Path, candidate: dict[str, Any], durable_io, loader=None) -> None:
    """Mechanism 3, shared by advance and seed: pre-write round-trip validation, then the one
    disk mutation. The temp file sits beside the target (same directory, same volume) so
    atomic_replace_durable's MoveFileExW/os.replace boundary is the only concurrency primitive in
    play."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    staged_path = target_path.parent / f'.{target_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp'
    payload_bytes = (json.dumps(candidate, indent=2, sort_keys=True) + '\n').encode('utf-8')
    try:
        with open(staged_path, 'xb') as handle:
            handle.write(payload_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        # Raises and leaves the target untouched if the candidate would fail validation.
        (loader or load_selected_continuation_head)(staged_path)
        durable_io.atomic_replace_durable(staged_path, target_path)
    finally:
        try:
            staged_path.unlink()
        except FileNotFoundError:
            pass


def _cli_seed(args: argparse.Namespace) -> int:
    repo_root = args.root.resolve(strict=True)
    receipts_root = args.receipts_root.resolve()
    checkpoint_root = args.checkpoint.resolve(strict=True)
    hour_result_path = args.hour_result.resolve(strict=True)
    # hour_result_sha256 is a caller-supplied provenance pointer, not re-derived internally by
    # seed_selected_continuation_head (the same design as advance_selected_continuation_head's
    # identical parameter) -- computed here with the plain streaming-sha256-of-bytes convention
    # every digest in this tool family already uses.
    hour_result_sha256 = hashlib.sha256(hour_result_path.read_bytes()).hexdigest()
    candidate = seed_selected_continuation_head(
        repo_root=repo_root, receipts_root=receipts_root,
        published_checkpoint_root=checkpoint_root, hour_result_path=hour_result_path,
        hour_result_sha256=hour_result_sha256, reason=args.reason)
    print(json.dumps(candidate, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Issue #2119 section 5: the durable selected-continuation-head pointer.')
    subparsers = parser.add_subparsers(dest='command', required=True)

    seed_parser = subparsers.add_parser(
        'seed',
        help='seed the pointer from an existing, already-published checkpoint -- legal only '
             'while the pointer has never been written (a lineage with trained history that '
             'predates this pointer is never silently restarted from genesis)')
    seed_parser.add_argument('--root', required=True, type=Path, help='ember repository root')
    seed_parser.add_argument('--receipts-root', required=True, type=Path,
                              help='host-wide receipts root (training_continuity_ledger.ledger_root)')
    seed_parser.add_argument('--checkpoint', required=True, type=Path,
                              help='published checkpoint root (contains checkpoint-manifest.json)')
    seed_parser.add_argument('--hour-result', required=True, type=Path,
                              help='the hour-result.json this checkpoint was published by')
    seed_parser.add_argument('--reason', required=True,
                              help='non-empty: why this pointer is being seeded rather than advanced')
    seed_parser.set_defaults(func=_cli_seed)

    parsed = parser.parse_args(argv)
    return parsed.func(parsed)


if __name__ == '__main__':
    sys.exit(main())
