<!-- EMBER_CONSERVATION_V1
minimum_new_network_parameters=3000000000
destination_total_parameters=>27000000000
required_native_capabilities=text,image,audio,reasoning,structured_tool_use
borrowed_lineage=frozen_reference_only
mechanism_erasure=forbidden
-->

# Research registry and dispatch gate

This contract is subordinate to GOAL.md and applies before every sanctioned
training, growth, evaluation, serving, or control dispatch.

## Registry semantics

Legal evidence states describe observations without erasing research:

- CANDIDATE
- TESTED_NEGATIVE
- TESTED_POSITIVE
- ADOPTED_CURRENT_CONFIG
- INACTIVE_CURRENT_CONFIG
- HISTORICAL_EVIDENCE
- RETEST_ELIGIBLE

KILL, PARK, EXCLUDED, RETIRED, mandatory-successor, or equivalent terminal
states are illegal. A negative row records regime, scale, modality, data,
budget, precision, routing, order, controls, result, and retest conditions.

## Dispatch preconditions

While `GOAL.md` declares `authority_only_goal=true`, every training, growth,
evaluation, serving, borrowed-reference, and experiment dispatch is denied.
Schema roles below describe later-goal admissibility; they do not grant
EMBER-00 runtime authority.

A config fails closed unless it:

- binds the exact active goal_id and next_executed_outcome;
- is not historical-only;
- declares whether it is a candidate, milestone, deterministic control, or
  frozen borrowed reference;
- contains at least 3,000,000,000 parameters for any neural execution;
- includes native text, image, audio, reasoning, and structured tool use;
- declares total, trainable, and active parameters;
- uses no published-family backbone or forbidden model-mediated signal;
- binds architecture, checkpoint, tokenizer, data, parentage, mechanisms,
  backend, controls, and rollback; and
- passes the authority conservation verifier.

Every mechanism named in `registry.consumes` must exist and have status
`ADOPTED_CURRENT_CONFIG`. A historical, inactive, negative, retest-eligible,
or unknown row cannot be smuggled into a runnable config. Evidence edges may
still preserve composition history without granting dispatch.

Borrowed references may execute under a later non-authority goal only in an
explicit frozen comparison seat with `execution_authority=reference_only`,
`frozen=true`, `lineage_ingress=false`, `capability_credit=none`, and no
model-mediated signal. They never satisfy an Ember-model result.
Historical configs are denied execution. Deterministic non-neural fixtures may
test gate logic but receive no neural or capability credit.

The gate emits a receipt containing goal binding, authority verdict, config
identity, and the next executed outcome.
