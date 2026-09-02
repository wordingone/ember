# GitHub Work-System Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Ember's checked-in and live GitHub work system truthfully enforce the policies claimed by PR #1183 after the separately merged label-sync containment.

**Architecture:** The protected `repo-policy-gate` remains the trusted, base-pinned kernel. It will fetch live pull-request metadata as inert JSON and run a closed validator from trusted base bytes; templates and issue forms will be validated through their real consumers; reporting-only workflows will be removed or renamed to their actual mechanisms; live issue corrections will be driven by a content-addressed semantic-review manifest rather than keyword inference.

**Tech Stack:** Python 3, YAML, GitHub Actions, GitHub REST API through `gh`, Git, unittest/pytest, repository guard.

## Global Constraints

- Exactly one remediation PR follows the already merged containment PR.
- Never execute pull-request-controlled code with write authority.
- Do not claim semantic review without reviewer identity, exact source snapshot, and classification basis.
- Preserve historical issue bodies through an explicit legacy policy.
- Live mutations must be deterministic, bounded, and independently reviewable.
- PR #1183 receives an append-only correction only after remediation lands and live verification passes.

---

### Task 1: Template and intake integration

**Files:**
- Create: `.github/PULL_REQUEST_TEMPLATE.md`
- Modify: `.github/PULL_REQUEST_TEMPLATE/*.md`
- Modify: `.github/ISSUE_TEMPLATE/01-defect.yml`
- Modify: `src/ember/governance/scripts/github/template_policy.py`
- Modify: `src/ember/governance/scripts/github/test_template_policy.py`
- Modify: `scripts/tests/test_check_pr_authority_binding.py`

**Interfaces:**
- Consumes: `check_pr_authority_binding.validate_pr_body(body, goal, outcome, workstreams)`
- Produces: ten type-specific templates and one default template that pass the literal authority contract; uncertainty-compatible defect intake.

- [ ] Add failing integration tests that render every template through the real authority validator and require a safe default template.
- [ ] Add failing tests proving the four uncertainty fields may be optional while substantive defect observations remain required.
- [ ] Run the focused tests and confirm the expected failures.
- [ ] Add visible literal authority lines to every template, add the default template, and narrow the form requirement policy.
- [ ] Run the focused tests to green.

### Task 2: Trusted live pull-request policy

**Files:**
- Create: `src/ember/governance/scripts/github/live_pr_policy.py`
- Create: `src/ember/governance/scripts/github/test_live_pr_policy.py`
- Modify: `.github/workflows/repo-policy-gate.yml`
- Modify: `.github/workflows/ci-pr.yml`
- Modify: `.github/auto-merge-exclusion.test.sh`

**Interfaces:**
- Consumes: a closed JSON snapshot of live PR metadata, fully paginated changed files, trusted GOAL.md authority, and the immutable base/head event values.
- Produces: a deterministic human-PR verdict or a narrow Dependabot verdict covering title, labels, milestone/exception, authority, acceptance, claim boundary, review provenance, rollback, actor, base/head, and changed paths.

- [ ] Add failing unit tests for valid human and Dependabot schemas and adversarial omissions, spoofed base/head, bot paths, titles, labels, milestones, and body sections.
- [ ] Confirm the tests fail because the validator is absent.
- [ ] Implement the closed validator without network access.
- [ ] Integrate trusted API acquisition into `repo-policy-gate` without executing hostile bytes; preserve `guard` as the required stable context.
- [ ] Run focused tests and workflow-policy audit to green.

### Task 3: Truthful workflow surfaces

**Files:**
- Delete: `.github/workflows/gpu-receipt-verify.yml`
- Delete: `.github/workflows/issue-lifecycle-sweep.yml`
- Move: `.github/workflows/branch-hygiene-audit.yml` to `.github/workflows/branch-inventory.yml`
- Move: `.github/workflows/release-rehearsal.yml` to `.github/workflows/cli-build-smoke.yml`
- Modify: corresponding workflow names, path filters, documentation, and workflow tests.

**Interfaces:**
- Produces: workflow names that match executed mechanisms and no duplicate or false-green required surface.

- [ ] Add failing policy tests for prohibited overstated workflow names and duplicate report-only lifecycle jobs.
- [ ] Confirm failures against current workflows.
- [ ] Remove the no-op receipt verifier and duplicate lifecycle workflow; rename inventory and build-smoke workflows.
- [ ] Run all workflow-policy tests and the complete workflow audit to green.

### Task 4: Semantic metadata correction

**Files:**
- Modify: `src/ember/governance/scripts/github/work_items_engine.py`
- Modify: `src/ember/governance/scripts/github/test_work_items.py`
- Modify: `.github/WORK_POLICY.md`
- Create: `manifests/github-work-system-v1/priority-semantic-review-v2.json`
- Modify: `manifests/github-work-system-v1/open-work-review-plan-v1.json`

**Interfaces:**
- Consumes: full live bodies/comments for every P0/P1/S0/S1 issue.
- Produces: `MACHINE_CLASSIFIED` for unreviewed rows and reviewer/source/basis-bound semantic classifications for the priority set; issues #286 and #894 are corrected first; uncertain rows return to triage with `needs:review`.

- [ ] Add failing tests that forbid heuristic output from becoming reviewed truth and require reviewer evidence for semantic status.
- [ ] Confirm failures.
- [ ] Implement honest review statuses and the explicit legacy-body policy.
- [ ] Fetch and semantically classify the complete priority set into the manifest; validate source hashes.
- [ ] Apply exact live label changes through the label engine/API and verify the live population.

### Task 5: Publish, review, merge, and live certification

**Files:**
- Create: `receipts/github-work-system/github-work-system-remediation-v2.json`

**Interfaces:**
- Produces: one immutable remediation PR, independent exact-head verdict, exact-head required checks, protected contexts `guard`, `compiled-lifecycle`, and `ci-pr`, post-merge live verification, and the append-only PR #1183 correction.

- [ ] Run all focused tests, repository guard, diff checks, and static workflow audit.
- [ ] Commit and push one remediation branch; open one PR using the corrected authority envelope.
- [ ] Obtain independent exact-head review across Actions security, templates, live metadata, required checks, and workflow truthfulness; repair every P0/P1.
- [ ] Require exact-head checks, merge, and add `ci-pr` to protected required contexts without dropping existing contexts.
- [ ] Verify live master, branch protection, workflows, labels, and metadata; publish the bounded receipt.
- [ ] Append the correction comment to PR #1183 linking containment/remediation and the final verified state.
