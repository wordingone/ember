# Issue 567 Spec-Lattice Enforcement Design

## Outcome

Close the remaining enforcement gap in issue #567 without creating a general documentation
program. The two proven stale documents are already corrected on public master. This change makes
the ember-cli spec directory a deterministic, fail-closed freshness surface and requires newly
added ember-cli components to carry a consumer-bound spec node.

## Contract

Every Markdown file under `tools/ember-cli/specs/` must decode as strict UTF-8 and declare one
top-level `Status:` line. A `CURRENT` or `SHIPPED` node must also declare one or more repository-root
relative `Consumer:` paths. Each named consumer must be normalized, remain inside the repository,
and exist as a file. `OPEN` nodes may name planned files but cannot be represented as current.

The trusted live PR policy consumes GitHub's complete changed-file names, the base-pinned policy
checkout, and the pull-request merge subject checked out as hostile data. It derives an addition
only when a TypeScript source path under `tools/ember-cli/src/components/`,
`tools/ember-cli/src/screens/`, or `tools/ember-cli/src/services/` is absent from the trusted base
and present in the subject. The PR must also change at least one Markdown spec node whose validated
consumer set includes every added component path. No candidate-owned policy code is imported or
executed. Dependabot remains governed by its narrower existing schema.

## Components

`src/ember/governance/scripts/ember_cli_spec_policy.py` owns strict spec parsing, consumer-path normalization, and
new-component coverage. It has no network access and accepts only caller-supplied paths and
repository roots.

`src/ember/governance/scripts/check_docs_freshness.py` calls the same parser over the complete ember-cli spec directory,
so scheduled/local freshness checks include the operator-visible body.

`scripts/github/live_pr_policy.py` invokes the trusted parser with separate base and subject roots.
The base-pinned repository guard therefore evaluates candidate spec data and component existence
without trusting GitHub status strings or executing candidate-owned policy code.

## Failure semantics

Invalid UTF-8, a missing or duplicate status, missing consumer binding on a current node, an unsafe
consumer path, a missing consumer file, malformed changed-file paths, or an added component without
an exact changed spec consumer is terminal. A missing base/subject root or a changed component path
missing from both roots is also terminal. No warning-only path exists for these conditions.

## Verification

Tests first prove the current code fails to reject missing consumer bindings and added components
without matching specs. Green tests exercise real temporary repositories and the real live-policy
validator. Existing docs-freshness, live-PR-policy, workflow-integration, and repository guards
must remain green. No issue closure occurs until exact-head checks and trusted post-merge CI pass.
