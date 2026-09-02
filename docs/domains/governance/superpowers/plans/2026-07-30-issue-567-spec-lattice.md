# Issue 567 Spec-Lattice Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ember-cli spec nodes fail-closed and require newly added components to carry an exact consumer-bound spec update.

**Architecture:** A small shared Python policy module parses spec nodes and evaluates trusted base-versus-subject paths. The docs freshness checker and trusted base-pinned live PR policy call that module, avoiding duplicate rules and candidate-owned authority.

**Tech Stack:** Python 3.12, `unittest`/`pytest`, trusted and hostile GitHub checkouts, Markdown metadata lines.

## Global Constraints

- Keep the existing Dependabot schema unchanged.
- Execute no candidate-owned code from the write-capable or base-trusted policy path.
- Treat invalid UTF-8 and malformed metadata as terminal.
- Preserve the already-corrected stale document bytes unless a consumer-binding line is required.

---

### Task 1: Fail-closed spec-node parser

**Files:**
- Create: `src/ember/governance/scripts/ember_cli_spec_policy.py`
- Create: `tests/domain-governance/test_ember_cli_spec_policy.py`

**Interfaces:**
- Produces: `load_spec_nodes(repo_root: Path) -> list[SpecNode]`
- Produces: `validate_added_component_coverage(repo_root: Path, changed_files: Sequence[Mapping[str, str]]) -> list[str]`

- [ ] Write tests using real temporary files for strict UTF-8, status cardinality, current-node consumer requirements, unsafe paths, missing files, and complete valid nodes.
- [ ] Run `python -B -m pytest -q tests/domain-governance/test_ember_cli_spec_policy.py` and confirm failures because the module does not exist.
- [ ] Implement the minimal parser and validator.
- [ ] Re-run the focused tests and require a clean pass.

### Task 2: Freshness integration

**Files:**
- Modify: `src/ember/governance/scripts/check_docs_freshness.py`
- Modify: `tests/domain-governance/test_docs_freshness_observational.py`
- Modify: `src/ember/infrastructure/tools/ember-cli/specs/services-prompt-suggestion.md`

**Interfaces:**
- Consumes: `load_spec_nodes`
- Produces: `DocsFreshnessChecker.check_ember_cli_specs()`

- [ ] Add a real fixture test proving a shipped node without a consumer creates a deterministic defect and a bound node passes.
- [ ] Run the new test and confirm the missing-check failure.
- [ ] Call the shared parser from `run_all_checks()` and convert policy errors into freshness defects.
- [ ] Add the exact shipped consumer paths to the existing prompt-suggestion spec.
- [ ] Run the focused docs and spec-policy suites.

### Task 3: Trusted live-PR enforcement

**Files:**
- Modify: `src/ember/governance/scripts/github/live_pr_policy.py`
- Create: `src/ember/governance/scripts/github/test_live_pr_spec_floor.py`
- Modify: `src/ember/governance/scripts/github/test_live_pr_workflow_integration.py`
- Modify: `.github/workflows/repo-policy-gate.yml`

**Interfaces:**
- `validate_added_component_coverage_between_roots(base_root, subject_root, changed_files)` derives additions from exact filesystem state.
- `validate_live_pull_request(..., base_root, subject_root)` invokes exact coverage only at the trusted base-pinned boundary.

- [ ] Add real policy tests for an added component without a spec, an added component with an exact consumer-bound changed spec, and a missing subject root.
- [ ] Run the tests and confirm the validator does not yet accept the base/subject inputs.
- [ ] Derive additions from trusted base absence and hostile-subject presence; never import candidate policy code.
- [ ] Pass both roots from the required base-pinned workflow.
- [ ] Re-run all `scripts/github/test_*.py` tests.

### Task 4: Exact verification and publication

**Files:**
- Verify all changed files above.

- [ ] Run focused tests, `python -B src/ember/governance/scripts/check_docs_freshness.py --repo .`, `python -B src/ember/governance/scripts/github/workflow_policy.py --root .`, and repository guard.
- [ ] Confirm `git diff --check`, exact scope, and clean generated state.
- [ ] Commit, push, open the canonical self-review PR, obtain exact-head review, and require `guard`, `compiled-lifecycle`, and `ci-pr`.
- [ ] Squash merge, verify trusted `ci-main`, recapture issue #567, execute the trusted close-half only if every issue clause is proven, and record rollback evidence.
