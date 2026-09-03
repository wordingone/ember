# Ember R1 A1 dense comparator contract v1

`goal_id: EMBER-02`

`workstream_id: EMBER-02B`

`next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember`

This contract defines the source carrier for preregistered arm A1. It does not
claim that A1 has run or that R1-E8 is met.

## Dense identity

The canonical machine contract is
`tools/ember-restart-3b/ember-restart-3b-a1.json`. Its architecture revision is
`ember-dense-a1-3b-v1`: 56 dense decoder layers at width 2048, with one 4H
SwiGLU FFN in every layer and no router or expert bank. The dense FFN inherits
the sparse arm's SwiGLU math through an ancestry-clean owned class; an
identical-weight test requires byte-identical forward outputs from both classes.
The structural inventory is 3,839,344,640 unique parameters. The 32,000-token vocabulary, tied embedding,
raw 48x48x3 projector, raw 640-sample projector, attention geometry, and clean
random genesis remain comparable to the sparse arm.

## Closed mechanism binding

Tier 1 maps only to `FULL_STATE_ADAMW_CPU_OFFLOAD`. Tier 2 maps only to
`OWNED_Q_GALORE_PROJECTED_GRADIENT`; Tier 2 remains conditional and has no
implementation in Packet B1. A mismatched or free-form pair is a typed refusal.

Tier 1 keeps an FP32 CPU master tensor plus FP32 CPU first and second moments for
every registered parameter. Gradients move to CPU for the AdamW update and the
updated master value is copied back to the model parameter. State must be fully
initialized before the first step; partial or lazy coverage is refused.

## Threshold and claim boundary

The carrier reopens and hashes
`docs/domains/governance/spec/ember02-preregistration-thresholds-v1.json`, then derives T-08, T-09,
and T-20 from those bytes. A caller cannot supply or override those values.

Packet B1 proves source behavior on a small CPU fixture and meta-materializes the
production inventory. Packet B2 must separately add certified launch plumbing,
matched A3 identity/data/seed binding, resource admission, checkpoint/receipt
publication, and the real `r1_exit_battery -> r1_e8_validator` handoff. Only a
genuine dense >=3B execution can produce liveness or parity evidence.
