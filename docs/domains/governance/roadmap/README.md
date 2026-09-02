# Ember public roadmap

This directory makes Ember's complete milestone decomposition public without
creating a competing authority surface.

## One hierarchy, four surfaces

1. [`INVARIANT.md`](../../../authority/INVARIANT.md) is Ember's unamendable identity and
   [`GOAL.md`](../authority/GOAL.md) is its highest amendable authority.
2. The twelve [milestone contracts](milestones/) are the authoritative
   decomposition beneath `GOAL.md`.
3. [`execution-graph.json`](execution-graph.json) records current scheduling,
   prerequisites, and parallel work. It cannot change milestone outcomes.
4. GitHub issues and pull requests track concrete work and evidence. They do
   not become independent roadmap authority.

GitHub milestones and the twelve canonical roadmap-parent issues are
navigational projections of these files. A progress bar, merged pull request,
allocated parameter shell, smoke run, or closed child issue cannot substitute
for a milestone's completion certificate.

## Milestones

The [certificates/](certificates/) directory holds the public completion
record of each certified milestone. A milestone without a record there is not
certified, regardless of issue counts, progress bars, or closed children.

| ID | Public title | Depends on | Completion in plain language | Public certificate |
|---|---|---|---|---|
| [EMBER-00](milestones/EMBER-00.md) | Authority and totality lock | — | One non-contradictory public definition preserves Ember's entire intended destination. | — |
| [EMBER-01](milestones/EMBER-01.md) | Custody, identity, and experiment spine | EMBER-00 | Every relevant artifact, issue, experiment, benchmark, and claim resolves through one verifiable identity system. | [**CERTIFIED** 2026-08-05](certificates/EMBER-01.md) |
| [EMBER-02](milestones/EMBER-02.md) | Three-billion-parameter foundation birth | EMBER-01 | Ember first becomes a sufficiently trained, clean-genesis, native multimodal foundation model with reasoning and tool use. | — |
| [EMBER-03](milestones/EMBER-03.md) | Body, tools, and operator relationship | EMBER-02 | The owned model operates through Ember's real local body, tools, permissions, and configurable operator relationship. | — |
| [EMBER-04](milestones/EMBER-04.md) | Grounded memory, world model, and dreaming | EMBER-03 | Memory, learned environment prediction, replay, consolidation, and stateful reasoning produce verified model behavior. | — |
| [EMBER-05](milestones/EMBER-05.md) | Three-billion-parameter Verified Expert Accretion rung | EMBER-04 | Verified experience causes useful, persistent expert growth under matched causal controls. | — |
| [EMBER-06](milestones/EMBER-06.md) | Autonomous AI-research bootstrap | EMBER-05 | Ember repeatedly conducts bounded research cycles and transfers routine research burden from its founders. | — |
| [EMBER-07](milestones/EMBER-07.md) | Seven-billion-parameter hard rung | EMBER-06 | The owned system reaches and sufficiently trains the 7B rung without losing native capabilities or lineage integrity. | — |
| [EMBER-08](milestones/EMBER-08.md) | Fifteen-billion-parameter hard rung | EMBER-07 | The owned system reaches and sufficiently trains the 15B rung with verified scaling and causal evidence. | — |
| [EMBER-09](milestones/EMBER-09.md) | Owned model above twenty-seven billion parameters | EMBER-08 | Ember reaches the 30–35B destination on one 24 GiB GPU and competes honestly with frozen 27B/31B references. | — |
| [EMBER-10](milestones/EMBER-10.md) | General sovereign local AI laboratory | EMBER-09 | Ember's local laboratory creates a materially different clean-genesis intelligence of at least 3B parameters. | — |
| [EMBER-11](milestones/EMBER-11.md) | Independent local ownership and scientific release | EMBER-10 | Another person can independently own, operate, reproduce, study, and continue the complete Ember system. | — |

## Reading the contracts

The public contracts are rendered near-verbatim from the canonical milestone
files. Stable clause IDs make individual obligations addressable. The
[clause crosswalk](../../../../manifests/roadmap/clause-crosswalk-v1.json) records
the source and public digest of every normative block.

Four clauses containing machine-local paths were translated into public
language. Private staffing and session-routing sections were excluded as
non-normative execution metadata, with their source hashes and rationale
recorded explicitly. No outcome, required work, prohibition, completion
certificate, or reopening rule was removed.

## Historical issues

Older issues may resemble a former roadmap. They remain valuable evidence and
work records, but they do not override this hierarchy. The
[issue reconciliation](../../../../manifests/roadmap/issue-reconciliation-v1.json)
accounts for every issue that was open in the bound public snapshot:

- a whole single-milestone contract becomes a subissue of that milestone;
- a cross-cutting contract remains standalone and names every affected
  milestone;
- a mixed historical contract remains intact while its clauses are mapped
  losslessly; and
- an apparent duplicate or completion remains open until current-master
  evidence proves every acceptance clause.

This roadmap-publication operation closes no issues.
