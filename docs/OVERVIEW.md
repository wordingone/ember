# Ember in plain words: an overview for reviewers

This page is for a reader who has not worked on Ember and wants to know, in about ten minutes, what
the project is, what it has measured, what it has not achieved, and how to read its research record.
It summarizes other pages and links to them; where this page and a linked page disagree, the linked
page governs. Nothing here is new evidence.

**Status of this page.** Written on 2026-11-04 from the public tree at master commit
`df2a2d69603ffe8c1eca0faa54eb44837a0bd9b3` (the newest master commit, dated 2026-10-10). The newest
research events published in this repository are dated 2026-10-07. Work has not continued on master
since 2026-10-10, so read every "current" statement below as "as of that record".

## What Ember is

Ember is an attempt to build an AI model from scratch on one home computer with one consumer graphics
card (an NVIDIA RTX 4090 with 24 GB of memory), and to run it locally. "From scratch" means no borrowed
model weights, no teacher model and no judge model: every weight is to be learned here
([project front door](../README.md)). The work is organised as twelve milestones, from "the project
has one consistent definition" to "another person can independently own and continue the whole
system" ([public roadmap](domains/governance/roadmap/README.md)).

The milestone that matters for the model is the third one, called EMBER-02, "Three-billion-parameter
foundation birth": the first model that may be called Ember must have at least three billion
parameters, handle text, images and audio natively, reason, and use tools in a structured way
([EMBER-02 contract, Outcome](domains/governance/roadmap/milestones/EMBER-02.md#outcome)). It counts
as achieved only when a checkpoint passes all thirteen items of a public, independently replayable
certificate, which include benchmark floors relative to frozen reference models
([EMBER-02 contract, Completion certificate](domains/governance/roadmap/milestones/EMBER-02.md#completion-certificate)).

The repository also contains `ember-cli`, a terminal tool used to run and watch the training, and an
experiment lab. The code and research records were largely written by AI coding agents under the
owner's direction: of the newest 50 master commits (counted 2026-11-04 from `git log`), 49 carry an AI
coding-agent session or co-author line, and the research log attributes individual rulings to agent
"seats" ([research journal](domains/lab/research/journal.md.txt)).

## What has been achieved, and what has not

**Achieved and certified: the evidence spine, not a model.** The second milestone, EMBER-01
("Custody, identity, and experiment spine"), has a public certificate dated 2026-08-05
([certificate](domains/governance/roadmap/certificates/EMBER-01.md)). It certifies that artifacts,
experiments and claims resolve through one identity and receipt system. It explicitly grants no model,
training, benchmark or capability credit, and some of its legs can only be checked on the operator's
machine, not from a fresh clone ([continuity page](domains/governance/authority/CONTINUITY.md)).

**Not achieved: there is no admitted Ember model.** No checkpoint has passed the EMBER-02 certificate.
The roadmap lists no certificate for EMBER-02 or any later milestone
([roadmap table](domains/governance/roadmap/README.md#milestones)). The 3-billion minimum and the
above-27-billion destination are goals, not measurements of an existing model
([continuity page](domains/governance/authority/CONTINUITY.md)). The model card says the same: it
describes a target contract and makes no capability claims
([model card](domains/governance/anatomy/14_MODEL_CARD.md)).

**Not shown: benchmark ability.** The protected image-question benchmark used as a gate (MMMU) never
cleared its floor of 0.2857; the best recorded score was 0.285 and the newest 0.263. The journal also
records that, until 2026-09-27, the "missing image" and "wrong image" control runs used an evaluator
that ignored the image condition, so whether the model used the images at all was never measured
([journal, historical state and standing lessons](domains/lab/research/journal.md.txt)).

**A data-lineage caveat.** A July 2026 audit found that the earlier model line ("cbase") was trained
on a corpus whose largest prose source, FineWeb-Edu, had been selected by a classifier trained on
annotations from another company's model (Llama-3-70B-Instruct), and marked that line as not clean
([genesis audit](../receipts/genesis/genesis-audit-20260706.md)). A later corpus-cleaning record
documents dropping that source; the model card states that whether an equivalent clean-only corpus
was completed for the current three-billion-parameter contract is not established by that document
([model card, Training data](domains/governance/anatomy/14_MODEL_CARD.md)). Since 2026-10-03 the
project's policy also admits marked, licence-checked, separately counted published datasets that
contain AI-generated material ([training-data origin policy](domains/governance/roadmap/milestones/EMBER-02.md#training-data-origin-policy)).
This page therefore does not describe any lineage as certified clean.

## What has been measured

Most measurement in this repository is about the training system, not about model ability.

**Training speed on one card.** The largest research campaign (GitHub issue 1945, "Training
throughput on a single 4090") set six gates that one run must clear together: two speed gates of more
than 80,000 trained token positions per second (one over at least 1,024 warmed updates, one over a
continuous hour), a no-worse-learning check, the protected benchmark floor, a frozen data mixture, and
honest single-card accounting. Fourteen numbered attempts were made; none was accepted. On the newest
(attempt 14) the hour ran at 61,740 positions per second against the 80,000 target; three of the six
gates were met (no-worse learning, frozen mixture, accounting) and three were not (both speed gates
and the benchmark floor). Earlier attempts 7 to 9 met both speed gates on an earlier data mixture
(best 86,662.5 per second over the hour) but failed the benchmark gate; the mixture that brought the
benchmark closest lost the speed gates
([journal, historical state](domains/lab/research/journal.md.txt);
[campaign ledger](domains/lab/research/campaign.md.txt);
[issue 1945](https://github.com/wordingone/ember/issues/1945)).

**Hour-long continued training.** A later line of work (GitHub issue 2119, "Make retained EMBER-02
training the default GPU workflow") ran hour-long training segments that continue one checkpoint
lineage, scored each child checkpoint on held-out loss, and promoted or refused it by a rule written
before the score was read. For example, the newest entry promotes a child whose held-out loss was
4.8003 against its parent's 4.8278, and in the same sentence records that the run-to-run spread (0.2086)
is larger than that difference, "so not evidence of improvement"
([journal, newest log entry](domains/lab/research/journal.md.txt);
[issue 2119](https://github.com/wordingone/ember/issues/2119)). The continuity page lists further
hour results as owner-reported, bound to private receipts by hash, and not reproducible from this
checkout ([continuity page, dated training status](domains/governance/authority/CONTINUITY.md)).

**How much was tried.** The published research export contains 537 recorded hypotheses and 371
attempt-registry rows. Counting the final ruling of each hypothesis in that file gives 228 supported,
201 refuted, 50 inconclusive and 58 closed without a ruling (counted by the author of this page from
[`docs/domains/lab/research/export/research-index.json`](domains/lab/research/export/research-index.json);
the file states it is a selected subset, not the complete research history).

**Where the measurements live, and their limit.** Many figures above were produced on the operator's
machine. The research site names their source files as "seat record: ..." and gives their hashes, but
most receipt files are not in this public repository, so a reader can check that the published pages
are consistent with each other, not re-run the measurements
([how the research pages are made](domains/lab/research/method.html)).

## How to read the research log

The research record is a small static site generated from three records kept on the operator's
machine: an attempt registry, a hypothesis loop log, and a few named receipts. It is in
`docs/domains/lab/research/`. The `.html` files are the rendered pages (open them in a browser after
cloning; GitHub shows their source); the `.md.txt` files are readable as text on GitHub.

1. **Start with the journal** ([`journal.md.txt`](domains/lab/research/journal.md.txt)). Read
   "Historical #1945 state" (the six-gate table), then "Standing lessons", which lists mistakes the
   campaign made more than once, then the log, newest first.
2. **Read one log entry in four parts.** *Hypothesis* is the claim and the mechanism it proposes.
   *Frozen criterion* is the rule, written before the measurement, that would make the claim REFUTED.
   *Ruling* is what the measurement said against that rule: SUPPORTED, REFUTED or INCONCLUSIVE.
   *Receipt* names the evidence file (often host-local, so not public). A "PROMOTE" or "REFUSE" in a
   ruling is a separate checkpoint-acceptance decision under its own frozen policy.
3. **Expect corrections to stay visible.** Refuted and withdrawn results are kept, not deleted, with a
   list of what they do not close; a later attempt that replaces one names it as its successor
   ([hypothesis ledger](domains/lab/research/hypotheses.html)). One example: a registry row dated 2026-09-15
   records that a profiling probe never actually ran the captured (CUDA-graph) execution path it was
   meant to measure; later rows state which readings from that trace survive (kernel counts) and which
   do not (idle and dispatch time), and re-measure on the captured path.
4. **Use the campaign ledger for history** ([`campaign.md.txt`](domains/lab/research/campaign.md.txt)),
   which summarises the throughput campaign to 2026-09-27 by gate, with a source in brackets for every
   claim.
5. **Use the structured export for counts**
   ([`research-index.json`](domains/lab/research/export/research-index.json)); its `coverage` section
   says which fields were left out and why.

Words used on those pages: *diagnostic* means a measurement that explains where time goes but earns
no progress credit; *governed* means a run under the full accounting contract whose number can count;
*admitted* means accepted by the governing verifier and independent review for the exact claimed use
([glossary](GLOSSARY.md)).

## If you want to check something yourself

The smallest check needs no GPU, weights or credentials and grants no model capability:

```text
python src/ember/governance/scripts/verify_authority_conservation.py --root .
```

The [verification guide](guides/VERIFY.md) lists the full public replay set and expected results. For
exact current identities, use the [continuity page](domains/governance/authority/CONTINUITY.md), which
is the one page that owns mutable project state.
