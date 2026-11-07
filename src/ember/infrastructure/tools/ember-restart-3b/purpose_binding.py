# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# Moved into the repo for prepare_hour.py (source sha256 47a527cdb8432106); only the docstring wording changed.
"""Training-job purpose binding for the CIA hour dispatch preparers (issue #2119).

The runner's identity key set is closed: an identity carrying a key the runner does not know is
refused ('measurement identity fields differ'), and once the runner REQUIRES training_job_purpose an
identity without it is refused the same way. So a preparer adds the purpose exactly when the runner
it prepares for requires it, detected on the loaded runner module itself (the function the runner
calls to validate it), never on a branch name or a date.

No default purpose is derived. A purpose is a claim about what the run is FOR (advance the lineage,
a retention-eligible experiment, or a diagnostic that must say why it does not advance), and a
guessed claim is the thing #2119 exists to stop. When the runner requires it and the caller did not
state it, the preparer refuses with the flag to add.
"""

PURPOSES = ('CONTINUE_TRAINING', 'RETENTION_ELIGIBLE_EXPERIMENT', 'DIAGNOSTIC')
EXPERIMENT_KEYS = ('training_experiment_protocol', 'training_experiment_continuation_rule')
DIAGNOSTIC_KEYS = ('training_diagnostic_question', 'training_diagnostic_non_advancement_reason',
                   'training_diagnostic_return_condition')
OPTIONAL_DIAGNOSTIC_KEYS = ('training_diagnostic_readiness_blocker',)


def add_arguments(parser):
    parser.add_argument('--training-job-purpose', choices=PURPOSES)
    for key in EXPERIMENT_KEYS + DIAGNOSTIC_KEYS + OPTIONAL_DIAGNOSTIC_KEYS:
        parser.add_argument('--' + key.replace('_', '-'))


def runner_requires_purpose(runner):
    return callable(getattr(runner, 'validate_training_job_purpose', None))


def apply(identity, args, runner):
    """Add the purpose and its companion strings to identity, or leave it untouched when the
    runner predates the purpose requirement. Refuses a stated purpose the runner cannot accept."""
    supported = runner_requires_purpose(runner)
    stated = {key: getattr(args, key) for key in EXPERIMENT_KEYS + DIAGNOSTIC_KEYS + OPTIONAL_DIAGNOSTIC_KEYS
              if getattr(args, key, None)}
    if not supported:
        if args.training_job_purpose or stated:
            raise SystemExit('REFUSE: --training-job-purpose given but the runner at --root does not '
                             'accept training_job_purpose (closed identity key set)')
        return identity
    if not args.training_job_purpose:
        raise SystemExit('REFUSE: the runner at --root requires training_job_purpose; pass '
                         '--training-job-purpose ' + '|'.join(PURPOSES))
    identity['training_job_purpose'] = args.training_job_purpose
    identity.update(stated)
    # The runner revalidates at execute time; running its own predicate here makes a missing
    # companion fail at prepare time, before any custody or card window is spent.
    runner.validate_training_job_purpose(identity, hour=bool(identity.get('hour')))
    return identity
