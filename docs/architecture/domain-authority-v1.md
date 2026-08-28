<!--
goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
-->

# Ember domain authority map v1

Issue #1962 freezes the preparatory S1-S4 architecture contract. It does not move a
domain, establish a second implementation, or claim model, training, evaluation,
throughput, capability, or milestone credit.

## Decision

The checked-in authority is a compact declarative policy. A deterministic compiler
expands that policy against the exact Git tree into an exhaustive off-tree receipt.
The receipt, rather than a checked-in 4,520-row snapshot, lists every tracked path,
consumer, root, dependency edge, atomic touch set, conflict edge, carrier, and RED
baseline result. An independent verifier recomputes the expansion and the minimum
carrier proof from source and policy.

This design rejects two alternatives:

- A checked-in exhaustive path table would become stale on every unrelated path
  addition and would obscure the rules that produced its rows.
- Package-manager inference alone would omit documentation, workflows, hooks,
  installers, launchers, receipt consumers, mutable state, and external inputs.

## Ownership and dispositions

Every active tracked path has exactly one owner among Model, Data, Training,
Evaluation, Runtime, Lab, Infrastructure, and Governance. Every path also has exactly
one disposition: `MOVE`, `RETAIN_STABLE`, `MERGE`, `ARCHIVE`, `EXTERNALIZE`,
`DELETE_REDUNDANT`, or `DEFERRED_DEPENDENCY`.

Ordered policy rules are allowed for readability, but overlap is never precedence:
zero matches and multiple matches both fail. A more specific rule must explicitly
exclude its path from broader rules. Immutable receipt and manifest bytes are
`RETAIN_STABLE`; their producers, validators, indexers, and consumers remain eligible
for domain ownership and later movement.

Two deferrals are mandatory and visible:

- Data carrier membership is `DEFERRED_DEPENDENCY` until #1581's admitted data-plane
  identities are terminal and independently reviewed.
- Evaluation carrier membership is `DEFERRED_DEPENDENCY` until the Evaluation public
  API is stable and independently reviewed.

Each deferred row carries its issue, predicate, evidence selector, and failure state.
An undeclared or predicate-free deferral fails verification. Deferral classifies the
path today but cannot silently freeze its later carrier membership.

## Canonical roots and profiles

The policy declares typed roots for installation/source, application state, data,
model/checkpoint, cache, evidence, and worktrees. Code receives a resolved root bundle;
it does not infer a live root from caller CWD, a drive, a maintainer profile, or an
artifact identity string. Platform defaults live only in explicit local profiles.
External roots are input-only inventory and are never cleanup scope.

The Python backend remains `setuptools==84.0.0` from wheel
`setuptools-84.0.0-py3-none-any.whl` with SHA-256
`51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670`.
The sdist `setuptools-84.0.0.tar.gz` with SHA-256
`f4695c21257f0d9b537ec2692c941d02ee143b7cc1276941349a546573b2ef73`
and every substitute refuse. Rust and TypeScript/Bun declarations and replayable lock
authorities are explicit inputs to the same map.

## Census compiler

The compiler binds `git ls-files` and the exact source commit, then emits these
independently counted sets:

1. tracked paths and top-level roots;
2. Python imports, dynamic loaders, sibling imports, and `sys.path` mutations;
3. Rust crate/workspace declarations and dependency edges;
4. TypeScript/Bun package/workspace declarations and import edges;
5. workflows, hooks, installers, launchers, guards, and command references;
6. documentation links and command examples;
7. receipt, manifest, schema, configuration, and authority consumers;
8. mutable-state and generated-output references;
9. typed local roots and non-mutating external-root inputs.

Each consumer row binds consumer path, referenced path or interface, discovery class,
owner, disposition, and atomic touch-set ID. Unsupported syntax is a named census
finding, never silently ignored. The compiler refuses uncovered paths or consumers,
duplicate classifications, owner collisions, ambiguous roots, forbidden dependency
edges, unexplained cycles, path-string identities, and undeclared deferrals.

## RED baseline

Before topology changes, the compiler records honest `PASS`, `FAIL`, or `SKIP` results
for random clean-clone installation paths, spaces and non-ASCII paths, outside-CWD
invocation, operator-profile absence, native Windows, Linux CPU availability, declared
authority/import checks, exact wheel and substitution refusal, a tiny direct
Model-to-Runtime fixture, and the same fixture through Lab. A missing Linux runner or
missing domain API remains RED as `SKIP` or `FAIL`; no failure is manufactured and no
unexecuted leg is narrated green. Evaluation in this matrix is fixture semantics only.

## Conflict graph and minimum K

A node is one atomic authority-switch touch set: its authoritative implementation,
every active consumer, declarations, tests, documentation references, and rollback
unit. Nodes conflict when they share a path or consumer, cannot share one rollback
unit, would create a forbidden intermediate dependency, cross an unresolved deferral,
or exceed a named reviewability limit derived from the measured A0 canary.

Dependency precedence forms a directed acyclic order over nodes. The compiler performs
exact branch-and-bound coloring under that order, visiting stable node and color IDs in
lexicographic order. It emits:

- the complete graph and algorithm identity;
- K and ordered carrier membership;
- a K-color witness;
- a K-1 unsatisfiability certificate containing the exhaustive bounded search result;
- per-carrier consumer census, rollback unit, predecessors, and deferred exclusions.

The verifier independently recomputes both the witness and K-1 unsatisfiability. The
algorithm has a declared compute budget. If exact proof exceeds it, generation stops
with `EXACT_COLORING_BUDGET_EXCEEDED`; no heuristic or silent cap may replace it.

## Receipt and verification

The exhaustive receipt is written only to fresh dated no-overwrite custody. It uses the
project's raw/self convention: raw SHA-256 hashes exact file bytes; self SHA-256 hashes
canonical sorted compact JSON with `self_sha256` removed. It binds the source commit,
policy/schema/compiler hashes, all census counts, RED rows, graph, K proof, and every
generated carrier spec.

Checked-in tests plant negatives for an uncovered path, overlapping rules, omitted
consumer, forbidden edge, cycle, undeclared deferral, backend substitution, altered
graph or K, invalid K-1 certificate, non-lexicographic tie, and exceeded exact-search
budget. The green path reruns deterministically at the same commit. Repo guard,
authority conservation, focused tests, exact backend verification, and independent
exact-head review are terminal gates.

## Failure and rollback

Generation is read-only with respect to source and external roots. A failed census or
proof writes no terminal receipt. Preparatory declarations may be reverted as one
carrier; preserved RED and graph evidence remain immutable. No source cutover occurs in
#1962, so there is no partial old layout to restore.

