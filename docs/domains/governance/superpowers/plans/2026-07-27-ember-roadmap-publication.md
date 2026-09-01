# Ember Roadmap Publication and Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the twelve canonical Ember milestone contracts and reconcile
every open issue into one reproducible, version-controlled public roadmap.

**Architecture:** Version-controlled Markdown and JSON are authoritative.
Python validators enforce clause conservation and complete issue coverage.
GitHub milestones, parent issues, labels, subissues, and dependencies are an
idempotent projection applied only from a validated manifest after the carrier
lands.

**Tech Stack:** Markdown, JSON Schema-style closed validation in Python 3,
GitHub REST/GraphQL through the repository's safe wrappers, Git, pytest/unittest.

## Global Constraints

- Preserve the authority of `INVARIANT.md` and `GOAL.md`.
- Publish `EMBER-00` through `EMBER-11` near-verbatim without host-private
  paths, founder-private instructions, or unexplained internal shorthand.
- Give every normative milestone statement a stable clause ID.
- Account for every live open issue exactly once without closing any issue.
- Treat uncertain, historical, mixed, or apparently completed issues as open
  until current-master clause evidence proves otherwise.
- Use one managed worktree and one repository carrier.
- Apply remote changes only through safe GitHub wrappers.
- Make mutation idempotent and publish a content-addressed receipt.

---

### Task 1: Freeze sources and public census

**Files:**
- Create: `manifests/roadmap/source-contracts-v1.json`
- Create: `manifests/roadmap/public-issue-census-v1.json`

**Interfaces:**
- Consumes: twelve local canonical `goal.md` files and live GitHub state.
- Produces: exact source SHA-256 values and a complete open-issue snapshot
  bound to repository, master SHA, capture time, and pagination counts.

- [ ] Capture the twelve source hashes and section inventories.
- [ ] Fetch all open issues, excluding pull requests, with complete pagination.
- [ ] Capture existing milestones, labels, and open parent candidates.
- [ ] Verify issue numbers are unique and count matches an independent query.
- [ ] Commit the immutable source and public-state inputs.

### Task 2: Publish the twelve milestone contracts

**Files:**
- Create: `docs/domains/governance/roadmap/README.md`
- Create: `docs/roadmap/milestones/EMBER-00.md` through `EMBER-11.md`
- Create: `manifests/roadmap/clause-crosswalk-v1.json`
- Modify: `GOAL.md`

**Interfaces:**
- Consumes: Task 1 source inventory.
- Produces: stable public clause IDs and a source-to-public relation for every
  normative or explicitly excluded operational clause.

- [ ] Copy each canonical contract without semantic reduction.
- [ ] Add plain-language title, purpose, outcome, term explanations, and clause
  IDs.
- [ ] Translate founder-private roles and local paths into durable public
  language.
- [ ] Record verbatim, translated, and non-normative-excluded relations in the
  crosswalk.
- [ ] Link the four-layer hierarchy from `GOAL.md`.
- [ ] Verify no source normative clause is missing or multiply mapped.

### Task 3: Define desired GitHub state

**Files:**
- Create: `docs/roadmap/execution-graph.json`
- Create: `manifests/roadmap/github-projection-v1.json`
- Create: `manifests/roadmap/issue-reconciliation-v1.json`

**Interfaces:**
- Consumes: public contracts and frozen issue census.
- Produces: twelve milestone definitions, twelve parent issue definitions,
  closed label definitions, dependencies, and exactly one disposition per open
  issue.

- [ ] Translate the current execution graph into public repository-relative
  paths and explain target milestone versus executable gate.
- [ ] Define twelve milestones and twelve canonical parent issues.
- [ ] Classify every open issue as `single_milestone`, `cross_cutting`,
  `mixed_historical`, or `evidence_pending`.
- [ ] Preserve mixed historical issues and describe any successor split without
  rewriting history.
- [ ] Encode intended labels, subissue links, and dependencies.
- [ ] Assert zero issue closures in the desired mutation set.

### Task 4: Build fail-closed validation

**Files:**
- Create: `scripts/roadmap/validate_roadmap.py`
- Create: `tests/roadmap/test_validate_roadmap.py`

**Interfaces:**
- Produces: `validate_repository(root: Path) -> dict[str, object]` and a CLI
  returning nonzero on stale snapshots, missing clauses/issues, duplicate
  mappings, unknown milestones, invalid dependencies, or closure mutations.

- [ ] Write negative tests for every failure class.
- [ ] Run the focused suite and witness RED.
- [ ] Implement closed validation and deterministic canonical hashing.
- [ ] Run focused tests GREEN.
- [ ] Validate the real repository artifacts.

### Task 5: Build idempotent projection tooling

**Files:**
- Create: `scripts/roadmap/apply_github_projection.py`
- Create: `tests/roadmap/test_apply_github_projection.py`

**Interfaces:**
- Consumes: validated projection and current GitHub state.
- Produces: a deterministic mutation plan or applies it through injected safe
  GitHub operations; never closes issues.

- [ ] Write tests for create, exact-match no-op, drift refusal, duplicate
  refusal, partial failure, and second-run zero-mutation behavior.
- [ ] Run tests RED.
- [ ] Implement dry-run planning and apply mode with exact before-state checks.
- [ ] Run tests GREEN and produce the pre-landing dry-run plan.

### Task 6: Review and land the repository carrier

**Files:**
- Modify only artifacts named in Tasks 1-5 plus the approved design/plan.

- [ ] Run focused tests, repository validator, syntax checks, and diff-check.
- [ ] Commit intentional bounded increments.
- [ ] Push the exact branch through `git-safe.ps1`.
- [ ] Open one draft PR and publish exact source/census/validation evidence.
- [ ] Resolve concrete review findings without reducing scope.
- [ ] Verify immutable head, repository guards, and clean replay.
- [ ] Merge the accepted carrier and verify public master.

### Task 7: Apply and prove the GitHub projection

**Files:**
- Create: `receipts/roadmap/roadmap-publication-v1.json`

- [ ] Refresh live state and refuse if master or issue population drifted.
- [ ] Apply twelve milestones, twelve parent issues, labels, relationships, and
  dependencies from the landed manifest.
- [ ] Re-run in dry-run mode and require zero semantic mutations.
- [ ] Verify every open issue is represented exactly once and none was closed.
- [ ] Commit and land the content-addressed execution receipt.
- [ ] Retire the carrier branch, worktree, and temporary artifacts through the
  lifecycle manager.
