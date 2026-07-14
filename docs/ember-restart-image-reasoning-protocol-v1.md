<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02C -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Restart Image and Reasoning Protocol v1

## Frozen source identity

- Evaluation source: `MMMU-Benchmark/MMMU`
- Source commit: `bc168a9119d986d7cdf1e07b1eeb96ed3e8f92fa`
- Source materialization: disk-budget receipt, C cap `0.20 GiB`, B cap
  `0.01 GiB`, exit `0`, checkout equal to the stated commit.

## Local scoring surface

The source contains local evaluation code and released test answer keys. It
supports image-plus-reasoning measurement without a hosted judge or leaderboard
submission. The initial eligible protocol is exact multiple-choice accuracy
with the source's local normalization/evaluation implementation, not a
free-form borrowed-model judge.

## Freeze before target inference

1. Pin the exact dataset revision and split bytes, including image payload
   hashes.
2. Hash the image preprocessing and placement procedure used by Ember's native
   raw-image-patch path.
3. Hash the prompt, answer-label extraction, and local scoring source.
4. Record the owned target checkpoint and full lineage manifest, then freeze
   comparator revisions under the identical protocol.
5. Run all acquisition and inference through `disk_budget_runner.py` with
   declared disk and wall-clock caps; retain per-item rows and aggregate
   uncertainty.

## Interpretation limits

MMMU establishes an external image-and-reasoning result, not audio, browser,
terminal, SQL, or general tool-use capability. It cannot be used to credit a
text-only checkpoint: the manifest must record actual image inputs reaching
the target's native modality path.
