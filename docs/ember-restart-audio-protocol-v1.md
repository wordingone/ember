<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02C -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Restart Audio Evaluation Disposition v1

## Source and bounded materialization result

- Candidate source: `THENIROCK/audiobench`
- Resolved source commit: `0fc7fef2709c00ac1e2eb2b372ec4c56362bb8c6`
- Source Git tree: `4a01fdd3731c70a496993055bbf11499053ea344`
- License: MIT; exact `LICENSE` SHA-256: `54233ca9f039653155e71f92b7cdf484041bee1fdcd90bafac2b5e21e4c916c9`
- Repeatable custody command: `scripts/ember_restart_eval_audiobench_source_audit.py`
- Verified source-only cache: 324 files and 11,013,938 bytes; the audit emits `PREFLIGHT_ONLY` with `closed_run_artifact_sha256: null`.
- Result: source custody is exact, but no closed-run artifact is materialized or eligible for target scoring.

## Judge-integrity exclusion

The source contains evaluator paths named for GPT-4 and Llama model judges, as
well as score artifacts labeled with those judges. Those paths are prohibited
for Ember target credit: a borrowed or hosted judge may not decide capability.
The full AudioBench aggregate therefore is excluded as a scoring authority.

## Eligible local components, pending independent freeze

Only objective metrics such as WER, BLEU, and exact string match are candidate
components. Before use, each component needs a separately materialized and
licensed audio split, raw-audio preprocessing hash, reference transcript or
answer hash, scorer source hash, target input/protocol hash, a content-addressed
closed-run artifact hash, and a disk-budget receipt. Until that closed-run hash
exists, the bound scorer rejects caller-selected run artifacts and emits no score.
The target must be an admitted owned checkpoint and the same local objective
scorer must run for every comparator.

## Failure meaning

This is not evidence that Ember lacks audio ability. It is evidence that the
candidate's current source package and judge topology cannot establish that
ability under the no-borrowed-judge and bounded-disk rules.
