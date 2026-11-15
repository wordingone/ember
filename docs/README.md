# Documentation map

Ember changed direction after most of these pages were written. This page says which pages describe
what Ember is now, which describe the earlier 3B lineage and still stand as record, and which are
archive. The [root README](../README.md) is the front door and says what Ember is now.

The checked navigation by audience, task and domain is the [canonical map](domains/governance/DOCS-README.md).
The machine-generated list of entry pages is the [generated index](INDEX.md). This page adds labels and
changes neither.

## Current

These pages describe how the repository works today.

- [Root README](../README.md): the four parts of Ember.
- [Status](STATUS.md): what runs today, what is a hypothesis, with test dates, and the 3B history.
- [System overview](architecture/system-overview.md): the adopted domains and their boundaries.
- [Glossary](GLOSSARY.md) and the [verification guide](guides/VERIFY.md).
- [Contributing](contributing.md) and the [operator documentation](domains/governance/operator/README.md).
- The eight domain overviews, listed in the [canonical map](domains/governance/DOCS-README.md#technical-domains).
- [Continuity](domains/governance/authority/CONTINUITY.md) owns exact mutable state. Its training
  status is about the earlier 3B lineage.

## Authority, still binding

These pages bind the records written under them. They were written for the 3B lineage and have not
been revised for Ember 27B A3B.

- The [goal](domains/governance/authority/GOAL.md), the [invariant](authority/INVARIANT.md) and its
  [successor](authority/INVARIANT-v2.md), and the [succession record](authority/SUCCESSION-2026-11-07.md).
- The [roadmap](domains/governance/roadmap/README.md) and its milestone contracts.

## Earlier 3B plan, kept as record

These pages were written for the 3B from-scratch lineage, which has ended. Read them as the plan that was.

- The [overview for reviewers](OVERVIEW.md) and the [start page](domains/governance/guides/START-HERE.md).
  Each carries a banner saying so. Their identity sentences are older than the root README.
- The [anatomy set](domains/governance/anatomy/00_INDEX.md), including the
  [model card](domains/governance/anatomy/14_MODEL_CARD.md). The set is a target contract for the 3B model.
- The [restart contracts](domains/governance/ember-restart/ember-restart-3b-namespaces.md) for the 3B run.

## Reference and archive

Reference pages explain or support work and do not govern by themselves. Archive pages are visible
historical record and never current instruction.

- Archive: the [pre-restart archive](domains/governance/archive/pre-restart/20260617-maximally-viable-product.md)
  and the [goal archive](domains/governance/archive/goal/goal-archive.md).
- Reference: the [research notes](domains/governance/research/README.md), the
  [audits](audit/class2-unwatched-mandates-recon-20260704.md) and the dated
  [plans](domains/governance/superpowers/plans/).
- The receipts, ledgers and checkpoints of the 3B lineage stay in the repository tree. Nothing is deleted.

## What is not here

The transplant paper, the Ember 27B A3B architecture notes and the experiment queue are not in this
repository yet. The root README names which parts of that work are established and which are
hypotheses.
