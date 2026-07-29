<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# GitHub Work System v1 Implementation Plan

## Phase 1: freeze and inventory

- Capture canonical live JSON for repository settings, branch protection,
  rulesets, labels, milestones, open issues, open pull requests, branches,
  workflows, recent runs, secrets names, variable names, and representative
  closed work.
- Record the exact public master SHA and content digest of the snapshot.
- Inventory every current workflow, invoked script, permission, artifact,
  required check, path assumption, and disposition.

## Phase 2: policies and schemas

- Add work, label, and template policies.
- Add a closed label manifest and complete old-label migration manifest.
- Add ten issue forms, ten pull-request templates, five review templates, and
  seven lifecycle comment templates.
- Add deterministic validators and unit tests before workflow integration.

## Phase 3: workflow migration

- Preserve `guard` and `compiled-lifecycle` check identities.
- Add always-reporting policy and PR-CI aggregation.
- Split fast PR, full main, nightly, health, security, GPU-receipt, and release
  rehearsal obligations only where current repository surfaces justify them.
- Convert capture workflows into finite `ops-*` campaigns.
- Pin actions, minimize permissions, add timeouts, and test workflow policy.

## Phase 4: dry-run and live metadata

- Run policy and label tests locally.
- Generate an exact live audit and mutation plan.
- Mechanically reconcile all open issues and pull requests.
- Apply deterministic label migrations and classifications.
- Verify no deprecated labels remain on open work and live definitions match
  the manifest.
- Add native relationships only where evidence is unambiguous.

## Phase 5: land and prove

- Apply the verified source patch to the managed Ember worktree.
- Run repository guard, focused policy tests, language CI, workflow validation,
  and the existing lifecycle acceptance.
- Commit coherently, push one branch, and open one migration pull request.
- Verify the exact head, required checks, and rollback instructions.
- Merge under delegated authority, synchronize labels/settings from master,
  retire the migration branch/worktree, and capture a post-migration snapshot.
- Publish the old-to-new workflow/label maps, tests, receipts, unresolved
  non-delegable actions, and explicit claim boundary.
