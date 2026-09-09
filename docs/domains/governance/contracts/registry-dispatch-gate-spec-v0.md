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


## 2026-09-09 fixed numerical conformance implementation

# Existing registry dispatch: bounded numerical qualification

This implements the 2026-09-08 canonical architecture decision. It does not
replace that decision, create a campaign, or qualify the model. Amend the existing
registry-dispatch-gate-spec-v0.md, registry_gate.py and the actual conformance
entry consumer together. Current source defects: obsolete ledger and conservation
verifier paths, and no purpose compatible with qualification_gated.

## Closed purpose

`numerical_conformance` is available only to a research_candidate declaring
qualification_gated under the exact active goal. Standard dispatch retains its
existing authority rules. No translation to allowed is made in the architecture
config. This purpose permits only fixed-input full-population numerical forward,
backward and one bounded in-memory component update for correctness checking.

The numerical registry verdict is emitted by the existing gate checks and captured in the owned run stdout, whose subject digest binds this purpose and immutable run identity to:

- Exact configuration bytes, complete source closure and source revision.
- Exact consuming test entry, its semantic argv and interpreter/runtime identity.
- Fixed input descriptor and digest, clean initialization recipe/seed, and at most
  one applied update. No supplied pretrained weights or checkpoint ingress.
- Owned wall-time, host memory, total-device supervision and allocator caps,
  disk budgets and shared GPU lease. Limits come from the actual launch envelope;
  an allocator fraction cannot stand in for total-device supervision.
- A rollback consisting of process-tree cleanup and discard of in-memory candidate
  state. No serving activation or retained learned checkpoint output is permitted.
- Zero trained-token, throughput, capability, model-birth and serving credit.

The actual consumer independently rechecks purpose and bound identities immediately
before CUDA initialization. It checks loaded module origins against the declared
source closure, not only files available on disk. Unsupported args, mutable inputs,
identity drift, missing budgets/lease, extra update steps or a missing gate binding
refuse execution. A caller-written PASS field is not sufficient: rerun the existing
pure authority/mechanism/identity checks against current bytes.

## Existing daemon dispatch requirement

The numerical controller is an authenticated run body of the existing Ember
daemon, not an independent launcher. Its closed entry consumes the daemon's
one-use dispatch token before starting any worker and requires the exact 20 GiB
native job ceiling. The subject binds the daemon binary and source identities;
the consumer verifies the controller's actual daemon parent. The existing
catalog, named pipe, custody, lease and manifest verification remain authoritative.

The daemon's `numerical_conformance` profile accepts only the closed run-body
arguments, verified launcher/helper bindings and matching custody directory.
It requires a v4/v5 manifest with the external VRAM wall. Other profiles cannot
dispatch this entry. No production memory-model certificate is borrowed.

On WDDM, `nvidia_smi_total_device_upper_bound` uses total device occupation,
including desktop and descendant allocations, as a conservative bound. It does
not measure per-process usage: that receipt field is null and the separately
named upper-bound field carries the observation. This provider is restricted to
the numerical profile; existing production provider requirements are unchanged.

## Preserved obligations

Keep authority conservation, exact >=3B population, declared native boundaries,
clean initialization, existing mechanism registry checks, operating disk reserves,
and existing owned-process cleanup. Use documented per-mechanism exemptions only
where actually necessary; never exempt the conformance purpose wholesale.
The currently inspected ledger has no ADOPTED_CURRENT_CONFIG rows, but the gate
must read the live ledger and preserve its future obligations.

No corpus ingestion, pretraining campaign, evaluation certificate, external input
acquisition, serving, generation admission or retained learned checkpoint is enabled
by this purpose. Those keep their own complete production qualification gates.

## Required implementation checks

1. Standard and historical/reference dispatch behavior remains unchanged.
2. qualification_gated refuses standard dispatch; the closed purpose refuses
   incomplete/wrong plans, identities, budgets and commands.
3. Wrong source/config/fixture/runtime bytes and wrong loaded module origins refuse.
4. Mechanism and authority conservation failures remain refusals for conformance.
5. The real consumer rejects forged/mismatched receipt fields and extra update
   work; metadata-only gate tests do not establish that a CUDA run happened.
6. Execute the full-population conformance only through the existing owned process,
   disk budget, shared GPU lease and total-device supervision controls. Preserve
   success/failure receipts, numerical tolerances and cleanup without shrinking
   the model if the run exceeds a limit or fails correctness.
