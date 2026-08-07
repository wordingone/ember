# Issue #917 architecture crosswalk

This document is the lossless current-architecture mapping for the historical
daemon wording. That name is historical provenance only; the sole current
authority is the repo-owned Ember Lab crate at `runtime/ember-lab`.

| Historical obligation | Current Ember Lab owner | Classification | Preserved obligation |
| --- | --- | --- | --- |
| historical `rehearse <manifest>` | `runtime/ember-lab/src/main.rs` `episode`/`rehearse` commands and `rehearsal::episode` | RENAMED | ordered admission, data verification, train, checkpoint, publish, selectable checkpoint, restore phases |
| strict-gate census | `runtime/ember-lab/src/rehearsal.rs` `production_strict_gate_census` plus producer/consumer tests | REORGANIZED | every listed strict comparison has an explicit producer, consumer, and binding kind |
| measured-number admission | `rehearsal::Measurement`, `AdmissionBounds`, and `episode` | REORGANIZED | missing/unobserved evidence, memory, storage, and duration violations refuse before the runner |
| self-diagnosing refusal receipt | `rehearsal::RehearsalReceipt` and `write_receipt` | RENAMED | closed refusal code, phase, gate, offending value/bound, and one `next_action` |
| operator-alone capability entrypoint | Ember Lab `episode --capability` CLI | RENAMED | one entrypoint chains admission and all rehearsal phases; it emits `NO_CAPABILITY_CLAIM` |
| generated operator runbook | `rehearsal::generate_runbook` and its exhaustive test | REORGANIZED | runbook vocabulary is generated from the closed receipt-code enum |
| six historical death classes | `DeathClass::all` and the prevention-layer test | REORGANIZED | each class is mapped to layer 1/2/3 and its dynamic reason is retained |

No second daemon, launcher, RPC, lease, ledger, schema, receipt family,
corpus/model authority, or policy gate is introduced. Existing Ember Lab
dispatch/lease/identity/receipt primitives remain the production authority;
the new rehearsal module is a contract adapter and deterministic CPU/fake-runner
seam only. It makes no GPU, training, checkpoint, or capability claim.
