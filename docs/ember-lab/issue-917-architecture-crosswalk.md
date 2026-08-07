# Issue #917 architecture crosswalk

This document is the lossless current-architecture mapping for the historical
daemon wording. That name is historical provenance only; the sole current
authority is the repo-owned Ember Lab crate at `runtime/ember-lab`.

| Historical obligation | Current Ember Lab owner | Classification | Preserved obligation |
| --- | --- | --- | --- |
| historical `rehearse <manifest>` | `runtime/ember-lab/src/main.rs` `episode`/`rehearse` commands and `rehearsal::episode`, driven by `Daemon::dispatch_manifest` | RENAMED | ordered admission, data verification, train, checkpoint, publish, selectable checkpoint, restore phases; CLI refuses without the current dispatch authority |
| strict-gate census | `runtime/ember-lab/src/rehearsal.rs` `production_strict_gate_census` plus producer/consumer tests | REORGANIZED | every listed strict comparison has an explicit producer, consumer, and binding kind |
| measured-number admission | `rehearsal::Measurement`, `AdmissionBounds`, and `episode` | REORGANIZED | missing/unobserved evidence, memory, storage, and duration violations refuse before the runner |
| self-diagnosing refusal receipt | existing `ember-lab-dispatch-preflight-v1` receipt, augmented with the in-memory rehearsal observation | RENAMED | closed refusal code, phase, gate, offending value/bound, and one plain-language `next_action`; no second receipt family |
| operator-alone capability entrypoint | Ember Lab `episode --capability` CLI | RENAMED | one entrypoint chains admission and all rehearsal phases; it emits `NO_CAPABILITY_CLAIM` |
| generated operator runbook | `rehearsal::generate_runbook` and its exhaustive test | REORGANIZED | runbook vocabulary is generated from the closed receipt-code enum |
| six historical death classes | `DeathClass::all` and the prevention-layer test | REORGANIZED | each class is mapped to layer 1/2/3 and its dynamic reason is retained |

No second daemon, launcher, RPC, lease, ledger, or receipt family,
corpus/model authority, or policy gate is introduced. Existing Ember Lab
dispatch/lease/identity/receipt primitives remain the production authority;
the rehearsal module is an in-memory contract adapter and deterministic
CPU/fake-runner seam for tests only. The operator CLI requires a current
dispatch manifest and daemon database, rehashes phase evidence, and augments
the existing dispatch preflight receipt. It makes no GPU, training,
checkpoint, or capability claim.

The rehearsal manifest binds the current source commit, the SHA-256 of the
closed strict-gate census contract, a structured measured whole-run peak file,
and one exact byte-hashed evidence file for every ordered phase. The receipt
records those bindings, the capability-only chain, and plain-language refusal
actions. A missing or changed binding refuses before the daemon can spawn.
