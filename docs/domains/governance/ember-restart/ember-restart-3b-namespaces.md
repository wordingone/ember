<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02B -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

# Ember restart sparse 3B namespace and run contract

[configs/ember-restart-3b.json](../../../../configs/ember-restart-3b.json) version 2 supersedes the retired dense, positionless declaration before any production allocation. It describes a clean-random 14-layer H=2048 unified decoder with shared attention and four independently trainable SwiGLU banks per layer: vision, audio, reasoning, and tool.

Each episode or batch declares exactly one active expert. All other expert banks are frozen for that episode, while shared attention, token embeddings, raw projectors, RMSNorm weights, and the selected bank remain trainable. This is capacity accounting, not a claim of completed training: total unique capacity is validated on a meta-instantiated model, and active cost is separately measured in run receipts.

Raw 48x48x3 RGB patches and raw 640-sample audio frames are projected directly into decoder-width soft tokens. Text and audio use parameter-free 1D RoPE; image markers use explicit 2D coordinates. Multimodal spans carry a tested causal or isolated attention policy. No pretrained encoder, borrowed checkpoint, or learned external routing signal is admitted.

## Exclusive namespaces

| Namespace | Exclusive root |
| --- | --- |
| model | models/ember-restart-3b |
| training | src/ember/infrastructure/tools/ember-restart-3b |
| checkpoints | receipts/ember-restart-3b |
| inference | inference/ember-restart-3b |
| data | data/ember-restart-3b |

The runtime supports meta construction for exact parameter inspection. Bounded GPU work records its receipts in the checkpoint namespace.
