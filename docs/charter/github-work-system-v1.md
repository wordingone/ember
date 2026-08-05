<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember GitHub Work System v1

Status: implementation design for the repository-governance migration.

## Outcome

Ember's GitHub surface is one deterministic work system. Issues describe
durable outcomes, investigations, experiments, decisions, or maintenance
obligations. Pull requests deliver coherent outcomes and bind their claims to
an exact base and reviewed head. Labels are version-controlled orthogonal
metadata. Native milestones, sub-issues, dependencies, and closing links carry
relationships. CI separates fast pull-request evidence, post-merge truth,
scheduled diagnostics, and bounded operator campaigns.

This design preserves two proven boundaries:

- the trusted base-repository `guard` check continues to inspect untrusted
  pull-request bytes without executing them under write authority;
- the required `compiled-lifecycle` check continues to exercise the real
  Windows/ConPTY Ember CLI lifecycle and publish diagnostics.

Stable required check names remain unchanged until their successor workflows
have reported successfully and branch protection has been verified.

## Policy authority

The checked-in policy sources are:

- `.github/WORK_POLICY.md`
- `.github/LABEL_POLICY.md`
- `.github/TEMPLATE_POLICY.md`
- `.github/labels.yml`
- `.github/label-migrations.yml`

The manifests are machine-readable and closed: unknown fields, unknown labels,
invalid cardinalities, deprecated labels on open work, and ambiguous migration
rules fail validation. Human judgment may classify ambiguous historical work,
but it cannot silently change the deterministic rules.

## Deterministic enforcement

`scripts/github/policy.py` validates repository-owned policy artifacts and
GitHub work-item snapshots. It does not grade whether prose is true. It checks
structure, exact markers, label cardinalities, mutual exclusions, required
sections, closing-link acceptance mapping, claim boundaries, rollback
sections, and review provenance.

`scripts/github/labels.py` owns label audit, planning, application, and
verification. Every operation accepts or emits content-addressed JSON. Apply
mode is explicit, uses an exact before-state digest, preserves associations,
refuses ambiguous mappings, and will not delete a label that remains in use.
Issue bodies and acceptance clauses are never rewritten by label migration.

## Workflow architecture

### Required landing gates

- `repo-policy-gate.yml` keeps the stable `guard` job and extends its trusted
  kernel with deterministic policy validation.
- `cli-windows-lifecycle-e2e.yml` keeps the stable `compiled-lifecycle` job.
- `pr-policy.yml` reports structural work-item policy for every pull request.
- `ci-pr.yml` is an always-triggered aggregate landing gate. Optional
  language jobs may skip only where the workflow declares that boundary; the
  aggregate itself reports and becomes a protected required context after its
  first successful corrective-head run.

### Pull-request evidence

Language-specific reusable work is invoked only when relevant:

- Python compile, focused unit, and changed-artifact checks;
- Rust format, check, and unit tests for `runtime/ember-lab`;
- Bun type/build/unit checks for `tools/ember-cli/src`;
- documentation, workflow-schema, and template validation;
- bounded integration checks.

Privileged workflows never execute pull-request code. Actions are pinned to
immutable commit SHAs, permissions are minimal, jobs have timeouts, and
concurrency cancels superseded unprivileged work.

### Default-branch and scheduled truth

- `ci-main.yml` runs broader clean-checkout verification after merge.
- `ci-nightly.yml` runs extended behavioral, dependency, performance, and
  repository audits without making branch activity a correctness signal.
- `repo-health-report.yml` publishes measurements rather than treating quiet
  trunk time as failure.
- `branch-inventory.yml` is read-only and reports candidates; it never
  deletes branches.

### Bounded campaigns

The existing oldest-issue and remote-branch capture workflows become named
`ops-*` campaigns with owner, finite scope, completion evidence, and retirement
conditions. They remain non-authorizing and cannot close issues or delete refs.

## Migration transaction

The migration is one rollback boundary:

1. capture repository settings, protections, labels, milestones, open work,
   representative closed work, workflows, runs, and branch inventory;
2. hash the canonical pre-migration snapshot;
3. validate policy sources and generate a deterministic label/work-item plan;
4. apply only deterministic label operations using the exact snapshot digest;
5. classify every open issue and pull request from its body, comments,
   milestones, relationships, and existing evidence—not its title alone;
6. use native relationships only where the source and destination are
   unambiguous;
7. verify counts and write a content-addressed migration receipt;
8. land the implementation in one pull request;
9. enable/synchronize default-branch-only write workflows after merge;
10. update repository settings and required checks only after successor checks
    have reported;
11. capture and hash the post-migration snapshot.

Legacy issue bodies created on or before the immutable PR #1183 merge boundary
(`2026-07-29T18:40:52Z`) remain historical. Metadata events enforce canonical
label cardinality without forcing those bodies through the new issue-form
schema. New issues and deliberately rewritten legacy issues must use the
current form marker and schema.

All GitHub mutations are replayable from the plan and auditable from the
receipt. Rollback uses the migration commit/revert plus the before snapshot and
inverse label-association plan. No issue body is mass-rewritten.

## Claim boundary

This system proves repository metadata and automation conformance. It does not
prove that an issue's scientific claim is true, that a model capability exists,
that training was sufficient, or that a reviewer independently reproduced an
artifact. Those require their own evidence and exact-head review.
