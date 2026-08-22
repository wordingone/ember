# Ember training signature census v1

This observation-only schema binds issue #1413 CUDA-graph authority to the static facts of the real decoded Ember training batch. It does not activate FP8 or CUDA graphs.

The signature is layout-sensitive by design. Tensor `device_index` and `stride` remain inside the hashed identity because a captured CUDA graph binds operand placement, address-compatible layout, and execution shape. Logically equivalent values on another GPU index or with another stride are therefore different signatures and require separate census admission.

Each `ember-training-step-signature-v1` SHA-256 covers the closed `contract` object: capture region, gradient-checkpointing mode, active expert, ordered tensor descriptors, and ordered multimodal-span descriptors. The census binds those signatures to exact source commit, model-config hash, input-identity hash, and runner-source hash. Its status is `OBSERVED_NOT_ACTIVATED`, `activation_enabled` is false, and `fallbacks` is zero.

The producer refuses an existing output path. A consumer must reopen the exact census bytes and self-hash; an unlisted signature, layout drift, placement drift, or hash mismatch refuses activation. The later activation path must cache by a cheap static tuple and hash only first-seen layouts—canonical JSON and SHA-256 are not permitted on every graph replay.
