#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1945 hour <-> Evaluation INTERFACE: one table, read at each producer's own source.

WHY THIS EXISTS. The hour-acceptance predicate held `EVIDENCE_BINDINGS` as a tuple of bare field
NAMES -- run_id, source_commit, child_manifest_sha256 -- and asked every evidence artifact to carry
them at the top level. That was my belief about the producers' shapes, never a reading of them. The
counterpart seat replayed it against the ACTUAL producers and the belief was wrong for every
artifact but the hour itself (37662). The cure it named, and the constraint it attached, are both
binding here:

    a per-artifact mapping from an hour field to that producer's REAL field PATH, each read at its
    own source and recorded with the source digest that supplied it, plus an explicit schema
    identity per artifact -- and NO duplicate producer fields added merely to satisfy fixtures.

The second half is the load-bearing one. When a producer does not emit a field, the lawful moves are
to bind the field it DOES emit, or to refuse; adding the field to the producer so my table matches
is manufacturing the agreement the table is supposed to test. Everything below therefore records
what was read and at which digest. Where the read produced NO join, the artifact is recorded as
unjoinable with its reason rather than refused: a producer that structurally cannot bind to an hour
would otherwise refuse every invocation forever, taking the throughput subverdict down with it, and
a check that can never pass is the mirror of the check-that-cannot-fail this packet is repairing.
A join that is DECLARED and then disagrees still refuses, which is the case that can actually fire.

WHAT WAS READ, AND WHERE IT LEFT EACH ARTIFACT
----------------------------------------------
1. HOUR (`ember-cia-hour-result-v1`), cia_hour.py:445-460 at ROOT 717cf. Emits, at top level:
   child_manifest_sha256, parent_manifest_sha256, source_commit, run_id, lineage, input_binding,
   prediction_sha256, complete_step_p10_positions_per_second, quantile, measured_updates,
   applied_positions, governed_wall_seconds, pre_checkpoint_wall_seconds, rows_sha256. It emits NO
   checkpoint path: custody is held externally by the runner, so `checkpoint_root` has no producer
   field and cannot be mapped. It is supplied and VERIFIED instead (see verify_custody_root).

2. EVALUATION (gate `issue1947-evaluation-minimum`, receipt_version 4),
   evaluation_minimum_gate.py:1186-1188 and :1013. JOINS, at real paths that are NOT the names the
   old table used: run_id -> `run_id`; the hour's source_commit -> `source_head_sha`; the hour's
   child_manifest_sha256 -> NESTED `structural.checkpoint_manifest_sha256`. Two of three were
   wrong before, which is why the real payload refused on source_commit.

3. NUMERICAL LICENCE (`ember-cia-trajectory-comparison-v1`), cia_trajectory.py:306-309. This one
   does not join at all, and the finding is worth more than the mapping would have been: the
   comparison binds `arm_sha256` and emits NEITHER run_id, NOR source_commit, NOR any checkpoint
   manifest digest. Its subject is a set of arms, not a run and not a child. The hour emits
   `prediction_sha256`, which is a different quantity from an arm digest and is not asserted here to
   equal one. So the join from an hour to its licence needs a link that NOTHING I have read states,
   and this module refuses rather than inventing one. My previous table's ('run_id',
   'source_commit') for this artifact was not merely at the wrong path -- those fields do not exist
   in the producer's output.

4. CUSTODY. No producer found. A repository search for a custody-receipt schema returns the hour
   result and the trajectory comparison and nothing else, so there is no artifact whose shape I can
   bind. Declared UNREAD, and recorded unjoinable on the same footing as the licence -- with one
   difference: the licence's producer at least DECLARES a schema, so that much stays checked.

CONSEQUENCE, STATED PLAINLY: composed acceptance stays NOT_ESTABLISHED, and it now stays there for
a reason with a source behind it rather than a reason I asserted. Two of the four artifacts have no
readable join to an hour. That is a real gap in #1945's evidence chain, it is the counterpart seat's
to close where it owns the producers, and naming it is worth more than a table that would have
appeared to work against fixtures I wrote myself.

NOTHING HERE MOVES A GATE. Gate B remains UNMET and gate D's checkpoint-bound term remains ZERO.
This is interface authorship: it makes a future join checkable, and it adjudicates nothing.

OWNERSHIP (the counterpart seat's 37666, adopted): this seat authors the adapter AND the schema
mapping as one frozen interface packet; that seat owns repository placement, integration review, CI
and public delivery, so the two directions cannot drift apart in two trees.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

MISSING = object()          # distinct from a present JSON null -- see dig()

HOUR_SCHEMA = 'ember-cia-hour-result-v1'

# Every ember-side row below was read in a checkout of THIS repository at PRODUCER_COMMIT.
# Revision 4 carried a different, older checkout's line numbers, and at least one of them
# (cia_hour.py:445) pointed at a different function -- so the table's own provenance was stale
# while the table was being used to correct other people's provenance. The COMMIT is what makes a
# row re-readable by anyone; the checkout path only makes it findable on one host, so the commit
# is recorded and the path is not.
PRODUCER_ROOT = 'the ember repository, read at PRODUCER_COMMIT'
PRODUCER_COMMIT = '717cf23412516865bb4271dbff2a225018efed69'


class InterfaceRefusal(Exception):
    """A join could not be made. Carries a token so callers can map it to their own refusal set."""

    def __init__(self, token, detail, observed=None, expected=None):
        super().__init__('%s: %s' % (token, detail))
        self.token, self.detail = token, detail
        self.observed, self.expected = observed, expected


# --------------------------------------------------------------------------------------------
# The table. Every row was produced by opening the named source at the named digest and reading
# the expression that WRITES the artifact -- never a docstring, a schema note, or a fixture.
# --------------------------------------------------------------------------------------------
ARTIFACTS = {
    'hour': {
        'producer': 'src/ember/infrastructure/tools/ember-restart-3b/cia_hour.py',
        'producer_root': PRODUCER_ROOT,
        'producer_commit': PRODUCER_COMMIT,
        # Revision 4 cited cia_hour.py:445. That line is inside validate_continuation, not the
        # writer -- a stale line number from an older worktree, which the counterpart seat caught.
        # Every site below was re-read at PRODUCER_COMMIT in this revision.
        'emit_site': 'cia_hour.py:757 runner._write_new(custody / "hour-result.json", dict(...))',
        'identity': (('schema',), HOUR_SCHEMA),
        'joinable': True,
        # The hour is the REFERENCE side: these are the fields other artifacts are matched against.
        'fields': {
            'run_id': ('run_id',),
            'source_commit': ('source_commit',),
            'child_manifest_sha256': ('child_manifest_sha256',),
        },
        # The hour's OWN custody authority, read rather than invented. Revision 4 declared a
        # separate 'custody' artifact with no producer; there is no such artifact and there was
        # nothing to invent. cia_hour.py:103-107 requires identity['checkpoint_probe'] to be
        # exactly {custody_root, result_sha256, prediction_sha256, owned_sha256, disk_sha256,
        # worker_terminal_sha256}; :108-109 requires the root to be on B: and named measurement-*;
        # :131-132 fixes the child at custody_root/trained-child and binds its manifest to the
        # hour result's child_manifest_sha256; :134-136 reopens the child through
        # parameter_counter._cia_realization_receipt and compares it to the on-disk receipt.
        # validate_continuation:449 additionally requires root.name == 'measurement-' + run_id,
        # so the custody root's NAME carries the run identity. That is the join revision 4 said
        # did not exist.
        'custody_authority': (
            'cia_hour.validate_checkpoint_probe:95-136 (composed probe custody, six bound digests, '
            'child reopened through parameter_counter._cia_realization_receipt) and '
            'cia_hour.validate_continuation:437-500 (native job outcome, measurement-file digests, '
            'owned/disk/terminal/rows, and the child continuation binding at :500)'),
        'not_emitted': ('checkpoint_root as a PATH. The result names no directory; custody is '
                        'external and is bound by the authorities above. verify_custody_root '
                        'therefore makes a supplied root falsifiable rather than declared.'),
    },
    'evaluation': {
        'producer': ('scripts/issue1947/evaluation_minimum_gate.py -- tooling outside this '
                     'repository, pinned by the producer_sha256 below rather than by any '
                     'checkout path'),
        'producer_sha256': 'ced9c0c4fbe6dd58c209c583c5ba1245dbc2f6823ae6ef312100196579b4029a',
        'emit_site': ('evaluation_minimum_gate.py:1186 receipt.update({... "source_head_sha": '
                      'hour["source_head_sha"], "run_id": hour["run_id"], "structural": structural '
                      '...}), with structural["checkpoint_manifest_sha256"] set at :1013'),
        'identity': (('gate',), 'issue1947-evaluation-minimum'),
        'identity_version': (('receipt_version',), 4),
        'joinable': True,
        # hour field -> THIS producer's real path. Two of the three are not the hour's own name.
        'fields': {
            'run_id': ('run_id',),
            'source_commit': ('source_head_sha',),
            'child_manifest_sha256': ('structural', 'checkpoint_manifest_sha256'),
        },
        'not_bound': ('the receipt\'s VERDICT. This module binds identity only; whether the '
                      'Evaluation minimum was met belongs to that gate, and its own receipt '
                      'already records evaluator_binding NOT_ESTABLISHED, which no join here '
                      'upgrades.'),
    },
    'numerical_licence': {
        'producer': 'src/ember/infrastructure/tools/ember-restart-3b/cia_trajectory.py',
        'producer_root': PRODUCER_ROOT,
        'producer_commit': PRODUCER_COMMIT,
        'emit_site': ('cia_trajectory.py:314 result = dict(schema='
                      '"ember-cia-trajectory-comparison-v1", arm_sha256=...)   [revision 4 said '
                      ':306; corrected by re-reading at PRODUCER_COMMIT]'),
        'identity': (('schema',), 'ember-cia-trajectory-comparison-v1'),
        'joinable': False,
        'identity_checkable': True,
        'fields': {},
        # Revision 4 said this producer has no path to an hour at all. That was wrong, and the
        # counterpart seat located the path; every step below was then re-read here at
        # PRODUCER_COMMIT rather than taken from its mail.
        'transitive_path': (
            'comparison.arm_sha256 (:314) -> adjudicate_arms:283 requires _file_sha256('
            'root/"t2-arm-<name>.json") == arm_sha256[name] at :290-292 -> the arm artifact is '
            'written at :676 from result = dict(arm=..., execution_mode=..., start=start, ...) at '
            ':662, so the arm EMBEDS the start block -> start:575-587 carries source_commit, '
            'source_sha256, seed, population and population_sha256, rng, cursor, support, '
            'geometry, input_binding, shard_ledger_sha256, optimizer, comparison_id, '
            'local_routing_mode, the attention selection and frozen_population_sha256.'),
        'no_join_reason': (
            'the path above reaches the invariant TRAINING CONTRACT, source identity and '
            'selectors -- it does not reach the hour. The trajectory run and the governed hour are '
            'DIFFERENT RUNS, so equality of run ids is the wrong comparison and is not made here; '
            'the arm\'s own child_manifest_sha256 at :675-676 is the arm\'s checkpoint, not the '
            'hour\'s, and comparing it to the hour\'s child would be a category error rather than '
            'a strict check. What a join needs is a COMPATIBILITY consumer over the invariant '
            'contract, source and selectors plus a proven input prefix, carrying the declared arm '
            'treatment and the arm\'s actual verdict. No such adjudicator exists in the bytes '
            'either seat has read. So the evidence exists and the adjudicator does not, which is a '
            'different statement from revision 4\'s "no readable join" and is the accurate one.'),
    },
}

# What the Evaluation minimum gate needs of an hour receipt.
#
# REQUIRED_RECEIPT_FIELDS (evaluation_minimum_gate.py:187) is a STRUCTURAL PRESENCE set, and
# revision 4 described those four as the consumer contract. They are not: the gate also reads
# hour.get('published_step', hour.get('step')) at :1137 and REFUSES when it is absent (:1138-1141),
# so an adapter emitting only the four produces a receipt the gate declines further down. Naming a
# partial set as complete is the same error class as a stale line number -- it reads as verified.
EVALUATION_INPUT_SOURCES = {
    'run_id': ('hour', ('run_id',)),
    'source_head_sha': ('hour', ('source_commit',)),
    'checkpoint_manifest_sha256': ('hour', ('child_manifest_sha256',)),
    'checkpoint_root': ('supplied+verified', None),
    'published_step': ('hour-continuation', ('terminal_data_cursor', 'global_step')),
}

REQUIRED_RECEIPT_FIELDS_NOTE = (
    'evaluation_minimum_gate.py:187 lists four fields; that constant is a presence check, not the '
    'whole contract. published_step is required at :1137-1146 and is supplied here from a source '
    'independent of the checkpoint. This set is still not asserted to be exhaustive -- it is what '
    'reading the gate produced, and a later gate revision can add to it.')

CHILD_DIRECTORY_NAME = 'trained-child'
MANIFEST_NAME = 'checkpoint-manifest.json'
CONTINUATION_HOUR_NAME = 'continuation-hour.json'


def dig(payload, path):
    """Resolve a tuple path, returning MISSING for an absent key at any level.

    MISSING is distinct from a present JSON null on purpose. Revision 3 of the predicate was
    repaired for exactly this confusion one level up: an absent binding read as None and DISABLED
    the comparison instead of failing it. A path that does not exist in a payload is a schema
    disagreement and must refuse; a path that exists and holds null is a producer emitting nothing,
    which is a different finding and also refuses, but says so differently.
    """
    node = payload
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return MISSING
        node = node[key]
    return node


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def check_identity(kind: str, payload: dict):
    """Refuse an artifact that does not declare the schema this table was read against.

    A same-named field in a different schema is the failure this guards: `run_id` means one thing
    in an hour result and could mean another anywhere else, and a table of paths is only sound if
    the payload is the shape the paths were read from.
    """
    spec = ARTIFACTS[kind]
    for label, entry in (('schema identity', spec.get('identity')),
                         ('schema version', spec.get('identity_version'))):
        if entry is None:
            continue
        path, want = entry
        got = dig(payload, path)
        if got is MISSING:
            raise InterfaceRefusal(
                'interface:schema-identity-absent',
                'the %s artifact declares no %s at %s, so nothing establishes that its fields mean '
                'what this table read them to mean' % (kind, label, '.'.join(path)),
                None, want)
        if got != want:
            raise InterfaceRefusal(
                'interface:schema-identity-unknown',
                'the %s artifact declares %s %r; this table was read against %r and a different '
                'shape may carry the same field names with different meanings'
                % (kind, label, got, want), got, want)


def bindings_for(kind: str) -> dict:
    """The hour-field -> real-path mapping for one artifact. Empty when the producer cannot join."""
    return dict(ARTIFACTS[kind]['fields'])


def bind_artifact(kind: str, payload: dict, hour: dict) -> dict:
    """Compare one artifact against the hour at THIS producer's real paths.

    Returns the bound values with the path each came from, so a reader of the receipt can re-derive
    the comparison without reading this module.
    """
    spec = ARTIFACTS[kind]
    if not spec['joinable'] and spec.get('identity_checkable'):
        # The producer declares a schema even though no field joins, so the one thing that IS
        # checkable about it stays checked: that the artifact is the shape whose emit site was read.
        check_identity(kind, payload)
    if not spec['joinable']:
        # NOT a refusal. The producer structurally emits nothing that binds to an hour, so raising
        # here would make the whole predicate unrunnable and take the throughput subverdict down
        # with it -- a check that can never pass. The absence is recorded instead, in the receipt,
        # where a reader sees that this artifact was NOT checked rather than quietly assuming it
        # was. Composed acceptance is already NOT_ESTABLISHED and this is one of its reasons.
        return {'kind': kind, 'bound': {}, 'join_state': 'NO-READABLE-JOIN',
                'producer': spec.get('producer'),
                'content_adjudicated': False,
                'no_join_reason': spec['no_join_reason']}
    check_identity(kind, payload)
    bound = {}
    for hour_field, path in bindings_for(kind).items():
        want = dig(hour, ARTIFACTS['hour']['fields'][hour_field])
        if want is MISSING:
            raise InterfaceRefusal(
                'interface:hour-field-absent',
                'the hour result carries no %s, so there is nothing for the %s artifact to match'
                % (hour_field, kind), None, hour_field)
        got = dig(payload, path)
        if got is MISSING:
            raise InterfaceRefusal(
                'interface:artifact-field-absent',
                'the %s artifact has no %s, which this table read as its home for the hour\'s %s. '
                'The lawful cures are to bind a field it does emit or to refuse -- never to add the '
                'field to the producer so this comparison passes'
                % (kind, '.'.join(path), hour_field), None, '.'.join(path))
        if got != want:
            raise InterfaceRefusal(
                'interface:binding-differs',
                'the %s artifact declares %s %r at %s and the hour declares %r, so it is evidence '
                'about a different %s' % (kind, hour_field, got, '.'.join(path), want,
                                          'checkpoint' if hour_field == 'child_manifest_sha256'
                                          else 'run'),
                got, want)
        bound[hour_field] = {'value': got, 'artifact_path': '.'.join(path)}
    return {'kind': kind, 'bound': bound, 'join_state': 'BOUND',
            'schema_identity': ARTIFACTS[kind]['identity'][1],
            'producer': ARTIFACTS[kind].get('producer'),
            'content_adjudicated': False,
            'note': ARTIFACTS[kind].get('not_bound', '')}


def load_hour(hour_path, expected_sha256: str) -> dict:
    """Read the hour result HASH-BOUND, per the counterpart seat's constraint in 37666.

    An adapter that reads whatever is at a path adapts whatever is at that path. Binding the digest
    is what makes the output about one specific hour rather than about a filename.
    """
    path = Path(hour_path)
    if not path.is_file():
        raise InterfaceRefusal('interface:hour-absent', 'not a file: %s' % path)
    actual = digest_file(path)
    if not expected_sha256:
        raise InterfaceRefusal(
            'interface:hour-digest-not-supplied',
            'the hour result must be consumed hash-bound; without a declared digest this adapter '
            'would describe whatever currently sits at %s' % path, None, 'a sha256')
    if actual != expected_sha256:
        raise InterfaceRefusal(
            'interface:hour-digest-differs',
            'the hour result at %s digests to %s, not the declared %s' % (path, actual,
                                                                          expected_sha256),
            actual, expected_sha256)
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise InterfaceRefusal('interface:hour-unreadable', 'the hour result is not a JSON object')
    check_identity('hour', payload)
    return payload


def verify_custody_root(custody_root, hour: dict) -> dict:
    """Make a SUPPLIED custody root falsifiable against the hour's own child manifest digest.

    `checkpoint_root` is the one required field with no producer field to map, because the hour
    holds custody externally. Copying a path in from the command line and calling it the hour's
    checkpoint would be exactly the synthetic admission the constraint forbids. Instead the supplied
    root must CONTAIN a child manifest that digests to the value the hour recorded -- the same check
    cia_hour.py:131 performs on itself when it reopens the probe's child. A wrong root fails.
    """
    root = Path(custody_root)
    if not root.is_dir():
        raise InterfaceRefusal('interface:custody-root-absent', 'not a directory: %s' % root)
    manifest = root / CHILD_DIRECTORY_NAME / MANIFEST_NAME
    if not manifest.is_file():
        raise InterfaceRefusal(
            'interface:custody-manifest-absent',
            'the supplied custody root has no %s/%s, so it cannot be shown to be this hour\'s '
            'checkpoint' % (CHILD_DIRECTORY_NAME, MANIFEST_NAME), str(manifest), 'a child manifest')
    want = dig(hour, ARTIFACTS['hour']['fields']['child_manifest_sha256'])
    if want is MISSING:
        raise InterfaceRefusal('interface:hour-field-absent',
                               'the hour result carries no child_manifest_sha256')
    actual = digest_file(manifest)
    if actual != want:
        raise InterfaceRefusal(
            'interface:custody-manifest-differs',
            'the child manifest under %s digests to %s and the hour recorded %s, so the supplied '
            'root is a different checkpoint' % (root, actual, want), actual, want)
    # checkpoint_root is the CHILD directory, not the custody root. Revision 4 returned the custody
    # root and its own forward battery passed, because every case asserted THIS adapter's four
    # fields instead of executing the consumer's path. The consumer builds
    # checkpoint_root/'checkpoint-manifest.json' at evaluation_minimum_gate.py:990 and refuses at
    # :992 when it is absent, then os.path.samefile()s the hour receipt's checkpoint_root against
    # the same directory at :1087. Under revision 4 the gate refused this adapter's own output.
    # Found by the counterpart seat EXECUTING the frozen module, which is the only thing that could
    # have found it: a fixture written from the same belief as the code agrees with the code.
    return {'checkpoint_root': str(manifest.parent), 'custody_root': str(root),
            'child_manifest_path': str(manifest), 'child_manifest_sha256': actual,
            'consumer_check': ('evaluation_minimum_gate.py:990 opens checkpoint_root/%s and :1087 '
                               'samefiles it against the hour receipt\'s checkpoint_root' % MANIFEST_NAME),
            'basis': ('supplied then VERIFIED: the child directory is admitted because its manifest '
                      'digests to the value the hour itself recorded, not because a root was named '
                      'on a command line')}


def read_published_step(custody_root, hour: dict) -> dict:
    """The hour's published step, from a source INDEPENDENT of the checkpoint being judged.

    The obvious source is the child manifest's data_cursor.global_step, and it is the wrong one.
    The gate compares checkpoint data_cursor.global_step against published_step
    (evaluation_minimum_gate.py:1136-1146); sourcing published_step from that same cursor makes the
    comparison a value against its own source, which can never fail. That is the defect this whole
    packet was opened to repair, one level up, and it would have been written in on instruction.

    The hour has a genuinely separate record. cia_hour.py:609 writes
    terminal_data_cursor=terminal_state['data_cursor'] into continuation-hour.json alongside
    live_state_verified_before_restore=True -- captured from the LIVE training state before the
    restore, not read back from the written bytes. (The sibling field terminal_checkpoint.global_step
    at :600 IS copied from the manifest and is therefore unusable here; it is the nearest trap.)
    cia_hour.py:500 already asserts child['data_cursor'] == hour_binding['terminal_data_cursor'],
    so a gate comparing them re-verifies a real upstream invariant across two producers.

    Availability is not conditional in practice: cia_hour.py:752 writes the continuation for every
    non-probe hour, and :634-635 puts hour_binding_sha256 into the hour result. When the descriptor
    is absent this REFUSES rather than falling back to the manifest -- a checkpoint probe is not a
    governed hour and cannot satisfy gate D regardless, so the refusal costs nothing real and the
    fallback would cost the check.
    """
    descriptor = hour.get('continuation')
    if not isinstance(descriptor, dict):
        raise InterfaceRefusal(
            'interface:hour-continuation-absent',
            'the hour result carries no continuation descriptor, so it has no record of its '
            'terminal cursor independent of the checkpoint; a checkpoint probe cannot supply '
            'gate D', type(descriptor).__name__, 'a continuation descriptor (cia_hour.py:634)')
    want = descriptor.get('hour_binding_sha256')
    if not isinstance(want, str) or len(want) != 64:
        raise InterfaceRefusal(
            'interface:hour-continuation-digest-absent',
            'the continuation descriptor carries no hour_binding_sha256, so continuation-hour.json '
            'cannot be admitted', repr(want), 'a 64-character digest')
    binding_path = Path(custody_root) / CONTINUATION_HOUR_NAME
    if not binding_path.is_file():
        raise InterfaceRefusal(
            'interface:hour-continuation-file-absent',
            'no %s under the supplied custody root' % CONTINUATION_HOUR_NAME, str(binding_path),
            'the hour binding the descriptor names')
    actual = digest_file(binding_path)
    if actual != want:
        raise InterfaceRefusal(
            'interface:hour-continuation-digest-differs',
            '%s digests to %s and the hour result recorded %s' % (CONTINUATION_HOUR_NAME, actual, want),
            actual, want)
    binding = json.loads(binding_path.read_text(encoding='utf-8'))
    step = dig(binding, ('terminal_data_cursor', 'global_step'))
    if step is MISSING:
        raise InterfaceRefusal(
            'interface:published-step-absent',
            '%s carries no terminal_data_cursor.global_step' % CONTINUATION_HOUR_NAME,
            None, 'terminal_data_cursor.global_step')
    if type(step) is not int:
        raise InterfaceRefusal(
            'interface:published-step-not-exact',
            'terminal_data_cursor.global_step is %r, and the gate compares steps exactly '
            '(evaluation_minimum_gate.py:1144-1146)' % (step,), type(step).__name__, 'int')
    return {'published_step': step, 'path': str(binding_path), 'sha256': actual,
            'source': 'continuation-hour.json terminal_data_cursor.global_step (cia_hour.py:609)',
            'independence': ('captured from the live training state before restore, not read from '
                             'the checkpoint manifest the gate is judging; cia_hour.py:500 asserts '
                             'the two agree, so the gate\'s comparison has two real producers')}


def adapt_hour_for_evaluation(hour_path, hour_sha256, custody_root) -> dict:
    """Forward direction: the Evaluation gate's required fields, each with its provenance.

    Returns a record the caller writes verbatim into its receipt. Every field says where it came
    from, so "did the adapter invent this" is answerable by reading the output.

    Three origins, and they are different KINDS of claim, which is why they are not one branch:
    'hour' is copied from the hash-bound hour result; 'supplied+verified' is admitted only because
    its manifest digests to the value the hour recorded; 'hour-continuation' is read from a second
    artifact the hour itself binds by digest, and is used for published_step precisely because the
    obvious source would make the consumer's step check compare a value to itself.
    """
    hour = load_hour(hour_path, hour_sha256)
    custody = verify_custody_root(custody_root, hour)
    published = read_published_step(custody_root, hour)

    fields, provenance = {}, {}
    for target, (origin, path) in EVALUATION_INPUT_SOURCES.items():
        if origin == 'hour':
            value = dig(hour, path)
            if value is MISSING:
                raise InterfaceRefusal(
                    'interface:hour-field-absent',
                    'the hour result has no %s, which is the Evaluation gate\'s only source for %s'
                    % ('.'.join(path), target), None, '.'.join(path))
            fields[target] = value
            provenance[target] = {'origin': 'hour result', 'path': '.'.join(path)}
        elif origin == 'hour-continuation':
            fields[target] = published['published_step']
            provenance[target] = {'origin': 'hour continuation binding, digest-verified',
                                  'path': '.'.join(path), 'file': published['path'],
                                  'sha256': published['sha256'],
                                  'independence': published['independence']}
        else:
            fields[target] = custody['checkpoint_root']
            provenance[target] = {'origin': 'supplied custody root, verified',
                                  'basis': custody['basis'],
                                  'consumer_check': custody['consumer_check']}

    return {
        'schema': 'ember-1945-hour-evaluation-adapter-v1',
        'hour_path': str(hour_path),
        'hour_sha256': hour_sha256,
        'hour_schema': HOUR_SCHEMA,
        'evaluation_gate_required_fields': fields,
        'field_provenance': provenance,
        'custody_verification': custody,
        'published_step_source': published,
        'claim_boundary': (
            'This states only that these fields were read from ONE hash-bound hour result, one '
            'custody root proven to hold that hour\'s child manifest, and one continuation binding '
            'the hour records by digest. The field set is the one this seat has READ in the '
            'consumer at PRODUCER_COMMIT and is NOT asserted exhaustive: see '
            'REQUIRED_RECEIPT_FIELDS_NOTE, which records that the consumer\'s own named constant '
            'lists four fields while a fifth is required elsewhere in the same file. It is not an '
            'admission, not an Evaluation verdict, and not evidence that the gate has ever been '
            'executed against this checkpoint. Gate D\'s decisive term is that execution and '
            'remains ZERO until it happens.'),
    }


def unjoinable() -> dict:
    """The artifacts with no readable join, for a receipt that must not imply they were checked.

    Revision 4 iterated every non-joinable row and returned two, one of which -- `custody` -- was a
    slot I had invented for a producer that does not exist. Deleting that row is the repair; making
    this function name the surviving one EXPLICITLY is what stops the next invented slot from being
    reported as a finding about the evidence chain. If a genuinely new unjoinable artifact appears,
    it is added here deliberately, with a producer read at source, or not at all.
    """
    expected = ('numerical_licence',)
    found = tuple(kind for kind, spec in ARTIFACTS.items() if not spec['joinable'])
    if found != expected:
        raise InterfaceRefusal(
            'interface:unjoinable-set-changed',
            'the set of artifacts with no readable join is %r and this module was written against '
            '%r; an unjoinable artifact is a claim about the evidence chain and is not reported '
            'from an unreviewed table' % (found, expected), repr(found), repr(expected))
    return {kind: ARTIFACTS[kind]['no_join_reason'] for kind in found}
