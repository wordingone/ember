<!-- goal_id: EMBER-01 -->
<!-- workstream_id: EMBER-01A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Restart Audio Evaluation Disposition v1

## Source and bounded materialization result

- Candidate source: `audiollms/audiobench`
- Resolved source commit: `85dcdb88c41e6ebb2bcb3ce19b15d061dfef9dba`
- Source-only materialization budget: C `0.50 GiB`, B `0.01 GiB`
- Result: `STOPPED_BY_DISK_BUDGET`, exit `125`, after C consumption exceeded
  the declared cap.

The partial checkout resolved to the stated commit but was not clean: its
working tree showed deleted tracked paths plus untracked paths after the runner
terminated the checkout. The on-disk partial tree occupied approximately
`562,349,037` bytes. It is not a frozen evaluator artifact.

## Judge-integrity exclusion

The source contains evaluator paths named for GPT-4 and Llama model judges, as
well as score artifacts labeled with those judges. Those paths are prohibited
for Ember target credit: a borrowed or hosted judge may not decide capability.
The full AudioBench aggregate therefore is excluded as a scoring authority.

## Eligible local components, pending independent freeze

Only objective metrics such as WER, BLEU, and exact string match are candidate
components. Before use, each component needs a separately materialized and
licensed audio split, raw-audio preprocessing hash, reference transcript or
answer hash, scorer source hash, target input/protocol hash, and a
disk-budget receipt. The target must be an admitted owned checkpoint and the
same local objective scorer must run for every comparator.

## Failure meaning

This is not evidence that Ember lacks audio ability. It is evidence that the
candidate's current source package and judge topology cannot establish that
ability under the no-borrowed-judge and bounded-disk rules.
