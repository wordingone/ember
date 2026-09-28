#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1945 terminal acceptance: the consumer that was missing, with TWO statistics, never one.

PORTED INTO EMBER SOURCE (2026-09-14). This file previously lived in the operating seat's own
tooling tree. #1945's gate B was audited as NOT RULABLE on two independent grounds, and the first
of them was that no consumer IN THE REPOSITORY reads the hour result's p10 -- which stayed true
however good the consumer outside it was. A censuses of src/ at the ported head finds
`complete_step_p10_positions_per_second` in exactly one place, cia_hour.py, the line that WRITES
it. This file is the reader. Its behaviour is unchanged by the move; what changed is that the
repository now contains it, its gates now run against it, and a fresh checkout can execute it.

Placement note: this is a governance acceptance consumer and binds EMBER-02A. The producer,
cia_hour.py, binds EMBER-02B under the path-prefix workstream partition, so the two cannot live in
one change; this file reads the producer's emitted JSON and imports nothing from it, which is what
makes the split lawful rather than merely convenient.

WHY THIS EXISTS. Censusing the source for the 80,000 consumer found the terminal had no executable
form: `complete_step_p10_positions_per_second` is written and read nowhere, `hour_complete` is a
duration-and-count test with no rate term, and the string 80,000 is not a threshold under src/ at
all. An arm producing 80,000 would have had nothing to rule on it.

TWO STATISTICS, never substituted (the counterpart seat's 37643): a high measured-step p10 combined
with slow I/O can still violate the governed-hour throughput. So

  WARMED STEP   nearest-rank p10 over >= 1,024 measured complete updates, strictly > 80,000
  GOVERNED HOUR measured positions / governed wall seconds, checkpoint write and restore
                verification INSIDE the wall, over a measured stretch of >= 3,600 s, strictly > 80,000

REVISION 2 (2026-09-13 08:35 PM LA) -- FOUR DEFECTS, all found by the counterpart seat (37650) with
a bounded CPU reproducer, all reproduced or confirmed at source before repair. Recorded here rather
than in a changelog because each one is a rule about how this kind of consumer goes wrong.

1. THE ACCOUNTING INEQUALITY WAS BACKWARDS, AND ITS TOLERANCE WAS INVENTED. Revision 1 required the
   phase sum to be at least the governed wall, and allowed it to exceed by `max(60 s, 1%)`. At
   717cf the producer captures `restore_finished = perf_counter()` as its own statement, THEN
   rechecks every source digest, THEN takes `governed_wall`. The three phases therefore telescope
   exactly to `restore_finished - started`, which PRECEDES the wall reading, so the true relation is
   `sum <= governed_wall` and the realistic endpoint (3600 / 5 / 1 against a 3606.1 wall) was being
   refused. Two lessons, and the second is the larger: my first re-read said the counterpart seat had
   the direction backwards, because I read the worktree at commit 514a212f, where the field is a
   lazily-evaluated `perf_counter()` inside the result dict and the sign genuinely is the other way.
   A stale worktree is a different program. And a tolerance whose size the author picks is a check
   that cannot fail: 60 seconds of unaccounted time inside a 3,600 second hour is 1.7% of the whole
   measurement, admitted by a constant nobody derived.

2. COMPOSED ACCEPTANCE WAS SET FROM THROUGHPUT. Revision 1 accepted any three existing files as the
   numerical, Evaluation and custody evidence -- they were not even required to be JSON -- and then
   assigned `composed_acceptance.met = throughput_met` and reported status ACCEPTED. The staging
   disclaimer in the receipt did not repair that, and the reason is worth stating exactly: a
   disclaimer changes who may rely on a verdict, never what the verdict says. Composed acceptance is
   now NOT_ESTABLISHED and false until each authority's own artifact is consumed AND binds to this
   run, and ACCEPTED is unreachable without it.

3. THE ROWS WERE TRUSTED TO AUDIT THEMSELVES. Revision 1 read `row['positions_per_second']` and never
   recomputed it, never checked that a row belonged to this run, and never checked the row ordering.
   The counterpart seat's fixture -- 72,000 rows each with applied 0, wall 100, a foreign run_id and
   a declared rate of 90,000 -- produced a MET verdict on both statistics. That is the same defect
   this seat has a written rule about one layer over: the producer's own field cannot audit the
   producer, exactly as a stub cannot audit the interface it was written from.

4. `int()` TRUNCATION ADMITTED A NON-INTEGER COUNT. `measured_updates = 72000.5` passed. The producer
   itself is stricter -- `hour_complete` refuses on `type(measured_updates) is not int` -- so the
   consumer was weaker than the artifact it judges.

REVISION 3 (2026-09-13 08:55 PM LA) -- two compatibility findings from the counterpart seat's
replay of revision 2 against the ACTUAL 717cf producer expression (37660). Its six accounting cases
passed; these two did not.

5. AN ABSENT INPUT DIGEST DISABLED A CHECK INSTEAD OF FAILING ONE. `load_rows` compared each row's
   `input_sha256` to `input_binding.input_sha256` under `if bound_input is not None`, so deleting the
   field from the hour result removed the comparison and the hour still reached THROUGHPUT_MET. The
   digest is now read ONCE, before any row, and its absence refuses at
   `input:input-digest-not-bound`. This is defect 3 of revision 1 in a new place -- a missing field
   must never make a gate weaker -- and the guard that hid it is the same shape as a check that
   cannot change state.

6. THE EVIDENCE BINDING COULD NOT TELL TWO CHILDREN OF ONE RUN APART. `EVIDENCE_BINDINGS` held
   run_id and source_commit, which every checkpoint a run writes shares, so an Evaluation receipt
   naming a DIFFERENT `child_manifest_sha256` bound cleanly. Gate D's claim is about a checkpoint,
   so the two checkpoint-bound artifacts now must repeat this hour's child digest back. The learning
   licence does not: its subject is the run's trajectory, not a child manifest, and requiring the
   field there would invent one for a producer whose schema I have not read at its source. That
   remaining leg -- binding each authority's real emit at its own commit -- is exactly what keeps
   composed acceptance NOT_ESTABLISHED, and neither repair here changes that.

STATUS: STAGING, NOT TERMINAL AUTHORITY (the counterpart seat's 37643 ruling, adopted). The
acceptance consumer belongs in the repository beside the existing authority. Nothing this emits is a
certificate, and the receipt says so in its own `authority` field.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hour_evaluation_interface import (                            # noqa: E402
    ARTIFACTS, InterfaceRefusal, bind_artifact, unjoinable)

TERMINAL_POSITIONS_PER_SECOND = 80000.0
MINIMUM_WARMED_UPDATES = 1024            # cia_hour.hour_complete
MINIMUM_GOVERNED_SECONDS = 3600.0        # cia_hour.hour_complete, against pre_checkpoint_wall_seconds
HOUR_SCHEMA = 'ember-cia-hour-result-v1'

# Float roundoff only. NOT a tolerance for unaccounted time: see check_accounting, which discloses
# the residual instead of allowing it. Any constant here that is large enough to hide a real
# discrepancy is the revision-1 defect returning under a smaller number.
ROUNDOFF = 1e-6

# The three phase fields are MANDATORY. Revision 1 summed whichever ones happened to be present,
# so an artifact omitting the checkpoint cost produced a smaller sum that passed more easily --
# a missing field made the check weaker, which is the wrong direction for an absence to move a gate.
PHASE_FIELDS = ('pre_checkpoint_wall_seconds', 'checkpoint_write_seconds',
                'restore_and_verification_seconds')

# Fields every measured row must carry and every measured row must agree with the result on.
ROW_IDENTITY = (('run_id', 'run_id'), ('prediction_sha256', 'prediction_sha256'))

TOKENS = (
    'input:hour-result-absent',
    'input:hour-result-unreadable',
    'input:hour-result-schema-unknown',
    'input:geometry-not-bound',
    # The hour's own input digest is REQUIRED, not optional. Revision 2 read it with a
    # `if bound_input is not None` guard, so deleting `input_binding.input_sha256` removed the
    # check instead of failing it and the hour still reached THROUGHPUT_MET -- the counterpart
    # seat's replay found this. An absent binding must never make a gate weaker; that is the same
    # defect as the missing phase field, one field over.
    'input:input-digest-not-bound',
    'input:rows-absent',
    'input:rows-unreadable',
    'input:rows-digest-mismatch',
    'input:rows-empty',
    'input:rows-measured-count-disagrees',
    'input:rows-row-field-absent',
    'input:rows-row-not-numeric',
    'input:rows-rate-disagrees-with-row',
    'input:rows-identity-differs',
    'input:rows-index-not-contiguous',
    'input:rows-warm-shape-differs',
    'input:rows-applied-positions-differ-from-geometry',
    'custody:binding-field-absent',
    'field:absent',
    'field:not-numeric',
    'field:not-finite',
    'field:negative',
    'field:not-integer',
    'accounting:phase-field-absent',
    'accounting:phases-exceed-governed-wall',
    'accounting:applied-positions-disagree-with-rows',
    'accounting:measured-positions-disagree-with-rows',
    'statistic:recomputed-p10-disagrees-with-emitted',
    'statistic:recomputed-hour-rate-disagrees-with-emitted',
    'evidence:numerical-licence-absent',
    'evidence:evaluation-absent',
    'evidence:custody-absent',
    'evidence:unreadable',
    'evidence:binding-differs',
    # Revision 4. Each of these is a state the old bare-name table could not express, because it
    # assumed every artifact carried the hour's own field names at its top level.
    'evidence:schema-identity-absent',     # the artifact never declares what shape it is
    'evidence:schema-identity-unknown',    # it declares a shape this table was not read against
    'evidence:artifact-field-absent',      # the real path this table read is missing
)


class Refusal(Exception):
    def __init__(self, token: str, detail: str, observed=None, expected=None):
        super().__init__(detail)
        assert token in TOKENS, 'undeclared refusal token %r' % token
        self.token, self.detail = token, detail
        self.observed, self.expected = observed, expected


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path, absent_token: str, unreadable_token: str):
    if not path.is_file():
        raise Refusal(absent_token, 'not a file: %s' % path)
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:                                   # noqa: BLE001 - reported verbatim
        raise Refusal(unreadable_token, '%s: %s' % (type(exc).__name__, exc))


def number(payload: dict, field: str, *, allow_zero: bool = True,
           token_absent: str = 'field:absent') -> float:
    """A present, numeric, finite, non-negative value, or a refusal naming which of the four failed.

    Separate tokens rather than one. Filing an absent field as a malformed one makes a receipt
    mislead line by true line, which this seat has already paid for on another gate.
    """
    if field not in payload:
        raise Refusal(token_absent, 'the hour result carries no %r' % field)
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Refusal('field:not-numeric', '%r is %r' % (field, value))
    if not math.isfinite(value):
        raise Refusal('field:not-finite', '%r is %r' % (field, value))
    if value < 0 or (value == 0 and not allow_zero):
        raise Refusal('field:negative', '%r is %r' % (field, value))
    return float(value)


def exact_count(payload: dict, field: str) -> int:
    """An EXACT integer count.

    `int(72000.5)` is 72000, and revision 1 let that through into both the count comparison and the
    positions arithmetic. The producer's own `hour_complete` refuses `type(measured_updates) is not
    int`, so admitting a fractional count made this consumer weaker than the artifact it judges. A
    float that is exactly integral (72000.0, which is what JSON gives for a whole number written with
    a decimal point) is accepted and converted; anything else refuses.
    """
    if field not in payload:
        raise Refusal('field:absent', 'the hour result carries no %r' % field)
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Refusal('field:not-numeric', '%r is %r' % (field, value))
    if isinstance(value, float):
        if not math.isfinite(value) or value != int(value):
            raise Refusal('field:not-integer',
                          '%r is %r; a count is an exact integer and this predicate does not '
                          'truncate one into range' % (field, value), value, 'an exact integer')
        value = int(value)
    if value < 0:
        raise Refusal('field:negative', '%r is %r' % (field, value))
    return int(value)


def nearest_rank_p10(values: list) -> float:
    """The definition cia_hour.py names, restated ONLY because this tool recomputes it.

    Restating an exact comparison in a second place is a hazard with a standing rule against it, and
    the exception is deliberate: recomputation is worth nothing unless the second computation is
    independent. What must never be duplicated is a comparison whose two sides come from one source.
    """
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.1 * len(ordered)) - 1)]


def positions_per_update(hour: dict) -> int:
    """Derived from the run's own geometry, never the constant 4096.

    `cia_hour.prepare_inputs` builds the input binding from `identity`, which carries the geometry
    verbatim, and the producer computes `positions_per_update = sequence_length * documents_per_step`
    (cia_step_runner.py). Revision 1 hardcoded 4096, which is that product for the current geometry
    and silently wrong for any other -- a consumer that agrees with the producer by coincidence.
    """
    binding = hour.get('input_binding')
    geometry = binding.get('geometry') if isinstance(binding, dict) else None
    if not isinstance(geometry, dict):
        raise Refusal('input:geometry-not-bound',
                      'the hour result carries no input_binding.geometry, so positions per update '
                      'cannot be derived from the run and this predicate will not substitute a '
                      'constant for it')
    try:
        sequence = geometry['sequence_length']
        documents = geometry['documents_per_step']
    except KeyError as exc:
        raise Refusal('input:geometry-not-bound', 'the bound geometry carries no %s' % exc)
    if type(sequence) is not int or type(documents) is not int or sequence <= 0 or documents <= 0:
        raise Refusal('input:geometry-not-bound',
                      'the bound geometry is not two positive integers', [sequence, documents],
                      'positive integers')
    return sequence * documents


def bound_input_digest(hour: dict) -> str:
    """The hour's own input digest, REQUIRED.

    `cia_hour.prepare_inputs` always emits `input_binding.input_sha256`, and every measured row
    carries the same field, so this is the link that says the rows were produced against the input
    the hour declares. Revision 2 read it defensively and skipped the row comparison when it was
    absent, which meant deleting the field DISABLED the check rather than failing it. Read once,
    here, before any row is examined.
    """
    binding = hour.get('input_binding')
    value = binding.get('input_sha256') if isinstance(binding, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise Refusal('input:input-digest-not-bound',
                      'the hour result carries no input_binding.input_sha256, so its rows cannot '
                      'be bound to the input the hour declares', value, 'a digest string')
    return value


def row_number(row: dict, field: str, index) -> float:
    if field not in row:
        raise Refusal('input:rows-row-field-absent',
                      'measured row %r carries no %r' % (index, field))
    value = row[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise Refusal('input:rows-row-not-numeric',
                      'measured row %r has %r = %r' % (index, field, value))
    return float(value)


def load_rows(rows_path: Path, hour: dict, per_update: int) -> dict:
    """Read the hour's own rows, verify the digest, then RECOMPUTE and BIND every measured row.

    Revision 1 filtered by phase and took `positions_per_second` at face value. The counterpart
    seat's fixture -- 72,000 rows, each applied 0, wall 100, a foreign run_id, a declared rate of
    90,000 -- passed both statistics. Every check below exists because that fixture reached a MET
    verdict without it:

      * the rate is recomputed as applied / wall and must equal the declared value;
      * applied positions must equal the run's own positions-per-update, so a row cannot declare a
        rate it did no work to earn;
      * run_id and prediction_sha256 must equal the result's, so rows from another run cannot be
        counted toward this one;
      * indices must run contiguously from 0 with exactly one warm row at index 0, which is the
        shape cia_hour.py produces (`phase='warm' if self.index == 0 else 'measured'`), so a
        truncated, reordered or concatenated file is refused rather than averaged.

    Digest first, because a size or a row count is exactly the field a truncated or concurrently
    rewritten file is most likely to get right by accident.
    """
    bound_input = bound_input_digest(hour)
    if not rows_path.is_file():
        raise Refusal('input:rows-absent', 'not a file: %s' % rows_path)
    expected_digest = hour.get('rows_sha256')
    observed = digest_file(rows_path)
    if expected_digest and observed != expected_digest:
        raise Refusal('input:rows-digest-mismatch',
                      'the rows file is not the one the hour result records', observed,
                      expected_digest)

    rates, indices, warm_indices = [], [], []
    measured_positions = 0
    applied_positions = 0
    try:
        lines = rows_path.read_text(encoding='utf-8').splitlines()
    except Exception as exc:                                   # noqa: BLE001
        raise Refusal('input:rows-unreadable', '%s: %s' % (type(exc).__name__, exc))

    for lineno, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception as exc:                               # noqa: BLE001
            raise Refusal('input:rows-unreadable',
                          'line %d: %s: %s' % (lineno + 1, type(exc).__name__, exc))
        if not isinstance(row, dict):
            raise Refusal('input:rows-unreadable', 'line %d is not an object' % (lineno + 1))

        index = row.get('index')
        if type(index) is not int:
            raise Refusal('input:rows-row-field-absent',
                          'row on line %d carries no integer index' % (lineno + 1))
        indices.append(index)

        applied = row_number(row, 'applied_positions', index)
        applied_positions += applied
        phase = row.get('phase')
        if phase == 'warm':
            warm_indices.append(index)
            continue
        if phase != 'measured':
            raise Refusal('input:rows-warm-shape-differs',
                          'row %r declares phase %r; the hour emits only warm and measured'
                          % (index, phase), phase, 'warm or measured')

        for row_field, hour_field in ROW_IDENTITY:
            if row.get(row_field) != hour.get(hour_field):
                raise Refusal('input:rows-identity-differs',
                              'measured row %r carries %s %r and the hour result carries %r; rows '
                              'from another run cannot be counted toward this one'
                              % (index, row_field, row.get(row_field), hour.get(hour_field)),
                              row.get(row_field), hour.get(hour_field))
        if row.get('input_sha256') != bound_input:
            raise Refusal('input:rows-identity-differs',
                          'measured row %r is bound to input %r and the hour to %r'
                          % (index, row.get('input_sha256'), bound_input),
                          row.get('input_sha256'), bound_input)

        if applied != float(per_update):
            raise Refusal('input:rows-applied-positions-differ-from-geometry',
                          'measured row %r applied %r positions and the run geometry is %d per '
                          'update; a row cannot declare a rate it did no work to earn'
                          % (index, applied, per_update), applied, per_update)

        wall = row_number(row, 'wall_seconds', index)
        if wall <= 0:
            raise Refusal('input:rows-row-not-numeric',
                          'measured row %r has wall_seconds %r' % (index, wall))
        declared = row_number(row, 'positions_per_second', index)
        recomputed = applied / wall
        if abs(recomputed - declared) > max(ROUNDOFF, abs(recomputed) * 1e-9):
            raise Refusal('input:rows-rate-disagrees-with-row',
                          'measured row %r declares %r positions per second and its own applied '
                          'positions over its own wall are %r' % (index, declared, recomputed),
                          declared, recomputed)
        rates.append(recomputed)
        measured_positions += applied

    if not rates:
        raise Refusal('input:rows-empty',
                      'no measured rows in %s; the statistics cannot be recomputed and this tool '
                      'never falls back to an emitted figure, because comparing a producer\'s own '
                      'number to a threshold verifies the threshold and not the number' % rows_path)
    if warm_indices != [0]:
        raise Refusal('input:rows-warm-shape-differs',
                      'the hour emits exactly one warm update at index 0 and this file carries warm '
                      'rows at %r' % (warm_indices,), warm_indices, [0])
    if indices != list(range(len(indices))):
        raise Refusal('input:rows-index-not-contiguous',
                      'row indices are not 0..%d contiguous, so the file is truncated, reordered or '
                      'concatenated from more than one run' % (len(indices) - 1))
    return {'rates': rates, 'warm_rows': len(warm_indices),
            'measured_positions': measured_positions, 'applied_positions': applied_positions}


def check_accounting(hour: dict, governed_wall: float, measured_updates: int, per_update: int,
                     rows: dict, comparisons: list) -> dict:
    """Whether the artifact is internally coherent. None of this is throughput.

    THE PHASE RELATION, bound to the producer's own statement order at 717cf and not to a guess:

        elapsed_before_checkpoint = perf_counter() - started      # end of the measured stretch
        checkpoint_finished       = perf_counter()                # after publish
        restore_finished          = perf_counter()                # after verify_checkpoint_restore
        <every source digest rechecked>
        governed_wall             = perf_counter() - started

    pre + write + restore telescopes to `restore_finished - started`, and the wall is read after the
    source recheck, so the sum is a STRICT SUBSET of the wall: `sum <= governed_wall`.

    The residual `governed_wall - sum` is the source-recheck interval. This predicate DISCLOSES it
    and does not bound it, because no bound on it is derivable from the source and revision 1's
    invented `max(60 s, 1%)` allowance was large enough to hide 1.7% of an hour. It needs no bound
    for soundness in the direction that matters: the governed wall is the DENOMINATOR of the hour
    rate, so unaccounted time inside it can only make the reported rate worse, never better.
    """
    phases = 0.0
    parts = {}
    for field in PHASE_FIELDS:
        parts[field] = number(hour, field, token_absent='accounting:phase-field-absent')
        phases += parts[field]

    fits = phases <= governed_wall + ROUNDOFF
    residual = governed_wall - phases
    comparisons.append({'check': 'phase durations lie inside the governed wall',
                        'observed': phases, 'expected': '<= %r' % governed_wall, 'held': fits})
    if not fits:
        overshoot = phases - governed_wall
        commit = hour.get('source_commit')
        commit_text = ('%.12s' % commit) if isinstance(commit, str) and commit else 'unrecorded'
        # DIAGNOSIS, not a tolerance. Every hour on disk as of 2026-09-14 overshoots by 243 us to
        # 2.08 ms at two different producing commits (c3847b7d, f6c7b6f4), because at those commits
        # `governed_wall` is read at the statement BEFORE the one that computes
        # `restore_and_verification_seconds` as `perf_counter() - checkpoint_finished`. The overshoot
        # is therefore exactly the interval between those two reads -- the result-dict construction --
        # and the artifact's own two statements of the hour disagree by that much. At 717cf the order
        # was fixed: `restore_finished` is captured first and the wall is read after it, so the sum
        # telescopes to a strict subset of the wall. The refusal stands unchanged for a stale producer:
        # widening ROUNDOFF to admit these would be revision 1's invented allowance returning at a
        # smaller size, and an hour whose own two accountings disagree is not an hour this consumer
        # can rule on. What the message adds is which of the two failures it is.
        stale = ('the overshoot is small and positive, which is the signature of a producer that '
                 'reads the governed wall BEFORE the statement computing the restore phase; at '
                 '717cf that order was corrected and the phases telescope inside the wall. If this '
                 'hour was produced before that fix, re-run it at a producer whose wall is read '
                 'last -- this consumer does not widen to admit it.'
                 if 0.0 < overshoot <= 1.0 else
                 'the overshoot is too large to be a statement-order artifact, so the accounting '
                 'itself disagrees about which interval the hour occupied.')
        raise Refusal('accounting:phases-exceed-governed-wall',
                      'the measured, checkpoint-write and restore phases sum to more than the '
                      'governed wall that is supposed to contain them, so one of the two is not '
                      'measuring the hour that ran; overshoot %.9f s at source_commit %s. %s'
                      % (overshoot, commit_text, stale), phases, governed_wall)

    declared_applied = number(hour, 'applied_positions')
    applied_agrees = abs(declared_applied - rows['applied_positions']) < ROUNDOFF
    comparisons.append({'check': 'declared applied positions equal the sum over all rows',
                        'observed': declared_applied, 'expected': rows['applied_positions'],
                        'held': applied_agrees})
    if not applied_agrees:
        raise Refusal('accounting:applied-positions-disagree-with-rows',
                      'the result declares a total applied position count the rows do not sum to',
                      declared_applied, rows['applied_positions'])

    # MEASURED POSITIONS COME FROM THE ROWS, not from count * geometry. Revision 1 computed
    # `measured_updates * 4096` and then compared the declared field to that same product, so the
    # two sides of the comparison came from one source and the check could only fail on a producer
    # arithmetic slip -- never on a row that did no work.
    #
    # A token was RETIRED here rather than left declared. Revision 1 also carried
    # `accounting:update-count-disagrees-with-positions`, comparing the summed row positions against
    # measured_updates x per_update. With the row-level checks in load_rows -- every measured row
    # applies exactly per_update positions, and the measured row count equals the declared count --
    # that sum is the product by arithmetic and the comparison can no longer fail. A declared token
    # nothing can reach inflates a coverage figure, which is the same defect as a check that cannot
    # change state, so it is deleted rather than marked defensive.
    from_rows = rows['measured_positions']
    if 'measured_positions' in hour:
        declared = number(hour, 'measured_positions')
        agrees = abs(declared - from_rows) < ROUNDOFF
        comparisons.append({'check': 'declared measured positions equal the sum over measured rows',
                            'observed': declared, 'expected': from_rows, 'held': agrees})
        if not agrees:
            raise Refusal('accounting:measured-positions-disagree-with-rows',
                          'the result declares a measured position count the measured rows do not '
                          'sum to', declared, from_rows)
    return {'phase_seconds': parts, 'phase_sum_seconds': phases,
            'unaccounted_source_recheck_seconds': residual,
            'unaccounted_note': 'the residual between the phase sum and the governed wall is the '
                                'source-digest recheck the producer runs before reading the wall. '
                                'It is disclosed and deliberately NOT bounded here: no bound on it '
                                'is derivable from source, and it cannot inflate the hour rate '
                                'because the wall it sits inside is that rate\'s denominator.'}


# Which hour fields an evidence artifact must repeat back. Revision 2 used run_id and
# source_commit for all three, and the counterpart seat's replay showed the consequence: an
# Evaluation receipt naming a DIFFERENT child_manifest_sha256 still passed, because the run and the
# commit are shared by every checkpoint the run ever wrote. A binding that cannot distinguish two
# children of one run does not bind a checkpoint-bound claim.
#
# The asymmetry is deliberate and is argued rather than assumed. Gate D's Evaluation minimum and
# the custody receipt both make claims ABOUT A CHECKPOINT, so each must name the one this hour
# produced. The no-worse-learning licence adjudicates the run's LEARNING TRAJECTORY, which is not a
# property of a child manifest; requiring the field there would be inventing a field for a producer
# whose schema I have not read at its source.
#
# NOT the schema-at-source binding, and the receipt says so. These are necessary fields taken from
# the hour result's own required set. Reading each authority's emit at its own commit -- so the
# predicate consumes the producer's real field names rather than plausible ones -- is still open,
# and it is the same leg that keeps composed acceptance NOT_ESTABLISHED.
# REVISION 4. `EVIDENCE_BINDINGS` is gone. It was a tuple of bare field NAMES per artifact, which
# encoded my belief that every producer carries the hour's own names at its top level. The
# counterpart seat replayed revision 3 against the ACTUAL producers and that belief was wrong for
# every artifact except the hour itself: the Evaluation receipt emits `source_head_sha` and a NESTED
# `structural.checkpoint_manifest_sha256`, and the trajectory comparison emits none of the three
# fields at all. The table now lives in hour_evaluation_interface, is keyed by each producer's REAL
# field PATH, records the source and digest it was read from, and refuses where the read found no
# join -- rather than reporting a binding that only holds against fixtures I wrote.
#
# TOKEN MAPPING, not a re-raise of a foreign token: the interface refuses in its own vocabulary and
# this predicate owns its declared token set, so each interface token maps to a declared one here.
# An unmapped token is a programming error and surfaces as such rather than as a silent pass.
INTERFACE_TOKENS = {
    'interface:schema-identity-absent': 'evidence:schema-identity-absent',
    'interface:schema-identity-unknown': 'evidence:schema-identity-unknown',
    'interface:artifact-field-absent': 'evidence:artifact-field-absent',
    'interface:binding-differs': 'evidence:binding-differs',
}


def check_unbound_evidence(label: str, path, token: str) -> dict:
    """An evidence element the bar requires and NO interface-table row can bind.

    Presence and readability only. There is no producer to read, so there is no emit site, no
    schema and no field to compare against the hour -- and inventing one is the defect this
    function exists to make impossible. It refuses when the element is absent (the bar requires
    it) and otherwise records, in the receipt itself, that the artifact was NOT bound.
    """
    if path is None or not Path(path).is_file():
        raise Refusal(token,
                      '%s is required for composed acceptance and was not supplied; this predicate '
                      'fails closed rather than reporting a throughput result as issue completion'
                      % label, str(path) if path else None, 'a readable receipt')
    try:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception as exc:                                   # noqa: BLE001
        raise Refusal('evidence:unreadable',
                      '%s at %s is not readable JSON (%s: %s)' % (label, path, type(exc).__name__, exc))
    if not isinstance(payload, dict):
        raise Refusal('evidence:unreadable', '%s at %s is not a JSON object' % (label, path))
    return {'kind': 'custody', 'bound': {}, 'join_state': 'NO-PRODUCER-IDENTIFIED',
            'producer': None, 'content_adjudicated': False, 'path': str(path),
            'no_join_reason': (
                'No custody-receipt producer exists to read. A repository search for a '
                'custody-receipt schema returns the hour result and the trajectory comparison and '
                'nothing else, so there is no emitted shape to bind. This element is present and '
                'readable and NOTHING about it has been checked against this hour. The producer-side '
                'authorities that DO bind composed custody are cia_hour.py '
                'validate_checkpoint_probe:95-136 and validate_continuation:437-500; consuming them '
                'is an open leg.')}


def check_evidence(label: str, path, token: str, hour: dict, kind: str) -> dict:
    """One evidence artifact: present, JSON, and BOUND to this run.

    Revision 1 required only that the path exist. Three empty text files satisfied it, and the tool
    then reported composed acceptance as met. Each artifact must now parse as JSON and carry every
    binding field the hour result carries, with equal values -- otherwise it is evidence about some
    other run, or about nothing.

    This still does NOT adjudicate the artifact's content, and the receipt says so rather than
    implying otherwise. That is why composed acceptance below stays NOT_ESTABLISHED even when every
    binding holds: consuming each authority's own verdict requires binding its schema at ITS source,
    which is an open leg, and asserting composition before that is exactly the defect this revision
    is repairing.
    """
    if path is None or not Path(path).is_file():
        raise Refusal(token,
                      '%s is required for composed acceptance and was not supplied; this predicate '
                      'fails closed rather than reporting a throughput result as issue completion'
                      % label, str(path) if path else None, 'a readable receipt')
    try:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception as exc:                                   # noqa: BLE001
        raise Refusal('evidence:unreadable',
                      '%s at %s is not readable JSON (%s: %s); revision 1 accepted arbitrary bytes '
                      'here and then reported ACCEPTED'
                      % (label, path, type(exc).__name__, exc))
    if not isinstance(payload, dict):
        raise Refusal('evidence:unreadable', '%s at %s is not a JSON object' % (label, path))
    # The comparison itself is the interface table's, at each producer's real paths. Revision 3
    # compared `payload.get(field)` against `hour.get(field)` for a fixed name list, which is only
    # correct if every producer happens to use the hour's names -- and none of them does.
    try:
        record = bind_artifact(kind, payload, hour)
    except InterfaceRefusal as exc:
        token = INTERFACE_TOKENS.get(exc.token)
        if token is None:
            raise AssertionError('interface token not mapped: %r' % exc.token)
        raise Refusal(token, '%s: %s' % (label, exc.detail), exc.observed, exc.expected)
    record['path'] = str(path)
    return record


def evaluate(hour_path: Path, rows_path: Path, *, numerical_licence=None,
             evaluation_receipt=None, custody_receipt=None) -> dict:
    comparisons = []
    hour = read_json(hour_path, 'input:hour-result-absent', 'input:hour-result-unreadable')
    schema = hour.get('schema')
    if schema != HOUR_SCHEMA:
        raise Refusal('input:hour-result-schema-unknown',
                      'this predicate binds one schema by name; a different one may carry the same '
                      'field names with different meanings', schema, HOUR_SCHEMA)

    # CUSTODY BINDINGS, before any statistic. None is adjudicated here -- each has its own authority
    # -- but their ABSENCE is fatal, because a throughput number with no run, no source and no child
    # is a number about nothing.
    for field in ('run_id', 'source_commit', 'prediction_sha256', 'child_manifest_sha256',
                  'input_binding', 'rows_sha256'):
        if not hour.get(field):
            raise Refusal('custody:binding-field-absent',
                          'the hour result carries no %r; the rate cannot be attributed to a run, '
                          'a source, a prediction or a checkpoint without it' % field)

    per_update = positions_per_update(hour)
    measured_updates = exact_count(hour, 'measured_updates')
    governed_wall = number(hour, 'governed_wall_seconds', allow_zero=False)
    pre_checkpoint_wall = number(hour, 'pre_checkpoint_wall_seconds', allow_zero=False)

    rows = load_rows(rows_path, hour, per_update)
    if len(rows['rates']) != measured_updates:
        raise Refusal('input:rows-measured-count-disagrees',
                      'the rows file carries %d measured rows and the result declares %d measured '
                      'updates; the statistic and the count describe different runs'
                      % (len(rows['rates']), measured_updates),
                      len(rows['rates']), measured_updates)

    accounting = check_accounting(hour, governed_wall, measured_updates, per_update, rows,
                                  comparisons)
    measured_positions = rows['measured_positions']

    # -- SUBVERDICT 1: the warmed-step statistic, recomputed rather than adopted -------------
    recomputed = nearest_rank_p10(rows['rates'])
    emitted = hour.get('complete_step_p10_positions_per_second')
    if isinstance(emitted, (int, float)) and not isinstance(emitted, bool) and math.isfinite(emitted):
        agrees = abs(recomputed - float(emitted)) <= max(ROUNDOFF, abs(float(emitted)) * 1e-9)
        comparisons.append({'check': 'recomputed p10 equals the emitted p10',
                            'observed': recomputed, 'expected': float(emitted), 'held': agrees})
        if not agrees:
            raise Refusal('statistic:recomputed-p10-disagrees-with-emitted',
                          'the hour result reports a p10 this tool cannot reproduce from the rows '
                          'it names; one of the two describes a run that did not happen',
                          recomputed, float(emitted))

    enough_updates = measured_updates >= MINIMUM_WARMED_UPDATES
    step_over = recomputed > TERMINAL_POSITIONS_PER_SECOND
    step_met = bool(enough_updates and step_over)
    comparisons.append({'check': 'measured complete updates', 'observed': measured_updates,
                        'expected': '>= %d' % MINIMUM_WARMED_UPDATES, 'held': enough_updates})
    comparisons.append({'check': 'warmed-step p10 strictly exceeds the terminal',
                        'observed': recomputed,
                        'expected': '> %r' % TERMINAL_POSITIONS_PER_SECOND, 'held': step_over})

    # -- SUBVERDICT 2: the governed-hour WALL rate, checkpoint cost inside it -----------------
    #
    # MEASURED positions over the governed wall, never applied positions (which include the warm
    # update and would overstate the rate) and never the step statistic. Overstating is the one
    # direction a throughput gate must never be wrong in.
    hour_rate = measured_positions / governed_wall
    emitted_hour_rate = hour.get('overall_measured_positions_per_second')
    if (isinstance(emitted_hour_rate, (int, float)) and not isinstance(emitted_hour_rate, bool)
            and math.isfinite(emitted_hour_rate)):
        agrees_hour = abs(hour_rate - float(emitted_hour_rate)) <= max(
            ROUNDOFF, abs(float(emitted_hour_rate)) * 1e-9)
        comparisons.append({'check': 'recomputed hour rate equals the emitted hour rate',
                            'observed': hour_rate, 'expected': float(emitted_hour_rate),
                            'held': agrees_hour})
        if not agrees_hour:
            raise Refusal('statistic:recomputed-hour-rate-disagrees-with-emitted',
                          'the hour result reports an overall rate this tool cannot reproduce from '
                          'the rows it names', hour_rate, float(emitted_hour_rate))

    # The DURATION gate is the pre-checkpoint wall, which is the field the producer's own
    # `hour_complete` is called with (cia_hour.py, continuation validation). The governed wall
    # additionally contains the checkpoint and restore cost, so requiring 3,600 s of IT would admit
    # an hour whose measured stretch was shorter than an hour -- a weaker gate wearing the same
    # number. The RATE is still taken over the governed wall, so the checkpoint cost is charged.
    long_enough = pre_checkpoint_wall >= MINIMUM_GOVERNED_SECONDS
    hour_over = hour_rate > TERMINAL_POSITIONS_PER_SECOND
    hour_met = bool(long_enough and hour_over)
    comparisons.append({'check': 'continuous measured duration before the checkpoint',
                        'observed': pre_checkpoint_wall,
                        'expected': '>= %r' % MINIMUM_GOVERNED_SECONDS, 'held': long_enough})
    comparisons.append({'check': 'governed-hour wall rate strictly exceeds the terminal',
                        'observed': hour_rate,
                        'expected': '> %r' % TERMINAL_POSITIONS_PER_SECOND, 'held': hour_over})

    throughput_met = bool(step_met and hour_met)

    # -- COMPOSED ACCEPTANCE: never assigned from throughput -----------------------------------
    evidence = {
        'numerical_licence': check_evidence('the no-worse-learning licence for THIS number',
                                            numerical_licence,
                                            'evidence:numerical-licence-absent', hour,
                                            'numerical_licence'),
        'evaluation': check_evidence('the protected Evaluation minimum against this checkpoint',
                                     evaluation_receipt, 'evidence:evaluation-absent', hour,
                                     'evaluation'),
        # NOT routed through check_evidence, and the reason is a correction to revision 4 rather
        # than a shortcut. That revision carried a `custody` row in the interface table with
        # "no producer identified", and an artifact row for a producer nobody has read is an
        # invention: bind_artifact would have looked up a shape that was never emitted anywhere.
        # The row is deleted at its source. The BAR still requires checkpoint custody, so the
        # element stays here -- checked for presence and readability, explicitly not bound, and
        # labelled so no reader mistakes an unbound receipt for a checked one. Two existing
        # authorities DO bind composed custody at the producer (cia_hour.py validate_checkpoint_probe
        # :95-136 and validate_continuation :437-500, the latter joining on the custody root's own
        # directory NAME at :449); wiring this element to them is the open leg, and naming it is
        # what keeps it open instead of appearing satisfied.
        'custody': check_unbound_evidence('the checkpoint custody receipt for this hour',
                                          custody_receipt, 'evidence:custody-absent'),
    }
    # Every binding held, and composition is STILL not established. The three artifacts are present,
    # parseable and bound to this run; what has not happened is any reading of the verdict inside
    # them, which requires binding each authority's schema at its own source. Until that leg lands,
    # the only honest composed state is NOT_ESTABLISHED, and `met` is false regardless of throughput.
    composed_met = False
    composed_state = 'NOT_ESTABLISHED'
    evidence['artifacts_with_no_readable_join'] = unjoinable()
    evidence['interface_table_sources'] = {
        kind: {'producer': spec.get('producer'), 'emit_site': spec.get('emit_site'),
               'producer_sha256': spec.get('producer_sha256')}
        for kind, spec in ARTIFACTS.items()}
    composed_reason = ('the Evaluation artifact binds at its producer\'s REAL paths '
                       '(source_head_sha and the nested structural.checkpoint_manifest_sha256) '
                       'rather than at the hour\'s own names, and its VERDICT is still not read '
                       'here. The other two elements do not bind, and this says so instead of '
                       'appearing to check them. The trajectory comparison is arm-bound and emits '
                       'no run, source or checkpoint field, so it carries NO-READABLE-JOIN -- with '
                       'the correction that revision 4 got wrong in the other direction: a '
                       'transitive path to it EXISTS and was verified step by step at '
                       'PRODUCER_COMMIT, so the missing thing is an adjudicator, not the evidence. '
                       'The custody element has no producer at all, is checked for presence and '
                       'readability only, and is NOT an interface-table artifact; revision 4 gave '
                       'it a table row and thereby reported an invented slot as a gap in the '
                       'evidence chain. Composition therefore rests on authorities whose verdicts '
                       'nothing here reads. Revision 1 set this field from the throughput '
                       'subverdict and reported ACCEPTED; a throughput result is not issue '
                       'completion and no disclaimer makes it one.')

    return {
        'schema': 'ember-1945-hour-acceptance-v2',
        'authority': 'STAGING -- not terminal authority. Per the implementing seat (37643) the '
                     'acceptance consumer belongs in the repository beside the existing authority; '
                     'until it lands there this receipt is a reviewable prediction of that gate\'s '
                     'verdict and certifies nothing.',
        'terminal_positions_per_second': TERMINAL_POSITIONS_PER_SECOND,
        'comparator': 'strictly greater than, on both statistics',
        'positions_per_update': per_update,
        'positions_per_update_source': 'input_binding.geometry sequence_length x documents_per_step',
        'throughput_subverdict': {
            'met': throughput_met,
            'warmed_step': {'met': step_met, 'statistic': 'nearest-rank-p10 over per-step rates',
                            'recomputed_from': 'each measured row\'s own applied positions over its '
                                               'own wall, after the rows digest and every row '
                                               'identity binding were verified',
                            'warm_rows_excluded': rows['warm_rows'],
                            'value': recomputed, 'measured_updates': measured_updates,
                            'minimum_updates': MINIMUM_WARMED_UPDATES},
            'governed_hour': {'met': hour_met,
                              'statistic': 'measured positions / governed wall seconds, with the '
                                           'mandatory checkpoint write and restore verification '
                                           'INSIDE the wall',
                              'value': hour_rate, 'measured_positions': measured_positions,
                              'applied_positions_including_warm': rows['applied_positions'],
                              'governed_wall_seconds': governed_wall,
                              'pre_checkpoint_wall_seconds': pre_checkpoint_wall,
                              'minimum_measured_seconds': MINIMUM_GOVERNED_SECONDS},
            'why_two': 'a high measured-step p10 with slow I/O can still violate the governed-hour '
                       'throughput, so neither statistic substitutes for the other',
        },
        'accounting': accounting,
        'composed_acceptance': {
            'met': composed_met,
            'state': composed_state,
            'reason': composed_reason,
            'requires': ['throughput subverdict', 'no-worse-learning licence',
                         'protected Evaluation minimum', 'checkpoint custody'],
            'evidence': evidence,
        },
        'comparisons': comparisons,
        'inputs': {'hour_result': str(hour_path), 'rows': str(rows_path),
                   'numerical_licence': str(numerical_licence),
                   'evaluation_receipt': str(evaluation_receipt),
                   'custody_receipt': str(custody_receipt)},
    }


def status_of(payload: dict) -> str:
    """ACCEPTED is reachable only through composed acceptance, never through throughput.

    Four states rather than two, because collapsing them is what let revision 1 print ACCEPTED on a
    throughput pass. `THROUGHPUT_MET_COMPOSITION_NOT_ESTABLISHED` is the honest verdict for a
    qualifying number whose licence, Evaluation and custody verdicts have not been read.
    """
    if payload['composed_acceptance']['met']:
        return 'ACCEPTED'
    if payload['throughput_subverdict']['met']:
        return 'THROUGHPUT_MET_COMPOSITION_NOT_ESTABLISHED'
    return 'THROUGHPUT_NOT_MET'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hour-result', type=Path, required=True)
    parser.add_argument('--rows', type=Path, required=True)
    parser.add_argument('--numerical-licence', type=Path)
    parser.add_argument('--evaluation-receipt', type=Path)
    parser.add_argument('--custody-receipt', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        payload = evaluate(args.hour_result, args.rows,
                           numerical_licence=args.numerical_licence,
                           evaluation_receipt=args.evaluation_receipt,
                           custody_receipt=args.custody_receipt)
        payload['status'] = status_of(payload)
        code = 0 if payload['status'] == 'ACCEPTED' else 1
    except Refusal as refusal:
        payload = {'schema': 'ember-1945-hour-acceptance-v2', 'status': 'REFUSED',
                   'token': refusal.token, 'detail': refusal.detail,
                   'observed': refusal.observed, 'expected': refusal.expected}
        code = 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1, sort_keys=True) + '\n',
                        encoding='utf-8', newline='\n')
    print('%s %s' % (payload['status'], payload.get('token', '')))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
