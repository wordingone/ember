<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Work Policy

Version: `ember-work-policy/v1`

This is the binding repository policy for issues, pull requests, commits, and
work decomposition. Mechanical validation proves structure, not truth.

## Issues

An issue is a durable specification, investigation, experiment, governance
decision, or maintenance obligation with an independently meaningful terminal
condition. Every open issue has exactly one `kind:*`, one to three `area:*`,
exactly one `state:*`, one primary milestone, an explicit out-of-scope
boundary, required evidence, a claim boundary, and a terminal disposition.

Kinds are initiative, defect, feature, enhancement, engineering, research,
experiment, model behavior, maintenance, documentation, governance, and
release. An initiative coordinates multiple independently closable outcomes.
A defect restores promised behavior. A feature creates a new capability. An
enhancement measurably improves existing behavior. Research answers a
falsifiable question; an experiment executes a preregistered treatment/control
comparison. Receipt-only rewrapping is not a new experiment.

Do not create issues merely to decrement a counter, narrate a commit, run a
single already-governed command, or split homogeneous mechanical repair into
one item per file. Preserve the parent outcome and batch homogeneous repairs.

## Pull requests

A pull request delivers one coherent independently reviewable outcome. It must
bind an exact base and reviewed head, link the governing issue or document a
narrow exception, map acceptance clauses, state evidence and unverified areas,
record review provenance, bound claims, and include rollback.

A closing keyword is allowed only when every acceptance clause is explicitly
mapped and no unresolved clause is silently transferred. Age, inactivity,
superficial textual similarity, labels, or code landing alone never authorize
closure.

Batch homogeneous repairs when they share one mechanism, evidence class, and
rollback boundary. Split only when review, authority, or rollback boundaries
are materially independent.

Receipt-only work may be a PR when it establishes a new independently useful
proof or custody boundary. Pure metadata reformatting belongs with the outcome
that needs it.

## Commits

A commit communicates one actual change in imperative language, contains no
false completion claim, and remains bisectable. Generated evidence may accompany
the implementation it proves. Temporary probes and local paths are not public
history.

## Authority and claims

Labels and template sections record repository state but do not prove claims.
Exact-head review, content-addressed evidence, admission, scientific controls,
and operator authority remain separate. Automation is fail-closed and may not
self-grade untrusted code under write authority.
