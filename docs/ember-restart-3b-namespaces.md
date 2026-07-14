<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02B -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember restart 3B namespace and run contract

The immutable contract is [configs/ember-restart-3b.json](../configs/ember-restart-3b.json), version 1. It describes a clean-random-initialized, unified decoder with no parent checkpoint, borrowed weights, teacher outputs, model-derived data, or external judges. The contract is a declaration only: the source entries do not claim that any training artifact already exists.

## Exclusive namespaces

Every namespace below is exclusive. A producer may write only within its own root and may not claim a file from another root as its output.

| Namespace | Exclusive root | Boundary |
| --- | --- | --- |
| model | `models/ember-restart-3b` | model weights and model metadata |
| training | `tools/ember-restart-3b` | training entry points and run-local tooling |
| checkpoints | `receipts/ember-restart-3b` | checkpoint manifests and custody receipts |
| inference | `inference/ember-restart-3b` | serving and inference configuration derived from this model |

The contract file itself is `configs/ember-restart-3b.json`. No file below any of these declared roots—or below the contract path—can be claimed as a target output unless a later contract explicitly changes the boundary:

* `models/ember-restart-3b`
* `receipts/ember-restart-3b`
* `tools/ember-restart-3b`
* `configs/ember-restart-3b.json`

## Immutable model and training declarations

The model shape is H=3072, L=20, 24 attention heads, and a 32,000-token vocabulary with tied text embeddings. Image inputs are raw RGB patches of `48x48x3`; audio inputs are raw frames of 640 samples. Gradient checkpointing is enabled and the optimizer is paged 8-bit AdamW. GPU work requires the explicit memory and GPU-hour caps plus a receipt path in the JSON contract, and every write-heavy invocation must use the declared disk-budget runner contract.

The independently auditable unique-parameter formula is:

```text
vocab*hidden
+ layers*(4*hidden^2 + 12*hidden^2)
+ (48*48*3)*hidden
+ 640*hidden
```

With the declared shape this is 3,141,402,624 unique trainable parameters, above the assertion minimum of 3,000,000,000. The tied embedding is counted once; projection and decoder matrices are counted as trainable unique weights without inventing an artifact claim.

Text, image, and audio source arrays are intentionally non-empty declarations. They become claim-bearing only when later custody manifests bind concrete owned records and hashes.
