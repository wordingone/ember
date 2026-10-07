"""Issue #2119 sections 3 and 6: a durable diagnostic-allowance ledger and its readers.

Every CIA GPU dispatch declares a `training_job_purpose` (validated by
`certified_train_launch.py`'s shared `_validate_training_job_purpose`, imported rather than
duplicated -- see `cia_step_runner.load_purpose_module`). This module tracks how much of that
declared purpose set has been spent WITHOUT retained-training advancement, so a diagnostic or
failed-experiment lane cannot indefinitely postpone the training the operator actually wants.

The ledger is an append-only JSONL file with fsync, one file per custody parent (the same
directory `cia_step_runner.launch` receives as `--custody`, i.e. the directory that holds every
`measurement-<run_id>` custody launched against one lineage). It never keys rows by issue,
session, branch, or job name -- only by the lineage's checkpoint identity, so a rename or a
new dispatch cannot manufacture allowance. It resets implicitly: once a CONTINUE_TRAINING job
publishes a descendant, that descendant's manifest sha256 becomes the new lineage key, and no
row keyed to the OLD lineage counts toward it. Old rows are kept for audit, never deleted.

The only other way past the limit is an explicit operator-extension row carrying an authority
reference (`record_operator_extension`); nothing here can grant one to itself.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from durable_io import fsync_parent_directory

SCHEMA = 'ember-diagnostic-allowance-ledger-v1'
POLICY_SCHEMA = 'ember-training-continuity-policy-v1'
# Matches update_current_subject.py's GENESIS_SENTINEL convention: a lineage with no admitted
# parent checkpoint yet (first-ever dispatch against this repository) is not a missing key, it
# is the one value every reader already treats as the bootstrap case.
GENESIS_SENTINEL = 'GENESIS'
LEDGER_FILENAME = 'diagnostic-allowance-ledger.jsonl'
POLICY_FILENAME = 'training_continuity_policy.json'
# This module's own directory, at the same depth cia_step_runner.py computes its ROOT from
# (src/ember/infrastructure/tools/ember-restart-3b/<file>.py) -- used only as the default
# repo_root for selected_continuation_head_sha256 below.
_MODULE_ROOT = Path(__file__).resolve().parents[5]
CURRENT_SUBJECT_RELATIVE_PATH = Path('manifests') / 'ember-current-subject-v1.json'
# issue #2119 REDO finding: keying the ledger to a dispatch's --custody parent reset the
# allowance to zero on every #1945 dispatch, because each dispatch mints a fresh timestamped
# parent directory. The ledger therefore lives one level ABOVE the custody parent, in the
# host-wide receipts root every dispatch parent is minted under, so relabeling or restarting a
# job never resets the count -- issue #2119 section 3's binding requirement. The root is derived
# from the custody path the dispatch already receives, never written into source as a drive path.
# Overridable via env for test isolation only.
LEDGER_ROOT_ENV = 'EMBER_TRAINING_CONTINUITY_LEDGER_ROOT'


def ledger_root(custody_parent: Path | None = None) -> Path:
    """The one host-wide directory the durable ledger file lives under: the receipts root that
    contains every dispatch's --custody parent. See LEDGER_ROOT_ENV above."""
    override = os.environ.get(LEDGER_ROOT_ENV, '').strip()
    if override:
        return Path(override)
    if custody_parent is None:
        raise ValueError('training continuity ledger root needs the dispatch custody parent '
                         f'or {LEDGER_ROOT_ENV}')
    return Path(custody_parent).resolve().parent
DEFAULT_POLICY = {
    'schema': POLICY_SCHEMA,
    'max_diagnostic_occupancy_seconds': 4 * 3600,
    'max_postponement_seconds': 6 * 3600,
    'max_blocker_renewals': 2,
}
_RESERVATION_PURPOSES = {'DIAGNOSTIC'}


def default_policy_path() -> Path:
    return Path(__file__).resolve().parent / POLICY_FILENAME


def load_policy(path: Path | None = None) -> dict[str, Any]:
    """Read the scheduling-policy limits, or the shipped defaults if no file is present.

    The file is repo-tracked scheduling policy (like a config constant), not run state -- it
    never lives beside the ledger's own JSONL, and it is never written by this module.
    """
    path = default_policy_path() if path is None else Path(path)
    if not path.is_file():
        return dict(DEFAULT_POLICY)
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict) or payload.get('schema') != POLICY_SCHEMA:
        raise ValueError('training continuity policy schema differs')
    required = {'max_diagnostic_occupancy_seconds', 'max_postponement_seconds', 'max_blocker_renewals'}
    if not required <= set(payload):
        raise ValueError('training continuity policy is missing a required limit')
    for key in required:
        if not isinstance(payload[key], int) or payload[key] < 0:
            raise ValueError(f'training continuity policy {key} must be a nonnegative integer')
    return payload


def _bound_read(path: Path, digest: str) -> dict[str, Any]:
    """Read one small JSON file and require its bytes to match the declared sha256.

    A local primitive rather than cia_hour.bound_json: that function takes a `runner` object
    (cia_step_runner itself, self-passed) purely for its file_sha256/checked_sha/GIB helpers.
    Reusing it here would mean fabricating a fake runner just to satisfy an unrelated calling
    convention. This is the same well-known "read and verify" primitive, not a second copy of
    any validation predicate.
    """
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('lineage source artifact changed since it was bound')
    return json.loads(raw)


def _load_gen_readme_status(repo_root: Path):
    """Load gen_readme_status.py directly by path, the same dynamic-load idiom cia_step_runner.py
    uses for its own sibling scripts (spec_from_file_location + exec, not spec.loader.exec_module,
    matching the convention already established for this class of loader in this tool).

    Deliberately NOT update_current_subject._import_siblings(repo_root): that helper also imports
    checkpoint_artifacts.py, which imports torch and src.ember.model.ember_v0_model at module
    scope -- a needless torch dependency for a controller-side lineage-key lookup that runs
    before any model is allocated. gen_readme_status.py itself declares "Stdlib only. No
    network." in its own header, so loading it alone keeps this path torch-free.
    """
    path = Path(repo_root) / 'src/ember/governance/scripts/gen_readme_status.py'
    spec = importlib.util.spec_from_file_location('cia_gen_readme_status', path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def selected_continuation_head_sha256(
    repo_root: Path | None = None, *, current_subject_path: Path | None = None,
) -> str:
    """The lineage key for a dispatch with no checkpoint_probe/continuation reference of its own
    (a diagnostic with nothing to resume from): the repository's existing, durable SELECTED
    continuation-head authority, reused rather than reinvented.

    update_current_subject.py writes this record on every CONTINUE_TRAINING publication;
    gen_readme_status.load_current_subject reads and validates it (closed schema, digest
    re-derivation, authority binding). Before this fix, a diagnostic with no resume reference
    fell through to GENESIS_SENTINEL unconditionally -- so it accrued its occupancy against the
    bootstrap key rather than the lineage actually in flight, and a lineage that had already
    advanced past genesis could never see that diagnostic's spend reflected against it.

    Returns GENESIS_SENTINEL only in the genuine bootstrap case: no current-subject record has
    ever been published (repo_root / manifests/ember-current-subject-v1.json does not exist).
    """
    repo_root = _MODULE_ROOT if repo_root is None else Path(repo_root)
    target = (Path(current_subject_path) if current_subject_path is not None
              else repo_root / CURRENT_SUBJECT_RELATIVE_PATH)
    if not target.is_file():
        return GENESIS_SENTINEL
    module = _load_gen_readme_status(repo_root)
    current = module.load_current_subject(str(target))
    return current['subject']['checkpoint_manifest_sha256']


def lineage_checkpoint_manifest_sha256(
    identity: Mapping[str, Any], *, repo_root: Path | None = None,
    current_subject_path: Path | None = None,
) -> str:
    """The manifest sha256 of the checkpoint this dispatch resumes from, or the current
    selected-continuation-head, or GENESIS_SENTINEL.

    Reads only fields the identity schema already carries and already verifies elsewhere
    (checkpoint_probe / continuation reopen a real prior admitted hour); this extracts a field
    from that same hour-result, it does not introduce a second admission check.

    issue #2119 REDO finding: a dispatch with NEITHER checkpoint_probe NOR continuation (a
    diagnostic with no checkpoint reference, e.g. a measurement pair run against whatever the
    lineage currently is) used to key unconditionally to GENESIS_SENTINEL, accruing its
    occupancy against a lineage that may have advanced long ago. It now falls back to the
    repository's own selected-continuation-head authority (see
    selected_continuation_head_sha256 above), and only reaches GENESIS_SENTINEL when that
    authority itself has never been published.
    """
    probe = identity.get('checkpoint_probe')
    if isinstance(probe, dict) and 'result_sha256' in probe and 'custody_root' in probe:
        root = Path(probe['custody_root'])
        result = _bound_read(root / 'hour-result.json', probe['result_sha256'])
        return _require_child_manifest_sha256(result)
    continuation = identity.get('continuation')
    if isinstance(continuation, dict) and 'source_hour_result_path' in continuation:
        result = _bound_read(Path(continuation['source_hour_result_path']),
                              continuation['source_hour_result_sha256'])
        return _require_child_manifest_sha256(result)
    return selected_continuation_head_sha256(repo_root, current_subject_path=current_subject_path)


def _require_child_manifest_sha256(result: Mapping[str, Any]) -> str:
    """A partial publication (the referenced hour-result exists and matches its own bound
    digest, but never finished recording its child) must not silently advance the counters
    under a missing or fabricated key -- refuse explicitly instead of leaking a KeyError."""
    value = result.get('child_manifest_sha256')
    if not isinstance(value, str) or not value:
        raise ValueError('referenced hour result publication is incomplete: no child_manifest_sha256')
    return value


def ledger_path(custody_parent: Path | None = None) -> Path:
    """The one ledger file shared by every dispatch against this host's lineages, at a fixed
    location independent of any single dispatch's --custody parent.

    `custody_parent` is the dispatch's --custody directory; only its PARENT (the host-wide
    receipts root) locates the ledger, so two dispatches with different parents share one file.

    issue #2119 REDO finding: keying the ledger to the custody parent meant every #1945 dispatch
    (which mints a fresh timestamped parent directory under the receipts root) reset the
    allowance to zero, defeating the whole point of a durable allowance. The durable location is
    ledger_root(custody_parent) (see above), overridable via EMBER_TRAINING_CONTINUITY_LEDGER_ROOT for tests
    only -- production dispatches always resolve to the same file regardless of custody parent.
    """
    return ledger_root(custody_parent) / LEDGER_FILENAME


@contextlib.contextmanager
def exclusive_lock(target: Path, timeout_seconds: float = 30.0):
    """Cross-process exclusive lock keyed to `target` (a sibling `<name>.lock` file). The lock is an OS byte-range/flock lock held on an open
    handle, so it is released when the holder dies: there is no stale-lock state to clean. Raises TimeoutError after `timeout_seconds`."""
    lock_path = Path(target).with_name(Path(target).name + '.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, 'a+b')
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f'could not take the exclusive lock {lock_path} within {timeout_seconds} s') from None
                time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _append_row(path: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(row)
    payload = json.dumps(row, sort_keys=True, separators=(',', ':')).encode('utf-8') + b'\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('ab') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    fsync_parent_directory(path.parent)
    return row


def read_rows(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        return []
    rows = []
    with path.open('r', encoding='utf-8') as stream:
        for line in stream:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _lineage_rows(rows: Sequence[Mapping[str, Any]], lineage_sha: str) -> list[Mapping[str, Any]]:
    return [row for row in rows if row.get('lineage_checkpoint_manifest_sha256') == lineage_sha]


def diagnostic_occupancy_seconds(rows: Sequence[Mapping[str, Any]], lineage_sha: str) -> int:
    """Cumulative non-advancing seconds spent against this lineage: reserved DIAGNOSTIC budgets
    plus RETENTION_ELIGIBLE_EXPERIMENT runs that published no eligible descendant, minus any
    operator-extension credit for the same lineage."""
    total = 0
    for row in _lineage_rows(rows, lineage_sha):
        kind = row.get('row_kind')
        if kind == 'reservation' and row.get('training_job_purpose') in _RESERVATION_PURPOSES:
            total += int(row.get('budget_seconds', 0))
        elif kind == 'retention_experiment_outcome' and row.get('eligible_descendant_published') is False:
            total += int(row.get('occupancy_seconds', 0))
        elif kind == 'operator_extension':
            total -= int(row.get('extension_seconds', 0))
    return max(total, 0)


def postponement_seconds(rows: Sequence[Mapping[str, Any]], lineage_sha: str, *, now: float | None = None) -> int:
    """Wall-clock time since this lineage's first ledger row (i.e. since the last retained
    advancement that established this checkpoint as the lineage key), minus any extension
    credit. Zero when nothing has been ledgered against this lineage yet."""
    lineage_rows = _lineage_rows(rows, lineage_sha)
    if not lineage_rows:
        return 0
    now = time.time() if now is None else now
    earliest = min(float(row['ts']) for row in lineage_rows)
    extension = sum(int(row.get('extension_seconds', 0)) for row in lineage_rows
                     if row.get('row_kind') == 'operator_extension')
    return max(int(now - earliest) - extension, 0)


def _blocker_occurrences(rows: Sequence[Mapping[str, Any]], lineage_sha: str, blocker: str) -> int:
    return sum(1 for row in _lineage_rows(rows, lineage_sha)
               if row.get('row_kind') == 'reservation' and row.get('readiness_blocker') == blocker)


def reserve_diagnostic_dispatch(
    *, path: Path, lineage_sha: str, run_id: str, budget_seconds: int,
    diagnostic_question: str, non_advancement_reason: str, return_condition: str,
    readiness_blocker: str | None = None, policy: Mapping[str, Any] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Reserve a DIAGNOSTIC dispatch's declared budget BEFORE launch. Refuses (ValueError) once
    the lineage is at its occupancy or postponement limit unless a readiness blocker is named,
    and refuses even then once that exact blocker has already renewed its bounded number of
    times (occurrences <= max_blocker_renewals: the first use is the initial grant, each repeat
    is one renewal)."""
    if budget_seconds < 0:
        raise ValueError('diagnostic budget_seconds must be nonnegative')
    policy = load_policy() if policy is None else policy
    now = time.time() if now is None else now
    rows = read_rows(path)
    occupancy_before = diagnostic_occupancy_seconds(rows, lineage_sha)
    postponement_before = postponement_seconds(rows, lineage_sha, now=now)
    over_occupancy = occupancy_before + budget_seconds > policy['max_diagnostic_occupancy_seconds']
    over_postponement = postponement_before > policy['max_postponement_seconds']
    if over_occupancy or over_postponement:
        if not readiness_blocker:
            reason = 'occupancy' if over_occupancy else 'postponement'
            raise ValueError(
                f'diagnostic allowance exhausted ({reason}) for lineage {lineage_sha}; '
                'a readiness blocker is required to renew it')
        occurrences = _blocker_occurrences(rows, lineage_sha, readiness_blocker)
        if occurrences > policy['max_blocker_renewals']:
            raise ValueError(
                f'readiness blocker {readiness_blocker!r} has exhausted its renewals for lineage {lineage_sha}')
    row = {
        'schema': SCHEMA, 'row_kind': 'reservation', 'ts': now, 'run_id': run_id,
        'training_job_purpose': 'DIAGNOSTIC', 'lineage_checkpoint_manifest_sha256': lineage_sha,
        'budget_seconds': int(budget_seconds), 'diagnostic_question': diagnostic_question,
        'non_advancement_reason': non_advancement_reason, 'return_condition': return_condition,
        'readiness_blocker': readiness_blocker,
    }
    return _append_row(path, row)


def record_retention_experiment_outcome(
    *, path: Path, lineage_sha: str, run_id: str, eligible_descendant_published: bool,
    elapsed_seconds: int = 0, now: float | None = None, finalization_delay_seconds: int = 0,
) -> dict[str, Any] | None:
    """Record a RETENTION_ELIGIBLE_EXPERIMENT that published NO eligible descendant, so its
    elapsed time counts toward the lineage's occupancy the same way a diagnostic budget does.
    A no-op (returns None, appends nothing) when the experiment DID publish -- that case is
    tracked by update_current_subject.py's own lineage advance, not by this ledger.

    Idempotent by (lineage, run_id) (review 63367 P1-3): under the ledger's OS lock, a second call for the same run finds the row it
    already appended and returns it without appending, so a retry after a failed marker write never charges the occupancy twice
    and two competing callers cannot both append."""
    if eligible_descendant_published:
        return None
    now = time.time() if now is None else now
    row = {
        'schema': SCHEMA, 'row_kind': 'retention_experiment_outcome', 'ts': now, 'run_id': run_id,
        'training_job_purpose': 'RETENTION_ELIGIBLE_EXPERIMENT',
        'lineage_checkpoint_manifest_sha256': lineage_sha,
        'eligible_descendant_published': False, 'occupancy_seconds': int(elapsed_seconds),
        # delay between run completion and this finalization (scoring/review wait): its own field, never added to occupancy (review 63986 R1)
        'finalization_delay_seconds': max(int(finalization_delay_seconds), 0),
    }
    path = Path(path)
    with exclusive_lock(path):
        for existing in read_rows(path):
            if (existing.get('row_kind') == 'retention_experiment_outcome' and existing.get('run_id') == run_id
                    and existing.get('lineage_checkpoint_manifest_sha256') == lineage_sha):
                return existing
        return _append_row(path, row)


def record_operator_extension(
    *, path: Path, lineage_sha: str, authority_reference: str, extension_seconds: int = 0,
    now: float | None = None,
) -> dict[str, Any]:
    """An explicit, attributable extension of the lineage's allowance. Never self-granted by
    a dispatch -- the caller is the operator interface, and authority_reference is required
    non-empty so a blank extension can never appear in the ledger."""
    if not authority_reference:
        raise ValueError('operator extension requires a non-empty authority reference')
    if extension_seconds < 0:
        raise ValueError('operator extension_seconds must be nonnegative')
    now = time.time() if now is None else now
    row = {
        'schema': SCHEMA, 'row_kind': 'operator_extension', 'ts': now,
        'lineage_checkpoint_manifest_sha256': lineage_sha,
        'authority_reference': authority_reference, 'extension_seconds': int(extension_seconds),
    }
    return _append_row(Path(path), row)
