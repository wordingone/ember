<!-- EMBER_CONSERVATION_V1
minimum_new_network_parameters=3000000000
destination_total_parameters=>27000000000
required_native_capabilities=text,image,audio,reasoning,structured_tool_use
borrowed_lineage=frozen_reference_only
mechanism_erasure=forbidden
-->

# Technique evidence graph

`docs/technique-registry.jsonl` is the permanent machine-readable evidence
graph for training, inference, architecture, memory, routing, and systems
mechanisms studied around Ember. It is subordinate to `GOAL.md` and cannot
authorize a network, change a required capability, or define Ember by itself.

The registry preserves the useful intent of the earlier optimization program:
measure both delivered hardware efficiency and tokens-to-capability efficiency
on the single 24 GiB GPU, retain negative and positive results, and compound
what later experiments can learn. Earlier sub-3B proxy results remain history;
they cannot be resumed as neural experiments or promoted into model milestones.

## Evidence states

Legal status values are:

- `CANDIDATE`: a named, untested or incompletely tested hypothesis.
- `TESTED_NEGATIVE`: a prediction contradicted in an exact recorded regime.
- `TESTED_POSITIVE`: a prediction supported in an exact recorded regime.
- `ADOPTED_CURRENT_CONFIG`: active only for an exact admissible config binding.
- `INACTIVE_CURRENT_CONFIG`: measured evidence retained but not active in the
  exact current config.
- `HISTORICAL_EVIDENCE`: preserved evidence from an inadmissible, superseded,
  borrowed-signal, or otherwise non-current context.
- `RETEST_ELIGIBLE`: a retained question with an explicit materially different
  scale, modality, order, routing, substrate, precision, or interaction regime.

Terminal states such as `KILL`, `PARK`, `EXCLUDED`, and `RETIRED` are illegal.
A status updates evidence; it does not erase a mechanism, require a successor,
or prohibit an untested interaction. The operator alone may reduce Ember's
invariant scope through a conservation-audited authority change.

No registry row is currently `ADOPTED_CURRENT_CONFIG`: every existing neural
config is historical-only and execution-denied under EMBER-00. A future
adoption must bind the exact admissible config, goal, next executed outcome,
checkpoint identity, tested regime, and rollback/deletion control. It cannot
become a silent global mandate on all future architectures.

## Required evidence for an experiment row

Each material result must retain, directly or through cited receipts:

- exact implementation and code identity;
- model architecture, total/trainable/active parameters, and checkpoint hash;
- data, tokenizer, token count, modality mix, and leakage controls;
- GPU, precision, kernels, memory limit, and runtime identity;
- matched baseline, seeds, equal-token/FLOP/wall-clock boundary, and metrics;
- observed result, uncertainty, confounders, and contradicted prediction;
- untested regimes and plausible interactions; and
- artifact retention plus rollback or deletion evidence where attribution is
  claimed.

A paper claim, implementation, fixture, smoke, or administrative status is not
a result. Isolated negatives constrain only their measured condition. Factorial,
staged-composition, scale, order, and cross-modality studies remain available
when their interaction hypothesis is still open.

## Lineage and scale boundary

Any new neural experiment must pass the authority conservation verifier and
contain at least 3,000,000,000 parameters with native text, image, audio,
reasoning, and structured tool use. Borrowed weights, outputs, teachers,
judges, filters, ranks, curricula, stopping decisions, or hidden model
cognition cannot enter the target lineage. Rows based on those signals remain
historical or frozen-reference evidence only.

The registry may hold published ideas and transparent deterministic methods,
but adoption requires an owned implementation and checkpoint-bound evidence.
Inference optimizations are also research inputs: each may be decomposed into
the physical resource it saves and transformed into a falsifiable
training-side mechanism rather than assumed to transfer.

## Dispatch behavior

Before any sanctioned dispatch, the gate must:

1. run the authority conservation verifier;
2. reject historical configs and any unbound or sub-3B neural artifact;
3. validate the active goal and next executed outcome;
4. enforce only technique rows explicitly adopted by that exact config;
5. keep frozen borrowed references outside training and promotion signals; and
6. emit a receipt binding config bytes, registry bytes, checkpoint identity,
   outcome, and verdict.

Registry entries and receipts are retained. Corrections append or supersede
interpretation while preserving the original observation and its provenance.
