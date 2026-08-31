<!--
goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
-->

# Optimizer transplant provenance v1

Issue #677's unsafe historical BUILD path is explicitly execution-denied before
it reads or writes a checkpoint. Its only archived successor route is the
verified materialize-to-custody path. The reusable admission boundary is
`src/ember/governance/scripts/optimizer_transplant_provenance.py`; any current or future
owned-training path that performs an optimizer transplant must consume this
contract rather than revive the unreceipted BUILD path.

## Required evidence

A transplanted checkpoint is admissible only when all of the following are
true:

1. `transplant-provenance.json` has the closed
   `ember-optimizer-transplant-provenance/v1` schema and is byte-hash bound by
   `manifest.json`.
2. The identical provenance object is inline in the checkpoint manifest and in
   every run/checkpoint receipt resumed from it.
3. Every tensor-valued optimizer slot has exactly one sorted mapping row with
   optimizer name, local index, parameter FQN, slot, shape, dtype, source and
   destination content hashes, source and destination RMS, transform, error,
   and one of `mapped`, `authorized_fresh`, or `dropped`.
4. Missing, duplicate, unknown, or implicit-fresh mappings refuse admission.
   RMS is diagnostic and never establishes identity.
5. Canonical source and destination optimizer-state hashes include tensor
   content, parameter routing, scalar metadata, and parameter groups. The
   record also binds the source checkpoint, global step, scheduler, scaler,
   method, cure version, and build timestamp.
6. A second deterministic transplant replay reproduces every non-identity
   destination tensor hash before the provenance record can become verified.
7. The checkpoint is hardlinked or copied into a content-addressed custody root
   outside its disposable source worktree. Every payload is rehashed, the
   source is rehashed to prove it was not mutated, and the custody result is
   recorded in the destination manifest.

## Consumer rule

Consumers call `load_verified_custody_checkpoint`. It rejects noncanonical or
stale sidecars, inline/sidecar disagreement, wrong destination optimizer bytes,
unverified replay, missing custody, a path that does not match the custody
artifact ID, or any checkpoint payload that no longer matches its manifest.

The source build tree and source checkpoints remain read-only. The old
`optimizer-grown.pt` write beside the staged source is forbidden; an audit
copy, when requested, belongs to the new destination bundle.
