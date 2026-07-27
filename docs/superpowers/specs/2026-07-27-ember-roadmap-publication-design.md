# Ember Roadmap Publication and Reconciliation Design

## Purpose

Make Ember's complete milestone decomposition publicly readable without
creating another competing roadmap. Preserve the scope of the twelve canonical
local milestone contracts while translating founder-private operations,
machine-local paths, and unexplained internal shorthand into public language.

## Authority hierarchy

The public hierarchy has exactly four layers:

1. `INVARIANT.md` and `GOAL.md` retain their existing authority.
2. `docs/roadmap/milestones/EMBER-00.md` through `EMBER-11.md` are the
   authoritative milestone decomposition below `GOAL.md`.
3. `docs/roadmap/execution-graph.json` describes current scheduling,
   prerequisites, and parallel work; it does not redefine outcomes.
4. GitHub issues and pull requests describe concrete work and evidence; they
   do not become independent roadmap authority.

GitHub milestones and canonical tracking issues are navigational projections
of these version-controlled files.

## Contract publication

Each milestone specification preserves the canonical outcome, starting truth,
required work, prohibited substitutions, completion certificate, and reopening
rules. Every normative statement receives a stable clause identifier.

Founder names, local drive paths, session instructions, and temporary agent
allocation are translated into durable public roles or excluded as
non-normative execution metadata. Every exclusion is explicit in the
source-to-public crosswalk. Technical terms remain where needed, but the first
use is explained in ordinary language.

## Reconciliation model

The reconciliation manifest records every open issue in one and only one
primary disposition:

- `single_milestone`: the whole remaining contract belongs to one milestone;
- `cross_cutting`: the issue remains standalone and names every affected
  milestone;
- `mixed_historical`: the original remains preserved while separable
  successor work is represented explicitly;
- `evidence_pending`: apparent completion or duplication is not accepted
  without current-master clause evidence.

No disposition closes an issue. Closure remains a later evidence-bearing
operation under the drainage program.

## Reproducible mutation

Repository files define desired GitHub state: twelve milestones, twelve
canonical parent issues, labels, issue relationships, and dependencies. A
validator checks closed schemas, clause coverage, exact issue census coverage,
known milestone identifiers, dependency validity, and source snapshot binding.

After the repository carrier lands, a safe-wrapper migration command applies
only the validated desired state. It is idempotent: a second run performs zero
semantic mutations. A content-addressed receipt records the source commit,
manifest digest, public before/after state, mutations, refusals, and
idempotency replay.

## Completion boundary

Completion requires all twelve public contracts, a complete clause crosswalk,
one disposition for every live open issue, matching GitHub milestones and
parent issues, successful validation against the then-current public snapshot,
one landed repository carrier, an applied idempotent migration, and a public
execution receipt. No issue is closed merely to satisfy this publication goal.
