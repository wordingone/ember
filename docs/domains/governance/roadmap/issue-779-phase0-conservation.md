# Issue #779 terminal conservation ruling

Status: `SUPERSEDED_NOT_PLANNED` for the named run; scientific obligation
preserved under issue #723.

Source master: `9d2704d3023c9c061727f90589480b1feb6b1b34`.

## What #779 authorized

Issue #779 authorized one specific Phase-0 execution after the coordinated
#774 yield window: select the most recent completed rung-2 stabilization
checkpoint series and execute the #726 TRAJGATE Phase-0 runner. Its permitted
terminal results were signal present, no signal, or a named invalid refusal.
It did not authorize a different checkpoint family, a silent rerun, or a
treatment run.

That execution never produced a result receipt. Therefore this ruling claims
no signal, no null result, no model capability, and no completed experiment.

## Why the named run is no longer executable

1. The original #726 implementation (merge
   `988f3bfa4775d26c1ef3661e1356d0bb88869322`) was blocked for live use by
   pre-consumption Amendment 2 on #723. The amendment showed that its
   prevalence gate measured a band that the frozen treatment did not select.
2. The selector-aligned and definedness repair landed later in #732 (merge
   `f620a4be7f35f2159cc76b4be81fb624ad9b5b71`), followed by the tokenizer
   lineage sidecar repair in #737 (merge
   `548d8adfe3835296f5e39d41cb036288235e96b8`). Running "#726 exactly as
   merged", as #779 requires, would knowingly execute the blocked apparatus;
   running the repaired apparatus would violate #779's frozen invocation.
3. #774 was a dated 2026-07-11 2.2B/rung-2 yield window. It expired without a
   #779 result. Current `GOAL.md` makes the first sufficiently pretrained
   clean-genesis 3B Ember the next executed outcome and explicitly classifies
   the old 2.2B test subject as history.

These are architecture and authority changes, not evidence about the
scientific hypothesis.

## Lossless obligation transfer

The surviving scientific obligation remains exactly this falsifiable question:
before any trajectory-gated treatment spend, test whether same-run lagged loss
progress adds predictive information beyond instantaneous loss and whether the
replayed treatment selector actually targets a majority stationary-or-ascending
band.

That obligation is conserved on frozen preregistration issue #723, including
all six dated pre-consumption amendments. A future execution may occur only
when all of the following are true:

- it names the first admissible current Ember checkpoint family rather than the
  retired rung-2/2.2B subject;
- it uses the selector-aligned, definedness-guarded, tokenizer-lineage-bound
  current apparatus, never the original #726 bytes;
- its checkpoint, tokenizer, corpus, source, and receipt bytes are
  content-addressed and independently reopened before launch;
- its admission and execution flow through the current Ember Lab authority and
  the governed runner; no historical daemon, second launcher, parallel lease,
  or parallel receipt authority is revived;
- it preserves the frozen no-silent-rerun and named-result grammar from #723.

Issue #723 is the canonical scientific carrier because it owns the frozen
question, mechanism, amendments, kill conditions, and verdict grammar. #779
owned only the now-expired scheduling and checkpoint-selection instance. No
unique #779 obligation remains after this transfer.

## Closure effect

Close #779 as not planned/superseded after this ruling is on public master and
the transfer is linked from #723. This closure retires only the invalidated,
expired run instance. It does not retire #723, claim that Phase-0 ran, or grant
credit to Ember-01, Ember-02, Ember-05, or any model.
