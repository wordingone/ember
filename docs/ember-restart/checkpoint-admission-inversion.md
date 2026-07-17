<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02B -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

# Checkpoint admission inversion

Training success and checkpoint admission are different events. A judge defect must never erase completed training. Raw checkpoint bytes therefore publish atomically into `.checkpoint-quarantine` first. They remain non-selectable there. Idempotent judges inspect the durable candidate; only a passing verdict atomically promotes it to the normal checkpoint namespace.

## End-to-end boundary census

| Check | Previous location | Required location | Failure effect |
|---|---|---|---|
| Input manifests, hashes, tokenizer, source/records, semantic contract, transition authority | Before and during run | Admission before dispatch | Refuse cheaply; no training starts. |
| Host commit, VRAM, disk reserves, Job cap, write bound | Before dispatch and immediately before serialization | Admission plus irreducible live physics guard | Derive mechanics or refuse; never weaken semantics. |
| Replay bindings and declared parent/root inputs | Writer callback | Admission before dispatch where input-only | Refuse before training. |
| Candidate parameter/expert hashes and executed episode lineage | Writer callback | Post-run judge | Quarantine on failure; preserve bytes. |
| Atomic shard serialization and per-file hashing | Writer callback | Irreducible write mechanics | Leave crash residue non-selectable; never overwrite an admitted target. |
| Closed receipt field/schema checks | Writer and isolated counter | Shared build-time contract plus post-run judge | Test failure at build time; quarantine at runtime. |
| Isolated realization counter | Pre-promotion inside training callback | Post-run judge against durable candidate | Preserve and rejudge identical bytes. |
| Counter-success receipt | Pre-promotion inside training callback | Written by passing post-run judge | Required before promotion. |
| Retention/deletion | Around inline publication | Only admitted checkpoints and separately bounded quarantine policy | Never delete the sole raw candidate because a judge failed. |
| Load, serve, evaluation, resume selection | Explicit filesystem path | Admitted namespace only | Any path beneath `.checkpoint-quarantine` fails closed. |

## State machine

`STAGING_WRITE` is private and leased. After manifest-last serialization and hash closure it becomes `QUARANTINED_UNVERIFIED` by atomic rename. A judge failure leaves it there with content-addressed failure evidence. Re-running the corrected judge over the same candidate may transition it to `ADMITTED_SELECTABLE` by atomic rename. No other transition makes a checkpoint loadable.

The present implementation makes the raw candidate durable before the realization judge, preserves all shards on judge failure, supports rejudging without serialization or training, and rejects quarantine paths in the central loader. Immediately before promotion it rereads the manifest and every recorded shard, compares that final snapshot with the pre-judge receipt, and refuses any mutation or late target appearance; every directory transfer uses non-overwriting rename semantics, including quarantine collisions. Retention accounting charges the full custody tree, including quarantined candidates, while honoring receipt-declared zero-increment hardlinks, so moving bytes out of the selectable namespace never fakes reclaimed capacity. Process-level separation of the judge and consolidation of the Rust/Python host-capacity authority remain follow-on hardening; neither is allowed to weaken this state machine.
