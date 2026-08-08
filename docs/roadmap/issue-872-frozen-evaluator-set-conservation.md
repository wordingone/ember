# Issue #872 frozen-evaluator-set conservation ruling

Status: `SUPERSEDED_NOT_PLANNED` is conditional on independent review, green required checks, and merge of this carrier. No issue state or evaluator result changes merely because this document exists.

Source baseline: `cb0c181adf9ba6aa5b34e8310dfe55be1ab0f19c`.

## Accepted owner transfers

- OPEN EMBER-02 / #1116 owns the complete frozen evaluator set, certification, and no-overclaim gate: https://github.com/wordingone/ember/issues/1116#issuecomment-5225016700
- OPEN #1433 owns only the immediate Leg-B plus heldout subset: https://github.com/wordingone/ember/issues/1433#issuecomment-5225016905
- #872 bidirectional acceptance record: https://github.com/wordingone/ember/issues/872#issuecomment-5225018531

Both owners remain open. Their scopes are complementary and must not be collapsed.

## Historical retirement boundary

The dated 2026-07-20 schedule, 2026-07-23 forcing date, and named-reviewer assignment retire as expired scheduling provenance only. The missing-completion and drift-alarm record remains negative evidence. Independent exact-head review remains mandatory even when the reviewer identity changes.

Current individual adapters, scorers, registries, and fixtures are structural evidence only. #1433 explicitly records that its bound checkpoints are retired; it cannot grant a current full-suite result.

## Conserved complete-set clauses

1. Recursively snapshot and content-address admission, checkpoint, prediction, verifier, scorer, registry, and receipt bytes, then reopen those same bytes during independent replay.
2. Bind exact tool versions and revisions, configurations, splits, task/image/row manifests, harness, hashes, and evaluator identities for AudioBench, EvalPlus, Spider, MMMU, Terminal-Bench, MATH-500, and every other member of the frozen suite. An adapter, partial set, or seven-of-eight result is incomplete.
3. Run from a clean clone against the exact current owned checkpoint and bind architecture, tensors, tokenizer, data, inference parameters, source, executable, runtime, registry, split, raw predictions, scores, and receipts.
4. Persist raw predictions or transcripts before scoring.
5. Evidence must be machine-minted, content-addressed, independently reopenable, and non-self-attested. Missing, duplicate, foreign, stale, malformed, mutated, partial, or identity-mismatched evidence fails closed.
6. Require independent exact-head review and green required checks. A named historical reviewer may change; independence and exact-head binding may not.
7. Evaluator execution is distinct from capability. A harness, adapter, scorer, fixture, or tool passing does not grant model reasoning, training, checkpoint-quality, or milestone credit.
8. Preserve interruption, deletion, rollback, unavailable-suite, incomplete-suite, scorer/registry-drift, malformed-prediction, and no-result negatives.

## #1433 immediate subset

#1433 may produce ARC/HellaSwag Leg-B raw predictions plus the frozen heldout NLL/BPB receipt and registry links. That immediate subset is useful only for its exact bound checkpoint and inputs. It never narrows, replaces, or inherits the remaining #872 suite obligations.

## Terminal falsifier and reopen rule

The falsifier is an independent clean-clone replay of the complete frozen evaluator set against the exact current owned checkpoint, reopening every source, executable, runtime, registry, split, prediction, score, and receipt byte. Until that chain exists, #1116 and #1433 remain open. Removing a suite, substituting a retired checkpoint, accepting a partial set, or losing a bound artifact reopens #872.

No evidence inheritance is permitted: one suite cannot prove another, a #1433 subset cannot prove the full set, and structural adapter/scorer tests cannot prove current checkpoint evaluation.

## Credit boundary

- `completion_credit=false`
- `scientific_execution_credit=false`
- `acquisition_credit=false`
- `result_credit=false`
- `gpu_credit=false`
- `training_credit=false`
- `checkpoint_credit=false`
- `capability_credit=false`
- `milestone_credit=false`

OPEN #1116, OPEN #1433, and the current Ember Lab evaluator, checkpoint, receipt, and custody spine remain the sole authorities. This carrier creates no evaluator, scorer, registry, checkpoint, receipt, or certificate authority.

`NO_NEW_PARALLEL_AUTHORITY`
