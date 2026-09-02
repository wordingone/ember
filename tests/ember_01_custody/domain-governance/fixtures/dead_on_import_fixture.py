# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deliberately dead-on-import fixture, owned by
tests/ember_01_custody/domain-governance/test_verify_c0_failure_class_ledger.py's collectability-gate
negative test.

This file exists ONLY to be permanently uncollectable by `pytest --collect-only`.
It owns its own deadness by construction, rather than borrowing a PRODUCTION
file's incidental dead-on-import behavior -- the predecessor fixture
(src/ember/governance/scripts/tests/test_screen792_bf16_momentum.py) did the latter and broke the
moment that production file was legitimately fixed for unrelated reasons
(#1751): a negative fixture bound to production brokenness fails the instant
someone fixes the production file, because it never actually owned its dead
subject.

Do not add real tests to this file, and do not "fix" it to make it
collectable -- that is exactly the failure mode this fixture exists to guard
against recurring.
"""

raise SystemExit(
    "dead_on_import_fixture: this file is deliberately dead on import; it "
    "exists only as the collectability gate's negative-fixture subject and "
    "must never become collectable"
)
