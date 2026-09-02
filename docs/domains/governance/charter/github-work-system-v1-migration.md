<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# GitHub Work System v1 Migration

Status: v1 scaffold landed; the corrective migration is in progress.

## Transaction boundary

This migration replaces Ember's label, template, workflow, work-object, and
native-hierarchy control plane as one rollback unit. It does not close issues,
change issue bodies, rewrite acceptance clauses, claim roadmap completion, or
claim model, training, benchmark, research, or capability progress.

Source master at migration start:
`8c350dfc3987234467c89ddd1e3f06134e9ab2c6`.

Content-addressed full snapshots are retained outside Git because they contain
the complete body and comment history:

- pre-apply snapshot:
  `de52e5dad679ac166a310c9628bd358829c53f2e9ef27aa61ff27c1a527f068d`;
- post-metadata snapshot:
  `92afc43824de239e562b3e4bb135d4fa77fb733f7a8edc493a78545bf0c10afa`.

The source-controlled manifests retain the per-item body/comment hashes,
before/after label plan, and native edge identities needed to replay or audit
the transaction without publishing the full discussion corpus.

## Pre-migration inventory

| Surface | Pre-migration state |
|---|---:|
| Open issues | 155 |
| Open pull requests | 0 |
| Remote branches | 66 |
| Labels | 31 |
| Registered workflows | 11 |
| Milestones | 26 |
| Rulesets | 0 |
| Repository Actions secrets | 0 |
| Repository Actions variables | 0 |

The personal repository supports milestones and native sub-issues but not
organization issue types/fields. Therefore `kind:*`, `priority:*`, and
`state:*` remain the authoritative fallback fields.

Master protection required `guard` and `compiled-lifecycle`, enforced for
administrators, with no force-push or deletion. The migration preserves both
stable check identities. Repository settings already enabled squash/rebase,
auto-merge, update-branch, secret scanning, push protection, and automatic
branch deletion after merge.

## Live metadata outcome

- 97 canonical labels now match `.github/labels.yml` exactly.
- All 13 deprecated definitions were retired after every open usage was
  replaced and 73 remaining closed-history associations were removed.
- GitHub's issue/PR event history, bodies, acceptance clauses, and closure
  states were preserved.
- The original 155-item assignment was machine-classified. It was not a
  semantic review and the former `FULL_BODY_AND_COMMENT_REVIEWED` claim is
  retracted.
- The corrective transaction reviewed every live P0/P1 and S0/S1 candidate
  against the captured title, body, and complete comment snapshot. Reviewer
  identity, source hashes, and per-item basis are recorded in
  `priority-semantic-review-v2.json`.
- Every remaining uncertain item is explicitly `state:triage` and
  `needs:review`; machine output cannot assign authoritative priority/severity.
- Every open issue has exactly one kind and state plus zero-to-three areas.
  Priority and, where applicable, severity are present only on semantically
  reviewed non-triage work.
- 123 native sub-issue edges are verified. Of those, 122 already existed and
  one missing edge was added. Cross-cutting work remains unparented rather
  than being forced into one inaccurate parent.
- No issue or PR was opened or closed by the metadata migration.

Authoritative receipts:

- label verification:
  `31def13e152d3ce73f28b94cf47b177750d98be90eab5ed4bd7cff043d637213`;
- open-work apply:
  `dafc0a475ce3da744ca5055a9bbd422954d767c1484923efb8e06799f04eecca`;
- native relationship apply:
  `a483f2b9eb14baece6a29927525865f2ca0ab3d00a37940cfc83f3ca13169166`;
- native relationship verification:
  `c8d09d4fefa09106724bd61cd7bbf5758d6a99bc13facb02620a53bdb852be44`;
- deprecated-label retirement:
  `d56d766160e22dfbdb06c5f29b5973b8c3cb4e21356d8efcd10e45e8d5fce68f`.

## Workflow old-to-new map

| Previous workflow | Disposition | Successor |
|---|---|---|
| `repo-guard.yml` | Replaced, stable required job preserved | `repo-policy-gate.yml` (`guard`) |
| `ember-cli-lifecycle-smoke.yml` | Replaced, stable required job preserved | `cli-windows-lifecycle-e2e.yml` (`compiled-lifecycle`) |
| `auto-merge-enable.yml` | Narrowed and hardened | `pr-auto-merge-enrollment.yml` |
| `freshness-monitor.yml` | Split by responsibility | `repo-health-report.yml`, `ci-nightly.yml` |
| `oldest-issue-disposition-capture.yml` | Finite campaign, not permanent CI | `ops-issue-disposition-baseline.yml` |
| `remote-branch-salvage-capture.yml` | Finite campaign, not permanent CI | `ops-branch-recovery-inventory.yml` |

Permanent workflows:

- repository, PR, label, issue-intake, and template policy gates;
- fast PR CI, full main CI, nightly diagnostics;
- Windows CLI lifecycle;
- health and branch-inventory reporting;
- action/dependency/CodeQL security;
- CLI build smoke;
- safe auto-merge enrollment.

Bounded workflows:

- `ops-issue-disposition-baseline.yml`;
- `ops-branch-recovery-inventory.yml`.

Each bounded workflow declares its campaign, owner, completion condition, and
retirement rule. Neither creates work merely to move a counter.

## Required checks and rules

The stable `guard` context now includes the trusted, base-pinned live PR
metadata policy. `compiled-lifecycle` remains the real Windows/ConPTY
lifecycle gate. The `ci-pr` aggregate becomes required only after it reports
successfully on the corrective head and branch protection is verified without
reducing any existing protection.

The `guard` path reads untrusted pull-request bytes without executing them
under write authority. Privileged workflows do not run pull-request code.
Every action reference is pinned to a full commit SHA, permissions are
explicit, and all jobs have timeouts.

## Security analysis

- Pull-request workflows receive read-only repository permissions unless a
  narrowly defined metadata mutation is required.
- Auto-merge enrollment is allowlist- and policy-gated; it does not weaken
  required checks or review provenance.
- Receipt validation remains owned by the repository guard; the false-green
  `gpu-receipt-verify` workflow was removed.
- Dependency review and CodeQL are separated from ordinary CI.
- Workflow policy rejects floating action references, missing timeouts,
  overbroad permissions, and privileged execution of pull-request code.
- No external repository's secrets, telemetry, federation, or proprietary
  workflow body was imported.

## Tests and evidence

The source transaction must pass:

- `python -B -m unittest discover -s scripts/github -p "test_*.py"`;
- `python -B src/ember/governance/scripts/github/workflow_policy.py --root .`;
- `python -B src/ember/governance/scripts/github/template_policy.py --root .`;
- repository guard in both policy and PR-context modes;
- real Windows/ConPTY lifecycle acceptance;
- applicable Python, Rust, Bun, and documentation gates selected by the new
  workflows.

The policy tests cover no-busywork rejection, linked outcomes and exceptions,
acceptance mapping on closing PRs, feature/enhancement distinction,
research/experiment distinction, receipt-only claim boundaries, homogeneous
repair batching, and the rule that trunk inactivity alone is not failure.

## Rollback

Source rollback:

1. revert the migration squash commit on `master`;
2. allow `guard` and `compiled-lifecycle` to validate the revert;
3. merge the revert under the same protected-branch rules.

Metadata rollback:

1. use `manifests/github-work-system-v1/open-work-review-plan-v1.json` to
   restore each issue's `before_labels`;
2. use `manifests/github-work-system-v1/label-migration-plan-v1.json` to
   restore prior definitions/usages where required;
3. remove only the one native edge whose receipt records it as newly added;
4. recreate deprecated definitions only if the source revert again makes them
   authoritative.

Do not bulk-close, delete issue history, or infer rollback from counts.

Legacy issue bodies created on or before the immutable PR #1183 merge boundary
(`2026-07-29T18:40:52Z`) are preserved historical records. Label, milestone,
or reopen events continue to enforce metadata cardinality but do not require a
body rewrite. Issues created after that boundary must carry the current form
marker and schema. A substantial body migration is a separately reviewed
change, never an incidental consequence of metadata maintenance.

## Claim boundary

This migration proves only the GitHub work-system structure and the recorded
live metadata transaction. It does not prove an issue's acceptance clauses,
roadmap completion, an owned checkpoint, sufficient pretraining, benchmark
quality, model capability, a research result, or release readiness.
